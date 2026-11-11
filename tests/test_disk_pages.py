import tempfile
import unittest
import io
import zipfile
from pathlib import Path
from PIL import Image

from markdown_to_handwrite.config import ReportConfig
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.page_edits import apply_page_edits, normalize_page_edits
from markdown_to_handwrite.web import RenderService


class DiskPagesTests(unittest.TestCase):
    def test_disk_pages_match_in_memory_with_page_numbers_and_corrections(self):
        config = ReportConfig()
        config.page.dpi = 96
        config.layout.show_page_numbers = True
        config.handwriting.correction_probability = 10
        blocks = parse_markdown("\n\n<newpage>\n\n".join(["这是测试文稿，包含随机涂改。" * 12] * 3))
        expected = ReportRenderer(config).render(blocks)
        with tempfile.TemporaryDirectory() as directory:
            renderer = ReportRenderer(config, page_store_dir=Path(directory))
            actual = renderer.render(blocks)
            self.assertGreaterEqual(len(actual), 2)
            self.assertEqual(len(actual), len(expected))
            for index in range(len(actual)):
                self.assertEqual(actual[index].tobytes(), expected[index].tobytes())
            self.assertEqual(renderer.pages.active, None)

    def test_edit_export_matches_original_editing_and_preserves_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = RenderService(root)
            result = service.render("第一页\n\n<newpage>\n\n第二页", {"page": {"dpi": 96}})
            self.assertEqual(result["pageCount"], 2)
            job = root / result["jobId"]
            mark = {"kind": "comment", "text": "测试批注", "width": .03, "color": "#123456", "points": [[.2, .2]]}
            raw_edits = [{"rotation": 90, "crop": None, "marks": [mark]},
                         {"rotation": 0, "crop": [.1, .1, .8, .8], "marks": []}]
            edits = normalize_page_edits(raw_edits, 2)
            with zipfile.ZipFile(job / "markdown-to-handwrite.docx") as package:
                expected = []
                for i, edit in enumerate(edits, start=1):
                    with Image.open(io.BytesIO(package.read(f"word/media/page-{i}.png"))) as source:
                        expected.append(apply_page_edits(source, edit))
            edited = service.edit_pages(result["jobId"], raw_edits)
            self.assertIn("0", edited["commentImages"][0])
            with zipfile.ZipFile(job / "handwritten-pages.zip") as package:
                for index, expected_page in enumerate(expected, start=1):
                    with Image.open(io.BytesIO(package.read(f"handwritten-page-{index:03d}.png"))) as actual:
                        self.assertEqual(actual.convert("RGB").tobytes(), expected_page.convert("RGB").tobytes())
            self.assertTrue((job / "markdown-to-handwrite-edited.docx").is_file())


if __name__ == "__main__":
    unittest.main()
