import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clean_output_jobs.py"


class CleanOutputJobsTests(unittest.TestCase):
    def test_preview_and_explicit_delete_only_remove_selected_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ids = ["0123456789abcdef", "1111111111111111"]
            for job_id in ids:
                path = root / job_id
                path.mkdir()
                (path / "metadata.json").write_text("{}")
                (path / "export.pdf").write_bytes(b"example")
            command = [sys.executable, str(SCRIPT), "--root", str(root), "--job", ids[0]]
            subprocess.run(command, check=True, capture_output=True)
            self.assertTrue((root / ids[0]).exists())
            subprocess.run(command + ["--delete"], check=True, capture_output=True)
            self.assertFalse((root / ids[0]).exists())
            self.assertTrue((root / ids[1] / "export.pdf").exists())

    def test_invalid_selection_prevents_all_deletions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job = root / "0123456789abcdef"
            job.mkdir()
            (job / "metadata.json").write_text("{}")
            result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--job", job.name,
                                     "--job", "../outside", "--delete"], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(job.is_dir())


if __name__ == "__main__":
    unittest.main()
