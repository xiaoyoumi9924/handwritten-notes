"""Distinct exposure and local monochrome pipelines for photographed paper."""
import cv2
import numpy as np

from .scan_illumination import paper_background


def brighten_document(rgb: np.ndarray) -> np.ndarray:
    """Adapt exposure to paper brightness; apply one RGB gain to preserve hue."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    paper = float(np.percentile(gray, 80))
    # Near-white scans need little lifting, while dark photos need more. Keep
    # a bounded curve: severely underexposed noise cannot be recovered.
    gamma = float(np.clip(np.log(232 / 255) / np.log(max(1, min(paper, 254)) / 255), .58, .95))
    light = gray / 255
    gain = np.minimum(np.power(np.maximum(light, 1 / 255), gamma - 1), 2.2)
    # Compress a pixel's gain before any individual channel clips.
    maximum = rgb.max(axis=2).astype(np.float32)
    gain = np.minimum(gain, 255 / np.maximum(maximum, 1))
    return np.rint(np.clip(rgb.astype(np.float32) * gain[:, :, None], 0, 255)).astype(np.uint8)


def monochrome_document(rgb: np.ndarray) -> np.ndarray:
    """Sauvola local contrast on normalized paper, with soft grayscale edges.

    Local statistics prevent a black heading from setting the threshold for
    faint writing elsewhere. A narrow transition keeps antialiasing without
    morphology/dilation, which would widen handwriting and join small gaps.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    background = cv2.cvtColor(paper_background(rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    normalized = np.clip(gray * 255 / np.maximum(background, 1), 0, 255)
    window = max(15, min(151, (min(gray.shape) // 12) | 1))
    mean = cv2.boxFilter(normalized, -1, (window, window), borderType=cv2.BORDER_REFLECT)
    square_mean = cv2.boxFilter(normalized * normalized, -1, (window, window), borderType=cv2.BORDER_REFLECT)
    deviation = np.sqrt(np.maximum(square_mean - mean * mean, 0))
    threshold = mean * (1 + .20 * (deviation / 128 - 1))
    return np.rint(255 * np.clip((normalized - threshold) / 70 + .5, 0, 1)).astype(np.uint8)


def restore_pale_pen_color(rgb: np.ndarray, clean: np.ndarray) -> np.ndarray:
    """Retain subdued red/blue strokes without assigning color to blank paper.

    Absolute saturation alone misses faded pens. Require local chroma evidence
    relative to paper, the source hue, and an already detected ink pixel. Strong
    saturated ink keeps the existing exposure-only mapping and channel balance.
    """
    background = paper_background(rgb)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    paper_lab = cv2.cvtColor(background, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hue, saturation, _ = cv2.split(hsv)
    delta_a = lab[:, :, 1] - paper_lab[:, :, 1]
    delta_b = lab[:, :, 2] - paper_lab[:, :, 2]
    red = ((hue < 12) | (hue > 165)) * np.clip((delta_a - .5) / 1.5, 0, 1)
    blue = ((hue > 90) & (hue < 140)) * np.clip((-delta_b - 1) / 2, 0, 1)
    weight = np.maximum(red, blue) * np.clip((saturation - 18) / 15, 0, 1)
    weight *= np.clip((245 - clean.min(axis=2)) / 30, 0, 1)
    # This path supplements pale ink, leaving saturated inks on the existing
    # path. Smoothly fade at its boundary instead of switching at a threshold.
    weight *= np.clip((115 - saturation) / 20, 0, 1)
    light = cv2.cvtColor(background, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gain = np.clip(250 / np.maximum(light, 1), 1, 2.2)
    ink = np.rint(np.clip(rgb.astype(np.float32) * gain[:, :, None], 0, 255)).astype(np.uint8)
    ink_hsv = cv2.cvtColor(ink, cv2.COLOR_RGB2HSV).astype(np.float32)
    ink_hsv[:, :, 1] = np.minimum(255, ink_hsv[:, :, 1] *
        (1 + 1.5 * np.clip((115 - saturation) / 70, 0, 1)))
    ink = cv2.cvtColor(ink_hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    return clean * (1 - weight[:, :, None]) + ink * weight[:, :, None]


def sharpen_document(rgb: np.ndarray) -> np.ndarray:
    """Flatten paper, retain continuous color, and sharpen luminance edges.

    Unlike the smart ink extractor this keeps grayscale tone and broad colored
    fills. Gain and edge overshoot are bounded; it cannot recover lost detail.
    """
    paper_rgb = paper_background(rgb)
    background = cv2.cvtColor(paper_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # One global paper white balance removes camera cast without dividing
    # each colored cell by its own color and bleaching it to white.
    bright_paper = background >= np.percentile(background, 80)
    paper_color = np.median(paper_rgb[bright_paper], axis=0).astype(np.float32)
    balance = np.clip(np.mean(paper_color) / np.maximum(paper_color, 1), .85, 1.18)
    gain = np.minimum(255.0 / np.maximum(background, 1), 2.8)
    normalized = np.clip(rgb.astype(np.float32) * gain[:, :, None] * balance, 0, 255)
    # A soft black/white point lifts paper without hard-binarizing pencil edges.
    tone = np.clip((normalized - 24.0) / (242.0 - 24.0), 0, 1)
    corrected = np.rint(255 * np.power(tone, 1.8)).astype(np.uint8)
    corrected = cv2.bilateralFilter(corrected, 5, 10, 2)
    lab = cv2.cvtColor(corrected, cv2.COLOR_RGB2LAB)
    light = lab[:, :, 0].astype(np.float32)
    sigma = float(np.clip(min(rgb.shape[:2]) / 1000, .65, 1.3))
    detail = light - cv2.GaussianBlur(light, (0, 0), sigma)
    detail = np.sign(detail) * np.maximum(np.abs(detail) - 1.5, 0)
    sharpened = light + .85 * detail
    # Constrain overshoot to existing neighboring tones, preventing halos and
    # large negative ringing beside dark lines. No dilation of the ink mask.
    low = cv2.erode(light, np.ones((3, 3), np.uint8))
    high = cv2.dilate(light, np.ones((3, 3), np.uint8))
    lab[:, :, 0] = np.rint(np.clip(sharpened, low, high)).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
