"""Evaluate page outlines against FairScan validation masks (research use)."""
import argparse
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
parser = argparse.ArgumentParser()
parser.add_argument('dataset', type=Path, help='FairScan val directory')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--scanner', type=Path, help='Optional scanner.py snapshot for comparison')
args = parser.parse_args()
if args.scanner:
    spec = importlib.util.spec_from_file_location('markdown_to_handwrite._benchmark_scanner', args.scanner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    detect_page_geometry = module._detect_page_geometry
else:
    from markdown_to_handwrite.scanner import _detect_page_geometry as detect_page_geometry
rows = []
for path in sorted((args.dataset / 'images').glob('*')):
    mask_path = args.dataset / 'masks' / (path.stem + '.png')
    if not mask_path.exists():
        continue
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
    with Image.open(mask_path) as opened:
        mask = np.asarray(opened.convert('L').resize(image.size, Image.Resampling.NEAREST)) > 127
    corners, _ = detect_page_geometry(image)
    predicted = np.zeros((image.height, image.width), np.uint8)
    if corners:
        points = np.rint(np.asarray(corners) * [image.width, image.height]).astype(np.int32)
        cv2.fillConvexPoly(predicted, points, 1)
    intersection = np.logical_and(mask, predicted).sum()
    union = np.logical_or(mask, predicted).sum()
    rows.append({'image': path.name, 'detected': bool(corners), 'iou': float(intersection / union) if union else 0.0})
summary = {'count': len(rows), 'detected': sum(row['detected'] for row in rows),
           'mean_iou': float(np.mean([row['iou'] for row in rows])),
           'iou_at_least_0_9': sum(row['iou'] >= .9 for row in rows), 'results': rows}
args.output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
print({key: value for key, value in summary.items() if key != 'results'})
