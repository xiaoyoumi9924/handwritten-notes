#!/usr/bin/env python3
"""Crop a 7x8 SDT handwriting capture sheet into reviewable glyph candidates.

The crop labels follow the printed 56-character capture-sheet order. These
images are style references only; they are not a trained font or output glyphs.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "training/new_chinese_handwriting/source/page_012.png"
DEFAULT_OUT = PROJECT_ROOT / "training/new_chinese_handwriting/prepared/sdt-capture-page-012-review"
ROWS = ["的一是不在人有我", "他这中大来上国个", "到说们为了和你地", "出道也时年得就那", "要下以生会自着去", "之过家学对可她妈", "心爱笔风雨水山好"]
Y_BOUNDS = [(47, 90), (112, 155), (177, 221), (243, 287), (309, 354), (375, 420), (440, 485)]
X_BOUNDS = [(46, 92), (106, 145), (161, 200), (217, 252), (272, 308), (326, 366), (380, 422), (438, 480)]
# Review warnings for glyph cells visually behind the page watermark.
WATERMARK_RISK = {40, 47, 48, 51, 52, 53, 54, 55, 56}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--threshold", type=int, default=105)
    return parser.parse_args()


def remove_trailing_cell_separator(mask: np.ndarray) -> np.ndarray:
    """Drop tiny comma-like marks caught at the lower-left cell boundary."""
    cleaned = mask.copy()
    height, width = cleaned.shape
    seen = np.zeros_like(cleaned, dtype=bool)
    for start_y, start_x in zip(*np.nonzero(cleaned)):
        if seen[start_y, start_x]:
            continue
        queue = deque([(int(start_y), int(start_x))])
        seen[start_y, start_x] = True
        component = []
        while queue:
            y, x = queue.popleft()
            component.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (0 <= ny < height and 0 <= nx < width and cleaned[ny, nx]
                            and not seen[ny, nx]):
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        ys = [point[0] for point in component]
        xs = [point[1] for point in component]
        if len(component) <= 16 and min(xs) <= 2 and min(ys) >= height - 8:
            for y, x in component:
                cleaned[y, x] = False
    return cleaned


def main() -> None:
    args = parse_args()
    with Image.open(args.source) as opened:
        source = opened.convert("RGB")
    rgb = np.asarray(source)
    if len(ROWS) != len(Y_BOUNDS) or any(len(row) != len(X_BOUNDS) for row in ROWS):
        raise RuntimeError("Capture-sheet geometry and character sequence do not match")

    # Keep dark, nearly neutral pen pixels. This suppresses the red rules and
    # most light-gray watermark while preserving a clean, high-contrast sample.
    gray = np.asarray(source.convert("L"))
    neutral = ((rgb[:, :, 0].astype(np.int16) - rgb[:, :, 1]) < 20) & (
        (rgb[:, :, 0].astype(np.int16) - rgb[:, :, 2]) < 28
    )
    ink = (gray < args.threshold) & neutral

    args.output_dir.mkdir(parents=True, exist_ok=True)
    thumb_size = 112
    tile_w, tile_h = 132, 145
    columns = 8
    sheet = Image.new("RGB", (columns * tile_w, 7 * tile_h), "#f3efe6")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    samples = []

    for row_index, (characters, (y0, y1)) in enumerate(zip(ROWS, Y_BOUNDS)):
        for column_index, character in enumerate(characters):
            sample_id = row_index * 8 + column_index + 1
            x0, x1 = X_BOUNDS[column_index]
            cell_mask = remove_trailing_cell_separator(ink[y0:y1, x0:x1])
            ys, xs = np.nonzero(cell_mask)
            if len(xs) == 0:
                raise ValueError(f"No dark pen pixels detected for sample {sample_id} ({character})")
            left, right = max(0, int(xs.min()) - 2), min(x1 - x0, int(xs.max()) + 3)
            top, bottom = max(0, int(ys.min()) - 2), min(y1 - y0, int(ys.max()) + 3)
            # Binary black-on-white samples intentionally omit paper, red rules,
            # gray watermark, and camera shadows.
            crop = np.where(cell_mask[top:bottom, left:right], 0, 255).astype(np.uint8)
            glyph = Image.fromarray(crop, mode="L")
            glyph.thumbnail((56, 56), Image.Resampling.LANCZOS)
            canvas = Image.new("L", (64, 64), 255)
            canvas.paste(glyph, ((64 - glyph.width) // 2, (64 - glyph.height) // 2))
            filename = f"glyph_{sample_id:02d}.png"
            canvas.save(args.output_dir / filename)

            tile_x, tile_y = column_index * tile_w, row_index * tile_h
            preview = canvas.convert("RGB").resize((thumb_size, thumb_size), Image.Resampling.NEAREST)
            sheet.paste(preview, (tile_x + (tile_w - thumb_size) // 2, tile_y))
            risk = sample_id in WATERMARK_RISK
            draw.text((tile_x + 6, tile_y + thumb_size + 7), f"{sample_id:02d} {character}" + (" !" if risk else ""),
                      fill="#a33" if risk else "#222", font=font)
            samples.append({
                "file": filename,
                "label": character,
                "row": row_index + 1,
                "column": column_index + 1,
                "source_bbox": {"x": x0 + left, "y": y0 + top, "width": right - left, "height": bottom - top},
                "watermark_risk": risk,
                "status": "review_candidate_not_yet_promoted",
            })

    sheet_path = args.output_dir / "capture_reference_contact_sheet.png"
    sheet.save(sheet_path)
    manifest = {
        "source": str(args.source),
        "method": "manual 7x8 capture-sheet cell crops; dark neutral-ink threshold; aspect-preserving fit on white 64px canvas",
        "threshold": args.threshold,
        "size": [64, 64],
        "sample_count": len(samples),
        "watermark_risk_ids": sorted(WATERMARK_RISK),
        "contact_sheet": sheet_path.name,
        "warning": "Automated crops are review candidates. Watermark-adjacent cells are flagged and must not be used as style references until visually approved.",
        "samples": samples,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(samples)} glyph review crops to {args.output_dir}")
    print(f"Contact sheet: {sheet_path}")


if __name__ == "__main__":
    main()
