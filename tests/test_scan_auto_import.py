"""Auto framing must retain page content and decline uncertain photos."""
import unittest
import cv2
import numpy as np
from PIL import Image
from markdown_to_handwrite.scanner import (
    _detect_page_geometry,
    _detect_small_contrast_quad,
    _detect_text_bounds,
    _perspective_from_visible_sides,
    process_scan_image,
)

class AutoImportTests(unittest.TestCase):
    def test_small_candidate_is_ambiguous_with_multiple_labels(self):
        gray = np.full((900, 1200), 150, dtype=np.uint8)
        for start, end in [((200, 180), (500, 410)), ((650, 500), (850, 620)), ((250, 600), (450, 720))]:
            cv2.rectangle(gray, start, end, 230, -1)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.morphologyEx(cv2.Canny(gray, 35, 125), cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
        contours = sorted(cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2],
                          key=cv2.contourArea, reverse=True)
        self.assertIsNotNone(_detect_small_contrast_quad(gray, contours))
        self.assertIsNone(_detect_small_contrast_quad(gray, contours, reject_competing=True))

    def test_small_paper_needs_boundary_contrast(self):
        photo = np.full((1000, 1200, 3), 55, dtype=np.uint8)
        expected = np.array([[400, 250], [700, 230], [740, 570], [410, 590]], np.int32)
        cv2.fillConvexPoly(photo, expected, (230, 230, 230))
        corners, _ = _detect_page_geometry(Image.fromarray(photo))
        self.assertIsNotNone(corners)
        self.assertLess(np.max(np.linalg.norm(np.asarray(corners) * [1200, 1000] - expected, axis=1)), 8)
        photo[:] = 230
        cv2.rectangle(photo, (400, 250), (700, 590), (50, 50, 50), -1)
        self.assertIsNone(_detect_page_geometry(Image.fromarray(photo))[0])

    def test_text_fallback_keeps_footer_and_trims_side_clutter(self):
        rgb = np.full((1200, 900, 3), 210, dtype=np.uint8)
        for row in range(140, 970, 55):
            for col in range(145, 835, 100):
                cv2.putText(rgb, 'Math', (col, row), cv2.FONT_HERSHEY_SIMPLEX, .42, (30, 30, 30), 1)
        cv2.putText(rgb, '1', (450, 1100), cv2.FONT_HERSHEY_SIMPLEX, .8, (20,20,20), 2)
        rgb[:300, :35] = (30, 30, 30)
        corners = _detect_text_bounds(rgb)
        self.assertIsNotNone(corners)
        self.assertGreater(corners[0][0], .02)
        self.assertGreater(corners[2][1], .92)
        output = process_scan_image(Image.fromarray(rgb), corners, 'smart')
        self.assertLess(output.getpixel((output.width//2, output.height-50))[0], 200)

    def test_sparse_or_dark_photo_has_no_content_crop(self):
        sparse = np.full((1200, 900, 3), 215, np.uint8)
        cv2.putText(sparse, 'one', (330, 500), cv2.FONT_HERSHEY_SIMPLEX, 1, (20,20,20), 2)
        self.assertIsNone(_detect_text_bounds(sparse))
        self.assertIsNone(_detect_text_bounds(np.full((1200, 900, 3), 45, np.uint8)))

    def test_visible_paper_sides_enable_perspective_correction(self):
        height, width = 1200, 900
        rgb = np.full((height, width, 3), 45, dtype=np.uint8)
        page = np.array([[65, 0], [805, 0], [895, 1199], [5, 1199]], dtype=np.int32)
        cv2.fillConvexPoly(rgb, page, (220, 220, 220))
        for row in range(120, 1080, 50):
            for col in range(125, 780, 90):
                cv2.putText(rgb, 'Math', (col, row), cv2.FONT_HERSHEY_SIMPLEX,
                            .42, (20, 20, 20), 1)
        corners = _detect_text_bounds(rgb)
        self.assertIsNotNone(corners)
        self.assertGreater(corners[0][0] - corners[3][0], .05)
        self.assertGreater(corners[2][0] - corners[1][0], .05)
        corrected = process_scan_image(Image.fromarray(rgb), corners, 'original')
        self.assertGreater(corrected.width, 800)

    def test_perspective_requires_both_visible_paper_sides(self):
        rgb = np.full((1200, 900, 3), 220, dtype=np.uint8)
        cv2.fillPoly(rgb, [np.array([[0, 0], [65, 0], [5, 1199], [0, 1199]])], (45, 45, 45))
        rectangle = [[.1, .05], [.9, .05], [.9, .95], [.1, .95]]
        self.assertIsNone(_perspective_from_visible_sides(rgb, rectangle))
