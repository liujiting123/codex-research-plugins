"""Resolve renamed desktop bundles and existing runtimes without touching the host."""
import os
from pathlib import Path
import plistlib
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import host_environment as host


class HostEnvironmentTests(unittest.TestCase):
    def bundle(self, directory, identifier=host.BUNDLE_ID):
        app = Path(directory) / "Custom Apps" / "Research Codex.app"
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": identifier, "CFBundleExecutable": "Desktop",
        }))
        (contents / "MacOS/Desktop").touch()
        return app

    def executable(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        path.chmod(0o755)
        return path

    def test_renamed_app_in_directory_with_spaces_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.bundle(directory)
            with patch.dict(os.environ, {"CODEX_DESKTOP_APP": str(app)}):
                self.assertEqual(host.app_bundle(), app.resolve())

    def test_override_rejects_an_unrelated_application(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.bundle(directory, "example.unrelated")
            with patch.dict(os.environ, {"CODEX_DESKTOP_APP": str(app)}):
                self.assertIsNone(host.app_bundle())

    def test_cli_falls_back_to_the_validated_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.bundle(directory)
            cli = self.executable(app / "Contents/Resources/codex")
            with patch.dict(os.environ, {"CODEX_DESKTOP_APP": str(app)}), \
                 patch.object(host.shutil, "which", return_value=None):
                self.assertEqual(host.codex_cli(), str(cli.resolve()))

    def test_node_prefers_existing_bundle_runtime_and_probes_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.bundle(directory)
            node = self.executable(app / "Contents/Resources/cua_node/bin/node")
            with patch.dict(os.environ, {"CODEX_DESKTOP_APP": str(app), "CODEX_SKIN_NODE": ""}), \
                 patch.object(host.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as probe:
                self.assertEqual(host.node_runtime(), node.resolve())
                self.assertEqual(probe.call_args.args[0][0], str(node.resolve()))

    def test_incompatible_node_override_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            node = self.executable(Path(directory) / "node")
            with patch.dict(os.environ, {"CODEX_SKIN_NODE": str(node)}), \
                 patch.object(host.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                self.assertIsNone(host.node_runtime())


if __name__ == "__main__":
    unittest.main()
