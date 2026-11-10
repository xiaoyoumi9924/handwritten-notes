from __future__ import annotations

import io
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from markdown_to_handwrite.config import ReportConfig
from markdown_to_handwrite.docx_importer import import_docx_bytes
from markdown_to_handwrite.markdown_parser import FormulaBlock, ImageBlock, TableBlock, parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer


DOCUMENT_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:body>
    <w:p><w:r><w:t>中文 English 混排</w:t></w:r></w:p>
    <w:tbl>
      <w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>
      <w:tr>
        <w:tc><w:p><w:r><w:t>指标 Prompt</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>公式 Formula</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>均值 Mean</w:t></w:r></w:p></w:tc>
        <w:tc>
          <w:p>
            <w:r><w:t>结果: </w:t></w:r>
            <m:oMath>
              <m:f>
                <m:num><m:r><m:t>a+b</m:t></m:r></m:num>
                <m:den><m:r><m:t>c</m:t></m:r></m:den>
              </m:f>
            </m:oMath>
          </w:p>
        </w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <m:oMathPara>
        <m:oMath>
          <m:sSup>
            <m:e><m:r><m:t>x</m:t></m:r></m:e>
            <m:sup><m:r><m:t>2</m:t></m:r></m:sup>
          </m:sSup>
        </m:oMath>
      </m:oMathPara>
    </w:p>
    <w:p><w:r><w:drawing/></w:r></w:p>
  </w:body>
</w:document>
'''


def make_docx_bytes(document_xml: str = DOCUMENT_XML) -> bytes:
    package = io.BytesIO()
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return package.getvalue()


class DocxImportTests(unittest.TestCase):
    def test_bilingual_table_formula_imports_and_renders_end_to_end(self):
        imported = import_docx_bytes(make_docx_bytes())

        self.assertEqual(imported.warnings, [])
        self.assertIn("中文 English 混排", imported.markdown)
        self.assertIn(r"结果: \(\frac{a+b}{c}\)", imported.markdown)
        self.assertNotIn("图片", imported.markdown)

        blocks = parse_markdown(imported.markdown)
        self.assertFalse(any(isinstance(block, ImageBlock) for block in blocks))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        formula_cell = table.rows[0][1]
        self.assertEqual(
            [(part.kind, part.text) for part in formula_cell],
            [("text", "结果: "), ("math", r"\frac{a+b}{c}")],
        )
        display_formula = next(block for block in blocks if isinstance(block, FormulaBlock))
        self.assertEqual(display_formula.text, "{x}^{2}")

        config = ReportConfig()
        config.page.dpi = 72
        config.background.style = "plain"
        config.background.auto_discover = False
        config.background.draw_margin_line = False
        config.handwriting.prefer_handright = False
        config.handwriting.sdt_trajectory_enabled = False
        config.handwriting.second_layer_enabled = False
        config.layout.show_page_numbers = False
        pages = ReportRenderer(config).render(blocks)

        self.assertEqual(len(pages), 1)
        self.assertIsNotNone(pages[0].getchannel("A").getbbox())


if __name__ == "__main__":
    unittest.main()
