import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from markdown_to_handwrite.scanner import ScanService, decode_scan_image


class ScanFormatTests(unittest.TestCase):
    def make_image(self, fmt):
        image = Image.new('RGB', (160, 100), 'white')
        ImageDraw.Draw(image).rectangle((20, 20, 50, 80), fill='black')
        stream = io.BytesIO()
        image.save(stream, format=fmt)
        return stream.getvalue()

    def test_heic_heif_and_existing_formats_upload_and_process(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            for suffix, fmt in [('HEIC', 'HEIF'), ('heif', 'HEIF'), ('png', 'PNG'), ('jpg', 'JPEG'), ('webp', 'WEBP'), ('bmp', 'BMP')]:
                with self.subTest(suffix=suffix):
                    page = service.upload('image.' + suffix, self.make_image(fmt))
                    result = service.process(page['scanId'], {'mode': 'smart'})
                    self.assertTrue(result['url'])
                    self.assertTrue((Path(folder)/page['scanId']/'current.png').is_file())

    def test_jpeg_orientation_is_applied_once(self):
        image = Image.new('RGB', (120, 60), 'white')
        ImageDraw.Draw(image).rectangle((0, 0, 39, 29), fill='black')
        exif = Image.Exif()
        exif[274] = 6
        stream = io.BytesIO()
        image.save(stream, format='JPEG', exif=exif)
        decoded = decode_scan_image(stream.getvalue())
        self.assertEqual(decoded.size, (60, 120))
        self.assertLess(decoded.getpixel((45, 15))[0], 30)
        self.assertGreater(decoded.getpixel((15, 105))[0], 220)

    def test_invalid_heic_gives_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, '无法读取'):
                ScanService(Path(folder)).upload('bad.HEIC', b'not an image')

if __name__ == '__main__':
    unittest.main()
