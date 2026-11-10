import io
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.scanner import _clear_partial_corner_artifacts, _detect_clipped_top_page, _detect_color_separated_page, _detect_partial_page, _estimate_page_skew, _order_points, process_scan_image, validate_page_corners, ScanService


class ScanCornerTests(unittest.TestCase):
    def test_color_separation_recovers_complete_paper_on_warm_surface(self):
        rng = np.random.default_rng(5)
        rgb = np.full((600, 500, 3), (175, 125, 75), dtype=np.uint8)
        expected = np.array([[75, 55], [425, 60], [450, 540], [50, 540]])
        cv2.fillConvexPoly(rgb, expected, (220, 220, 215))
        rgb = np.clip(rgb.astype(float) + rng.normal(0, 5, rgb.shape), 0, 255).astype(np.uint8)
        result = _detect_color_separated_page(rgb)
        self.assertIsNotNone(result)
        actual = np.asarray(result) * [500, 600]
        self.assertLess(np.max(np.linalg.norm(actual - expected, axis=1)), 12)

    def test_color_separation_rejects_incomplete_or_unverified_page(self):
        warm = np.full((600, 500, 3), (175, 125, 75), dtype=np.uint8)
        self.assertIsNone(_detect_color_separated_page(warm))
        # White page touching the image boundary lacks evidence for every side.
        cv2.rectangle(warm, (60, 60), (440, 599), (225, 225, 225), -1)
        self.assertIsNone(_detect_color_separated_page(warm))

    def test_deskew_expands_canvas_and_uses_white_corners(self):
        image = Image.new("RGB", (300, 200), "white")
        ImageDraw.Draw(image).rectangle((0, 0, 12, 12), fill="black")
        result = process_scan_image(image, None, "original", deskew_angle=6)
        self.assertGreater(result.width, image.width)
        self.assertGreater(result.height, image.height)
        self.assertEqual(result.getpixel((result.width - 1, 0)), (255, 255, 255))
        self.assertLess(np.asarray(result).min(), 30)

    def test_deskew_requires_evidence(self):
        image = Image.new("RGB", (400, 300), "white")
        self.assertEqual(_estimate_page_skew(image, [[0, 0], [.999, 0], [.999, .999], [0, .999]]), 0)

    def test_clipped_top_page_detects_book_gutter_and_keeps_top_as_image_boundary(self):
        image = np.full((784, 1080), 130, dtype=np.uint8)
        image[:, :110] = 175
        cv2.fillConvexPoly(image, np.array([[110, 0], [745, 0], [1060, 60], [1054, 783], [95, 783]]), 225)
        result = _detect_clipped_top_page(cv2.GaussianBlur(image, (5, 5), 0))
        self.assertIsNotNone(result)
        corners, partial = result
        self.assertAlmostEqual(corners[0][1], 0)
        self.assertAlmostEqual(corners[1][1], 0)
        self.assertGreater(corners[0][0], .07)
        self.assertLess(corners[0][0], .14)
        self.assertIn("topClip", partial)
        self.assertIsNone(_detect_clipped_top_page(np.full((784, 1080), 220, dtype=np.uint8)))

    def test_top_clip_cleans_exterior_without_cutting_top_edge_content(self):
        image = Image.new("RGB", (400, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((300, 0, 399, 35), fill=(80, 80, 80))
        draw.rectangle((90, 0, 110, 8), fill="black")
        for mode in ("smart", "shadow", "bw"):
            with self.subTest(mode=mode):
                result = process_scan_image(image, None, mode, top_clip=[[.5, 0], [1, .2]])
                self.assertEqual(result.getpixel((350, 2)), (255, 255, 255))
                if mode == "bw":
                    self.assertEqual(result.getpixel((100, 3)), (255, 255, 255))
                    self.assertLess(result.getpixel((100, 6))[0], 100)
                else:
                    self.assertLess(result.getpixel((100, 3))[0], 100)
        original = process_scan_image(image, None, "original", top_clip=[[.5, 0], [1, .2]])
        self.assertEqual(original.getpixel((350, 2)), (80, 80, 80))

    def test_clipped_top_preview_and_main_scan_share_geometry(self):
        image = np.full((784, 1080), 130, dtype=np.uint8)
        image[:, :110] = 175
        cv2.fillConvexPoly(image, np.array([[110, 0], [745, 0], [1060, 60], [1054, 783], [95, 783]]), 225)
        cv2.putText(image, "TOP", (220, 25), cv2.FONT_HERSHEY_SIMPLEX, .8, 0, 2)
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            scan_id = service.upload("clipped.png", buffer.getvalue())["scanId"]
            root = Path(folder) / scan_id
            result = service.process(scan_id, {"mode": "smart"})
            self.assertTrue(result["autoCorners"])
            preview = service.filter_preview(scan_id, {"mode": "smart"})
            with Image.open(root / "current.png") as full, Image.open(root / Path(preview["url"]).name) as thumb:
                expected = full.copy()
                expected.thumbnail((400, 400), Image.Resampling.LANCZOS)
                self.assertEqual(thumb.size, expected.size)
                self.assertLess(np.abs(np.asarray(thumb.convert("RGB")).astype(float) - np.asarray(expected.convert("RGB")).astype(float)).mean(), 3)

    def test_partial_page_detection_requires_three_page_edges(self):
        image = np.full((600, 400), 100, dtype=np.uint8)
        cv2.fillConvexPoly(image, np.array([[30, 35], [370, 55], [370, 599], [30, 599]]), 220)
        points = _detect_partial_page(cv2.GaussianBlur(image, (5, 5), 0))
        self.assertIsNotNone(points)
        self.assertLess(points[0][0], .1)
        self.assertGreater(points[1][0], .9)
        self.assertGreater(points[2][1], .99)
        self.assertIsNone(_detect_partial_page(np.full((600, 400), 220, dtype=np.uint8)))

    def test_corner_cleanup_removes_dense_block_but_preserves_edge_text_and_border_line(self):
        image = Image.new("RGB", (1000, 1000), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((985, 750, 999, 999), fill="black")
        draw.rectangle((997, 400, 999, 699), fill=(190, 190, 190))
        draw.line((0, 100, 0, 999), fill="black", width=2)
        draw.rectangle((980, 200, 999, 210), fill="black")
        result = _clear_partial_corner_artifacts(image)
        self.assertEqual(result.getpixel((995, 900)), (255, 255, 255))
        self.assertEqual(result.getpixel((998, 500)), (255, 255, 255))
        self.assertEqual(result.getpixel((0, 500)), (0, 0, 0))
        self.assertEqual(result.getpixel((990, 205)), (0, 0, 0))

    def test_partial_edge_cleanup_is_only_enabled_for_automatic_smart_scan(self):
        image = Image.new("RGB", (1000, 1000), "white")
        ImageDraw.Draw(image).rectangle((985, 750, 999, 999), fill="black")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            scan_id = service.upload("partial.png", buffer.getvalue())["scanId"]
            root = Path(folder) / scan_id
            metadata = json.loads((root / "scan.json").read_text())
            metadata.update(corners=[[0, 0], [.999, 0], [.999, .999], [0, .999]], partialCorners=True)
            (root / "scan.json").write_text(json.dumps(metadata))
            service.process(scan_id, {"mode": "smart"})
            with Image.open(root / "current.png") as automatic:
                self.assertGreater(automatic.getpixel((990, 900))[0], 240)
            service.process(scan_id, {"mode": "smart", "corners": metadata["corners"]})
            with Image.open(root / "current.png") as manual:
                self.assertLess(manual.getpixel((990, 900))[0], 100)

    def test_diamond_order_never_duplicates_a_corner(self):
        points = np.array([[50, 0], [100, 50], [50, 100], [0, 50]], dtype=np.float32)
        ordered = _order_points(points[[2, 0, 3, 1]])
        self.assertEqual(len(set(map(tuple, ordered))), 4)
        self.assertTrue(cv2.isContourConvex(ordered))

    def test_invalid_quadrilaterals_are_rejected(self):
        cases = [[], [[0, 0]] * 4, [[0, 0], [1, 1], [1, 0], [0, 1]],
                 [[0, 0], [1.1, 0], [1, 1], [0, 1]],
                 [[0, 0], [True, 0], [1, 1], [0, 1]],
                 [[0, 0], [float("nan"), 0], [1, 1], [0, 1]],
                 [[0, 0], [.01, 0], [.01, .01], [0, .01]]]
        for points in cases:
            with self.subTest(points=points), self.assertRaises(ValueError):
                validate_page_corners(points)

    def test_manual_corners_apply_to_export_and_previews_without_changing_auto_detection(self):
        image = Image.new("RGB", (400, 300), (70, 70, 70))
        ImageDraw.Draw(image).polygon([(60, 40), (340, 60), (300, 260), (40, 220)], fill="white")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            uploaded = service.upload("paper.png", buffer.getvalue())
            root = Path(folder) / uploaded["scanId"]
            metadata_before = (root / "scan.json").read_bytes()
            points = [[.15, .133333], [.85, .2], [.75, .866667], [.1, .733333]]
            result = service.process(uploaded["scanId"], {"mode": "original", "corners": points})
            self.assertEqual(result["warning"], "")
            with Image.open(root / "current.png") as corrected:
                self.assertLess(corrected.width, 400)
                self.assertLess(corrected.height, 300)
                self.assertGreater(np.mean(np.asarray(corrected)[10:-10, 10:-10]), 250)
            first = service.filter_preview(uploaded["scanId"], {"mode": "original", "corners": points})
            second = service.filter_preview(uploaded["scanId"], {"mode": "original", "corners": [[0,0],[1,0],[1,1],[0,1]]})
            self.assertNotEqual(first["url"], second["url"])
            self.assertEqual(metadata_before, (root / "scan.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
