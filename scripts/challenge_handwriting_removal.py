"""Stress-test local erasure against its first-release baseline.

Transformations are synthetic, not independent real photos. Region-change
measurements are diagnostics, not a complete handwriting-accuracy score.
"""
from pathlib import Path
import argparse
import json
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from markdown_to_handwrite.handwriting_removal import _load_model, remove_handwriting


def baseline(rgb):
    """Frozen v1: raw input, single threshold, and solid-white fill."""
    import torch
    h, w = rgb.shape[:2]
    scale = min(1.0, 1024/max(h, w))
    iw, ih = max(1, round(w*scale)), max(1, round(h*scale))
    padded = np.ones((1024, 1024, 3), dtype=np.uint8)
    padded[:ih, :iw] = cv2.resize(rgb, (iw, ih), interpolation=cv2.INTER_AREA)[:, :, ::-1]
    tensor = torch.from_numpy(padded.copy()).permute(2, 0, 1).float()[None]/255-.5
    with torch.inference_mode():
        probability = _load_model()(tensor)[0][0][0, 0].numpy()[:ih, :iw]
    mask = cv2.dilate((probability >= .35).astype(np.uint8), np.ones((3, 3), np.uint8))
    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
    result = rgb.copy()
    result[mask] = 255
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("output/handwriting-removal/sources"))
    parser.add_argument("--output", type=Path, default=Path("output/handwriting-robustness/final"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    _load_model()
    for path in sorted(args.sources.iterdir()):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        rgb = np.asarray(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))
        h, w = rgb.shape[:2]
        variants = ["original", "shadow", "rotate4"]
        if path.stem == "eraser-test2":
            variants.append("scale2")
        for variant in variants:
            image = rgb.copy()
            header = np.zeros((h, w), np.uint8)
            answer = np.zeros((h, w), np.uint8)
            if path.stem == "eraser-test2":
                header[:180] = 1
                answer[180:680] = 1
            if variant == "shadow":
                lighting = np.tile(np.linspace(.35, 1, w, dtype=np.float32), (h, 1))
                image = np.rint(image*lighting[:, :, None]).astype(np.uint8)
            if variant == "rotate4":
                transform = cv2.getRotationMatrix2D((w/2, h/2), 4, 1)
                image = cv2.warpAffine(image, transform, (w, h), borderValue=(255, 255, 255))
                header = cv2.warpAffine(header, transform, (w, h), flags=cv2.INTER_NEAREST)
                answer = cv2.warpAffine(answer, transform, (w, h), flags=cv2.INTER_NEAREST)
            if variant == "scale2":
                image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                header = cv2.resize(header, (w*2, h*2), interpolation=cv2.INTER_NEAREST)
                answer = cv2.resize(answer, (w*2, h*2), interpolation=cv2.INTER_NEAREST)
            outputs = [("input", image)]
            # Measure ink locations on the pre-shadow source, so the synthetic
            # shadow itself is not mistaken for additional handwritten ink.
            ink_source = image
            if variant == "shadow":
                ink_source = rgb
            dark = ink_source.min(axis=2) < 150
            for method, function in (("baseline", baseline), ("improved", remove_handwriting)):
                start = time.perf_counter()
                result = function(image)
                entry = {"sample": path.name, "variant": variant, "method": method,
                         "seconds": round(time.perf_counter()-start, 3),
                         "unchanged": bool(np.array_equal(image, result))}
                changed = np.any(result != image, axis=2)
                if path.stem == "eraser-test2":
                    for name, region in (("printed_header", header), ("answer_region", answer)):
                        region_ink = dark & region.astype(bool)
                        entry[name+"_dark_changed_fraction"] = round(float((changed & region_ink).sum()/max(1, region_ink.sum())), 5)
                records.append(entry)
                outputs.append((method, result))
                Image.fromarray(result).save(args.output/f"{path.stem}-{variant}-{method}.png")
                print(entry, flush=True)
            sheet = Image.new("RGB", (1500, 600), "#e8edf5")
            draw = ImageDraw.Draw(sheet)
            for i, (label, result) in enumerate(outputs):
                thumb = ImageOps.contain(Image.fromarray(result), (490, 560), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (i*500+(500-thumb.width)//2, 30))
                draw.text((i*500+10, 8), label, fill="black")
            sheet.save(args.output/f"{path.stem}-{variant}-comparison.jpg", quality=94)
    (args.output/"metrics.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
