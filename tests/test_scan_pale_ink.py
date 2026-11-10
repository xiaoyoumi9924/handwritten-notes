"""Behavioral checks for faded pens and two adjacent out-of-frame edges."""
import unittest
import cv2
import numpy as np
from PIL import Image, ImageDraw
from markdown_to_handwrite.scanner import _detect_corner_clipped_page, process_scan_image


class PalePenTests(unittest.TestCase):
    def test_faded_red_and_blue_remain_colored_with_white_paper(self):
        image = Image.new('RGB', (600, 500), (195, 189, 180))
        draw = ImageDraw.Draw(image)
        draw.line((40, 100, 550, 100), fill=(160, 127, 124), width=3)
        draw.line((40, 200, 550, 200), fill=(125, 133, 159), width=3)
        draw.line((40, 300, 550, 300), fill=(65, 65, 65), width=3)
        output = process_scan_image(image, None, 'smart')
        red, blue, black = [output.getpixel((250, y)) for y in (100, 200, 300)]
        self.assertGreater(red[0]-red[1], 35)
        self.assertGreater(blue[2]-blue[0], 30)
        self.assertLess(max(black)-min(black), 4)
        self.assertLess(max(black), 100)
        self.assertEqual(output.getpixel((250, 400)), (255,)*3)

    def test_paper_tint_does_not_color_neutral_pencil(self):
        for paper in ((195, 189, 180), (180, 195, 215)):
            image = Image.new('RGB', (500, 400), paper)
            ImageDraw.Draw(image).line((40, 200, 450, 200), fill=(110,)*3, width=3)
            output = process_scan_image(image, None, 'smart')
            pixel = output.getpixel((250, 200))
            self.assertLess(max(pixel)-min(pixel), 4)
            self.assertEqual(output.getpixel((250, 300)), (255,)*3)

    def test_corner_clipped_page_all_rotations(self):
        image = np.full((900, 700), 75, np.uint8)
        expected = np.array([[0, 0], [520, 0], [640, 820], [0, 870]])
        cv2.fillConvexPoly(image, expected, 215)
        for rotation in range(4):
            work = np.ascontiguousarray(np.rot90(image, rotation))
            result = _detect_corner_clipped_page(cv2.GaussianBlur(work, (5, 5), 0))
            self.assertIsNotNone(result, rotation)
            points = np.asarray(result)*[work.shape[1], work.shape[0]]
            detected = np.zeros_like(work)
            cv2.fillConvexPoly(detected, np.rint(points).astype(np.int32), 1)
            truth = work > 150
            self.assertGreater(np.logical_and(detected, truth).sum()/np.logical_or(detected, truth).sum(), .98)

    def test_clipped_fallback_rejects_blank_paper_and_internal_rules(self):
        image = np.full((900, 700), 215, np.uint8)
        self.assertIsNone(_detect_corner_clipped_page(image))
        cv2.line(image, (520, 0), (640, 820), 0, 3)
        cv2.line(image, (0, 870), (640, 820), 0, 3)
        self.assertIsNone(_detect_corner_clipped_page(cv2.GaussianBlur(image, (5, 5), 0)))
