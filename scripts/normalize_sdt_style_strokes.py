#!/usr/bin/env python3
"""Create a topology-preserving, thin-stroke SDT reference variant.

The output remains style-conditioning input only; it is never used as a set of
font glyphs. Zhang-Suen thinning is used instead of erosion so narrow strokes
are less likely to break apart.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DEFAULT = ROOT / "training/new_chinese_handwriting/prepared/sdt-style-samples"
OUTPUT_DEFAULT = ROOT / "training/new_chinese_handwriting/generated/diagnostics/style-skeleton"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DEFAULT)
    return parser.parse_args()


def zhang_suen_thin(binary: np.ndarray) -> np.ndarray:
    """Return a 1-pixel medial-line mask while preserving connected strokes."""
    image = np.asarray(binary, dtype=np.uint8).copy()
    while True:
        changed = False
        for phase in (0, 1):
            padded = np.pad(image, 1)
            north = padded[:-2, 1:-1]
            north_east = padded[:-2, 2:]
            east = padded[1:-1, 2:]
            south_east = padded[2:, 2:]
            south = padded[2:, 1:-1]
            south_west = padded[2:, :-2]
            west = padded[1:-1, :-2]
            north_west = padded[:-2, :-2]
            neighbors = (north, north_east, east, south_east, south, south_west, west, north_west)
            neighbor_count = sum(neighbors)
            ring = neighbors + (north,)
            transitions = sum(
                ((ring[index] == 0) & (ring[index + 1] == 1)).astype(np.uint8)
                for index in range(8)
            )
            candidates = (image == 1) & (neighbor_count >= 2) & (neighbor_count <= 6) & (transitions == 1)
            if phase == 0:
                remove = candidates & ((north * east * south) == 0) & ((east * south * west) == 0)
            else:
                remove = candidates & ((north * east * west) == 0) & ((north * south * west) == 0)
            if np.any(remove):
                image[remove] = 0
                changed = True
        if not changed:
            return image


def make_contact_sheet(images: list[Path], output: Path) -> None:
    columns = 7
    cell = 92
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell, rows * cell), "#f5f2ea")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, path in enumerate(images):
        image = Image.open(path).convert("L").convert("RGB")
        x, y = index % columns * cell, index // columns * cell
        sheet.paste(image, (x + 14, y + 2))
        draw.text((x + 4, y + 68), f"{index + 1:02}", fill="#222", font=font)
    sheet.save(output)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(args.input_dir.glob("style_[0-9][0-9].png"))
    if len(files) < 15:
        raise ValueError(f"Expected at least 15 numbered style images, found {len(files)}")
    for old in args.output_dir.glob("style_[0-9][0-9].png"):
        old.unlink()

    output_files = []
    for source in files:
        image = np.asarray(Image.open(source).convert("L"))
        skeleton = zhang_suen_thin(image < 128)
        result = np.where(skeleton, 0, 255).astype(np.uint8)
        destination = args.output_dir / source.name
        Image.fromarray(result).save(destination, optimize=True)
        output_files.append(destination)

    source_manifest_path = args.input_dir / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8")) if source_manifest_path.is_file() else {}
    manifest = {
        "method": "Zhang-Suen topology-preserving thinning of binary SDT reference glyphs",
        "status": "diagnostic_style_condition_variant_not_a_font_glyph_set",
        "image_count": len(output_files),
        "input_directory": str(args.input_dir),
        "source_samples": source_manifest.get("samples", []),
        "warning": "Use only as style-conditioning input. This diagnostic thins reference strokes; the resulting glyphs must not be packaged as or confused with the generated font.",
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_contact_sheet(output_files, args.output_dir / "style_reference_contact_sheet.png")
    print(f"Wrote {len(output_files)} topology-preserving thin references to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
