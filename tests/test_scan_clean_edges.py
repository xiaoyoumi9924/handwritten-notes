import unittest
import numpy as np
from PIL import Image, ImageDraw
from markdown_to_handwrite.scanner import process_scan_image

class CleanEdgeTests(unittest.TestCase):
    def test_perimeter_is_clean_only_for_bw_and_invert(self):
        im = Image.new('RGB', (500, 400), 'white')
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 499, 7), fill='black')
        d.rectangle((100, 100, 120, 120), fill='black')
        for mode, value in [('bw', 255), ('invert', 0)]:
            result = np.asarray(process_scan_image(im, None, mode))
            self.assertTrue(np.all(result[0] == value))
            self.assertTrue(np.all(result[-1] == value))
            self.assertTrue(np.all(result[:, 0] == value))
            self.assertTrue(np.all(result[:, -1] == value))
            self.assertNotEqual(int(result[110, 110, 0]), value)
        self.assertLess(process_scan_image(im, None, 'smart').getpixel((250, 3))[0], 100)

    def test_cut_corner_outside_paper_is_cleared(self):
        im = Image.new('RGB', (600, 800), (100, 75, 55))
        d = ImageDraw.Draw(im)
        d.polygon([(65, 0), (599, 0), (599, 799), (0, 799), (0, 600)], fill=(220, 220, 220))
        d.line((160, 300, 500, 300), fill='black', width=3)
        for mode, value in [('bw', 255), ('invert', 0)]:
            result = process_scan_image(im, None, mode)
            self.assertEqual(result.getpixel((20, 200)), (value,)*3)
            self.assertNotEqual(result.getpixel((250, 300)), (value,)*3)
