"""Exercise public config RPCs in temporary homes, without the desktop app."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import native_settings
from host_environment import codex_cli
from runtime import atomic_json
from themes import export_theme


@unittest.skipUnless(codex_cli(),
                     "requires the already installed Codex CLI")
class NativeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / "codex-home"
        self.home.mkdir()
        self.state = Path(self.directory.name) / "state"
        self.config = self.home / "config.toml"
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.native = export_theme("dsh:nebula")["native"]

    def read_user(self):
        # Each read opens and closes a new actual CLI process, not a cached config.
        with native_settings._AppServer() as server:
            return server.read()["desktop"]

    def journal(self):
        return json.loads((self.state / native_settings.JOURNAL).read_text())

    def write_fixture(self):
        self.config.write_text(
            '# retained root comment\nmodel = "test-model" # retained inline comment\n'
            '[desktop]\n# retained unrelated desktop comment\nkeepMe = "keep"\n'
            'appearanceTheme = "system"\nappearanceLightCodeThemeId = "github"\n'
            '[desktop.appearanceDarkChromeTheme]\nsurface = "#112233"\n'
            '[desktop.appearanceDarkChromeTheme.fonts]\nui = "Original UI"\n'
        )

    def test_native_theme_persists_in_fresh_cli_with_nullable_fonts(self):
        self.write_fixture()
        before = deepcopy(self.native)
        result = native_settings.persist_theme(self.native, self.state, atomic_json)
        self.assertTrue(result["saved"])
        self.assertTrue(native_settings.theme_is_saved(self.native))
        desktop = self.read_user()
        self.assertEqual(desktop["appearanceTheme"], "dark")
        self.assertEqual(desktop["appearanceDarkCodeThemeId"], "catppuccin")
        self.assertEqual(desktop["appearanceDarkChromeTheme"]["fonts"], {})
        self.assertEqual(desktop["appearanceDarkChromeTheme"]["surface"], self.native["theme"]["surface"])
        self.assertEqual(desktop["keepMe"], "keep")
        self.assertEqual(desktop["appearanceLightCodeThemeId"], "github")
        self.assertEqual(self.native, before)
        text = self.config.read_text()
        for comment in ("# retained root comment", "# retained inline comment", "# retained unrelated desktop comment"):
            self.assertIn(comment, text)
        self.assertEqual(tomllib.loads(text)["model"], "test-model")
        journal = self.journal()
        self.assertEqual(set(journal["lastApplied"]), set(result["keys"]))
        self.assertEqual(set(journal["original"]), {"appearanceTheme", "appearanceDarkChromeTheme"})
        self.assertEqual(journal["lastApplied"]["appearanceDarkChromeTheme"]["fonts"], {})
        self.assertNotIn("model", json.dumps(journal))

    def test_restore_keeps_subsequent_user_appearance_edit_and_removes_absent_key(self):
        self.write_fixture()
        original_chrome = self.read_user()["appearanceDarkChromeTheme"]
        native_settings.persist_theme(self.native, self.state, atomic_json)
        with native_settings._AppServer() as server:
            snapshot = server.read()
            server.write(snapshot, {"appearanceTheme": "light"})
        result = native_settings.restore_theme(self.state, atomic_json)
        desktop = self.read_user()
        self.assertEqual(result["preserved"], ["appearanceTheme"])
        self.assertEqual(set(result["restored"]), {"appearanceDarkChromeTheme", "appearanceDarkCodeThemeId"})
        self.assertEqual(desktop["appearanceTheme"], "light")
        self.assertEqual(desktop["appearanceDarkChromeTheme"], original_chrome)
        self.assertNotIn("appearanceDarkCodeThemeId", desktop)
        self.assertEqual(desktop["keepMe"], "keep")
        self.assertFalse(native_settings.theme_is_saved(self.native))
        self.assertEqual(self.journal()["lastApplied"], {})

    def test_restore_respects_user_changes_inside_chrome_theme(self):
        native_settings.persist_theme(self.native, self.state, atomic_json)
        with native_settings._AppServer() as server:
            snapshot = server.read()
            changed = deepcopy(snapshot["desktop"]["appearanceDarkChromeTheme"])
            changed["accent"] = "#654321"
            server.write(snapshot, {"appearanceDarkChromeTheme": changed})
        result = native_settings.restore_theme(self.state, atomic_json)
        desktop = self.read_user()
        self.assertEqual(result["preserved"], ["appearanceDarkChromeTheme"])
        self.assertEqual(desktop["appearanceDarkChromeTheme"], changed)
        self.assertNotIn("appearanceTheme", desktop)
        self.assertNotIn("appearanceDarkCodeThemeId", desktop)

    def test_switching_variants_and_reapplying_retains_the_initial_backup(self):
        self.write_fixture()
        original = self.read_user()
        native_settings.persist_theme(self.native, self.state, atomic_json)
        native_settings.persist_theme(self.native, self.state, atomic_json)
        light = export_theme("dsh:ivory")["native"]
        native_settings.persist_theme(light, self.state, atomic_json)
        self.assertTrue(native_settings.theme_is_saved(light))
        native_settings.restore_theme(self.state, atomic_json)
        self.assertEqual(self.read_user(), original)

    def test_explicit_reapply_adopts_a_user_edit_as_the_restore_baseline(self):
        self.write_fixture()
        native_settings.persist_theme(self.native, self.state, atomic_json)
        with native_settings._AppServer() as server:
            snapshot = server.read()
            server.write(snapshot, {"appearanceDarkCodeThemeId": "nord"})
        native_settings.persist_theme(self.native, self.state, atomic_json)
        native_settings.restore_theme(self.state, atomic_json)
        self.assertEqual(self.read_user()["appearanceDarkCodeThemeId"], "nord")

    def test_version_guard_rejects_a_concurrent_config_edit(self):
        self.write_fixture()
        original = self.config.read_text()
        raced = False

        def racing_writer(path, value):
            nonlocal raced
            atomic_json(path, value)
            if "pending" in value and not raced:
                raced = True
                self.config.write_text(original.replace('model = "test-model"', 'model = "user-changed-model"'))

        with self.assertRaises(native_settings.NativeSettingsError):
            native_settings.persist_theme(self.native, self.state, racing_writer)
        self.assertTrue(raced)
        self.assertEqual(self.config.read_text(), original.replace('model = "test-model"', 'model = "user-changed-model"'))
        self.assertEqual(self.journal()["lastApplied"], {})
        self.assertNotIn("pending", self.journal())

    def test_interrupted_journal_commit_can_still_restore_successful_write(self):
        self.write_fixture()
        original = self.read_user()

        def interrupted_writer(path, value):
            if "pending" not in value:
                raise OSError("fixture interrupted final journal commit")
            atomic_json(path, value)

        with self.assertRaises(native_settings.NativeSettingsError):
            native_settings.persist_theme(self.native, self.state, interrupted_writer)
        self.assertTrue(native_settings.theme_is_saved(self.native))
        self.assertIn("pending", self.journal())
        native_settings.restore_theme(self.state, atomic_json)
        self.assertEqual(self.read_user(), original)

    def test_wrong_home_and_invalid_journal_never_overwrite_config(self):
        self.write_fixture()
        native_settings.persist_theme(self.native, self.state, atomic_json)
        before = self.config.read_bytes()
        journal = self.journal()
        journal["filePath"] = str(Path(self.directory.name) / "different-home" / "config.toml")
        atomic_json(self.state / native_settings.JOURNAL, journal)
        with self.assertRaises(native_settings.NativeSettingsError):
            native_settings.restore_theme(self.state, atomic_json)
        self.assertEqual(self.config.read_bytes(), before)
        (self.state / native_settings.JOURNAL).write_text('{"invalid": true}')
        with self.assertRaises(native_settings.NativeSettingsError):
            native_settings.persist_theme(self.native, self.state, atomic_json)
        self.assertEqual(self.config.read_bytes(), before)

    def test_invalid_native_never_launches_cli(self):
        invalid = deepcopy(self.native)
        invalid["theme"]["accent"] = "invalid"
        with patch("native_settings._AppServer") as server, self.assertRaises(ValueError):
            native_settings.persist_theme(invalid, self.state, atomic_json)
        server.assert_not_called()
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
