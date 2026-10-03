"""Locate existing desktop tools without installing or modifying them."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

BUNDLE_ID = "com.openai.codex"


def _codex_bundle(path):
    try:
        with (path / "Contents/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        executable = path / "Contents/MacOS" / info["CFBundleExecutable"]
        return info.get("CFBundleIdentifier") == BUNDLE_ID and executable.is_file()
    except (OSError, KeyError, plistlib.InvalidFileException):
        return False


def app_bundle():
    override = os.environ.get("CODEX_DESKTOP_APP")
    if override:
        path = Path(override).expanduser().resolve()
        return path if _codex_bundle(path) else None
    if sys.platform != "darwin":
        return None
    for directory in (Path("/Applications"), Path.home() / "Applications"):
        for name in ("Codex.app", "ChatGPT.app"):
            path = directory / name
            if _codex_bundle(path):
                return path.resolve()
    try:
        found = subprocess.run(
            ["/usr/bin/mdfind", "kMDItemCFBundleIdentifier == 'com.openai.codex'"],
            capture_output=True, text=True, timeout=2,
        )
        for raw in found.stdout.splitlines():
            path = Path(raw)
            if _codex_bundle(path):
                return path.resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def codex_cli():
    cli = shutil.which("codex")
    if cli:
        return cli
    app = app_bundle()
    bundled = app / "Contents/Resources/codex" if app else None
    return str(bundled) if bundled and bundled.is_file() and os.access(bundled, os.X_OK) else None


def node_runtime():
    override = os.environ.get("CODEX_SKIN_NODE")
    app = app_bundle() if not override else None
    candidates = [override] if override else [
        str(app / "Contents/Resources/cua_node/bin/node") if app else None,
        shutil.which("node"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        try:
            result = subprocess.run(
                [str(path), "-e", "process.exit(typeof WebSocket === 'function' && typeof fetch === 'function' && typeof AbortSignal.timeout === 'function' ? 0 : 1)"],
                capture_output=True, timeout=2,
            )
            if result.returncode == 0:
                return path.resolve()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None
