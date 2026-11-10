from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Sequence

from PIL import Image


def export_pages_as_docx(
    pages: Sequence[Image.Image],
    output_path: str | Path,
    page_width_mm: float,
    page_height_mm: float,
    *, page_pngs: Sequence[bytes] | None = None,
) -> Path:
    """Save rendered pages as full-page images in a Word document."""
    if not pages:
        raise ValueError("没有可导出的手稿页面。")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    width_emu = round(page_width_mm * 36_000)
    height_emu = round(page_height_mm * 36_000)
    width_twips = round(page_width_mm * 1_440 / 25.4)
    height_twips = round(page_height_mm * 1_440 / 25.4)

    images = list(page_pngs) if page_pngs is not None else []
    if page_pngs is None:
        for page in pages:
            image = io.BytesIO()
            page.convert("RGB").save(image, format="PNG", compress_level=3)
            images.append(image.getvalue())
    if len(images) != len(pages):
        raise ValueError("页面图片数量不一致。")

    paragraphs = []
    relationships = []
    for index in range(1, len(images) + 1):
        page_break = '<w:pageBreakBefore/>' if index > 1 else ""
        rel_id = f"rId{index}"
        paragraphs.append(
            f'''<w:p><w:pPr>{page_break}<w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/></w:pPr>
              <w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="0" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">
                <wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>
                <wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>
                <wp:extent cx="{width_emu}" cy="{height_emu}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>
                <wp:docPr id="{index}" name="手稿第{index}页" descr="生成的手写文稿第{index}页"/>
                <wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
                <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
                  <pic:nvPicPr><pic:cNvPr id="{index}" name="page-{index}.png"/><pic:cNvPicPr><a:picLocks noChangeAspect="1"/></pic:cNvPicPr></pic:nvPicPr>
                  <pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
                  <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
                </pic:pic></a:graphicData></a:graphic>
              </wp:anchor></w:drawing></w:r></w:p>'''
        )
        relationships.append(
            f'<Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/page-{index}.png"/>'
        )

    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
        xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
        xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <w:body>{''.join(paragraphs)}
          <w:sectPr><w:pgSz w:w="{width_twips}" w:h="{height_twips}"/><w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>
        </w:body>
      </w:document>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
      <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Default Extension="png" ContentType="image/png"/>
        <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
      </Types>'''
    root_relationship = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
      <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
      </Relationships>'''
    document_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(relationships)}</Relationships>'
    )

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", root_relationship)
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", document_relationships)
        for index, image in enumerate(images, start=1):
            package.writestr(f"word/media/page-{index}.png", image, compress_type=zipfile.ZIP_STORED)
    return output
