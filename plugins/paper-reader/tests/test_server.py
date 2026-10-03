"""Targeted checks for private PDF transport and input boundaries (no live Zotero needed)."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.pdf = Path(self.folder.name) / "source.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nprivate document content")
        self.library = server.Library()
        self.library.documents["test-document"] = {"path": self.pdf, "size": self.pdf.stat().st_size, "pages": 2}
        self.library_patch = patch.object(server, "LIBRARY", self.library)
        self.library_patch.start()

    def tearDown(self):
        self.library_patch.stop()
        self.folder.cleanup()

    def test_pdf_transport_uses_private_metadata(self):
        value = server.handle("tools/call", {"name": "read_pdf_chunk", "arguments": {
            "document_id": "test-document", "offset": 2, "length": 12}})
        self.assertEqual(base64.b64decode(value["_meta"]["reader_data"]["data"]), self.pdf.read_bytes()[2:14])
        self.assertNotIn("private document", json.dumps(value["content"]))
        self.assertNotIn("data", value["structuredContent"])

    def test_pdf_chunk_cannot_escape_open_documents(self):
        for arguments in [{"document_id": "../../etc/passwd"},
                          {"document_id": "test-document", "offset": -1},
                          {"document_id": "test-document", "length": server.CHUNK_BYTES + 1}]:
            with self.subTest(arguments=arguments):
                value = server.handle("tools/call", {"name": "read_pdf_chunk", "arguments": arguments})
                self.assertTrue(value["isError"])

    def test_invalid_pages_do_not_run_pdf_commands(self):
        with patch.object(server.subprocess, "run") as run:
            for page in [0, 3, True, "1"]:
                value = server.handle("tools/call", {"name": "read_paper_page", "arguments": {
                    "document_id": "test-document", "page": page}})
                self.assertTrue(value["isError"])
            run.assert_not_called()

    def test_unknown_arguments_are_rejected(self):
        value = server.handle("tools/call", {"name": "read_pdf_chunk", "arguments": {
            "document_id": "test-document", "path": "/etc/passwd"}})
        self.assertTrue(value["isError"])

    def test_stdio_can_negotiate_without_zotero(self):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        process = subprocess.run([sys.executable, str(server.ROOT / "server.py")],
                                 input="\n".join(map(json.dumps, requests)) + "\n", text=True,
                                 capture_output=True, timeout=10, check=True)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        private = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "read_pdf_chunk")
        self.assertEqual(private["_meta"]["ui"]["visibility"], ["app"])


if __name__ == "__main__":
    unittest.main()
