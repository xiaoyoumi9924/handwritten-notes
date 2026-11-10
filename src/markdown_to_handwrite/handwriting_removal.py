"""Optional local handwriting erasure, for printed worksheets (experimental)."""
from functools import lru_cache
import hashlib
import importlib.util
from pathlib import Path
import threading

import cv2
import numpy as np
from .scan_illumination import paper_background

MODEL_PATH = Path(__file__).resolve().parents[2] / "models/handwriting/isnet5.pth"
MODEL_SHA256 = "d685cc76a8c4d6aebf9a82499b7771d13aaa27ebd90e933036bdd004db4beefa"
MODEL_SIZE = 176718414
_LOCK = threading.Lock()


def available() -> bool:
    return MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == MODEL_SIZE and importlib.util.find_spec("torch") is not None


@lru_cache(maxsize=1)
def _load_model():
    if not available():
        raise ValueError("去除手写模型未安装，请先安装本地模型和扫描 AI 依赖。")
    digest = hashlib.sha256()
    with MODEL_PATH.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError("去除手写模型校验失败，请重新下载模型。")
    import torch
    from .vendor.isnet import ISNetDIS
    model = ISNetDIS().eval()
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True))
    return model


def mask_from_probability(probability: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Use absolute probabilities, never stretch a low-confidence empty page.

    Page-wise min/max normalization could turn 0.01 false positives on an
    entirely printed page into confident erasure. Keep low-threshold regions
    only when connected to a high-threshold seed, then expand one model pixel
    to include antialiased pen edges and map to the original resolution.
    """
    count, labels = cv2.connectedComponents((probability >= .35).astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[np.unique(labels[probability >= .8])] = True
    keep[0] = False
    mask = keep[labels].astype(np.uint8)
    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8))
    height, width = shape
    return cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)


def _predict(model, rgb: np.ndarray, *, enlarge: bool = False) -> np.ndarray:
    """Run one model input and return probabilities in the input coordinates."""
    import torch
    height, width = rgb.shape[:2]
    scale = 1024 / max(height, width)
    if not enlarge:
        scale = min(1.0, scale)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    resized = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    padded = np.ones((1024, 1024, 3), dtype=np.uint8)
    padded[:h, :w] = resized[:, :, ::-1]
    tensor = torch.from_numpy(padded.copy()).permute(2, 0, 1).float()[None] / 255.0 - .5
    with torch.inference_mode():
        prediction = model(tensor)[0][0][0, 0].cpu().numpy()[:h, :w]
    return cv2.resize(prediction, (width, height), interpolation=cv2.INTER_LINEAR)


def _needs_detail_pass(probability: np.ndarray) -> bool:
    """Retry only a substantial, ambiguous response without confident ink."""
    return .5 <= float(probability.max()) < .8 and float(np.percentile(probability, 99.9)) >= .14


def _needs_sparse_detail_pass(probability: np.ndarray) -> bool:
    """Retry sparse annotations even when a few strokes already have seeds.

    Dense handwriting stays on the whole-page path. These are conservative
    workload gates, not a classifier for handwritten versus printed text.
    """
    strong = float(np.mean(probability >= .8))
    candidate = float(np.mean(probability >= .35))
    return .0001 <= strong < .003 and .001 <= candidate < .015


def _detail_probability(model, rgb: np.ndarray) -> np.ndarray:
    """Magnify small writing, while bounding the number of model calls."""
    height, width = rgb.shape[:2]
    scale = min(1.0, 1800 / max(height, width))
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    work = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    result = np.zeros((h, w), dtype=np.float32)
    weights = np.zeros((h, w), dtype=np.float32)

    def starts(length):
        last = max(0, length - 768)
        return sorted(set([*range(0, last, 640), last]))

    for y in starts(h):
        for x in starts(w):
            patch = work[y:y + 768, x:x + 768]
            ph, pw = patch.shape[:2]
            # Overlap supplies context around strokes cut by a tile boundary.
            # Trust the patch centre more, without creating zero-weight edges.
            wy = np.minimum(np.arange(ph) + 1, np.arange(ph, 0, -1))
            wx = np.minimum(np.arange(pw) + 1, np.arange(pw, 0, -1))
            blend = np.minimum(wy[:, None], wx[None, :]).clip(1, 64).astype(np.float32)
            result[y:y + ph, x:x + pw] += _predict(model, patch, enlarge=True) * blend
            weights[y:y + ph, x:x + pw] += blend
    return result / weights


def _long_straight_lines(rgb: np.ndarray) -> np.ndarray:
    """Identify long rules likely to be part of a printed form.

    This also protects handwritten straight lines; distinguishing them from
    printed rules requires semantic information this detector does not have.
    """
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ink = (gray < 150).astype(np.uint8)
    length = max(30, min(120, min(height, width) // 30))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((length, 1), np.uint8))
    return cv2.dilate(horizontal | vertical, np.ones((3, 3), np.uint8)).astype(bool)


def remove_handwriting(rgb: np.ndarray) -> np.ndarray:
    # Serialize model use to bound concurrent preview/processing memory.
    with _LOCK:
        model = _load_model()
        height, width = rgb.shape[:2]
        # Normalize only the model input. Output outside the erasure mask must
        # retain its original pixels, including colored print and paper cast.
        background = paper_background(rgb)
        normalized = cv2.divide(rgb, background, scale=250)
        prediction = _predict(model, normalized)
        mask = mask_from_probability(prediction, (height, width))
        if (_needs_detail_pass(prediction)
                or (max(height, width) > 1024 and _needs_sparse_detail_pass(prediction))):
            detail = _detail_probability(model, normalized)
            # Threshold each scale independently: mixing probabilities could
            # connect a weak false region to a seed from an unrelated scale.
            mask |= mask_from_probability(detail, (height, width))
        mask &= ~_long_straight_lines(normalized)
        if not mask.any():
            return rgb.copy()
        # Extend adjacent paper into erased areas to avoid bright patches on
        # shadowed pages. Pixels outside the detected mask remain untouched.
        repaired = cv2.inpaint(rgb, mask.astype(np.uint8), 3, cv2.INPAINT_TELEA)
        result = rgb.copy()
        result[mask] = repaired[mask]
        return result
