"""Render experimental erasure through the production path, with negative controls.

PYTHONPATH=src .venv/bin/python scripts/evaluate_handwriting_removal.py --sources DIR
No reference targets are assumed: pixel-change counts are diagnostic, not
handwriting accuracy. Pure printed negatives should remain unchanged.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from markdown_to_handwrite.scanner import process_scan_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("output/handwriting-removal/results"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for path in sorted(args.sources.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        start = time.perf_counter()
        result = process_scan_image(image, None, "remove_handwriting")
        elapsed = time.perf_counter()-start
        result.save(args.output / f"{path.stem}-removed.png")
        original, cleaned = np.asarray(image), np.asarray(result)
        dark = original.min(axis=2) < 150
        removed = np.any(original != cleaned, axis=2)
        record = {"sample": path.name, "seconds": round(elapsed, 3),
                  "unchanged": bool(np.array_equal(original, cleaned)),
                  "dark_pixels_changed_fraction": round(float((removed & dark).sum()/max(1, dark.sum())), 5)}
        if path.stem == "eraser-test2":
            header_dark = dark[:180]
            record["printed_header_dark_pixels_changed_fraction"] = round(float((removed[:180] & header_dark).sum()/max(1, header_dark.sum())), 5)
        records.append(record)
        sheet = Image.new("RGB", (1200, 650), "#e8edf5")
        draw = ImageDraw.Draw(sheet)
        for index, (label, picture) in enumerate((("Original", image), ("Handwriting removal (trial)", result))):
            thumb = ImageOps.contain(picture, (590, 610), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (index*600+(600-thumb.width)//2, 30))
            draw.text((index*600+10, 8), label, fill="black")
        sheet.save(args.output / f"{path.stem}-comparison.jpg", quality=94)
        print(record, flush=True)
    (args.output / "metrics.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
