"""Guard the reversible runtime boundary without touching the real app."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        # Runtime tests isolate both app configuration and the UI transport.
        self.persist = patch("runtime.persist_theme", return_value={"saved": True}).start()
        self.restore = patch("runtime.restore_theme", return_value={"restored": True}).start()
        patch("runtime.theme_is_saved", return_value=True).start()
        self.addCleanup(patch.stopall)

    def test_prepare_keeps_full_dsh_palette_and_validated_wallpaper_options(self):
        config = runtime.prepare("dsh:nebula", {"accent": "#ffffff"}, {"material": "liquid"})
        self.assertEqual(config["native"]["theme"]["accent"], "#ffffff")
        self.assertEqual(config["native"]["theme"]["surface"], "#12101a")
        self.assertIn("--dsw-alias-label-secondary", config["tokens"])
        self.assertEqual(config["options"]["material"], "liquid")
        self.assertEqual(config["options"]["wallpaper"], {"kind": "ambient"})

    def test_wallpaper_rejects_external_urls_svg_and_out_of_range_options(self):
        for options in ({"wallpaper": {"kind": "image", "dataUrl": "https://example.com/wall.jpg"}},
                        {"wallpaper": {"kind": "image", "dataUrl": "data:image/svg+xml;base64,PHN2Zz4="}},
                        {"canvasOpacity": -1}, {"glassBlur": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                runtime.clean_options(options)

    def test_preview_apply_and_pause_never_write_state_or_call_the_engine(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory, "CODEX_SKIN_PREVIEW": "1"}):
            status = runtime.apply_skin("dsh:nebula", {"accent": "#123456"})
            self.assertEqual(status["phase"], "preview")
            self.assertFalse(status["applied"])
            runtime.pause_skin()
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.persist.assert_not_called()
            self.restore.assert_not_called()

    def test_missing_connection_is_saved_as_waiting_not_success(self):
        waiting = {"phase": "waiting", "connected": False, "applied": False, "message": "not connected"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory}), \
             patch("runtime.run_engine", return_value=waiting), patch("runtime.start_watcher"), \
             patch("relaunch.schedule") as restart:
            status = runtime.apply_skin("dsh:nebula", {"accent": "#123456"})
            self.assertFalse(status["applied"])
            self.assertEqual(status["phase"], "waiting")
            self.assertTrue(status["nativeSaved"])
            self.assertTrue(runtime.current_preferences()["enabled"])
            self.assertEqual(runtime.current_preferences()["overrides"]["accent"], "#123456")
            self.assertFalse(runtime.runtime_status()["applied"])
            restart.assert_not_called()

    def test_restart_saves_the_selected_wallpaper_before_scheduling(self):
        waiting = {"phase": "waiting", "connected": False, "applied": False}
        restarting = {"phase": "restarting", "connected": False, "applied": False}
        image = "data:image/png;base64,YWJj"
        def schedule(directory):
            saved = json.loads((directory / "skin.json").read_text())
            self.assertEqual(saved["themeId"], "dsh:nebula")
            self.assertEqual(saved["options"]["wallpaper"]["dataUrl"], image)
            self.assertEqual(saved["native"]["theme"]["accent"], "#123456")
            return restarting
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory}), \
             patch("runtime.run_engine", return_value=waiting), patch("runtime.start_watcher"), \
             patch("relaunch.schedule", side_effect=schedule) as restart:
            status = runtime.apply_skin("dsh:nebula", {"accent": "#123456"},
                                        {"wallpaper": {"kind": "image", "dataUrl": image}}, True)
            self.assertEqual(status, {**restarting, "nativeSaved": True})
            restart.assert_called_once()

    def test_connected_apply_never_restarts(self):
        applied = {"phase": "applied", "connected": True, "applied": True}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory}), \
             patch("runtime.run_engine", return_value=applied), patch("runtime.start_watcher"), \
             patch("relaunch.schedule") as restart:
            self.assertEqual(runtime.apply_skin("dsh:nebula", restart_when_needed=True), {**applied, "nativeSaved": True})
            restart.assert_not_called()

    def test_native_save_failure_keeps_previous_skin_and_never_restarts(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory}), \
             patch("runtime.run_engine") as engine, patch("relaunch.schedule") as restart:
            path = Path(directory) / "skin.json"
            original = runtime.prepare("dsh:aurora")
            runtime.atomic_json(path, original)
            self.persist.side_effect = ValueError("configuration changed")
            with self.assertRaises(ValueError):
                runtime.apply_skin("dsh:nebula", restart_when_needed=True)
            self.assertEqual(json.loads(path.read_text()), original)
            engine.assert_not_called()
            restart.assert_not_called()

    def test_preview_cannot_schedule_a_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory, "CODEX_SKIN_PREVIEW": "1"}), \
             patch("relaunch.schedule") as restart:
            self.assertEqual(runtime.apply_skin("dsh:nebula", restart_when_needed=True)["phase"], "preview")
            restart.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_pause_retains_original_preferences_and_disables_restore(self):
        status = {"phase": "paused", "connected": True, "applied": False, "message": "removed"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_SKIN_STATE_DIR": directory}), \
             patch("runtime.run_engine", return_value=status), patch("runtime.start_watcher"), patch("runtime.stop_watcher"):
            runtime.apply_skin("dsh:aurora")
            path = Path(directory) / "skin.json"
            before = json.loads(path.read_text())
            runtime.pause_skin()
            after = json.loads(path.read_text())
            self.assertFalse(after.pop("enabled"))
            before.pop("enabled")
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
