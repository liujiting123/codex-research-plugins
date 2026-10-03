"""Plugin-owned skin preferences and a loopback runtime; no external skin app."""
import atexit
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import relaunch
from host_environment import app_bundle, node_runtime

from themes import library, export_theme, rgba, validate_native
from native_settings import persist_theme, restore_theme, theme_is_saved

ROOT = Path(__file__).resolve().parent
PORT = 9341
MAX_IMAGE = 8_000_000
DEFAULT_OPTIONS = {
    "material": "frosted", "wallpaper": {"kind": "ambient"},
    "canvasOpacity": .80, "sidebarOpacity": .72, "composerOpacity": .86,
    "glassBlur": 20, "wallpaperOpacity": 1, "wallpaperBlur": 0, "wallpaperFit": "cover",
}
_watcher = None


def state_dir():
    if os.environ.get("CODEX_SKIN_STATE_DIR"):
        return Path(os.environ["CODEX_SKIN_STATE_DIR"])
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "native-themes"


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".skin-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def clean_options(options):
    if options is None:
        return deepcopy(DEFAULT_OPTIONS)
    if not isinstance(options, dict) or set(options) - set(DEFAULT_OPTIONS):
        raise ValueError("皮肤选项无效")
    result = {**deepcopy(DEFAULT_OPTIONS), **options}
    if result["material"] not in {"frosted", "liquid", "flat"}:
        raise ValueError("材质需要 frosted、liquid 或 flat")
    if result["wallpaperFit"] not in {"cover", "contain"}:
        raise ValueError("壁纸填充方式无效")
    for key in ("canvasOpacity", "sidebarOpacity", "composerOpacity", "wallpaperOpacity"):
        value = result[key]
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"{key} 必须在 0 到 1 之间")
    for key, maximum in (("glassBlur", 60), ("wallpaperBlur", 40)):
        value = result[key]
        if type(value) not in (int, float) or not 0 <= value <= maximum:
            raise ValueError(f"{key} 超出允许范围")
    wallpaper = result["wallpaper"]
    if not isinstance(wallpaper, dict) or wallpaper.get("kind") not in {"none", "ambient", "image"}:
        raise ValueError("壁纸类型无效")
    if wallpaper["kind"] == "image":
        value = wallpaper.get("dataUrl")
        if not isinstance(value, str) or len(value) > MAX_IMAGE or not re.fullmatch(r"data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}", value):
            raise ValueError("图片需要 PNG/JPEG/WebP/GIF 的本地 data URL，最大 8 MB")
        wallpaper = {"kind": "image", "dataUrl": value}
    else:
        wallpaper = {"kind": wallpaper["kind"]}
    result["wallpaper"] = wallpaper
    return result


def prepare(theme_id, overrides=None, options=None):
    record = next((t for t in library()["themes"] if t["id"] == theme_id), None)
    if record is None:
        raise ValueError("主题不存在，请刷新主题库")
    payload = export_theme(theme_id, overrides)["native"]
    tokens = dict(record.get("tokens", {}))
    for color in tokens.values():
        rgba(color)
    config = {"version": 1, "enabled": True, "themeId": theme_id, "name": record["name"],
              "native": payload, "tokens": tokens, "options": clean_options(options)}
    config["fingerprint"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:20]
    return config


def current_preferences(include_image=False):
    path = state_dir() / "skin.json"
    if not path.exists():
        return {"enabled": False, "themeId": None, "options": deepcopy(DEFAULT_OPTIONS)}
    try:
        data = json.loads(path.read_text())
        native = validate_native(data.get("native"))
        options = clean_options(data.get("options"))
        if not include_image and options["wallpaper"]["kind"] == "image":
            options["wallpaper"] = {"kind": "image", "saved": True}
        overrides = {key: native["theme"][key] for key in ("surface", "ink", "accent", "contrast", "opaqueWindows")}
        overrides["codeThemeId"] = native["codeThemeId"]
        return {"enabled": data.get("enabled") is True, "themeId": data.get("themeId"), "options": options, "overrides": overrides}
    except (OSError, ValueError, TypeError):
        return {"enabled": False, "themeId": None, "options": deepcopy(DEFAULT_OPTIONS), "warning": "保存的皮肤设置无法读取，原文件已保留"}


def runtime_status():
    if os.environ.get("CODEX_SKIN_PREVIEW") == "1":
        return {"phase": "preview", "connected": False, "applied": False, "port": PORT,
                "message": "预览模式 · 未连接主窗口", "enabled": False}
    preferences = current_preferences()
    native_saved = False
    if preferences["enabled"]:
        try:
            native_saved = theme_is_saved(json.loads((state_dir() / "skin.json").read_text())["native"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
    fallback = {"phase": "idle", "connected": False, "applied": False, "port": PORT,
                "message": "换肤连接未开启，当前无法直接应用；首次连接需要重新打开一次 Codex。"}
    status_path = state_dir() / "runtime-status.json"
    try:
        value = json.loads(status_path.read_text())
        for key in ("phase", "connected", "applied", "port", "message", "checkedAt", "themeId", "targetCount", "compatibility"):
            if key in value:
                fallback[key] = value[key]
        # An exited plugin process is not evidence that its old connection remains live.
        from datetime import datetime, timezone
        checked = datetime.fromisoformat(value.get("checkedAt", "").replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - checked).total_seconds() > 20:
            fallback.update(phase="unknown", connected=False, applied=False, message="连接状态已过期，应用后会重新检查")
    except (OSError, ValueError, TypeError):
        pass
    if fallback["phase"] in {"idle", "waiting", "unknown"} and not fallback["connected"]:
        fallback["message"] = ("配色配置已保存，当前窗口尚未确认生效。换肤连接未开启；首次连接需要重新打开一次 Codex。" if native_saved
                               else "换肤连接未开启，当前无法直接应用；首次连接需要重新打开一次 Codex。")
    restarting = relaunch.restart_status(state_dir())
    return {**fallback, **(restarting or {}), "enabled": preferences["enabled"], "nativeSaved": native_saved}


def engine_args(node, command):
    args = [str(node), str(ROOT / "engine.mjs"), command,
            "--state-dir", str(state_dir()), "--port", str(PORT)]
    app = app_bundle()
    if app:
        args.extend(["--app-path", str(app)])
    return args


def run_engine(command):
    if os.environ.get("CODEX_SKIN_PREVIEW") == "1":
        return {"phase": "preview", "connected": False, "applied": False, "port": PORT,
                "message": "当前是预览页，未连接 Codex 主窗口"}
    node = node_runtime()
    if node is None:
        return {"phase": "error", "connected": False, "applied": False, "message": "未找到可用的 Node 运行时；需要 Codex 内置 Node 或已有 Node.js 22+（支持 WebSocket）"}
    try:
        proc = subprocess.run(engine_args(node, command),
                              capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {"phase": "error", "connected": False, "applied": False,
                "message": "换肤连接超时，窗口应用状态尚未确认"}
    except OSError:
        return {"phase": "error", "connected": False, "applied": False,
                "message": "无法启动已有 Node 运行时"}
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"phase": "error", "connected": False, "applied": False,
                "message": "换肤引擎没有返回有效状态"}


def stop_watcher():
    global _watcher
    if _watcher is not None and _watcher.poll() is None:
        _watcher.terminate()
        try:
            _watcher.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _watcher.kill()
    _watcher = None


def start_watcher():
    global _watcher
    if os.environ.get("CODEX_SKIN_PREVIEW") == "1":
        return
    if _watcher is None or _watcher.poll() is not None:
        node = node_runtime()
        if node is None:
            return
        _watcher = subprocess.Popen(engine_args(node, "watch") + ["--owner-pid", str(os.getpid())],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_skin(theme_id, overrides=None, options=None, restart_when_needed=False):
    if type(restart_when_needed) is not bool:
        raise ValueError("自动重启参数需要布尔值")
    config = prepare(theme_id, overrides, options)
    if os.environ.get("CODEX_SKIN_PREVIEW") == "1":
        return run_engine("apply")
    persist_theme(config["native"], state_dir(), atomic_json)
    atomic_json(state_dir() / "skin.json", config)
    pending = relaunch.restart_status(state_dir())
    if pending and pending.get("phase") == "restarting":
        return {**pending, "nativeSaved": True}
    relaunch.dismiss_result(state_dir())
    status = run_engine("apply")
    if status.get("phase") == "waiting" and restart_when_needed:
        status = relaunch.schedule(state_dir())
    elif status.get("phase") == "waiting":
        status = {**status, "message": "配色配置已保存，当前窗口尚未确认生效。换肤连接未开启，请先开启直接换肤连接。"}
    status = {**status, "nativeSaved": True}
    atomic_json(state_dir() / "runtime-status.json", status)
    start_watcher()
    return status


def pause_skin():
    if os.environ.get("CODEX_SKIN_PREVIEW") == "1":
        return run_engine("pause")
    relaunch.cancel_before_quit(state_dir())
    restored = restore_theme(state_dir(), atomic_json)
    path = state_dir() / "skin.json"
    if path.exists():
        data = json.loads(path.read_text())
        data["enabled"] = False
        atomic_json(path, data)
    stop_watcher()
    status = run_engine("pause")
    if restored.get("restored"):
        status = {**status, "message": "已暂停完整效果，并保存原来的主题配色；重开 Codex 后生效。"}
    status = {**status, "nativeSaved": False, "nativeRestored": bool(restored.get("restored"))}
    atomic_json(state_dir() / "runtime-status.json", status)
    return status


def initialize():
    if current_preferences()["enabled"]:
        start_watcher()


atexit.register(stop_watcher)
