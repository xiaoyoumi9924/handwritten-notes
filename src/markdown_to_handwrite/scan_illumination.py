"""Shared illumination estimation for light-paper scans."""
import cv2
import numpy as np


def _paper_background(channel: np.ndarray) -> np.ndarray:
    """Close dark strokes before smoothing; bound cost on large camera images."""
    height, width = channel.shape
    scale = min(1.0, 1400 / max(height, width))
    work = cv2.resize(channel, (max(1, round(width*scale)), max(1, round(height*scale))), interpolation=cv2.INTER_AREA) if scale < 1 else channel
    size = max(15, min(101, (min(work.shape)//16) | 1))
    background = cv2.morphologyEx(work, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    background = cv2.GaussianBlur(background, (0, 0), max(1.0, size/8))
    if scale < 1:
        background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.maximum(background, 1)


def paper_background(rgb: np.ndarray) -> np.ndarray:
    return np.stack([_paper_background(rgb[:, :, channel]) for channel in range(3)], axis=2)


def remove_paper_shadow(rgb: np.ndarray, background: np.ndarray | None = None) -> np.ndarray:
    # Correct luminance with one common gain rather than stretching each color
    # channel separately. This retains the relative color of colored ink and
    # avoids amplifying one noisy channel much more strongly in deep shadows.
    if background is None:
        background = paper_background(rgb)
    light = cv2.cvtColor(background, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gain = np.clip(245.0 / np.maximum(light, 1), 1.0, 2.2)
    return np.rint(np.clip(rgb.astype(np.float32) * gain[:, :, None], 0, 255)).astype(np.uint8)
