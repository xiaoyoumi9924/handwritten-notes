#!/usr/bin/env python3
"""Create provisional glyph crops only where line text and ink runs match.

This conservative first pass does not guess cuts for mismatched rows. Every
output remains a candidate because source transcription and watermarks still
need manual review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
SOURCE = DATASET / "source"
NORMALIZED = DATASET / "prepared" / "normalized"
OCR_FILE = DATASET / "ocr-lines.json"
REVIEW_FILE = DATASET / "ocr-review.csv"
OUTPUT = DATASET / "prepared" / "glyph-candidates"


def text_glyphs(text: str) -> list[str]:
    return [char for char in text if not char.isspace()]


def active_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    occupied = mask.any(axis=0)
    starts = np.flatnonzero(occupied & ~np.r_[False, occupied[:-1]])
    ends = np.flatnonzero(occupied & ~np.r_[occupied[1:], False]) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-page", type=int, default=1, help="only process pages at or after this number")
    args = parser.parse_args()

    ocr = json.loads(OCR_FILE.read_text(encoding="utf-8"))
    with REVIEW_FILE.open(encoding="utf-8-sig", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    review = {(row["page"], int(row["line_index"])): row for row in review_rows}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old_crop in OUTPUT.glob("page_*_line_*_char_*.png"):
        old_crop.unlink()
    for generated in (OUTPUT / "glyph-candidates.json", OUTPUT / "glyph-candidates.csv"):
        if generated.exists():
            generated.unlink()

    samples: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    glyph_counts: Counter[str] = Counter()
    processed_lines = 0

    for page in ocr["pages"]:
        page_number = int(Path(page["file"]).stem.split("_")[-1])
        if page_number < args.from_page:
            continue

        mask_path = NORMALIZED / Path(page["file"]).name.replace(".png", "_ink_candidate.png")
        color_path = NORMALIZED / Path(page["file"]).name.replace(".png", "_rules_suppressed.png")
        with Image.open(mask_path) as image:
            page_mask = np.asarray(image.convert("L")) < 128
        with Image.open(color_path) as image:
            page_color = image.convert("L")

        for line_index, line in enumerate(page["lines"], start=1):
            record = review[(page["file"], line_index)]
            chars = text_glyphs(record["corrected_text"])
            if not chars or record["review_status"] == "overlapping_box_manual_check":
                skipped.append({"page": page["file"], "line_index": line_index, "reason": "empty_or_overlapping_text_box"})
                continue

            box = line["box"]
            y0 = max(0, box["y"] - 4)
            y1 = min(page_mask.shape[0], box["y"] + box["height"] + 4)
            x0 = max(0, box["x"])
            x1 = min(page_mask.shape[1], box["x"] + box["width"])
            line_mask = page_mask[y0:y1, x0:x1]
            runs = active_runs(line_mask)
            if len(runs) != len(chars):
                skipped.append({
                    "page": page["file"],
                    "line_index": line_index,
                    "reason": "projection_run_count_mismatch",
                    "text_glyph_count": len(chars),
                    "ink_run_count": len(runs),
                    "transcription_status": record["review_status"],
                })
                continue

            processed_lines += 1
            for char_index, (char, (left, right)) in enumerate(zip(chars, runs, strict=True), start=1):
                top = max(0, y0 + int(np.flatnonzero(line_mask[:, left:right].any(axis=1))[0]) - 2)
                bottom = min(page_color.height, y0 + int(np.flatnonzero(line_mask[:, left:right].any(axis=1))[-1]) + 3)
                crop_left = max(0, x0 + left - 1)
                crop_right = min(page_color.width, x0 + right + 1)
                crop = page_color.crop((crop_left, top, crop_right, bottom))
                filename = f"page_{page_number:03}_line_{line_index:02}_char_{char_index:03}.png"
                crop.save(OUTPUT / filename, optimize=True)
                glyph_counts[char] += 1
                samples.append({
                    "file": f"prepared/glyph-candidates/{filename}",
                    "label_candidate": char,
                    "page": page["file"],
                    "line_index": line_index,
                    "char_index": char_index,
                    "bbox": {"x": crop_left, "y": top, "width": crop.width, "height": crop.height},
                    "line_confidence": line["confidence"],
                    "status": "provisional_unverified",
                    "watermark_retained": True,
                    "transcription_status": record["review_status"],
                })

    report = {
        "method": "vertical ink projection; only exact character-count/run-count lines emitted",
        "status": "provisional_candidates_only",
        "processed_lines": processed_lines,
        "glyph_crop_count": len(samples),
        "unique_label_candidates": len(glyph_counts),
        "character_frequency": dict(sorted(glyph_counts.items())),
        "samples": samples,
        "skipped_lines": skipped,
        "warning": "Exact run counts do not prove correct glyph boundaries. Transcription, watermark overlap, and every crop require visual review before font construction.",
    }
    (OUTPUT / "glyph-candidates.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUTPUT / "glyph-candidates.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        columns = [
            "file", "label_candidate", "page", "line_index", "char_index", "bbox_x", "bbox_y",
            "bbox_width", "bbox_height", "line_confidence", "status", "watermark_retained",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for sample in samples:
            bbox = sample["bbox"]
            writer.writerow({
                "file": sample["file"],
                "label_candidate": sample["label_candidate"],
                "page": sample["page"],
                "line_index": sample["line_index"],
                "char_index": sample["char_index"],
                "bbox_x": bbox["x"],
                "bbox_y": bbox["y"],
                "bbox_width": bbox["width"],
                "bbox_height": bbox["height"],
                "line_confidence": sample["line_confidence"],
                "status": sample["status"],
                "watermark_retained": sample["watermark_retained"],
            })

    manifest_path = DATASET / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["glyph_candidate_segmentation"] = {
        "method": report["method"],
        "processed_lines": processed_lines,
        "glyph_crop_count": len(samples),
        "unique_label_candidates": len(glyph_counts),
        "skipped_lines": len(skipped),
        "status": "provisional_requires_visual_review",
        "warning": report["warning"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Provisional lines segmented: {processed_lines}")
    print(f"Candidate glyph crops: {len(samples)} across {len(glyph_counts)} distinct labels")
    print(f"Lines skipped for review: {len(skipped)}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
