#!/usr/bin/env python3
"""Create local numbered image sheets so OCR text can be checked row by row."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
SOURCE = DATASET / "source"
OCR_FILE = DATASET / "ocr-lines.json"
OUTPUT = DATASET / "prepared"
LEFT_GUTTER = 64
PAD_Y = 12
ROW_GAP = 7


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-page", type=int, default=1, help="create sheets starting at this page number")
    args = parser.parse_args()
    dataset = json.loads(OCR_FILE.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    label_font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 20)
    total = 0

    for page in dataset["pages"]:
        page_number = int(Path(page["file"]).stem.split("_")[-1])
        if page_number < args.from_page:
            continue
        image_path = SOURCE / page["file"]
        with Image.open(image_path) as source:
            source = source.convert("RGB")
            crops = []
            for line_number, line in enumerate(page["lines"], start=1):
                box = line["box"]
                top = max(0, box["y"] - PAD_Y)
                bottom = min(source.height, box["y"] + box["height"] + PAD_Y)
                crop = source.crop((0, top, source.width, bottom))
                crops.append((line_number, crop))

            sheet_height = sum(crop.height + ROW_GAP for _, crop in crops) + 24
            sheet = Image.new("RGB", (source.width + LEFT_GUTTER, sheet_height), "white")
            draw = ImageDraw.Draw(sheet)
            y = 12
            for line_number, crop in crops:
                draw.text((10, y + max(0, (crop.height - 22) // 2)), f"{line_number:02}", fill=(30, 35, 33), font=label_font)
                sheet.paste(crop, (LEFT_GUTTER, y))
                y += crop.height + ROW_GAP

            output_path = OUTPUT / f"{Path(page['file']).stem}_line_review.png"
            sheet.save(output_path, optimize=True)
            total += len(crops)
            print(f"{output_path.name}: {len(crops)} numbered lines, {sheet.width}x{sheet.height}")

    print(f"Created {total} local line crops; originals were not changed.")


if __name__ == "__main__":
    main()
