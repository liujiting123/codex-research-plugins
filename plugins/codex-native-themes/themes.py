"""DSH palette conversion and a local library for Codex native theme imports."""
from __future__ import annotations

import base64
import colorsys
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
PREFIX = "codex-theme-v1:"
PACK_FORMAT = "dsh-dream-skin/pack"
MAX_INPUT = 512_000
REQUIRED_TOKENS = (
    "--dsw-alias-bg-base", "--dsw-alias-bg-layer-1",
    "--dsw-alias-label-primary", "--dsw-alias-label-secondary",
    "--dsw-alias-brand-primary", "--dsw-alias-border-l1", "--dsw-alias-border-l2",
)
# IDs and variants in the installed Codex 26.928.31416 native theme schema.
CODE_THEMES = {
    "absolutely": ["dark", "light"], "ayu": ["dark"],
    "catppuccin": ["dark", "light"], "codex": ["dark", "light"],
    "dracula": ["dark"], "everforest": ["dark", "light"],
    "github": ["dark", "light"], "gruvbox": ["dark", "light"],
    "linear": ["dark", "light"], "lobster": ["dark"], "material": ["dark"],
    "matrix": ["dark"], "monokai": ["dark"], "night-owl": ["dark"],
    "nord": ["dark"], "notion": ["dark", "light"], "og": ["dark"],
    "oscurange": ["dark"], "one": ["dark", "light"], "proof": ["light"],
    "raycast": ["dark", "light"], "rose-pine": ["dark", "light"],
    "sentry": ["dark"], "solarized": ["dark", "light"], "temple": ["dark"],
    "tokyo-night": ["dark"], "vercel": ["dark", "light"],
    "vscode-plus": ["dark", "light"], "xcode": ["dark", "light"],
}
CODE_MATCH = {
    "abyss": "nord", "aurora": "everforest", "nebula": "catppuccin",
    "ember": "gruvbox", "midnight": "codex", "ivory": "xcode",
    "mist": "github", "rose": "catppuccin",
}


def _number(value: str, scale: float = 1) -> float:
    result = float(value[:-1]) / 100 * scale if value.endswith("%") else float(value)
    if not math.isfinite(result):
        raise ValueError("颜色数值必须有限")
    return result


def _unit(value: str, scale: float) -> float:
    return max(0, min(scale, _number(value, scale)))


def rgba(value: str) -> tuple[float, float, float, float]:
    """Parse concrete CSS colors; never carry arbitrary CSS into the UI."""
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("颜色必须是 CSS 颜色字符串")
    color = value.strip().lower()
    named = {"black": "#000000", "white": "#ffffff", "transparent": "#00000000"}
    color = named.get(color, color)
    if re.fullmatch(r"#[0-9a-f]{3,4}|#[0-9a-f]{6}|#[0-9a-f]{8}", color):
        bits = color[1:]
        if len(bits) in (3, 4):
            bits = "".join(c * 2 for c in bits)
        parts = [int(bits[i:i + 2], 16) for i in range(0, len(bits), 2)]
        return (*parts[:3], parts[3] / 255 if len(parts) == 4 else 1.0)
    match = re.fullmatch(r"(rgba?|hsla?)\(([-+\d.eE%,/\sradturng]+)\)", color)
    if not match:
        raise ValueError(f"不支持的颜色：{value[:64]}")
    parts = re.split(r"\s*[,/]\s*|\s+", match[2].strip())
    if len(parts) not in (3, 4):
        raise ValueError("RGB/HSL 颜色需要 3 个分量和可选的透明度")
    alpha = _unit(parts[3], 1) if len(parts) == 4 else 1.0
    if match[1].startswith("rgb"):
        return (*(_unit(c, 255) for c in parts[:3]), alpha)
    hue = parts[0]
    if hue.endswith("turn"):
        h = _number(hue[:-4]) * 360
    elif hue.endswith("grad"):
        h = _number(hue[:-4]) * .9
    elif hue.endswith("rad"):
        h = _number(hue[:-3]) * 180 / math.pi
    else:
        h = _number(hue.removesuffix("deg"))
    if not all(c.endswith("%") for c in parts[1:3]):
        raise ValueError("HSL 的饱和度和亮度需要百分比")
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, _unit(parts[2], 1), _unit(parts[1], 1))
    return r * 255, g * 255, b * 255, alpha


def hex_color(value: str, backdrop: str = "#000000") -> str:
    r, g, b, a = rgba(value)
    br, bg, bb, _ = rgba(backdrop)
    channels = [math.floor(c * a + bc * (1 - a) + .5) for c, bc in zip((r, g, b), (br, bg, bb))]
    return "#" + "".join(f"{c:02x}" for c in channels)


def css_color(value: str) -> str:
    r, g, b, a = rgba(value)
    return f"rgba({math.floor(r + .5)}, {math.floor(g + .5)}, {math.floor(b + .5)}, {a:.5f})"


def validate_native(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("variant") not in {"light", "dark"}:
        raise ValueError("原生主题需要 light/dark variant")
    code = payload.get("codeThemeId")
    if code not in CODE_THEMES or payload["variant"] not in CODE_THEMES[code]:
        raise ValueError("代码主题不支持所选的浅色或深色模式")
    theme = payload.get("theme")
    if not isinstance(theme, dict):
        raise ValueError("缺少原生 theme 对象")
    for key in ("accent", "ink", "surface"):
        if not isinstance(theme.get(key), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", theme[key]):
            raise ValueError(f"{key} 必须是六位 HEX 颜色")
    contrast = theme.get("contrast")
    if type(contrast) is not int or not 0 <= contrast <= 100:
        raise ValueError("contrast 必须是 0 到 100 的整数")
    if type(theme.get("opaqueWindows")) is not bool:
        raise ValueError("opaqueWindows 必须是布尔值")
    if theme.get("accentSource", "custom") not in {"chatgpt", "custom"}:
        raise ValueError("accentSource 无效")
    fonts = theme.get("fonts")
    if not isinstance(fonts, dict) or not all(k in fonts and (fonts[k] is None or isinstance(fonts[k], str)) for k in ("code", "ui")):
        raise ValueError("fonts 需要 code 和 ui，可设置为 null 使用默认字体")
    if "content" in fonts and fonts["content"] is not None and not isinstance(fonts["content"], str):
        raise ValueError("content 字体无效")
    for key in ("codeFace", "uiFace", "contentFace"):
        if key in fonts:
            face = fonts[key]
            if not isinstance(face, dict) or not all(isinstance(face.get(k), str) for k in ("family", "fullName", "postscriptName")):
                raise ValueError("字体描述无效")
    semantic = theme.get("semanticColors")
    if not isinstance(semantic, dict) or not all(isinstance(semantic.get(k), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", semantic[k]) for k in ("diffAdded", "diffRemoved", "skill")):
        raise ValueError("semanticColors 需要 diffAdded、diffRemoved 和 skill 的 HEX 颜色")
    return deepcopy(payload)


def share_code(payload: dict) -> str:
    return PREFIX + json.dumps(validate_native(payload), ensure_ascii=False, separators=(",", ":"))


def _label(value, default="") -> str:
    return value.strip()[:160] if isinstance(value, str) else default


def convert_pack(pack: dict, source="DSH 导入") -> dict:
    if not isinstance(pack, dict) or pack.get("format") != PACK_FORMAT or type(pack.get("version")) is not int or pack["version"] != 1:
        raise ValueError("需要 dsh-dream-skin/pack v1 主题包")
    manifest = pack.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("缺少主题 manifest")
    theme_id = _label(manifest.get("id"))
    name = _label(manifest.get("name"))
    variant = manifest.get("colorScheme")
    if not theme_id or not name or variant not in {"light", "dark"}:
        raise ValueError("主题需要 id、name 和 light/dark colorScheme")
    tokens = manifest.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("缺少主题颜色 tokens")
    for key in REQUIRED_TOKENS:
        if key not in tokens:
            raise ValueError(f"缺少颜色：{key}")
        rgba(tokens[key])
    base = hex_color(tokens["--dsw-alias-bg-base"], "#000000" if variant == "dark" else "#ffffff")
    ink = hex_color(tokens["--dsw-alias-label-primary"], base)
    accent = hex_color(tokens["--dsw-alias-brand-primary"], base)
    defaults = {"diffAdded": "#40c977" if variant == "dark" else "#00a240",
                "diffRemoved": "#fa423e" if variant == "dark" else "#ba2623", "skill": accent}
    semantic = dict(defaults)
    for native_key, dsh_key in (("diffAdded", "--dsw-alias-state-success-primary"), ("diffRemoved", "--dsw-alias-state-error-primary")):
        if dsh_key in tokens:
            try:
                semantic[native_key] = hex_color(tokens[dsh_key], base)
            except ValueError:
                pass
    payload = {
        "variant": variant, "codeThemeId": CODE_MATCH.get(theme_id, "codex"),
        "theme": {"surface": base, "ink": ink, "accent": accent, "accentSource": "custom",
                  "contrast": 60 if variant == "dark" else 45, "opaqueWindows": True,
                  "fonts": {"ui": None, "code": None}, "semanticColors": semantic},
    }
    safe_tokens = {}
    for key, value in tokens.items():
        if isinstance(key, str) and re.fullmatch(r"--dsw-(?:alias|specific)-[a-z0-9-]+", key):
            try:
                safe_tokens[key] = css_color(value)
            except ValueError:
                pass
    return {"id": "dsh:" + theme_id, "name": _label(manifest.get("nameZh"), name) or name,
            "nameEn": name, "source": source, "sourceId": theme_id,
            "description": _label(manifest.get("description")), "native": validate_native(payload), "tokens": safe_tokens}


def parse_import(raw: str, name="导入主题") -> dict:
    if not isinstance(raw, str) or not raw.strip() or len(raw.encode("utf-8")) > MAX_INPUT:
        raise ValueError("主题内容为空或超过 512 KB")
    raw = raw.strip()
    if "#dream-skin-pack=" in raw or raw.startswith("dream-skin-pack="):
        fragment = urlsplit(raw).fragment if "#" in raw else raw
        encoded = parse_qs(fragment).get("dream-skin-pack", [None])[0]
        if not encoded:
            raise ValueError("DSH 分享链接中缺少主题内容")
        try:
            # parse_qs treats '+' as a space; DSH uses standard base64 as well as URL encoding.
            encoded = encoded.replace(" ", "+")
            raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            raise ValueError("DSH 分享链接的主题编码无效") from None
    if raw.startswith(PREFIX):
        raw = raw[len(PREFIX):]
        payload = validate_native(json.loads(raw if raw.startswith("{") else unquote(raw)))
        digest = hashlib.sha256(share_code(payload).encode()).hexdigest()[:12]
        return {"id": "native:" + digest, "name": _label(name, "导入主题"), "nameEn": "Imported",
                "source": "Codex 导入", "description": "", "native": payload}
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("format") == PACK_FORMAT:
        return convert_pack(data)
    raise ValueError("支持 DSH 主题包 JSON、DSH 分享链接和 codex-theme-v1 导入码")


def store_path() -> Path:
    if os.environ.get("CODEX_SKIN_STATE_DIR"):
        return Path(os.environ["CODEX_SKIN_STATE_DIR"]) / "library.json"
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "native-themes" / "library.json"


def load_saved(path=None) -> list:
    path = Path(path) if path is not None else store_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("本地主题库格式无效，原文件未修改")
    for record in data:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise ValueError("本地主题库记录无效，原文件未修改")
        validate_native(record.get("native"))
    return data


def save_import(raw: str, name="导入主题", path=None) -> dict:
    record = parse_import(raw, name)
    path = Path(path) if path is not None else store_path()
    records = load_saved(path)
    # Idempotent imports keep the library compact; changed imports replace their own ID only.
    records = [item for item in records if item["id"] != record["id"]] + [record]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".library-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return record


def read_dsh_state(path: Path) -> dict:
    """Select only theme keys from DSH's mixed settings; never return other settings."""
    if path.stat().st_size > 32_000_000:
        raise ValueError("DSH 设置超过 32 MB，请单独导入主题包")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("DSH 设置格式无效")
    packs = data.get("dsh-dream-skin:packs", [])
    if isinstance(packs, str):
        packs = json.loads(packs)
    if not isinstance(packs, list):
        raise ValueError("DSH 主题包列表格式无效")
    current = _label(data.get("dsh-dream-skin:skin")) or None
    return {"current": current, "packs": packs[:100]}


def library(*, dsh_paths=None, saved_path=None) -> dict:
    raw_builtins = json.loads((ROOT / "assets/dsh-themes.json").read_text())
    themes = {item["id"]: item for item in (convert_pack(p, "DSH 内置") for p in raw_builtins)}
    warnings = []
    current = None
    dsh_found = False
    if dsh_paths is None:
        configured = Path(os.environ["DSH_HOME"]) / "dream-skin.json" if os.environ.get("DSH_HOME") else None
        dsh_paths = [p for p in (configured, Path.home() / ".dsh/profiles/desktop/dream-skin.json", Path.home() / ".dsh/dream-skin.json") if p is not None]
    for path in dict.fromkeys(map(Path, dsh_paths)):
        if not path.is_file():
            continue
        try:
            state = read_dsh_state(path)
            dsh_found = True
            current = state["current"]
            for entry in state["packs"]:
                try:
                    # DSH 9.29 persists {id, manifest}, not the original top-level package.
                    pack = {"format": PACK_FORMAT, "version": 1, "manifest": entry.get("manifest")} if isinstance(entry, dict) else None
                    record = convert_pack(pack, "DSH 本地")
                    themes[record["id"]] = record
                except (ValueError, TypeError, AttributeError):
                    warnings.append("有一套 DSH 本地主题无法转换；其余主题仍可使用")
            break
        except (OSError, ValueError):
            warnings.append("无法读取一处 DSH 外观设置；可手动导入主题包")
    try:
        for record in load_saved(saved_path):
            themes[record["id"]] = record
    except (OSError, ValueError):
        warnings.append("本地主题库无法读取；原文件已保留")
    current_id = None
    if current:
        source_id = current.removeprefix("dream-pack:")
        current_id = "dsh:" + source_id
        if current_id not in themes:
            current_id = None
    return {"themes": list(themes.values()), "dshCurrentId": current_id, "dshFound": dsh_found,
            "codeThemes": CODE_THEMES, "warnings": list(dict.fromkeys(warnings)),
            "schemaVersion": "codex-theme-v1", "checkedAppVersion": "26.928.31416"}


def export_theme(theme_id: str, overrides=None) -> dict:
    record = next((item for item in library()["themes"] if item["id"] == theme_id), None)
    if record is None:
        raise ValueError("主题不存在，请刷新主题库")
    payload = deepcopy(record["native"])
    overrides = overrides or {}
    if not isinstance(overrides, dict) or set(overrides) - {"surface", "ink", "accent", "contrast", "opaqueWindows", "codeThemeId"}:
        raise ValueError("主题调整参数无效")
    for key, value in overrides.items():
        if key == "codeThemeId":
            payload[key] = value
        else:
            payload["theme"][key] = value
    return {"name": record["name"], "native": validate_native(payload), "shareCode": share_code(payload),
            "instructions": "Codex 设置 → 外观 → 对应浅色/深色主题的导入，粘贴此码。主界面配色通过原生主题生效。"}
