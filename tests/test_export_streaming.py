import tempfile
import unittest
import zipfile
import io
from pathlib import Path

from PIL import Image
from docx import Document
import pymupdf

from markdown_to_handwrite.docx_exporter import export_pages_as_docx
from markdown_to_handwrite.page_edits import save_pages_pdf
from markdown_to_handwrite.web import _save_page_images


class ExportStreamingTests(unittest.TestCase):
    def test_docx_uses_same_pngs_as_image_archive(self):
        pages = [Image.new("RGBA", (12, 16), color) for color in ("red", "blue")]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            images = _save_page_images(pages, root / "pages.zip")
            docx = export_pages_as_docx(pages, root / "pages.docx", 210, 297, page_png_archive=images)
            with zipfile.ZipFile(images) as source, zipfile.ZipFile(docx) as package:
                for index in range(1, 3):
                    self.assertEqual(source.read(f"handwritten-page-{index:03d}.png"),
                                     package.read(f"word/media/page-{index}.png"))
            document = Document(docx)
            self.assertEqual(len(document.paragraphs), 2)
            self.assertEqual(len(document.part.rels), 2)

    def test_docx_can_encode_pages_without_an_image_archive(self):
        pages = [Image.new("RGB", (8, 10), "white"), Image.new("RGB", (8, 10), "black")]
        with tempfile.TemporaryDirectory() as folder:
            docx = export_pages_as_docx(pages, Path(folder) / "pages.docx", 210, 297)
            with zipfile.ZipFile(docx) as package:
                self.assertIn("word/media/page-1.png", package.namelist())
                self.assertIn("word/media/page-2.png", package.namelist())

    def test_pdf_reuses_pngs_without_changing_page_pixels(self):
        pages = [Image.new("RGB", (12, 16), color) for color in ("red", "blue")]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            images = _save_page_images(pages, root / "pages.zip")
            pdf = save_pages_pdf(pages, root / "pages.pdf", 210, 297, page_png_archive=images)
            with pymupdf.open(pdf) as document:
                self.assertEqual(len(document), 2)
                for index, page in enumerate(document):
                    xref = page.get_images()[0][0]
                    extracted = document.extract_image(xref)["image"]
                    with Image.open(io.BytesIO(extracted)) as image:
                        self.assertEqual(image.convert("RGB").tobytes(), pages[index].tobytes())


if __name__ == "__main__":
    unittest.main()
