import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.scanner import ScanService, process_scan_image


class ScanPreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = ScanService(Path(self.folder.name))
        image = Image.new("RGB", (280, 180), (160, 170, 180))
        ImageDraw.Draw(image).line((20, 80, 250, 80), fill="black", width=2)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        self.scan_id = self.service.upload("notes.png", buffer.getvalue())["scanId"]
        self.root = Path(self.folder.name) / self.scan_id
        # Isolate filter behavior from edge detection in this test.
        metadata = json.loads((self.root / "scan.json").read_text())
        metadata["corners"] = None
        (self.root / "scan.json").write_text(json.dumps(metadata))
        self.image = image

    def test_thumbnail_uses_full_pipeline_without_changing_export_result(self):
        self.service.process(self.scan_id, {"mode": "original"})
        before = (self.root / "current.png").read_bytes()
        result = self.service.filter_preview(self.scan_id, {"mode": "bw", "rotation": 90})
        preview_path = self.root / Path(result["url"]).name
        with Image.open(preview_path) as preview:
            expected = process_scan_image(self.image, None, "bw", rotation=90)
            self.assertEqual(preview.size, expected.size)
            # WebP thumbnails use lossy encoding; compare with a small tolerance.
            difference = np.abs(np.asarray(preview.convert("RGB")).astype(float) - np.asarray(expected).astype(float))
            self.assertLess(difference.mean(), 3)
        self.assertEqual(before, (self.root / "current.png").read_bytes())

    def test_original_mode_reuses_identical_processed_page(self):
        with patch("markdown_to_handwrite.scanner.process_scan_image", wraps=process_scan_image) as process:
            self.service.process(self.scan_id, {"mode": "original"})
        self.assertEqual(process.call_count, 1)
        with Image.open(self.root / "current.png") as current, Image.open(self.root / "aligned-original.png") as aligned:
            self.assertEqual(current.tobytes(), aligned.tobytes())

    def test_cached_preview_is_reused_and_geometry_has_distinct_keys(self):
        first = self.service.filter_preview(self.scan_id, {"mode": "smart"})
        with patch("markdown_to_handwrite.scanner.process_scan_image", side_effect=AssertionError("cache miss")):
            self.assertEqual(first, self.service.filter_preview(self.scan_id, {"mode": "smart"}))
        rotated = self.service.filter_preview(self.scan_id, {"mode": "smart", "rotation": 90})
        cropped = self.service.filter_preview(self.scan_id, {"mode": "smart", "crop": [0, 0, 0.5, 0.5]})
        self.assertEqual(len({first["url"], rotated["url"], cropped["url"]}), 3)

    def test_unsupported_mode_cannot_create_a_fake_preview(self):
        with self.assertRaises(ValueError):
            self.service.filter_preview(self.scan_id, {"mode": "nonexistent_filter"})
        self.assertFalse((self.root / "current.png").exists())


if __name__ == "__main__":
    unittest.main()
