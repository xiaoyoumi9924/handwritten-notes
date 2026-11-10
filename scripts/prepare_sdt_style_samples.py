#!/usr/bin/env python3
"""Prepare isolated handwriting references for the official SDT style encoder.

These crops are style-conditioning inputs only. They are never assembled into
font glyphs; SDT is expected to generate new characters from the references.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
GLYPH_REPORT = DATASET / "prepared" / "glyph-candidates" / "glyph-candidates.json"
NORMALIZED = DATASET / "prepared" / "normalized"
OUTPUT = DATASET / "prepared" / "sdt-style-samples"
# Use several high-confidence lines from the same writer instead of relying on
# one line. SDT's user-generation loader consumes every image in style_path.
SOURCE_LINES = [("page_004.png", 5), ("page_005.png", 2), ("page_006.png", 3)]
MAX_REFERENCES = 50
CANVAS = 64
INK_SIZE = 56


def main() -> None:
    report = json.loads(GLYPH_REPORT.read_text(encoding="utf-8"))
    selected_samples = []
    seen_labels: set[str] = set()
    for page, line_index in SOURCE_LINES:
        line_samples = [
            sample for sample in report["samples"]
            if sample["page"] == page and int(sample["line_index"]) == line_index
        ]
        for sample in line_samples:
            label = sample["label_candidate"]
            if (len(label) != 1 or not ("\u4e00" <= label <= "\u9fff")
                    or sample["line_confidence"] < 0.8 or label in seen_labels):
                continue
            selected_samples.append(sample)
            seen_labels.add(label)
            if len(selected_samples) >= MAX_REFERENCES:
                break
        if len(selected_samples) >= MAX_REFERENCES:
            break
    if len(selected_samples) < 15:
        raise ValueError(f"Need at least 15 clean style candidates, found {len(selected_samples)}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT.glob("style_*.png"):
        old.unlink()

    provenance = []
    prepared_images: list[Image.Image] = []
    for output_index, sample in enumerate(selected_samples, start=1):
        page = sample["page"]
        with Image.open(NORMALIZED / page.replace(".png", "_ink_candidate.png")) as image:
            ink_mask = np.asarray(image.convert("L")) < 128
        box = sample["bbox"]
        margin = 2
        x0 = max(0, box["x"] - margin)
        y0 = max(0, box["y"] - margin)
        x1 = min(ink_mask.shape[1], box["x"] + box["width"] + margin)
        y1 = min(ink_mask.shape[0], box["y"] + box["height"] + margin)
        crop = Image.fromarray(np.where(ink_mask[y0:y1, x0:x1], 0, 255).astype(np.uint8))
        # ``thumbnail`` only shrinks; these source crops are smaller than 56px,
        # so it left the handwriting tiny inside the 64px canvas. Scale up while
        # preserving aspect ratio to match the glyph occupancy of SDT references.
        scale = INK_SIZE / max(crop.width, crop.height)
        resized = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(resized, Image.Resampling.LANCZOS)
        canvas = Image.new("L", (CANVAS, CANVAS), 255)
        canvas.paste(crop, ((CANVAS - crop.width) // 2, (CANVAS - crop.height) // 2))
        filename = f"style_{output_index:02}.png"
        canvas.save(OUTPUT / filename, optimize=True)
        prepared_images.append(canvas)
        provenance.append({
            "file": filename,
            "source_page": page,
            "source_line": int(sample["line_index"]),
            "source_char_index": int(sample["char_index"]),
            "label_candidate_for_reference_only": sample["label_candidate"],
            "line_confidence_candidate": sample["line_confidence"],
            "source_bbox": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
            "use": "unlabelled style conditioning input; not a font glyph",
        })

    manifest = {
        "method": "first unique Han glyphs from three high-confidence lines; thresholded crops, aspect-preserving upscale to 56px, centered on a 64px canvas",
        "status": "expanded_reference_images_prepared_pending_visual_review_and_sdt_inference",
        "image_count": len(provenance),
        "size": [CANVAS, CANVAS],
        "source_lines": [{"page": page, "line": line} for page, line in SOURCE_LINES],
        "samples": provenance,
        "warning": "These unlabelled images condition the pretrained generator; they are not font glyphs. Candidate line text is OCR-derived and used only to avoid duplicates; reject any visibly corrupted crop before inference.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cell_w, cell_h, columns = 104, 112, 5
    rows = (len(provenance) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "#f6f3eb")
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 14, index=0)
    for index, (sample, image) in enumerate(zip(provenance, prepared_images, strict=True)):
        x, y = (index % columns) * cell_w, (index // columns) * cell_h
        sheet.paste(image.convert("RGB"), (x + 20, y + 4))
        draw.text((x + 4, y + 72), f"{index + 1:02}  {sample['label_candidate_for_reference_only']}", font=label_font, fill="#28312c")
    sheet.save(OUTPUT / "style_reference_contact_sheet.png", optimize=True)
    print(f"Prepared {len(provenance)} SDT style-reference images in {OUTPUT}")


if __name__ == "__main__":
    main()
