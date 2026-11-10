#!/usr/bin/env python3
"""Build local contact sheets for auditing provisional character crops."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
REPORT = DATASET / "prepared" / "glyph-candidates" / "glyph-candidates.json"
OUTPUT = DATASET / "prepared" / "glyph-candidates" / "review-sheets"
CELL_W = 84
CELL_H = 92
COLUMNS = 10
LINES_PER_SHEET = 4


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    lines: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for sample in report["samples"]:
        lines[(sample["page"], int(sample["line_index"]))].append(sample)

    ordered = sorted(lines.items(), key=lambda item: (item[0][0], item[0][1]))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 14, index=0)

    for old in OUTPUT.glob("glyph_audit_*.png"):
        old.unlink()

    sheet_number = 0
    for offset in range(0, len(ordered), LINES_PER_SHEET):
        group = ordered[offset : offset + LINES_PER_SHEET]
        block_heights = [30 + math.ceil(len(samples) / COLUMNS) * CELL_H for _, samples in group]
        sheet = Image.new("RGB", (COLUMNS * CELL_W, sum(block_heights) + 10), "#f6f3eb")
        draw = ImageDraw.Draw(sheet)
        y = 5

        for (page, line_index), samples in group:
            samples.sort(key=lambda sample: int(sample["char_index"]))
            draw.text((8, y + 4), f"{page}  line {line_index:02}  ({len(samples)} glyph crops)", font=font, fill="#28312c")
            y += 30

            for index, sample in enumerate(samples):
                x = (index % COLUMNS) * CELL_W
                row_y = y + (index // COLUMNS) * CELL_H
                label = f"{sample['char_index']:02} {sample['label_candidate']}"
                draw.text((x + 3, row_y + 2), label, font=font, fill="#242824")
                crop_path = DATASET / sample["file"]
                with Image.open(crop_path) as image:
                    crop = image.convert("L")
                    crop.thumbnail((CELL_W - 12, CELL_H - 24), Image.Resampling.LANCZOS)
                    sheet.paste(crop.convert("RGB"), (x + (CELL_W - crop.width) // 2, row_y + 22 + (CELL_H - 24 - crop.height) // 2))

            y += math.ceil(len(samples) / COLUMNS) * CELL_H

        sheet_number += 1
        sheet.save(OUTPUT / f"glyph_audit_{sheet_number:02}.png", optimize=True)

    print(f"Created {sheet_number} review sheets for {len(ordered)} candidate lines in {OUTPUT}")


if __name__ == "__main__":
    main()
