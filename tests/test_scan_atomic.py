import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from markdown_to_handwrite.scanner import _save_image_atomic


class ScanAtomicWriteTests(unittest.TestCase):
    def test_failed_write_keeps_previous_image_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "current.png"
            Image.new("RGB", (2, 2), "red").save(target)
            before = target.read_bytes()
            image = Image.new("RGB", (2, 2), "blue")

            def fail(path, **kwargs):
                Path(path).write_bytes(b"partial")
                raise OSError("write failed")

            with patch.object(image, "save", side_effect=fail):
                with self.assertRaises(OSError):
                    _save_image_atomic(image, target, format="PNG")
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(root.iterdir()), [target])

    def test_success_replaces_previous_image(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "current.png"
            Image.new("RGB", (2, 2), "red").save(target)
            _save_image_atomic(Image.new("RGB", (2, 2), "blue"), target, format="PNG")
            with Image.open(target) as result:
                self.assertEqual(result.getpixel((0, 0)), (0, 0, 255))


if __name__ == "__main__":
    unittest.main()
