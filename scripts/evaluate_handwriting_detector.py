"""Inspect a candidate detector; never erase pixels based on these boxes.

Requires ultralytics in an experimental environment. Example:
  python scripts/evaluate_handwriting_detector.py --model /path/best.pt
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def main():
    from ultralytics import YOLO

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=Path("output/scan-challenge/sources"))
    parser.add_argument("--output", type=Path, default=Path("output/scan-challenge/detector"))
    parser.add_argument("--confidence", type=float, default=0.5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)
    records = []
    for path in sorted(args.sources.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        result = model.predict(image, device="cpu", verbose=False, conf=args.confidence)[0]
        boxes = result.boxes.xyxy.tolist()
        draw = ImageDraw.Draw(image)
        for box in boxes:
            draw.rectangle(tuple(box), outline="red", width=2)
        image.save(args.output / f"{path.stem}-boxes.jpg")
        records.append({"sample": path.name, "count": len(boxes), "boxes": boxes, "confidence": result.boxes.conf.tolist()})
    (args.output / "boxes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Inspected {len(records)} images at confidence {args.confidence}; no pixels erased")


if __name__ == "__main__":
    main()
