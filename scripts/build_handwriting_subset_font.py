#!/usr/bin/env python3
"""Build an isolated raster-traced TTF prototype from provisional glyph crops.

The output is a local inspection artifact only. It must not be installed or
added to the app until its glyph labels and watermarked samples are reviewed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
NORMALIZED = DATASET / "prepared" / "normalized"
GLYPH_DIR = DATASET / "prepared" / "glyph-candidates"
REPORT_FILE = GLYPH_DIR / "glyph-candidates.json"
OCR_FILE = DATASET / "ocr-lines.json"
OUTPUT = DATASET / "prepared" / "prototype"
UPM = 1000
BASELINE = 140
BODY_HEIGHT = 760


def glyph_name(char: str) -> str:
    codepoint = ord(char)
    return f"uni{codepoint:04X}" if codepoint <= 0xFFFF else f"u{codepoint:05X}"


def is_han(char: str) -> bool:
    cp = ord(char)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x323AF
    )


def advance_for(char: str) -> int:
    if is_han(char):
        return 700
    if char in "，。！？；：、（）《》【】“”‘’—…,.!?;:'\"()[]":
        return 470
    if char.isdigit():
        return 520
    if char.isascii() and char.isalpha():
        return 560 if char.isupper() else 500
    return 600


def row_runs(row: np.ndarray) -> list[tuple[int, int]]:
    occupied = row.astype(bool)
    starts = np.flatnonzero(occupied & ~np.r_[False, occupied[:-1]])
    ends = np.flatnonzero(occupied & ~np.r_[occupied[1:], False]) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def build_pixel_glyph(
    char: str,
    mask: np.ndarray,
    glyph_bbox: dict[str, int],
    line_box: dict[str, int],
    advance: int,
) -> tuple[object, int]:
    pen = TTGlyphPen(None)
    x = glyph_bbox["x"]
    y = glyph_bbox["y"]
    width = glyph_bbox["width"]
    height = glyph_bbox["height"]
    bitmap = mask[y : y + height, x : x + width]
    points = np.argwhere(bitmap)
    if not len(points):
        return pen.glyph(), advance

    scale_y = BODY_HEIGHT / max(1, line_box["height"])
    scale_x = scale_y * (1.5 if is_han(char) else 1.15)
    ink_width = int(points[:, 1].max() - points[:, 1].min() + 1)
    if ink_width * scale_x > advance * 0.88:
        scale_x = (advance * 0.88) / ink_width
    scaled_width = ink_width * scale_x
    left_bearing = max(0, round((advance - scaled_width) / 2))
    left_ink = int(points[:, 1].min())
    top_ink = int(points[:, 0].min())
    bottom_ink = int(points[:, 0].max() + 1)
    line_bottom = line_box["y"] + line_box["height"]

    for row_index, row in enumerate(bitmap):
        if not row.any():
            continue
        source_y_top = y + row_index
        source_y_bottom = source_y_top + 1
        font_y_bottom = round(BASELINE + (line_bottom - source_y_bottom) * scale_y)
        font_y_top = round(BASELINE + (line_bottom - source_y_top) * scale_y)
        for start, end in row_runs(row):
            x0 = round(left_bearing + (start - left_ink) * scale_x)
            x1 = round(left_bearing + (end - left_ink) * scale_x)
            if x1 <= x0:
                continue
            # Each scanline run becomes one filled contour. At this resolution
            # the existing renderer's skeletonizer recovers a stroke centerline.
            pen.moveTo((x0, font_y_bottom))
            pen.lineTo((x0, font_y_top))
            pen.lineTo((x1, font_y_top))
            pen.lineTo((x1, font_y_bottom))
            pen.closePath()

    pen_glyph = pen.glyph()
    pen_glyph.recalcBounds(None)
    return pen_glyph, advance


def main() -> None:
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    ocr = json.loads(OCR_FILE.read_text(encoding="utf-8"))
    line_boxes = {
        (page["file"], index): line["box"]
        for page in ocr["pages"]
        for index, line in enumerate(page["lines"], start=1)
    }

    grouped = defaultdict(list)
    for sample in report["samples"]:
        grouped[sample["label_candidate"]].append(sample)
    selected = {
        char: max(samples, key=lambda sample: (sample["line_confidence"], -sample["line_index"]))
        for char, samples in grouped.items()
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    pages_mask: dict[str, np.ndarray] = {}
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (800, 0), "space": (300, 0)}
    cmap = {0x20: "space"}
    name_map = {char: glyph_name(char) for char in sorted(selected, key=ord)}

    for char, sample in selected.items():
        page = sample["page"]
        if page not in pages_mask:
            mask_path = NORMALIZED / page.replace(".png", "_ink_candidate.png")
            with Image.open(mask_path) as image:
                pages_mask[page] = np.asarray(image.convert("L")) < 128
        line_box = line_boxes[(page, int(sample["line_index"]))]
        glyph, advance = build_pixel_glyph(
            char,
            pages_mask[page],
            sample["bbox"],
            line_box,
            advance_for(char),
        )
        glyph_name_for_char = name_map[char]
        glyphs[glyph_name_for_char] = glyph
        metrics[glyph_name_for_char] = (advance, 0)
        cmap[ord(char)] = glyph_name_for_char

    order = [".notdef", "space", *[name_map[char] for char in sorted(selected, key=ord)]]
    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=900, descent=-160, lineGap=80)
    builder.setupOS2(
        sTypoAscender=900,
        sTypoDescender=-160,
        usWinAscent=900,
        usWinDescent=160,
        usWeightClass=400,
        usWidthClass=5,
        sxHeight=500,
        sCapHeight=700,
    )
    builder.setupNameTable({
        "familyName": "Handwriting Sample Prototype",
        "styleName": "Provisional",
        "uniqueFontIdentifier": "HandwritingSamplePrototype-0.1",
        "fullName": "Handwriting Sample Prototype Provisional",
        "psName": "HandwritingSamplePrototype-Provisional",
        "version": "Version 0.1",
    })
    builder.setupPost()
    builder.setupMaxp()

    font_path = OUTPUT / "handwriting_sample_prototype.ttf"
    builder.save(font_path)

    # Render an inspection sheet using a source line that is fully represented
    # in the prototype subset. This is not an app integration or font release.
    preview_text = "特朗普1946年6月14日出生于纽约，父亲弗雷德·特朗普是一名房地产开发商。"
    font = ImageFont.truetype(str(font_path), 44)
    image = Image.new("RGB", (1600, 170), "#fbf8ef")
    draw = ImageDraw.Draw(image)
    draw.text((32, 24), preview_text, font=font, fill="#171815")
    draw.text((32, 112), "Provisional subset · source labels and watermark regions need review", fill="#6d716b")
    preview_path = OUTPUT / "handwriting_sample_prototype_preview.png"
    image.save(preview_path, optimize=True)

    summary = {
        "font_file": font_path.name,
        "preview": preview_path.name,
        "glyph_count": len(selected),
        "sample_count": len(report["samples"]),
        "status": "isolated_inspection_prototype_unverified",
        "source_method": "raster glyph crops traced as pixel-run outlines; existing renderer can skeletonize them",
        "warning": "Do not use for production: incomplete charset and unverified labels/watermark contamination.",
    }
    (OUTPUT / "prototype-manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_path = DATASET / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["font_prototype"] = {
        "file": str(font_path.relative_to(DATASET)),
        "preview": str(preview_path.relative_to(DATASET)),
        "glyph_count": len(selected),
        "source_sample_count": len(report["samples"]),
        "status": "unverified_inspection_only_not_integrated",
        "warning": summary["warning"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Prototype font: {font_path}")
    print(f"Glyphs: {len(selected)}; source crops: {len(report['samples'])}")
    print(f"Preview: {preview_path}")


if __name__ == "__main__":
    main()
