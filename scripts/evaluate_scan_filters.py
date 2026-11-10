"""Render real scan samples through the production filter path for visual QA.

PYTHONPATH=src .venv/bin/python scripts/evaluate_scan_filters.py
Supply --sources for a different local image directory. Samples are QA data,
not bundled application assets; see references/scan-filter-research.md.
"""
from pathlib import Path
import argparse
import json
import time

from PIL import Image, ImageDraw, ImageOps
from markdown_to_handwrite.scanner import process_scan_image, detect_page_corners


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("output/scan-challenge/sources"))
    parser.add_argument("--output", type=Path, default=Path("output/scan-challenge/after"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    modes = ("original", "smart", "bw", "bright", "grayscale", "invert")
    metrics = []
    sheets = []
    for path in sorted(args.sources.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        # Use identical geometry for every filter, including original.
        corners = detect_page_corners(image)
        sheet = Image.new("RGB", (300 * len(modes), 430), "#e8edf5")
        draw = ImageDraw.Draw(sheet)
        for i, mode in enumerate(modes):
            start = time.perf_counter()
            result = process_scan_image(image, corners, mode)
            elapsed = time.perf_counter() - start
            result.save(args.output / f"{path.stem}-{mode}.png")
            thumb = ImageOps.contain(result, (290, 390), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (i * 300 + (300 - thumb.width) // 2, 30 + (390 - thumb.height) // 2))
            draw.text((i * 300 + 10, 8), mode, fill="black")
            metrics.append({"sample": path.name, "mode": mode, "seconds": round(elapsed, 3), "corners_detected": bool(corners), "size": list(result.size)})
        sheet.save(args.output / f"{path.stem}-comparison.jpg", quality=94)
        sheets.append(sheet)
    if sheets:
        overview = Image.new("RGB", (300 * len(modes), 430 * len(sheets)), "white")
        for i, sheet in enumerate(sheets):
            overview.paste(sheet, (0, 430 * i))
        overview.save(args.output / "overview.jpg", quality=94)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Rendered {len(sheets)} samples, {len(metrics)} filter results in {args.output}")


if __name__ == "__main__":
    main()
