import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("output_usage", Path(__file__).resolve().parents[1] / "scripts" / "output_usage.py")
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


class OutputUsageTests(unittest.TestCase):
    def test_counts_jobs_and_other_files_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job = root / "0123456789abcdef"
            job.mkdir()
            (job / "metadata.json").write_text("{}")
            (job / "result.pdf").write_bytes(b"12345")
            scans = root / "scans"
            scans.mkdir()
            (scans / "image.png").write_bytes(b"123")
            (root / "linked").symlink_to(scans, target_is_directory=True)
            jobs, other = usage.collect_usage(root)
            self.assertEqual(jobs, [(job.name, 7)])
            self.assertEqual(other, [("scans", 3)])


if __name__ == "__main__":
    unittest.main()
