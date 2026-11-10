#!/usr/bin/env python3
"""Create non-destructive local working copies with red ruling lines suppressed.

Watermarks are deliberately retained. These outputs are candidates for visual
inspection and later glyph extraction, not final training masks.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, median_filter


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "training" / "new_chinese_handwriting"
SOURCE = DATASET / "source"
OCR_FILE = DATASET / "ocr-lines.json"
OUTPUT = DATASET / "prepared" / "normalized"


def suppress_red_rules(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pixels = rgb.astype(np.int16)
    red_rule = (
        (pixels[:, :, 0] > 95)
        & ((pixels[:, :, 0] - pixels[:, :, 1]) > 8)
        & ((pixels[:, :, 0] - pixels[:, :, 2]) > 14)
        & (pixels[:, :, 0] > pixels[:, :, 1] * 1.02)
    )
    # The ruled line spans a few pixels; use a taller vertical neighborhood so
    # the replacement median comes from paper above and below the red stroke.
    local = median_filter(rgb, size=(11, 1, 1), mode="nearest")
    result = rgb.copy()
    result[red_rule] = local[red_rule]
    return result, red_rule


def main() -> None:
    pages = json.loads(OCR_FILE.read_text(encoding="utf-8"))["pages"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_rows = []

    for page in pages:
        filename = page["file"]
        with Image.open(SOURCE / filename) as source:
            rgb = np.asarray(source.convert("RGB"), dtype=np.uint8)

        cleaned, red_mask = suppress_red_rules(rgb)
        gray = (
            0.299 * cleaned[:, :, 0]
            + 0.587 * cleaned[:, :, 1]
            + 0.114 * cleaned[:, :, 2]
        ).astype(np.uint8)

        # Keep a deliberately conservative ink candidate for visual inspection.
        # Gray watermarks are not inpainted or erased and may still remain here.
        background = gaussian_filter(gray.astype(np.float32), sigma=18)
        contrast = background - gray.astype(np.float32)
        # A conservative darkness threshold removes most translucent gray
        # watermark strokes. Faint handwriting is retained for review in the
        # color copy, not guessed into this binary candidate.
        ink_candidate = (gray < 96) & (contrast > 34)
        ink_candidate[red_mask] = False

        stem = Path(filename).stem
        color_path = OUTPUT / f"{stem}_rules_suppressed.png"
        mask_path = OUTPUT / f"{stem}_ink_candidate.png"
        Image.fromarray(cleaned, mode="RGB").save(color_path, optimize=True)
        Image.fromarray(np.where(ink_candidate, 0, 255).astype(np.uint8), mode="L").save(mask_path, optimize=True)
        manifest_rows.append({
            "source": f"source/{filename}",
            "rules_suppressed": str(color_path.relative_to(DATASET)),
            "ink_candidate": str(mask_path.relative_to(DATASET)),
            "red_pixels_suppressed": int(red_mask.sum()),
            "ink_candidate_pixels": int(ink_candidate.sum()),
            "warning": "Watermarks retained; manually inspect before training.",
        })

    report = OUTPUT / "preprocess-manifest.json"
    report.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(manifest_rows)} color working copies and conservative ink masks in {OUTPUT}")
    print("Original source images were not changed; watermarks were not removed.")


if __name__ == "__main__":
    main()
