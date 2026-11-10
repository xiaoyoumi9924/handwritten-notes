#!/usr/bin/env python3
"""Build a local, human-correctable review sheet from Apple Vision OCR output.

The OCR text is personal source material, so the generated CSV and OCR JSON are
kept out of Git. The tracked manifest receives aggregate coverage statistics
only; it never receives transcribed page text.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
OCR_FILE = DATASET / "ocr-lines.json"
REVIEW_FILE = DATASET / "ocr-review.csv"
MANIFEST_FILE = DATASET / "manifest.json"
LOW_CONFIDENCE = 0.60


def is_han(char: str) -> bool:
    codepoint = ord(char)
    if char == "〇":
        return True
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x323AF
    )


def main() -> None:
    if not OCR_FILE.exists():
        raise SystemExit(f"OCR output not found: {OCR_FILE}; run scripts/ocr_handwriting_pages.swift first")

    dataset = json.loads(OCR_FILE.read_text(encoding="utf-8"))
    prior_rows: dict[tuple[str, int], dict[str, str]] = {}
    if REVIEW_FILE.exists():
        with REVIEW_FILE.open(encoding="utf-8-sig", newline="") as handle:
            for prior in csv.DictReader(handle):
                try:
                    key = (prior["page"], int(prior["line_index"]))
                except (KeyError, ValueError):
                    continue
                prior_rows[key] = prior

    rows: list[dict[str, str | int | float]] = []
    candidates: list[str] = []
    confidences: list[float] = []
    page_summaries = []

    for page in dataset["pages"]:
        page_confidences = []
        for line_index, line in enumerate(page["lines"], start=1):
            box = line["box"]
            text = line["text"]
            confidence = float(line["confidence"])
            key = (page["file"], line_index)
            previous = prior_rows.get(key, {})
            rows.append({
                "page": page["file"],
                "line_index": line_index,
                "confidence": f"{confidence:.3f}",
                "box_x": box["x"],
                "box_y": box["y"],
                "box_width": box["width"],
                "box_height": box["height"],
                "candidate_text": text,
                "corrected_text": previous.get("corrected_text", ""),
                "review_status": previous.get("review_status", "needs_review"),
                "review_notes": previous.get("review_notes", ""),
            })
            candidates.append(text)
            confidences.append(confidence)
            page_confidences.append(confidence)

        page_summaries.append({
            "file": page["file"],
            "lines": len(page["lines"]),
            "mean_confidence": round(sum(page_confidences) / len(page_confidences), 4) if page_confidences else 0,
            "below_0_60": sum(value < LOW_CONFIDENCE for value in page_confidences),
        })

    columns = [
        "page", "line_index", "confidence", "box_x", "box_y", "box_width", "box_height",
        "candidate_text", "corrected_text", "review_status", "review_notes",
    ]
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    han_chars = [char for text in candidates for char in text if is_han(char)]
    summary = {
        "method": "Apple Vision OCR; uncorrected line candidates",
        "review_file": "ocr-review.csv (local and gitignored)",
        "line_count": len(rows),
        "han_character_candidates": len(han_chars),
        "unique_han_character_candidates": len(set(han_chars)),
        "mean_line_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0,
        "lines_below_0_60_confidence": sum(value < LOW_CONFIDENCE for value in confidences),
        "manual_review_required": True,
        "warning": "Candidate character coverage is approximate; OCR errors, watermark overlap, and ruled lines require manual review.",
        "pages": page_summaries,
    }

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    manifest["ocr_preliminary"] = summary
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Review sheet: {len(rows)} lines; {len(set(han_chars))} unique Han candidates; "
        f"mean OCR confidence {summary['mean_line_confidence']:.3f}; "
        f"{summary['lines_below_0_60_confidence']} lines below {LOW_CONFIDENCE:.2f}."
    )
    print(f"Local review CSV: {REVIEW_FILE}")
    print("Manifest updated with aggregate counts only; source transcription stays local.")


if __name__ == "__main__":
    main()
