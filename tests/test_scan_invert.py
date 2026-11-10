import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from markdown_to_handwrite.scanner import ScanService, process_scan_image, validate_scan_options


class InvertFilterTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (400, 300), (210, 210, 210))
        d = ImageDraw.Draw(self.image)
        d.line((30, 90, 370, 90), fill=(150, 25, 25), width=3)
        d.line((30, 160, 370, 160), fill=(20, 20, 20), width=2)

    def test_inverse_keeps_geometry_and_complements_color_without_ai(self):
        options = dict(rotation=90, crop=[.1, .1, .8, .8])
        with patch('markdown_to_handwrite.handwriting_removal._load_model', side_effect=AssertionError('retired AI must not run')):
            smart = process_scan_image(self.image, None, 'smart', **options)
            inverted = process_scan_image(self.image, None, 'invert', **options)
        self.assertTrue(np.array_equal(np.asarray(inverted)[8:-8, 8:-8], np.asarray(ImageOps.invert(smart))[8:-8, 8:-8]))
        self.assertTrue(np.all(np.asarray(inverted)[0] == 0))

    def test_dark_paper_bright_ink_and_complementary_red(self):
        inverted = process_scan_image(self.image, None, 'invert')
        self.assertEqual(inverted.getpixel((200, 240)), (0, 0, 0))
        self.assertGreater(min(inverted.getpixel((200, 160))), 200)
        red, green, blue = inverted.getpixel((200, 90))
        self.assertGreater(green, red + 60)
        self.assertGreater(blue, red + 60)

    def test_partial_page_cleanup_precedes_inversion(self):
        options = dict(top_clip=[[.5, 0], [1, .2]])
        smart = process_scan_image(self.image, None, 'smart', **options)
        inverted = process_scan_image(self.image, None, 'invert', **options)
        self.assertTrue(np.array_equal(np.asarray(inverted), 255-np.asarray(smart)))

    def test_preview_and_export_match_and_erasure_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            data = io.BytesIO(); self.image.save(data, 'PNG')
            scan_id = service.upload('notes.png', data.getvalue())['scanId']
            service.process(scan_id, {'mode': 'invert'})
            preview = service.filter_preview(scan_id, {'mode': 'invert'})
            export = service.export([scan_id], 'png')
            with Image.open(Path(folder)/scan_id/'current.png') as full, Image.open(Path(folder)/scan_id/Path(preview['url']).name) as thumb, Image.open(Path(folder)/'exports'/Path(export['url']).name) as png:
                self.assertTrue(np.array_equal(np.asarray(full), np.asarray(png)))
                self.assertLess(np.abs(np.asarray(full).astype(float)-np.asarray(thumb.convert('RGB')).astype(float)).mean(), 3)
            for fn in (service.process, service.filter_preview):
                with self.assertRaises(ValueError): fn(scan_id, {'mode': 'remove_handwriting'})
        with self.assertRaises(ValueError): validate_scan_options('remove_handwriting', 'auto', 0, None)
