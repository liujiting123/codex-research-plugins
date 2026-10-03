"""Public-behavior tests for DSH palette conversion and local imports."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

import themes


ASSET_PACKS = Path(__file__).resolve().parent / "assets" / "dsh-themes.json"


def builtin_packs() -> list[dict]:
    return json.loads(ASSET_PACKS.read_text(encoding="utf-8"))


class ThemeConversionTests(unittest.TestCase):
    def test_real_builtin_palettes_convert_and_round_trip_as_native_import_codes(self):
        expected = {
            "abyss": ("#101014", "#f4f5f7", "#5e6ad2"),
            "aurora": ("#0e1316", "#eefaf4", "#2dd4bf"),
            "nebula": ("#12101a", "#f3f0fb", "#8b7cf6"),
            "ember": ("#16110d", "#fdf0e6", "#f59e5b"),
            "midnight": ("#0b0b0e", "#f2f2f6", "#7c8cff"),
            "ivory": ("#f4f4f6", "#1c1c1e", "#0071e3"),
            "mist": ("#e9eef6", "#0f1b33", "#2196f3"),
            "rose": ("#f7f0f3", "#3a1424", "#e91e63"),
        }
        with tempfile.TemporaryDirectory() as directory:
            catalog = themes.library(
                dsh_paths=[], saved_path=Path(directory) / "missing-library.json"
            )

        records = {record["sourceId"]: record for record in catalog["themes"]}
        self.assertEqual(set(records), set(expected))
        for source_id, (surface, ink, accent) in expected.items():
            with self.subTest(theme=source_id):
                record = records[source_id]
                native = themes.validate_native(record["native"])
                self.assertEqual(
                    (native["theme"]["surface"], native["theme"]["ink"], native["theme"]["accent"]),
                    (surface, ink, accent),
                )
                imported = themes.parse_import(themes.share_code(native))
                self.assertEqual(imported["native"], native)

    def test_rgb_rgba_and_hsl_colors_convert_to_hex(self):
        self.assertEqual(themes.hex_color("rgb(255, 0, 128)"), "#ff0080")
        self.assertEqual(themes.hex_color("rgba(255, 0, 0, 0.5)"), "#800000")
        self.assertEqual(themes.hex_color("hsl(120, 100%, 50%)"), "#00ff00")

    def test_dsh_share_link_imports_a_theme_pack(self):
        pack = builtin_packs()[0]
        raw = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        link = "https://dsh.example/#dream-skin-pack=" + quote(encoded, safe="")

        imported = themes.parse_import(link)

        self.assertEqual(imported["sourceId"], pack["manifest"]["id"])
        self.assertEqual(imported["nameEn"], pack["manifest"]["name"])
        self.assertEqual(imported["native"]["variant"], pack["manifest"]["colorScheme"])

    def test_reads_the_persisted_dsh_id_manifest_record_without_other_settings(self):
        manifest = deepcopy(builtin_packs()[0]["manifest"])
        manifest.update({
            "id": "persisted-local",
            "name": "Persisted Local",
            "nameZh": "本地主题",
            "accent": None,
        })
        entry = {"id": "dream-pack:persisted-local", "manifest": manifest}
        state = {
            "dsh-dream-skin:skin": "dream-pack:persisted-local",
            "dsh-dream-skin:packs": json.dumps([entry], ensure_ascii=False),
            "dsh-dream-skin:wallpaper": "synthetic wallpaper fixture",
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "dream-skin.json"
            library_path = Path(directory) / "library.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            selected_state = themes.read_dsh_state(state_path)
            catalog = themes.library(dsh_paths=[state_path], saved_path=library_path)

        self.assertEqual(set(selected_state), {"current", "packs"})
        self.assertEqual(selected_state["packs"], [entry])
        self.assertTrue(catalog["dshFound"])
        self.assertEqual(catalog["dshCurrentId"], "dsh:persisted-local")
        persisted = next(record for record in catalog["themes"] if record["id"] == "dsh:persisted-local")
        self.assertEqual(persisted["nameEn"], "Persisted Local")
        self.assertEqual(persisted["name"], "本地主题")
        themes.validate_native(persisted["native"])

    def test_import_rejects_unknown_css_and_active_content_as_colors(self):
        for unsafe_value in (
            "var(--untrusted-color)",
            "linear-gradient(red, blue)",
            "url(javascript:alert(1))",
        ):
            with self.subTest(value=unsafe_value):
                pack = deepcopy(builtin_packs()[0])
                pack["manifest"]["tokens"]["--dsw-alias-bg-base"] = unsafe_value
                with self.assertRaises(ValueError):
                    themes.parse_import(json.dumps(pack))

    def test_failed_import_leaves_existing_library_byte_for_byte_unchanged(self):
        valid_raw = json.dumps(builtin_packs()[0], ensure_ascii=False)
        invalid_pack = deepcopy(builtin_packs()[1])
        invalid_pack["manifest"]["tokens"]["--dsw-alias-brand-primary"] = "url(javascript:alert(1))"

        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "library.json"
            themes.save_import(valid_raw, path=library_path)
            before = library_path.read_bytes()

            with self.assertRaises(ValueError):
                themes.save_import(json.dumps(invalid_pack), path=library_path)

            self.assertEqual(library_path.read_bytes(), before)
            self.assertEqual(len(json.loads(before)), 1)

    def test_reimporting_the_same_pack_is_idempotent(self):
        raw = json.dumps(builtin_packs()[0], ensure_ascii=False)

        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / "library.json"
            first = themes.save_import(raw, path=library_path)
            after_first = library_path.read_bytes()
            second = themes.save_import(raw, path=library_path)

            self.assertEqual(second["id"], first["id"])
            self.assertEqual(library_path.read_bytes(), after_first)
            self.assertEqual(len(json.loads(after_first)), 1)


if __name__ == "__main__":
    unittest.main()
