import http.client
import tempfile
import threading
import unittest
import shutil
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from PIL import Image

from markdown_to_handwrite.config import config_from_dict
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import LimitedHTTPServer, RenderService, WebApp, validate_config, main


class WebSafetyTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected(self):
        for config in ({"page": {"margin_top_mm": "22"}},
                       {"handwriting": {"seed": {}}},
                       {"page": False}, {"page": {"dpi": True}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                config_from_dict(config)

    def test_high_resolution_a4_is_allowed(self):
        validate_config(config_from_dict({"page": {"dpi": 600}}))

    def test_long_input_and_custom_font_reach_parser(self):
        with tempfile.TemporaryDirectory() as tmp, patch("markdown_to_handwrite.web.parse_markdown", side_effect=ValueError("parser reached")):
            with self.assertRaisesRegex(ValueError, "parser reached"):
                RenderService(Path(tmp)).render("a" * 50_001, {"handwriting": {"font_path": str(Path(tmp) / "custom.ttf")}})

    def test_custom_font_outside_project_works_in_local_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            font = root / "custom.ttf"
            shutil.copyfile(Path(__file__).resolve().parents[1] / "font" / "Latin-Caveat-Regular.ttf", font)
            result = RenderService(root / "output").render("Local font test", {
                "page": {"dpi": 96},
                "handwriting": {"font_path": str(font), "latin_font_path": str(font), "sdt_trajectory_enabled": False},
            })
            self.assertTrue((root / "output" / result["jobId"] / "markdown-to-handwrite.pdf").is_file())

    def test_total_pixel_budget_stops_before_allocating_another_page(self):
        renderer = object.__new__(ReportRenderer)
        renderer.pages = [object()]
        renderer.page_w = renderer.page_h = 100
        renderer.max_total_pixels = 19_999
        with self.assertRaisesRegex(ValueError, "页数或分辨率过大"):
            renderer._new_page()

    def test_failed_export_removes_only_its_incomplete_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing"
            existing.mkdir()
            (existing / "keep.txt").write_text("keep")
            with patch("markdown_to_handwrite.web.ReportRenderer") as renderer_class:
                renderer = renderer_class.return_value
                renderer.render.return_value = [Image.new("RGB", (2, 2))]
                renderer.warnings = []
                with patch("markdown_to_handwrite.web._save_page_images", side_effect=OSError("export failed")):
                    with self.assertRaisesRegex(OSError, "export failed"):
                        RenderService(root).render("hello", {})
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["existing"])
            self.assertEqual((existing / "keep.txt").read_text(), "keep")

    def test_host_origin_and_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = WebApp(Path(tmp))
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port
            try:
                def request(method, path, headers, body=None):
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    try:
                        conn.request(method, path, body=body, headers=headers)
                        response = conn.getresponse()
                        response.read()
                        return response.status
                    finally:
                        conn.close()

                self.assertEqual(request("GET", "/api/health", {}), 200)
                self.assertEqual(request("GET", "/api/health", {"Host": f"evil.example:{port}"}), 403)
                self.assertEqual(request("POST", "/api/render", {"Origin": "https://evil.example", "Content-Type": "application/json"}, "{}"), 403)
                self.assertEqual(request("POST", "/api/render", {"Content-Type": "application/json"}, "{}"), 403)
                self.assertEqual(request("POST", "/api/render", {"Content-Type": "text/plain", "X-Miaobi-Token": app.csrf_token}, "{}"), 415)
                self.assertEqual(request("POST", "/api/render", {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json", "X-Miaobi-Token": app.csrf_token}, "{}"), 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_connection_limit_rejects_overload_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = LimitedHTTPServer(("127.0.0.1", 0), WebApp(Path(tmp)).handler_class(), max_connections=1)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertTrue(server._connection_slots.acquire(blocking=False))
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/api/health")
                self.assertEqual(conn.getresponse().status, 503)
                conn.close()
                server._connection_slots.release()
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_local_scan_does_not_have_server_five_page_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = WebApp(Path(tmp))
            with self.assertRaisesRegex(ValueError, "已失效"):
                app.scan_service.export([f"{i:016x}" for i in range(6)], "pdf")

    def test_server_does_not_bind_to_public_interfaces(self):
        with self.assertRaises(SystemExit):
            main(["--host", "0.0.0.0", "--no-browser"])


if __name__ == "__main__":
    unittest.main()
