"""Regressions for distinct exposure, color and local threshold behaviour."""
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.scanner import process_scan_image
from markdown_to_handwrite.handwriting_removal import _detail_probability


class ScanEnhancementTests(unittest.TestCase):
    def test_bright_preserves_colored_ink_ratios(self):
        image = Image.new('RGB', (300, 200), (150, 150, 150))
        ImageDraw.Draw(image).line((20, 100, 280, 100), fill=(30, 60, 120), width=3)
        r, g, b = process_scan_image(image, None, 'bright').getpixel((150, 100))
        self.assertGreater(r, 30)
        self.assertAlmostEqual(g/r, 2, delta=.04)
        self.assertAlmostEqual(b/r, 4, delta=.08)

    def test_bright_adapts_exposure_and_retains_near_white_steps(self):
        dark = process_scan_image(Image.new('RGB', (100, 100), (100,)*3), None, 'bright')
        light = process_scan_image(Image.new('RGB', (100, 100), (240,)*3), None, 'bright')
        self.assertGreater(dark.getpixel((50, 50))[0] / 100, light.getpixel((50, 50))[0] / 240)
        self.assertLess(light.getpixel((50, 50))[0], 255)

    def test_bw_keeps_medium_width_pencil_with_black_heading(self):
        image = Image.new('RGB', (600, 600), (220,)*3)
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 550, 55), fill='black')
        draw.rectangle((100, 300, 500, 308), fill=(160,)*3)
        result = process_scan_image(image, None, 'bw')
        self.assertLess(result.getpixel((300, 304))[0], 150)
        self.assertEqual(result.getpixel((300, 400)), (255,)*3)

    def test_shadow_retains_interior_of_colored_table_fill(self):
        image = Image.new('RGB', (600, 600), (220,)*3)
        ImageDraw.Draw(image).rectangle((100, 100, 400, 300), fill=(80, 120, 180))
        r, g, b = process_scan_image(image, None, 'shadow').getpixel((250, 200))
        self.assertGreater(b-r, 70)
        self.assertGreater(g-r, 25)

    def test_smart_lifts_shadowed_colored_pen_without_changing_hue(self):
        image = Image.new('RGB', (400, 300), (150,)*3)
        ImageDraw.Draw(image).line((30, 100, 370, 100), fill=(20, 40, 100), width=3)
        r, g, b = process_scan_image(image, None, 'smart').getpixel((200, 100))
        self.assertGreater(b, 140)
        self.assertAlmostEqual(g/r, 2, delta=.08)
        self.assertAlmostEqual(b/r, 5, delta=.15)

    def test_detail_recovers_stroke_at_previous_tile_boundary(self):
        image = np.zeros((900, 1100, 3), dtype=np.uint8)
        image[450:460, 695:705] = 1
        def predict(model, tile, enlarge):
            response = tile[:, :, 0].astype(np.float32)
            # Mimic a detector needing surrounding context at tile edges.
            response[:32] = response[-32:] = 0
            response[:, :32] = response[:, -32:] = 0
            return response
        with patch('markdown_to_handwrite.handwriting_removal._predict', side_effect=predict):
            result = _detail_probability(None, image)
        self.assertGreater(result[455, 700], .8)
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(result[400, 700], 0)
