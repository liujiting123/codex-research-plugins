"""Persist native appearance through the installed Codex config RPC only."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import select
import subprocess
import time
import tomllib

from themes import validate_native
from host_environment import codex_cli


JOURNAL = "native-settings.json"
APPEARANCE_KEYS = frozenset({
    "appearanceTheme", "appearanceLightChromeTheme", "appearanceDarkChromeTheme",
    "appearanceLightCodeThemeId", "appearanceDarkCodeThemeId",
})


class NativeSettingsError(ValueError):
    """A human-readable configuration error, without config values or secrets."""


class _RpcRejected(NativeSettingsError):
    pass


def _without_nulls(value):
    # The desktop host omits nullable object fields when serializing TOML.
    if isinstance(value, dict):
        # Some installed CLI versions expose TOML numbers this way in raw layers.
        if set(value) == {"$serde_json::private::Number"}:
            try:
                number = json.loads(value["$serde_json::private::Number"])
                if type(number) in (int, float):
                    return number
            except (ValueError, TypeError):
                pass
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _appearance(native):
    native = validate_native(native)
    variant = native["variant"].capitalize()
    return {"appearanceTheme": native["variant"],
            f"appearance{variant}ChromeTheme": _without_nulls(native["theme"]),
            f"appearance{variant}CodeThemeId": native["codeThemeId"]}


class _AppServer:
    """Short-lived, config-only stdio connection; never starts a thread or MCP."""

    def __enter__(self):
        cli = codex_cli()
        if not cli:
            raise NativeSettingsError("未找到已安装的 Codex CLI，无法保存配色")
        self.home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
        env = dict(os.environ, CODEX_HOME=str(self.home))
        self.buffer = b""
        self.next_id = 0
        try:
            self.process = subprocess.Popen(
                [cli, "app-server", "--listen", "stdio://"], env=env, cwd=self.home,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise NativeSettingsError("无法启动已安装的 Codex 配置服务") from None
        try:
            self.request("initialize", {"clientInfo": {
                "name": "codex_native_themes", "title": "Native Themes", "version": "0.1.2",
            }})
            self._send({"method": "initialized"})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()

    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise NativeSettingsError("Codex 配置服务连接已中断，请重新应用") from None

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 10
        while True:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    raise NativeSettingsError("Codex 配置服务返回了无效响应") from None
                if not isinstance(message, dict) or message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise _RpcRejected("Codex 配置操作被拒绝，配置可能已更改；请重新应用")
                if not isinstance(message.get("result"), dict):
                    raise NativeSettingsError("Codex 配置服务返回了无效结果")
                return message["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeSettingsError("Codex 配置操作超时，保存状态尚未确认；请重新检查")
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if ready:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise NativeSettingsError("Codex 配置服务已退出，保存状态尚未确认")
                self.buffer += chunk

    def read(self):
        result = self.request("config/read", {"includeLayers": True})
        for layer in result.get("layers") or []:
            source = layer.get("name", {})
            if source.get("type") != "user" or source.get("profile") is not None:
                continue
            file_path = source.get("file")
            version = layer.get("version")
            config = layer.get("config")
            if (not isinstance(file_path, str) or not isinstance(version, str)
                    or not isinstance(config, dict)
                    or Path(file_path).resolve() != self.home / "config.toml"):
                raise NativeSettingsError("无法确认 Codex 用户配置文件与版本，未写入配色")
            desktop = config.get("desktop") or {}
            if not isinstance(desktop, dict):
                raise NativeSettingsError("Codex desktop 配置格式无效，原配置已保留")
            return {"filePath": file_path, "version": version, "desktop": desktop}
        raise NativeSettingsError("未找到 Codex 用户配置层，未写入配色")

    def write(self, snapshot, values):
        result = self.request("config/batchWrite", {
            "edits": [{"keyPath": "desktop." + key, "mergeStrategy": "replace", "value": value}
                      for key, value in values.items()],
            "expectedVersion": snapshot["version"], "filePath": snapshot["filePath"],
        })
        if result.get("status") not in {"ok", "okOverridden"}:
            raise NativeSettingsError("Codex 尚未确认配色写入成功，请重新检查")


@contextmanager
def _locked_journal(state_directory):
    directory = Path(state_directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".native-settings.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory / JOURNAL
    except OSError:
        raise NativeSettingsError("无法读取或保存原生配色备份，原文件已保留") from None


def _load_journal(path, file_path):
    empty = {"version": 1, "filePath": file_path, "original": {}, "lastApplied": {}}
    if not path.exists():
        return empty
    try:
        journal = json.loads(path.read_text())
        if (not isinstance(journal, dict) or journal.get("version") != 1
                or not isinstance(journal.get("filePath"), str)
                or any(not isinstance(journal.get(key, {}), dict)
                       or set(journal.get(key, {})) - APPEARANCE_KEYS
                       for key in ("original", "lastApplied", "pending"))
                or "original" not in journal or "lastApplied" not in journal):
            raise ValueError
    except (OSError, ValueError, UnicodeError):
        raise NativeSettingsError("保存的原生配色备份无效，原文件已保留") from None
    if Path(journal["filePath"]).resolve() != Path(file_path).resolve():
        raise NativeSettingsError("配色备份属于另一个 Codex 配置目录，原备份已保留")
    return journal


def _matches(desktop, key, value):
    return key in desktop and _without_nulls(desktop[key]) == _without_nulls(value)


def _resolved_journal(journal, desktop):
    journal = deepcopy(journal)
    # A saved intention makes an interrupted/uncertain RPC safe to recover.
    for key, value in journal.pop("pending", {}).items():
        if _matches(desktop, key, value):
            journal["lastApplied"][key] = value
    return journal


def persist_theme(native, state_directory, write_json):
    """Save only this variant's three native appearance keys, retaining a backup."""
    selected = _appearance(native)
    with _locked_journal(state_directory) as path, _AppServer() as server:
        snapshot = server.read()
        previous = _load_journal(path, snapshot["filePath"])
        journal = _resolved_journal(previous, snapshot["desktop"])
        for key in selected:
            last = journal["lastApplied"]
            if key not in last or not _matches(snapshot["desktop"], key, last[key]):
                # An explicit reapply adopts subsequent user edits as the new baseline.
                if key in snapshot["desktop"]:
                    journal["original"][key] = _without_nulls(snapshot["desktop"][key])
                else:
                    journal["original"].pop(key, None)
        journal["pending"] = selected
        write_json(path, journal)
        try:
            server.write(snapshot, selected)
        except _RpcRejected:
            write_json(path, previous)
            raise
        journal["lastApplied"].update(journal.pop("pending"))
        write_json(path, journal)
    return {"saved": True, "keys": list(selected)}


def restore_theme(state_directory, write_json):
    """Restore owned keys only while they still equal the last applied values."""
    with _locked_journal(state_directory) as path:
        if not path.exists():
            return {"restored": [], "preserved": []}
        with _AppServer() as server:
            snapshot = server.read()
            journal = _resolved_journal(_load_journal(path, snapshot["filePath"]), snapshot["desktop"])
            values, preserved = {}, []
            for key, last in journal["lastApplied"].items():
                if _matches(snapshot["desktop"], key, last):
                    # Null at the key itself is the public config RPC's delete operation.
                    values[key] = journal["original"].get(key)
                else:
                    preserved.append(key)
            if values:
                server.write(snapshot, values)
            write_json(path, {"version": 1, "filePath": snapshot["filePath"],
                              "original": {}, "lastApplied": {}})
    return {"restored": list(values), "preserved": preserved}


def theme_is_saved(native):
    """Read persisted settings cheaply for polling; do not assert UI application."""
    selected = _appearance(native)
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    try:
        with (home / "config.toml").open("rb") as file:
            desktop = tomllib.load(file).get("desktop") or {}
    except (OSError, ValueError):
        return False
    if not isinstance(desktop, dict):
        return False
    return all(_matches(desktop, key, value) for key, value in selected.items())
