"""Text-line correction must flatten varying tilt without touching straight pages."""
import math
import unittest

import cv2
import numpy as np
from PIL import Image

from markdown_to_handwrite.scanner import _refine_text_angle, _straighten_text_rows, process_scan_image


class TextRowStraighteningTests(unittest.TestCase):
    @staticmethod
    def _page(width=900, height=1200, paper=230, ink=20):
        page = np.full((height, width, 3), paper, dtype=np.uint8)
        for row in range(80, round(height * .79), 48):
            cv2.putText(page, 'MATH 12345 x=2 y=7 TEST',
                        (round(width * .07), row), cv2.FONT_HERSHEY_SIMPLEX,
                        width / 1200, (ink, ink, ink), max(1, round(width / 450)),
                        cv2.LINE_AA)
        return page

    @staticmethod
    def _row_angle(page):
        gray = cv2.cvtColor(page, cv2.COLOR_RGB2GRAY)
        threshold = min(180, int(np.median(gray) - 30))
        joined = cv2.dilate((gray < threshold).astype(np.uint8) * 255,
                            np.ones((3, 25), np.uint8))
        contours = cv2.findContours(joined, cv2.RETR_EXTERNAL,
                                     cv2.CHAIN_APPROX_SIMPLE)[0]
        angles = []
        for contour in contours:
            _, _, width, height = cv2.boundingRect(contour)
            if width < page.shape[1] * .24 or height > page.shape[0] * .08:
                continue
            points = cv2.boxPoints(cv2.minAreaRect(contour))
            edges = [points[(index + 1) % 4] - points[index]
                     for index in range(4)]
            longest = max(edges, key=lambda edge: abs(edge[0]))
            angle = math.degrees(math.atan2(longest[1], longest[0]))
            if angle > 90:
                angle -= 180
            if angle < -90:
                angle += 180
            angles.append(angle)
        return float(np.median(angles))

    @staticmethod
    def _top_angle(page):
        gray = cv2.cvtColor(page, cv2.COLOR_RGB2GRAY)
        rows = cv2.morphologyEx((gray < 120).astype(np.uint8) * 255,
                                 cv2.MORPH_CLOSE, np.ones((2, 25), np.uint8))
        lines = cv2.HoughLinesP(rows, 1, np.pi / 720, 25,
                                minLineLength=140, maxLineGap=10)
        angles = []
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            midpoint = (int(y1) + int(y2)) / 2
            if abs(int(x2) - int(x1)) > 140 and 60 < midpoint < 240:
                angle = math.degrees(math.atan2(int(y2) - int(y1),
                                                 int(x2) - int(x1)))
                if abs(angle) < 10:
                    angles.append(angle)
        return float(np.median(angles))

    def test_varying_text_tilt_is_straightened(self):
        flat = self._page()
        height, width = flat.shape[:2]
        y = np.arange(height, dtype=np.float32)
        x = np.arange(width, dtype=np.float32)
        angles = np.interp(y / height, [0, .15, .35, .55, .8, 1],
                           [5, 5, 2, 0, -1, -1])
        map_x = np.broadcast_to(x, (height, width)).copy()
        map_y = (y[:, None] - np.tan(np.deg2rad(angles))[:, None]
                 * (x[None, :] - width / 2)).astype(np.float32)
        tilted = cv2.remap(flat, map_x, map_y, cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=(230, 230, 230))
        corrected = _straighten_text_rows(tilted)
        self.assertGreater(self._top_angle(tilted), 3)
        self.assertLess(abs(self._top_angle(corrected)), 1.5)
        self.assertEqual(corrected.shape, tilted.shape)

    def test_straight_page_is_unchanged(self):
        page = self._page()
        self.assertTrue(np.array_equal(_straighten_text_rows(page), page))

    def test_top_only_text_can_be_straightened(self):
        page = np.full((1200, 900, 3), 230, dtype=np.uint8)
        for row in [95, 140, 185, 230, 275]:
            cv2.putText(page, 'MATH 12345 x=2 y=7 TEST', (70, row),
                        cv2.FONT_HERSHEY_SIMPLEX, .75, (20, 20, 20), 2, cv2.LINE_AA)
        height, width = page.shape[:2]
        y = np.arange(height, dtype=np.float32)
        x = np.arange(width, dtype=np.float32)
        map_x = np.broadcast_to(x, (height, width)).copy()
        map_y = (y[:, None] - math.tan(math.radians(4))
                 * (x[None, :] - width / 2)).astype(np.float32)
        tilted = cv2.remap(page, map_x, map_y, cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(230, 230, 230))
        corrected = _straighten_text_rows(tilted)
        self.assertGreater(abs(self._row_angle(tilted)), 3)
        self.assertLess(abs(self._row_angle(corrected)), 1)

    def test_sparse_diagram_lines_are_not_treated_as_text(self):
        page = np.full((1200, 900, 3), 230, dtype=np.uint8)
        for row in [95, 140, 185, 230, 275]:
            cv2.line(page, (70, row), (400, row + 25), (20, 20, 20), 2)
        self.assertTrue(np.array_equal(_straighten_text_rows(page), page))

    def test_small_text_page_is_corrected_at_original_resolution(self):
        page = cv2.resize(self._page(), (360, 480), interpolation=cv2.INTER_AREA)
        height, width = page.shape[:2]
        y = np.arange(height, dtype=np.float32)
        x = np.arange(width, dtype=np.float32)
        for angle in (-5, 5):
            with self.subTest(angle=angle):
                tilted = cv2.remap(page, np.broadcast_to(x, (height, width)).copy(),
                                   (y[:, None] - math.tan(math.radians(angle)) * (x[None, :] - width / 2)).astype(np.float32),
                                   cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(230, 230, 230))
                corrected = _straighten_text_rows(tilted)
                self.assertEqual(corrected.shape, tilted.shape)
                self.assertGreater(abs(self._row_angle(tilted)), 3)
                self.assertLess(abs(self._row_angle(corrected)), 1)
                unframed = np.asarray(process_scan_image(Image.fromarray(tilted), None, 'original'))
                self.assertLess(abs(self._row_angle(unframed)), 1)

    def test_small_high_texture_image_is_unchanged(self):
        rng = np.random.default_rng(12)
        image = rng.integers(30, 220, (480, 360, 3), dtype=np.uint8)
        self.assertTrue(np.array_equal(_straighten_text_rows(image), image))

    def test_projection_refines_a_biased_angle_estimate(self):
        page = self._page()
        height, width = page.shape[:2]
        y = np.arange(height, dtype=np.float32)
        x = np.arange(width, dtype=np.float32)
        tilted = cv2.remap(page, np.broadcast_to(x, (height, width)).copy(),
                           (y[:, None] - math.tan(math.radians(-5)) * (x[None, :] - width / 2)).astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(230, 230, 230))
        ink = (cv2.cvtColor(tilted, cv2.COLOR_RGB2GRAY) < 120).astype(np.uint8)
        self.assertAlmostEqual(_refine_text_angle(ink, -3.4), -5, delta=.3)
        self.assertEqual(_refine_text_angle(np.zeros_like(ink), 3), 3)

    def test_mask_follows_the_same_correction_as_image(self):
        page = self._page()
        height, width = page.shape[:2]
        y = np.arange(height, dtype=np.float32)
        x = np.arange(width, dtype=np.float32)
        page = cv2.remap(page, np.broadcast_to(x, (height, width)).copy(),
                         (y[:, None] - math.tan(math.radians(4)) * (x[None, :] - width / 2)).astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(230, 230, 230))
        page[990:1020, 700:730] = 0
        mask = np.zeros((height, width), dtype=bool)
        mask[990:1020, 700:730] = True
        corrected = _straighten_text_rows(page, mask)
        local_mask = mask[950:1050, 650:780]
        self.assertGreater(np.count_nonzero(local_mask), 800)
        self.assertLess(np.mean(corrected[950:1050, 650:780][local_mask]), 10)
        self.assertFalse(np.array_equal(mask, np.pad(np.ones((30, 30), bool), ((990, 180), (700, 170)))))

    def test_uniform_tilt_on_multiple_page_sizes_and_contrasts(self):
        cases = [
            (900, 1200, 230, 20, 5),
            (900, 1200, 230, 20, -5),
            (900, 1200, 180, 95, -4),
            (1200, 900, 230, 20, 4),
            (700, 1000, 220, 30, -3),
        ]
        for width, height, paper, ink, angle in cases:
            with self.subTest(size=(width, height), angle=angle):
                page = self._page(width, height, paper, ink)
                y = np.arange(height, dtype=np.float32)
                x = np.arange(width, dtype=np.float32)
                map_x = np.broadcast_to(x, (height, width)).copy()
                map_y = (y[:, None] - math.tan(math.radians(angle))
                         * (x[None, :] - width / 2)).astype(np.float32)
                tilted = cv2.remap(page, map_x, map_y, cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT,
                                   borderValue=(paper, paper, paper))
                corrected = _straighten_text_rows(tilted)
                self.assertGreater(abs(self._row_angle(tilted)), 2)
                self.assertLess(abs(self._row_angle(corrected)), 1)
                self.assertEqual(corrected.shape, tilted.shape)


if __name__ == '__main__':
    unittest.main()
