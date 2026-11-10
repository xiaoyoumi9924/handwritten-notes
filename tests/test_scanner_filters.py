import unittest

import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.scanner import process_scan_image


class ScanFilterTests(unittest.TestCase):
    def test_shadow_lifts_dark_paper_and_preserves_contrast(self):
        image = Image.new("RGB", (600, 600), (80, 80, 80))
        ImageDraw.Draw(image).line((50, 300, 550, 300), fill=(44, 44, 44), width=3)
        result = process_scan_image(image, None, "shadow")
        self.assertGreater(result.getpixel((200, 200))[0], 215)
        self.assertLess(result.getpixel((200, 300))[0], 100)

    def test_shadow_preserves_medium_width_faint_stroke(self):
        image = Image.new("RGB", (600, 600), (220, 220, 220))
        ImageDraw.Draw(image).rectangle((100, 100, 400, 108), fill=(160, 160, 160))
        result = process_scan_image(image, None, "shadow")
        self.assertLess(result.getpixel((250, 104))[0], 180)
        self.assertGreater(result.getpixel((250, 250))[0], 245)

    def test_smart_keeps_medium_width_faint_stroke_and_whitens_paper(self):
        image = Image.new("RGB", (600, 600), (220, 220, 220))
        ImageDraw.Draw(image).rectangle((100, 100, 400, 108), fill=(160, 160, 160))
        result = process_scan_image(image, None, "smart")
        self.assertLess(result.getpixel((250, 104))[0], 180)
        self.assertEqual(result.getpixel((250, 250)), (255, 255, 255))

    def test_shadow_cleans_paper_without_fading_faint_ink(self):
        image = Image.new("RGB", (400, 300), (175, 175, 175))
        ImageDraw.Draw(image).line((20, 150, 380, 150), fill=(115, 115, 115), width=2)
        result = process_scan_image(image, None, "shadow")
        self.assertGreater(result.getpixel((200, 200))[0], 248)
        self.assertLess(result.getpixel((200, 150))[0], 170)

    def test_bw_retains_soft_edges(self):
        image = Image.new("RGB", (400, 300), "white")
        ImageDraw.Draw(image).line((20, 150, 380, 150), fill=(180, 180, 180), width=2)
        result = process_scan_image(image, None, "bw")
        self.assertTrue(0 < result.getpixel((200, 150))[0] < 200)

    def test_shadow_keeps_colored_ink_channel_balance_on_tinted_paper(self):
        image = Image.new("RGB", (400, 300), (180, 195, 220))
        draw = ImageDraw.Draw(image)
        draw.line((30,100,370,100), fill=(30,60,120), width=3)
        result = process_scan_image(image, None, "shadow")
        r, g, b = result.getpixel((200,100))
        self.assertAlmostEqual(g/r, 2.0, delta=.12)
        self.assertAlmostEqual(b/r, 4.0, delta=.2)
        self.assertGreater(result.getpixel((200,200))[1], 220)

    def test_shadow_limits_extreme_dark_amplification(self):
        image = Image.new("RGB", (200, 200), (40,40,40))
        ImageDraw.Draw(image).line((20,100,180,100), fill=(10,10,10), width=1)
        result = process_scan_image(image, None, "shadow")
        self.assertLessEqual(result.getpixel((100,100))[0], 23)
        self.assertLessEqual(result.getpixel((100,150))[0], 89)

    def test_smart_removes_pale_patch_connected_to_dark_pen(self):
        image = Image.new("RGB", (400, 300), (220, 220, 220))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100,100,250,114), fill=(200,200,200))
        draw.line((180,100,180,160), fill=(20,20,20), width=2)
        result = process_scan_image(image, None, "smart")
        self.assertGreater(result.getpixel((120,107))[0], 245)
        self.assertLess(result.getpixel((180,135))[0], 80)

    def test_smart_keeps_dark_broad_stroke_and_single_pixel_line(self):
        image = Image.new("RGB", (500,400), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30,80,200,105), fill=(30,30,30))
        draw.line((30,180,400,180), fill=(30,30,30), width=1)
        result = process_scan_image(image, None, "smart")
        self.assertLess(result.getpixel((100,92))[0], 80)
        self.assertLess(result.getpixel((200,180))[0], 80)

    def test_smart_retains_faint_ink_alongside_dark_heading(self):
        image = Image.new("RGB", (400, 300), "white")
        draw = ImageDraw.Draw(image)
        draw.line((20, 50, 380, 50), fill=(0, 0, 0), width=5)
        draw.line((20, 150, 380, 150), fill=(190, 190, 190), width=2)
        result = process_scan_image(image, None, "smart")
        self.assertLess(result.getpixel((200, 150))[0], 160)
        self.assertGreater(result.getpixel((200, 200))[0], 240)

    def test_bright_keeps_highlight_steps_and_black(self):
        pixels = np.array([[[0, 0, 0], [120, 120, 120], [220, 220, 220], [240, 240, 240], [255, 255, 255]]], dtype=np.uint8)
        result = np.asarray(process_scan_image(Image.fromarray(pixels), None, "bright"))[0, :, 0]
        self.assertEqual(result[0], 0)
        self.assertGreater(result[1], 120)
        self.assertTrue(np.all(np.diff(result.astype(int)) > 0))

    def test_shadow_flattens_gradient_preserving_ink_and_color(self):
        gradient = np.tile(np.linspace(110, 235, 400).astype(np.uint8), (300, 1))
        image = Image.fromarray(np.repeat(gradient[:, :, None], 3, axis=2))
        draw = ImageDraw.Draw(image)
        draw.line((20, 100, 380, 100), fill=(10, 10, 10), width=2)
        draw.line((20, 160, 380, 160), fill=(20, 40, 100), width=3)
        result = np.asarray(process_scan_image(image, None, "shadow"))
        self.assertLess(np.std(result[50, 30:-30, 0]), 5)
        self.assertGreater(np.mean(result[50, 30:-30, 0]), 240)
        self.assertLess(result[100, 200, 0], 40)
        self.assertGreater(int(result[160, 200, 2]) - int(result[160, 200, 0]), 40)

    def test_unknown_mode_does_not_silently_apply_shadow(self):
        with self.assertRaises(ValueError):
            process_scan_image(Image.new("RGB", (40, 40)), None, "nonexistent_filter")

    def test_original_preserves_pixels_without_geometry_changes(self):
        image = Image.new("RGB", (120, 100), (70, 130, 190))
        result = process_scan_image(image, None, "original")
        self.assertTrue(np.array_equal(np.asarray(result), np.asarray(image)))

    def test_smart_preserves_colored_and_dark_ink_on_light_paper(self):
        image = Image.new("RGB", (400, 300), (220, 220, 220))
        draw = ImageDraw.Draw(image)
        draw.line((20, 20, 160, 20), fill=(20, 40, 180), width=3)
        draw.line((20, 80, 160, 80), fill=(25, 25, 25), width=3)
        result = process_scan_image(image, None, "smart")
        blue = result.getpixel((50, 20))
        self.assertGreater(blue[2], blue[0] + 40)
        self.assertLess(max(result.getpixel((50, 80))), 80)
        self.assertGreater(min(result.getpixel((300, 200))), 235)

    def test_bw_retains_thin_dark_stroke(self):
        image = Image.new("RGB", (200, 200), "white")
        ImageDraw.Draw(image).line((20, 100, 180, 100), fill="black", width=1)
        result = process_scan_image(image, None, "bw")
        self.assertLess(result.getpixel((100, 100))[0], 128)
        self.assertGreater(result.getpixel((100, 130))[0], 240)


if __name__ == "__main__":
    unittest.main()
