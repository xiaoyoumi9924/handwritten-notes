import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("clean_scan_cache", Path(__file__).resolve().parents[1] / "scripts" / "clean_scan_cache.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class ScanCacheCleanupTests(unittest.TestCase):
    def test_dry_run_and_delete_leave_other_files_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scan = root / "0123456789abcdef"
            scan.mkdir()
            old = scan / ("filter-" + "a" * 24 + ".webp")
            fresh = scan / ("restored-" + "b" * 24 + ".webp")
            original = scan / "original.png"
            for path in (old, fresh, original):
                path.write_bytes(b"123")
            now = 2_000_000.0
            os.utime(old, (now - 9 * 86400,) * 2)
            os.utime(fresh, (now,) * 2)
            os.utime(original, (now - 9 * 86400,) * 2)
            self.assertEqual(cleanup.clean_cache(root, now=now), (1, 3))
            self.assertTrue(old.exists())
            self.assertEqual(cleanup.clean_cache(root, now=now, delete=True), (1, 3))
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(original.exists())


if __name__ == "__main__":
    unittest.main()
