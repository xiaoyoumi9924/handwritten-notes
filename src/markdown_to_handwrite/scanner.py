from __future__ import annotations

import io
import hashlib
import json
import math
import re
import secrets
import zipfile
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from .scan_illumination import remove_paper_shadow as _remove_paper_shadow
from .scan_restoration import normalize_scan_edits, restore_regions, draw_scan_marks
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

register_heif_opener()

SCAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
SCAN_MODES = {"smart", "color", "bw", "original", "shadow", "bright", "sharp", "invert", "grayscale"}
SCAN_FORMATS = {"pdf", "jpg", "png", "docx"}
MAX_SCAN_BYTES = 18 * 1024 * 1024
MAX_SCAN_PIXELS = 60_000_000
MAX_EDGE = 9_000
PREVIEW_EDGE = 1_800
FILTER_PREVIEW_EDGE = 400
FILTER_PREVIEW_VERSION = "29"
PREVIEW_MODES = {"original", "smart", "grayscale", "bright", "bw", "invert", "sharp"}


def validate_scan_id(value: Any) -> str:
    if not isinstance(value, str) or not SCAN_ID_PATTERN.fullmatch(value):
        raise ValueError("扫描图片不存在，请重新上传。")
    return value


def decode_scan_image(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_SCAN_BYTES:
        raise ValueError("图片为空或超过 18 MB。")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_SCAN_PIXELS:
                raise ValueError("图片分辨率过大，请先缩小图片后再上传。")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("图片无法读取，请使用 JPG、PNG、HEIC、HEIF、BMP 或 WebP 格式。") from error
    if max(image.size) > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    return image


def detect_page_corners(image: Image.Image) -> list[list[float]] | None:
    return _detect_page_geometry(image)[0]


def _detect_page_geometry(image: Image.Image) -> tuple[list[list[float]] | None, bool | dict]:
    """Find the largest plausible four-corner page, returning normalized points."""
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 1200 / max(width, height))
    if scale < 1:
        work = cv2.resize(rgb, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    else:
        work = rgb
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 35, 125)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    found = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(found[-2], key=cv2.contourArea, reverse=True)
    work_area = work.shape[0] * work.shape[1]
    for contour in contours[:40]:
        area = cv2.contourArea(contour)
        if area < work_area * 0.12:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = _order_points(polygon.reshape(4, 2).astype(np.float32))
        quad_width = max(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3]))
        quad_height = max(np.linalg.norm(points[3] - points[0]), np.linalg.norm(points[2] - points[1]))
        if quad_width < work.shape[1] * 0.16 or quad_height < work.shape[0] * 0.16:
            continue
        return [[float(x / work.shape[1]), float(y / work.shape[0])] for x, y in points], False
    small_page = _detect_small_contrast_quad(gray, contours, reject_competing=True)
    if small_page:
        return small_page, False
    partial = _detect_partial_page(gray)
    if partial:
        return partial, True
    clipped = _detect_clipped_top_page(gray)
    if clipped:
        return clipped
    clipped_corner = _detect_corner_clipped_page(gray)
    if clipped_corner:
        return clipped_corner, False
    color_page = _detect_color_separated_page(work)
    if color_page:
        return color_page, False
    content_page = _detect_text_bounds(work)
    if content_page:
        return content_page, False
    small_page = _detect_small_contrast_quad(gray, contours)
    if small_page:
        return small_page, False
    return None, False


def _detect_small_contrast_quad(gray: np.ndarray, contours: list, reject_competing: bool = False) -> list[list[float]] | None:
    height, width = gray.shape
    work_area = height * width
    for contour in contours[:100]:
        area = cv2.contourArea(contour)
        if not work_area * .04 <= area < work_area * .12:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, .018 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = _order_points(polygon.reshape(4, 2).astype(np.float32))
        quad_width = max(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3]))
        quad_height = max(np.linalg.norm(points[3] - points[0]), np.linalg.norm(points[2] - points[1]))
        if quad_width < width * .16 or quad_height < height * .16:
            continue
        # A printed box inside a page can also be a small quadrilateral.
        # Require a consistent paper-to-background brightness transition on
        # at least three sides before using it as an automatic crop.
        center = points.mean(axis=0)
        margin = max(5, min(height, width) * .012)
        supported = 0
        for index in range(4):
            start, end = points[index], points[(index + 1) % 4]
            normal = center - (start + end) / 2
            length = np.linalg.norm(normal)
            if length < 1:
                continue
            normal *= margin / length
            samples = start + (end - start) * np.linspace(.15, .85, 80)[:, None]
            inside = np.rint(samples + normal).astype(int)
            outside = np.rint(samples - normal).astype(int)
            valid = ((inside[:, 0] >= 0) & (inside[:, 0] < width) &
                     (inside[:, 1] >= 0) & (inside[:, 1] < height) &
                     (outside[:, 0] >= 0) & (outside[:, 0] < width) &
                     (outside[:, 1] >= 0) & (outside[:, 1] < height))
            if np.count_nonzero(valid) < 50:
                continue
            inner, outer = inside[valid], outside[valid]
            difference = (gray[inner[:, 1], inner[:, 0]].astype(np.float32) -
                          gray[outer[:, 1], outer[:, 0]])
            if np.median(difference) > 12 and np.mean(difference > 8) > .6:
                supported += 1
        if supported < 3:
            continue
        if reject_competing:
            region = np.zeros((height, width), np.uint8)
            cv2.fillConvexPoly(region, np.rint(points).astype(np.int32), 1)
            threshold = max(140, float(np.median(gray[region != 0])) - 25)
            bright = (gray > threshold).astype(np.uint8)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
            competing = 0
            for label in range(1, count):
                x, y, box_w, box_h, pixels = stats[label]
                if not work_area * .005 < pixels < work_area * .06:
                    continue
                if x == 0 or y == 0 or x + box_w >= width or y + box_h >= height:
                    continue
                if pixels < box_w * box_h * .55 or box_w < 15 or box_h < 15:
                    continue
                if np.mean(region[labels == label]) < .1:
                    competing += 1
            if competing >= 2:
                continue
        return [[float(x / width), float(y / height)] for x, y in points]
    return None


def _perspective_from_visible_sides(rgb: np.ndarray, rectangle: list[list[float]]) -> list[list[float]] | None:
    """Turn a text crop into a perspective quad when both paper sides agree.

    Some photographed pages continue outside the frame. Extrapolated corners
    are clamped inside the photo; the crop never invents missing page pixels.
    """
    height, width = rgb.shape[:2]
    if height <= width:
        return None
    light = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 0]
    edges = cv2.Canny(cv2.GaussianBlur(light, (3, 3), 0), 10, 30)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=35,
        minLineLength=max(60, round(height * .22)),
        maxLineGap=max(12, round(height * .035)),
    )
    if lines is None:
        return None
    found = {"left": [], "right": []}
    offset = max(5, round(width * .009))
    for a, b, c, d in lines.reshape(-1, 4):
        a, b, c, d = map(float, (a, b, c, d))
        if abs(d - b) < height * .25 or min(b, d) > height * .08:
            continue
        slope = (c - a) / (d - b)
        top_x = a - slope * b
        side = (
            "left" if -.2 < slope < -.015 and 0 <= top_x < width * .12 else
            "right" if .04 < slope < .27 and width * .86 < top_x < width else None
        )
        if side is None:
            continue
        x = np.linspace(a, c, 100).astype(int)
        y = np.linspace(b, d, 100).astype(int)
        valid = (x >= offset) & (x < width-offset) & (y >= 0) & (y < height)
        x, y = x[valid], y[valid]
        if len(x) < 55:
            continue
        inward = offset if side == "left" else -offset
        difference = light[y, x + inward].astype(np.float32) - light[y, x - inward]
        if np.median(difference) < (10 if side == "left" else 3) or np.mean(difference > 0) < .6:
            continue
        found[side].append((abs(d - b), top_x, slope))
    if not found["left"] or not found["right"]:
        return None
    _, lx, ls = max(found["left"])
    _, rx, rs = max(found["right"])
    top = rectangle[0][1] * height
    bottom = rectangle[2][1] * height
    left_top = max(rectangle[0][0] * width, lx + ls * top + width * .015)
    right_top = min(rectangle[1][0] * width, rx + rs * top - width * .01)
    left_bottom = max(width * .015, min(rectangle[3][0] * width, lx + ls * bottom + width * .015))
    right_bottom = min(width * .985, max(rectangle[2][0] * width, rx + rs * bottom - width * .01))
    if (right_top - left_top < width * .65 or right_bottom - left_bottom < width * .7 or
            left_top - left_bottom < width * .03 or right_bottom - right_top < width * .03):
        return None
    points = [[left_top, top], [right_top, top], [right_bottom, bottom], [left_bottom, bottom]]
    return [[float(x / width), float(y / height)] for x, y in points]


def _detect_text_bounds(rgb: np.ndarray) -> list[list[float]] | None:
    """Conservative rectangular fallback for text pages lacking visible edges.

    Only trim modest blank margins around many distinct ink components. A
    sparse drawing or a page number near a boundary must keep the full image.
    """
    height, width = rgb.shape[:2]
    if min(height, width) < 500:
        return None
    scale = min(1.0, 1200 / max(height, width))
    if scale < 1:
        rgb = cv2.resize(rgb, (round(width*scale), round(height*scale)), interpolation=cv2.INTER_AREA)
        height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    center = gray[height//5:height*4//5, width//5:width*4//5]
    if np.median(center) < 155:
        return None
    size = max(15, min(35, (min(height, width)//35) | 1))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    ink = (cv2.subtract(background, gray) > 17).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes = []
    for x, y, w, h, area in stats[1:count]:
        if (4 <= area <= 1200 and 2 <= w <= 90 and 2 <= h <= 48
                and .06*width < x < .94*width and .06*height < y < .94*height):
            boxes.append((x, y, x+w, y+h))
    if len(boxes) < 80:
        return None
    boxes = np.asarray(boxes)
    left = max(0, np.quantile(boxes[:, 0], .01) - width*.05)
    top = max(0, np.quantile(boxes[:, 1], .01) - height*.06)
    right = min(width, np.quantile(boxes[:, 2], .99) + width*.04)
    bottom = min(height, boxes[:, 3].max() + height*.04)
    # Text near the lower edge may be a page number or a marginal note.
    if (left < width*.02 and top < height*.02 and right > width*.98 and bottom > height*.98):
        return None
    if (right-left < width*.7 or bottom-top < height*.8 or
            left > width*.13 or width-right > width*.13 or
            top > height*.1 or height-bottom > height*.1):
        return None
    points = [[left, top], [right, top], [right, bottom], [left, bottom]]
    rectangle = [[float(x/width), float(y/height)] for x, y in points]
    return _perspective_from_visible_sides(rgb, rectangle) or rectangle


def _detect_color_separated_page(rgb: np.ndarray) -> list[list[float]] | None:
    """Find pale paper on a distinctly warmer surface when edges are broken.

    Require a complete interior quadrilateral and independent color and
    brightness transitions on every side. Otherwise leave geometry unchanged.
    """
    height, width = rgb.shape[:2]
    if min(height, width) < 200:
        return None
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    light, yellow = lab[:, :, 0], lab[:, :, 2]
    threshold, _ = cv2.threshold(yellow, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if threshold < 138 or threshold > 175:
        return None
    mask = ((yellow.astype(np.float32) < threshold - 8) & (light > 100)).astype(np.uint8)
    size = max(7, min(21, (min(height, width) // 40) | 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if not .25 <= cv2.contourArea(contour) / (width * height) <= .88:
        return None
    polygon = cv2.approxPolyDP(contour, .02 * cv2.arcLength(contour, True), True)
    if len(polygon) != 4 or not cv2.isContourConvex(polygon):
        return None
    points = _order_points(polygon.reshape(4, 2).astype(np.float32))
    margin = max(8, round(min(width, height) * .01))
    if (np.any(points[:, 0] < margin) or np.any(points[:, 0] >= width - margin)
            or np.any(points[:, 1] < margin) or np.any(points[:, 1] >= height - margin)):
        return None
    center = points.mean(axis=0)
    for index in range(4):
        start, end = points[index], points[(index + 1) % 4]
        if np.linalg.norm(end - start) < min(width, height) * .2:
            return None
        samples = start + (end - start) * np.linspace(.1, .9, 100)[:, None]
        inward = center - (start + end) / 2
        inward *= margin / np.linalg.norm(inward)
        inside = np.rint(samples + inward).astype(int)
        outside = np.rint(samples - inward).astype(int)
        valid = ((inside[:, 0] >= 0) & (inside[:, 0] < width) & (inside[:, 1] >= 0) & (inside[:, 1] < height)
                 & (outside[:, 0] >= 0) & (outside[:, 0] < width) & (outside[:, 1] >= 0) & (outside[:, 1] < height))
        if valid.sum() < 70:
            return None
        inside, outside = inside[valid], outside[valid]
        difference = (lab[inside[:, 1], inside[:, 0]].astype(np.int16)
                      - lab[outside[:, 1], outside[:, 0]].astype(np.int16))
        if np.median(difference[:, 0]) < 15 or np.median(difference[:, 2]) > -12:
            return None
    return [[float(x / width), float(y / height)] for x, y in points]


def _detect_clipped_top_page(gray: np.ndarray) -> tuple[list[list[float]], dict] | None:
    """Find a clipped top edge and two long page sides without cutting top text."""
    height, width = gray.shape
    if width <= height or min(height, width) < 200:
        return None
    edges = cv2.Canny(gray, 25, 90)
    top_lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                                minLineLength=max(60, int(width * .1)), maxLineGap=max(8, int(width * .019)))
    side_lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=75,
                                 minLineLength=max(60, int(width * .16)), maxLineGap=max(8, int(width * .033)))
    if top_lines is None or side_lines is None:
        return None
    central = gray[int(height * .2):int(height * .8), int(width * .2):int(width * .85)]
    background = float(np.median(central))
    tops, lefts, rights = [], [], []
    for a, b, c, d in top_lines.reshape(-1, 4):
        dx, dy = int(c) - int(a), int(d) - int(b)
        if not (abs(dx) >= width * .12 and .04 <= dy / dx <= .4 and min(b, d) < height * .025
                and max(b, d) < height * .15 and max(a, c) > width * .7):
            continue
        x = np.linspace(a, c, 100).astype(int)
        y = np.linspace(b, d, 100).astype(int)
        valid = (y >= 10) & (y < height - 10) & (x >= 0) & (x < width)
        x, y = x[valid], y[valid]
        if len(x) >= 30 and np.median(gray[y + 8, x]) >= background - 20:
            contrast = float(np.median(gray[y + 8, x].astype(np.float32) - gray[y - 8, x]))
            if contrast >= 15:
                tops.append((abs(dx), (int(a), int(b), int(c), int(d))))
    for a, b, c, d in side_lines.reshape(-1, 4):
        dx, dy = int(c) - int(a), int(d) - int(b)
        mid = (int(a) + int(c)) / 2
        if abs(dy) < height * .45 or abs(dx) > abs(dy) * .07:
            continue
        left = width * .06 < mid < width * .2
        right = mid > width * .95
        if not (left or right):
            continue
        x = np.linspace(a, c, 160).astype(int)
        y = np.linspace(b, d, 160).astype(int)
        valid = (x >= 10) & (x < width - 10) & (y >= 0) & (y < height)
        x, y = x[valid], y[valid]
        if len(x) < 40:
            continue
        direction = 1 if left else -1
        offset = 10 if left else 6
        inside = gray[y, x + direction * offset].astype(np.float32)
        outside = gray[y, x - direction * offset].astype(np.float32)
        contrast = float(np.median(inside - outside))
        if contrast >= (5 if left else 12) and np.median(inside) >= background - 35:
            (lefts if left else rights).append((contrast, (int(a), int(b), dx, dy)))
    if not tops or not lefts or not rights:
        return None
    _, (tx1, ty1, tx2, ty2) = max(tops, key=lambda v: v[0])
    _, (lx, ly, ldx, ldy) = max(lefts, key=lambda v: v[0])
    _, (rx, ry, rdx, rdy) = max(rights, key=lambda v: v[0])
    bottom = height - 1.0
    left_top, left_bottom = lx - ldx * ly / ldy, lx + ldx * (bottom - ly) / ldy
    right_top, right_bottom = rx - rdx * ry / rdy, rx + rdx * (bottom - ry) / rdy
    points = np.array([[left_top, 0], [right_top, 0], [right_bottom, bottom], [left_bottom, bottom]], np.float32)
    if np.any(points[:, 0] < 0) or np.any(points[:, 0] >= width) or not cv2.isContourConvex(points) or cv2.contourArea(points) < width * height * .65:
        return None
    corners = [[float(x / width), float(y / height)] for x, y in points]
    return corners, {"topClip": [[tx1 / width, ty1 / height], [tx2 / width, ty2 / height]]}


def _detect_partial_page(gray: np.ndarray) -> list[list[float]] | None:
    """Infer a page clipped by the bottom image edge from three strong edges.

    This intentionally rejects ambiguous inputs. Extrapolation is limited to
    long lines near the image boundaries; the missing bottom remains the image
    boundary. Images with insufficient evidence keep the whole image.
    """
    height, width = gray.shape
    edges = cv2.Canny(gray, 25, 90)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=80,
                            minLineLength=max(50, int(width * .22)), maxLineGap=max(10, int(width * .065)))
    if lines is None:
        return None
    lines = lines.reshape(-1, 4)
    central = gray[int(height * .2):int(height * .8), int(width * .15):int(width * .85)]
    if central.size == 0:
        return None
    center_brightness = float(np.median(central))
    tops, lefts, rights = [], [], []
    for x1, y1, x2, y2 in lines:
        dx, dy = float(x2 - x1), float(y2 - y1)
        if abs(dx) >= width * .25 and abs(dy) <= abs(dx) * .2 and max(y1, y2) < height * .16:
            x = np.linspace(x1, x2, 80).astype(int)
            y = np.linspace(y1, y2, 80).astype(int)
            valid = (y >= 10) & (y < height - 10) & (x >= 0) & (x < width)
            x, y = x[valid], y[valid]
            if len(x) < 40:
                continue
            below = gray[y + 8, x].astype(np.float32)
            above = gray[y - 8, x].astype(np.float32)
            if np.median(below - above) >= 12 and np.median(below) >= center_brightness - 20:
                tops.append((abs(dx), (float(x1), float(y1), dx, dy)))
        elif abs(dy) >= height * .3 and abs(dx) <= abs(dy) * .1:
            mid_x = (x1 + x2) / 2
            line = (abs(dy), (float(x1), float(y1), dx, dy))
            if mid_x < width * .10:
                lefts.append(line)
            elif mid_x > width * .90:
                rights.append(line)
    if not tops or not lefts or not rights:
        return None
    _, (tx, ty, tdx, tdy) = max(tops, key=lambda v: v[0])
    _, (lx, ly, ldx, ldy) = max(lefts, key=lambda v: v[0])
    _, (rx, ry, rdx, rdy) = max(rights, key=lambda v: v[0])
    top_slope = tdy / tdx
    def intersection(x, y, dx, dy):
        slope = dx / dy
        yy = (ty + top_slope * (x - slope * y - tx)) / (1 - top_slope * slope)
        return x + slope * (yy - y), yy
    tl = intersection(lx, ly, ldx, ldy)
    tr = intersection(rx, ry, rdx, rdy)
    bottom_y = height - 1.0
    bl = (lx + ldx / ldy * (bottom_y - ly), bottom_y)
    br = (rx + rdx / rdy * (bottom_y - ry), bottom_y)
    points = np.asarray([tl, tr, br, bl], dtype=np.float32)
    if np.any(points[:, 0] < 0) or np.any(points[:, 0] >= width) or np.any(points[:, 1] < 0) or np.any(points[:, 1] >= height):
        return None
    if not cv2.isContourConvex(points) or cv2.contourArea(points) < width * height * .65:
        return None
    return [[float(x / width), float(y / height)] for x, y in points]


def _detect_corner_clipped_page(gray: np.ndarray) -> list[list[float]] | None:
    """Recover two missing adjacent edges only with two long exterior boundaries.

    Rotate the evidence, never the source image. Missing edges stay on the
    camera boundary; no content outside the photograph is reconstructed.
    """
    original_h, original_w = gray.shape
    for rotation in range(4):
        work = np.ascontiguousarray(np.rot90(gray, rotation))
        height, width = work.shape
        if min(height, width) < 200:
            continue
        paper = float(np.median(work[height//5:height*4//5, width//5:width*3//5]))
        if paper < 120:
            continue
        lines = cv2.HoughLinesP(cv2.Canny(work, 25, 90), 1, np.pi/720,
                                threshold=70, minLineLength=max(50, int(width*.25)),
                                maxLineGap=max(8, int(width*.03)))
        if lines is None:
            continue
        rights, bottoms = [], []
        for a, b, c, d in lines.reshape(-1, 4):
            a, b, c, d = map(float, (a, b, c, d))
            dx, dy = c-a, d-b
            right = (abs(dy) > height*.35 and abs(dx) < abs(dy)*.3
                     and min(b, d) < height*.3 and max(b, d) > height*.5
                     and min(a, c) > width*.6)
            bottom = (abs(dx) > width*.4 and abs(dy) < abs(dx)*.2
                      and min(b, d) > height*.8 and min(a, c) < width*.6)
            if not (right or bottom):
                continue
            x = np.linspace(a, c, 100).astype(int)
            y = np.linspace(b, d, 100).astype(int)
            offset = max(5, round(min(height, width)*.008))
            valid = (x >= 3*offset) & (x < width-3*offset) & (y >= 3*offset) & (y < height-3*offset)
            x, y = x[valid], y[valid]
            if len(x) < 60:
                continue
            inside = work[y, x-offset] if right else work[y-offset, x]
            outside = work[y, x+offset] if right else work[y+offset, x]
            farther = work[y, x+3*offset] if right else work[y+3*offset, x]
            if np.median(inside.astype(float)-farther) < (8 if right else 12):
                continue
            difference = inside.astype(float)-outside
            if (np.median(inside) < paper-25 or np.median(difference) < (8 if right else 12)
                    or np.mean(difference > 4) < .7):
                continue
            (rights if right else bottoms).append((a, b, dx, dy))
        for rx, ry, rdx, rdy in sorted(rights, key=lambda v: -abs(v[3])):
            for bx, by, bdx, bdy in sorted(bottoms, key=lambda v: -abs(v[2])):
                side_slope, bottom_slope = rdx/rdy, bdy/bdx
                right_top = rx-side_slope*ry
                bottom_left = by-bottom_slope*bx
                bottom_y = (bottom_left+bottom_slope*right_top)/(1-bottom_slope*side_slope)
                right_x = right_top+side_slope*bottom_y
                points = np.array([[0, 0], [right_top, 0], [right_x, bottom_y], [0, bottom_left]], np.float32)
                if (np.any(points < 0) or np.any(points[:, 0] >= width)
                        or np.any(points[:, 1] >= height)
                        or cv2.contourArea(points) < width*height*.65):
                    continue
                # Both camera boundaries must continue the same light surface.
                for border in (work[:max(2, height//100), :int(right_top*.9)],
                               work[:int(bottom_left*.9), :max(2, width//100)]):
                    if np.mean(border >= paper-30) < .75:
                        break
                else:
                    x, y = points[:, 0].copy(), points[:, 1].copy()
                    if rotation == 1:
                        points = np.column_stack((original_w-1-y, x))
                    elif rotation == 2:
                        points = np.column_stack((original_w-1-x, original_h-1-y))
                    elif rotation == 3:
                        points = np.column_stack((y, original_h-1-x))
                    points = _order_points(points.astype(np.float32))
                    return (points / [original_w, original_h]).tolist()
    return None


def _order_points(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    # Cyclic ordering cannot choose the same corner twice on diamond-shaped
    # pages, unlike independent sum/difference extrema.
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)


def validate_page_corners(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("请指定纸张的四个角。")
    points = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("纸张角点格式不正确。")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
            raise ValueError("纸张角点必须位于图片内。")
        points.append([float(v) for v in point])
    contour = np.asarray(points, dtype=np.float32)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < 0.015:
        raise ValueError("四角不能交叉，选区也不能过小。")
    if min(np.linalg.norm(contour[i] - contour[(i + 1) % 4]) for i in range(4)) < 0.02:
        raise ValueError("相邻角点距离过近。")
    return _order_points(contour).astype(float).tolist()


def validate_scan_options(
    mode: Any,
    orientation: Any,
    rotation: Any,
    crop: Any,
) -> tuple[str, str, int, list[float] | None]:
    if mode not in SCAN_MODES:
        raise ValueError("扫描模式无效。")
    if orientation not in {"auto", "portrait", "landscape"}:
        raise ValueError("页面方向无效。")
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation not in {0, 90, 180, 270}:
        raise ValueError("旋转角度无效。")
    normalized_crop = None
    if crop is not None:
        if not isinstance(crop, list) or len(crop) != 4:
            raise ValueError("裁切范围格式不正确。")
        values = []
        for value in crop:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("裁切范围包含无效数值。")
            values.append(float(value))
        x, y, width, height = values
        if x < 0 or y < 0 or width < 0.04 or height < 0.04 or x + width > 1.0001 or y + height > 1.0001:
            raise ValueError("裁切范围必须位于页面内且不能过小。")
        normalized_crop = values
    return mode, orientation, rotation, normalized_crop


def _outside_partial_edges(rgb: np.ndarray) -> np.ndarray | None:
    """Find short page edges that enter and exit adjacent image boundaries.

    Keep the page interior intact; only confident triangular exterior regions
    are marked. Test all rotations for clipped top, bottom, and side edges.
    """
    height, width = rgb.shape[:2]
    scale = min(1.0, 1000 / max(height, width))
    work = cv2.resize(rgb, (round(width*scale), round(height*scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    mask = np.zeros(work.shape[:2], dtype=np.uint8)
    for rotation, mirrored in ((r, m) for r in range(4) for m in (False, True)):
        image = np.ascontiguousarray(np.rot90(work, rotation))
        if mirrored:
            image = np.ascontiguousarray(np.fliplr(image))
        h, w = image.shape[:2]
        light = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)[:, :, 0]
        edges = cv2.Canny(cv2.GaussianBlur(light, (3, 3), 0), 5, 15)
        lines = cv2.HoughLinesP(edges, 1, np.pi/720, threshold=35,
            minLineLength=max(35, int(h*.13)), maxLineGap=max(8, int(h*.035)))
        if lines is None:
            continue
        candidates = []
        offset = max(5, round(min(w, h)*.01))
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            dx, dy = float(x2-x1), float(y2-y1)
            if abs(dy) < h*.14 or min(y1,y2) > h*.04:
                continue
            slope = dx/dy
            if not .035 < slope < .3:
                continue
            top_x = x1-slope*y1
            exit_y = (w-1-top_x)/slope
            if not (.88*w < top_x < w-2*offset and .14*h < exit_y < .75*h):
                continue
            x = np.linspace(x1, x2, 100).astype(int)
            y = np.linspace(y1, y2, 100).astype(int)
            valid = (x >= offset) & (x < w-offset)
            x, y = x[valid], y[valid]
            if len(x) < 45:
                continue
            diff = light[y,x-offset].astype(np.float32)-light[y,x+offset].astype(np.float32)
            if np.median(diff) < 3 or np.mean(diff > 0) < .6:
                continue
            candidates.append((abs(dy), top_x, slope))
        if candidates:
            _, top_x, slope = max(candidates)
            y = np.arange(h)[:, None]
            x = np.arange(w)[None, :]
            exterior = (x > top_x + slope*y - max(10, w*.025)).astype(np.uint8)
            if mirrored:
                exterior = np.fliplr(exterior)
            mask |= np.rot90(exterior, -rotation)
    if not mask.any():
        return None
    if scale < 1:
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    return mask.astype(bool)


def process_scan_image(
    source: Image.Image,
    corners: list[list[float]] | None,
    mode: str,
    orientation: str = "auto",
    rotation: int = 0,
    crop: list[float] | None = None,
    clean_partial_border: bool = False,
    top_clip: list[list[float]] | None = None,
    deskew_angle: float = 0,
) -> Image.Image:
    invert = mode == "invert"
    if invert:
        mode = "smart"
    rgb = np.asarray(source.convert("RGB"))
    white_mask = _outside_partial_edges(rgb) if (mode == "bw" or invert) and corners is None else None
    if mode in {"smart", "shadow", "sharp", "bw"} and top_clip is not None:
        height, width = rgb.shape[:2]
        (x1, y1), (x2, y2) = top_clip
        if abs(x2 - x1) > .01:
            top = (y1 + (np.arange(width) / width - x1) * (y2 - y1) / (x2 - x1)) * height + 2
            rgb = rgb.copy()
            top_mask = np.arange(height)[:, None] < top[None, :]
            white_mask = top_mask if white_mask is None else (white_mask | top_mask)
            rgb[white_mask] = 255
    if corners:
        rgb = _rectify(rgb, corners)
        if white_mask is not None:
            mask_rgb = np.repeat((white_mask.astype(np.uint8) * 255)[:, :, None], 3, axis=2)
            white_mask = _rectify(mask_rgb, corners)[:, :, 0] >= 250
        rgb = _straighten_text_rows(rgb, white_mask)
    elif _looks_like_small_page(rgb):
        rgb = _straighten_text_rows(rgb, white_mask)
    image = Image.fromarray(rgb, mode="RGB")
    mask_image = Image.fromarray((white_mask.astype(np.uint8) * 255), mode="L") if white_mask is not None else None
    if deskew_angle:
        image = image.rotate(deskew_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
        if mask_image is not None:
            mask_image = mask_image.rotate(deskew_angle, resample=Image.Resampling.NEAREST, expand=True, fillcolor=255)
    if orientation == "portrait" and image.width > image.height:
        image = image.rotate(90, expand=True)
        if mask_image is not None: mask_image = mask_image.rotate(90, expand=True)
    elif orientation == "landscape" and image.height > image.width:
        image = image.rotate(-90, expand=True)
        if mask_image is not None: mask_image = mask_image.rotate(-90, expand=True)
    if rotation:
        image = image.rotate(rotation, expand=True)
        if mask_image is not None: mask_image = mask_image.rotate(rotation, expand=True)
    if crop:
        x, y, width, height = crop
        left = round(x * image.width)
        top = round(y * image.height)
        right = min(image.width, round((x + width) * image.width))
        bottom = min(image.height, round((y + height) * image.height))
        image = image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
        if mask_image is not None: mask_image = mask_image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
    result = _enhance(image, mode)
    if mode in {"smart", "shadow", "sharp", "bw"} and clean_partial_border and crop is None and rotation == 0 and orientation == "auto" and not deskew_angle:
        result = _clear_partial_corner_artifacts(result)
    if mask_image is not None:
        result.paste((255, 255, 255), mask=mask_image)
    if mode == "bw" or invert:
        # These two styles explicitly use a clean perimeter. Apply after all
        # transforms so previews and exports have exactly the same background.
        edge_x = max(1, round(result.width * .02))
        edge_y = max(1, round(result.height * .02))
        pixels = np.asarray(result).copy()
        pixels[:edge_y, :] = pixels[-edge_y:, :] = 255
        pixels[:, :edge_x] = pixels[:, -edge_x:] = 255
        result = Image.fromarray(pixels, mode="RGB")
    return ImageOps.invert(result) if invert else result


def _looks_like_small_page(rgb: np.ndarray) -> bool:
    """Recognize an already-cropped, light page when no frame was detected."""
    height, width = rgb.shape[:2]
    if not 280 <= min(height, width) < 500:
        return False
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if np.median(gray) < 175:
        return False
    y = max(1, round(height * .04))
    x = max(1, round(width * .04))
    return all(np.median(edge) >= 165 for edge in
               (gray[:y, :], gray[-y:, :], gray[:, :x], gray[:, -x:]))


def _refine_text_angle(ink: np.ndarray, estimate: float) -> float:
    """Refine an independently detected angle using text-row projections."""
    height, width = ink.shape
    ys, xs = np.nonzero(ink)
    if len(xs) < 500 or len(xs) > height * width * .2:
        return estimate
    if len(xs) > 100_000:
        step = math.ceil(len(xs) / 100_000)
        xs, ys = xs[::step], ys[::step]
    xs = xs.astype(np.float32) - width / 2
    candidates = estimate + np.arange(-12, 13, dtype=np.float32) * .2
    region_angles = []
    for region in range(3):
        valid = (ys >= height * region / 3) & (ys < height * (region + 1) / 3)
        if np.count_nonzero(valid) < 400:
            continue
        region_x, region_y = xs[valid], ys[valid]
        scores = []
        for angle in candidates:
            positions = np.rint(region_y - math.tan(math.radians(float(angle))) * region_x).astype(np.int32)
            positions = positions[(positions >= 0) & (positions < height)]
            histogram = np.bincount(positions, minlength=height).astype(np.float64)
            scores.append(float(np.square(np.diff(histogram)).sum()))
        best = int(np.argmax(scores))
        if best in (0, len(scores) - 1) or scores[best] < max(scores[0], scores[-1]) * 1.05:
            return estimate
        region_angles.append(float(candidates[best]))
    if len(region_angles) < 2 or max(region_angles) - min(region_angles) > .8:
        return estimate
    return float(np.median(region_angles))


def _straighten_text_rows(rgb: np.ndarray, white_mask: np.ndarray | None = None) -> np.ndarray:
    """Remove residual tilt that changes down a perspective-corrected page.

    A four-corner warp cannot flatten text whose angle varies with height.
    Estimate several independent text rows, then use a smooth vertical remap.
    Consistent tilt uses one robust angle; changing tilt uses local angles.
    """
    height, width = rgb.shape[:2]
    if min(height, width) < 280:
        return rgb
    small_source = min(height, width) < 500
    scale = (min(1200 / max(height, width), 700 / min(height, width)) if small_source
             else min(1.0, 1200 / max(height, width)))
    work = cv2.resize(rgb, (round(width * scale), round(height * scale)),
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC) if abs(scale - 1) > .001 else rgb
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    small_height, small_width = gray.shape
    kernel_size = max(15, min(35, round(small_width * .025) | 1))
    background = cv2.morphologyEx(
        gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
    )
    ink = (cv2.subtract(background, gray) > 20).astype(np.uint8) * 255
    if small_source:
        # Texture in low-resolution photos can look like tilted text after
        # enlargement. Require a mostly light page with many small ink parts.
        if np.count_nonzero(ink) > ink.size * .12:
            return rgb
        count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        text_parts = sum(1 for _, _, w, h, area in stats[1:count]
                         if 3 <= area <= 1200 and 2 <= w <= 70 and 3 <= h <= 50)
        if text_parts < 40:
            return rgb
    rows = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                            np.ones((2, kernel_size), np.uint8))
    lines = cv2.HoughLinesP(
        rows, 1, np.pi / 720, threshold=25,
        minLineLength=round(small_width * .15),
        maxLineGap=max(5, round(small_width * .01)),
    )
    if lines is None:
        return rgb
    bands: list[list[tuple[float, float]]] = [[] for _ in range(9)]
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx = int(x2) - int(x1)
        if abs(dx) < small_width * .15:
            continue
        angle = math.degrees(math.atan2(int(y2) - int(y1), dx))
        if abs(angle) > 8:
            continue
        midpoint = (int(y1) + int(y2)) / 2
        band = int(midpoint / small_height * 10)
        if 0 <= band < len(bands):
            bands[band].append((angle, midpoint))
    anchors = []
    for band, samples in enumerate(bands):
        if len(samples) < 8:
            continue
        angles = np.asarray([angle for angle, _ in samples])
        positions = {int(y / (small_height * .025)) for _, y in samples}
        median = float(np.median(angles))
        if len(positions) < 2 or np.median(np.abs(angles - median)) > 1.5:
            continue
        anchors.append(((band + .5) / 10, median))
    refine_eligible = False
    if len(anchors) < 3 or anchors[-1][0] - anchors[0][0] < .4:
        # Short documents and notes often occupy only the top of a page.
        # Require several separate text lines and many ink components before
        # using one common angle over the whole image.
        if len(anchors) < 2 or anchors[-1][0] - anchors[0][0] < .09:
            return rgb
        count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        text_parts = sum(1 for _, _, w, h, area in stats[1:count]
                         if 3 <= area <= 1200 and 2 <= w <= 70 and 3 <= h <= 50)
        if text_parts < 40:
            return rgb
        joined = cv2.dilate(ink, np.ones((3, kernel_size), np.uint8))
        contours = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        line_angles = []
        for contour in contours:
            _, _, w, h = cv2.boundingRect(contour)
            if w < small_width * .15 or h > small_height * .08:
                continue
            points = cv2.boxPoints(cv2.minAreaRect(contour))
            vectors = [points[(i + 1) % 4] - points[i] for i in range(4)]
            vector = max(vectors, key=lambda edge: abs(edge[0]))
            angle = (math.degrees(math.atan2(vector[1], vector[0])) + 90) % 180 - 90
            if abs(angle) <= 8:
                line_angles.append(angle)
        if len(line_angles) < 4:
            return rgb
        common_angle = float(np.median(line_angles))
        if (abs(common_angle) < 2.5 or np.median(np.abs(np.asarray(line_angles) - common_angle)) > 1 or
                abs(common_angle - float(np.median([angle for _, angle in anchors]))) > 2):
            return rgb
        varying_tilt = False
    else:
        anchor_angles = np.asarray([angle for _, angle in anchors])
        head = float(np.median(anchor_angles[:min(3, len(anchors) // 2)]))
        tail = float(np.median(anchor_angles[-min(3, len(anchors) // 2):]))
        varying_tilt = abs(head - tail) >= 3
        if not varying_tilt:
            common_angle = float(np.median(anchor_angles))
            dispersion = float(np.median(np.abs(anchor_angles - common_angle)))
            if abs(common_angle) < 1.5 or dispersion > 1.5:
                return rgb
            spread = float(np.quantile(anchor_angles, .8) - np.quantile(anchor_angles, .2))
            refine_eligible = len(anchors) >= 6 and (dispersion >= .7 or spread > 2)
    if refine_eligible:
        common_angle = _refine_text_angle(ink, common_angle)
    y = np.arange(height, dtype=np.float32)
    x = np.arange(width, dtype=np.float32)
    if varying_tilt:
        angle_curve = np.interp(y / height, [a[0] for a in anchors],
                                anchor_angles).astype(np.float32)
        angle_curve = cv2.GaussianBlur(angle_curve[:, None], (1, 0),
                                       sigmaX=max(1, height * .025))[:, 0]
    else:
        angle_curve = np.full(height, common_angle, dtype=np.float32)
    shift = np.tan(np.deg2rad(angle_curve)) * (width / 2)
    if np.max(np.abs(np.gradient(shift))) > .45:
        return rgb
    result = np.empty_like(rgb)
    mask_source = white_mask.astype(np.uint8) if white_mask is not None else None
    mask_result = np.empty_like(mask_source) if mask_source is not None else None
    tangent = np.tan(np.deg2rad(angle_curve))
    for start in range(0, height, 256):
        end = min(height, start + 256)
        map_x = np.broadcast_to(x, (end - start, width)).copy()
        map_y = (y[start:end, None] + tangent[start:end, None]
                 * (x[None, :] - width / 2)).astype(np.float32)
        result[start:end] = cv2.remap(rgb, map_x, map_y, cv2.INTER_CUBIC,
                                     borderMode=cv2.BORDER_REPLICATE)
        if mask_result is not None:
            mask_result[start:end] = cv2.remap(mask_source, map_x, map_y, cv2.INTER_NEAREST,
                                              borderMode=cv2.BORDER_CONSTANT, borderValue=1)
    if white_mask is not None:
        white_mask[:] = mask_result != 0
    return result


def _estimate_page_skew(source: Image.Image, corners: list[list[float]]) -> float:
    """Estimate small skew only when lines across several areas agree."""
    rgb = _rectify(np.asarray(source.convert("RGB")), corners)
    h, w = rgb.shape[:2]
    scale = min(1.0, 1200 / max(h, w))
    if scale < 1:
        rgb = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    lines = cv2.HoughLinesP(cv2.Canny(gray, 45, 120), 1, np.pi / 720, 22,
                            minLineLength=max(35, round(w * .035)), maxLineGap=2)
    if lines is None:
        return 0.0
    candidates = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = int(x2) - int(x1), int(y2) - int(y1)
        if not dx or min(y1, y2) < h * .08:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        if abs(angle) <= 8:
            candidates.append((angle, (int(x1) + int(x2)) / (2 * w)))
    if len(candidates) < 4:
        return 0.0
    best = max(candidates, key=lambda c: sum(abs(c[0] - other[0]) <= 2.6 for other in candidates))
    group = [c for c in candidates if abs(c[0] - best[0]) <= 2.6]
    if len(group) < 4 or len({int(x * 4) for _, x in group}) < 3:
        return 0.0
    angle = float(np.median([a for a, _ in group]))
    return angle if abs(angle) >= 1 else 0.0


def _clear_partial_corner_artifacts(image: Image.Image) -> Image.Image:
    """Remove only narrow, dense dark blocks touching a lower outer corner."""
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    dark = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) < 90).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    result = rgb.copy()
    for x, y, w, h, area in stats[1:count]:
        touches_side = x <= 1 or x + w >= width - 1
        if (touches_side and y + h >= height - 1 and h >= height * .10
                and width * .005 <= w <= width * .025 and area >= w * h * .7):
            result[y:y + h, x:x + w] = 255
    # A long, narrow gray strip can remain where the desk just peeks through
    # along a detected side. Do not remove dark ruling or short edge marks.
    gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
    count, _, stats, _ = cv2.connectedComponentsWithStats((gray < 245).astype(np.uint8), connectivity=8)
    for x, y, w, h, area in stats[1:count]:
        if ((x <= 1 or x + w >= width - 1) and w <= width * .012 and h >= height * .2
                and np.mean(gray[y:y + h, x:x + w] < 90) < .15):
            result[y:y + h, x:x + w] = 255
    return Image.fromarray(result, mode="RGB")


def _rectify(rgb: np.ndarray, normalized_points: Sequence[Sequence[float]]) -> np.ndarray:
    height, width = rgb.shape[:2]
    source_points = np.asarray([[x * width, y * height] for x, y in normalized_points], dtype=np.float32)
    source_points = _order_points(source_points)
    top_width = np.linalg.norm(source_points[1] - source_points[0])
    bottom_width = np.linalg.norm(source_points[2] - source_points[3])
    left_height = np.linalg.norm(source_points[3] - source_points[0])
    right_height = np.linalg.norm(source_points[2] - source_points[1])
    output_width = max(64, round(max(top_width, bottom_width)))
    output_height = max(64, round(max(left_height, right_height)))
    scale = min(1.0, MAX_EDGE / max(output_width, output_height))
    output_width = round(output_width * scale)
    output_height = round(output_height * scale)
    destination = np.asarray([
        [0, 0],
        [output_width - 1, 0],
        [output_width - 1, output_height - 1],
        [0, output_height - 1],
    ], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source_points, destination)
    return cv2.warpPerspective(rgb, transform, (output_width, output_height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _enhance(image: Image.Image, mode: str) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    if mode == "original":
        return image.convert("RGB")
    if mode == "grayscale":
        # Preserve continuous tones, including faint pencil and paper shading.
        # No thresholding, white-point stretching, or sharpening in this mode.
        return ImageOps.grayscale(image).convert("RGB")
    if mode == "bright":
        # A concave tone curve lifts midtones while retaining highlight detail
        # and keeping black ink black; multiplying RGB clips bright paper.
        from .scan_enhancement import brighten_document
        return Image.fromarray(brighten_document(rgb), mode="RGB")
    if mode == "sharp":
        from .scan_enhancement import sharpen_document
        return Image.fromarray(sharpen_document(rgb), mode="RGB")
    if mode == "smart":
        return _enhance_handwriting(rgb, preserve_medium_strokes=True)
    if mode == "bw":
        from .scan_enhancement import monochrome_document
        return Image.fromarray(monochrome_document(rgb), mode="L").convert("RGB")
    if mode == "color":
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        lightness = cv2.createCLAHE(clipLimit=1.35, tileGridSize=(8, 8)).apply(lightness)
        rgb = cv2.cvtColor(cv2.merge((lightness, channel_a, channel_b)), cv2.COLOR_LAB2RGB)
        return _unsharp(Image.fromarray(rgb, mode="RGB"), amount=0.45)

    if mode == "shadow":
        # Clean the remaining paper texture and retain ink contrast on usable
        # exposures. Fade this step out for very dark images where separating
        # noise from real marks is unreliable.
        from .scan_illumination import paper_background
        background = paper_background(rgb)
        corrected = _remove_paper_shadow(rgb, background)
        light = cv2.cvtColor(background, cv2.COLOR_RGB2GRAY).astype(np.float32)
        # Start correcting moderately dark paper earlier, but do not apply
        # foreground extraction to severely underexposed regions.
        weight = (0.92 * np.clip((light - 45.0) / 55.0, 0, 1))[:, :, None]
        clean = np.asarray(_enhance_handwriting(rgb, preserve_medium_strokes=True), dtype=np.float32)
        # Colored fills/highlighters are content too. Foreground extraction
        # is reserved for neutral paper instead of bleaching these regions.
        saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1].astype(np.float32)
        color_content = np.clip((saturation - 50.0) / 35.0, 0, 1)
        weight *= 1.0 - color_content[:, :, None]
        result = corrected.astype(np.float32) * (1.0 - weight) + clean * weight
        return Image.fromarray(np.rint(result).astype(np.uint8), mode="RGB")

    raise ValueError("扫描模式无效。")


def _enhance_handwriting(rgb: np.ndarray, *, preserve_medium_strokes: bool = False) -> Image.Image:
    """Whiten paper and strengthen ink while retaining soft stroke boundaries."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Edge-preserving denoising avoids erasing the thin pen strokes that a
    # median filter can remove before foreground extraction.
    gray = cv2.bilateralFilter(gray, 5, 18, 3)
    kernel_size = max(3, min(101, (min(gray.shape) // 14) | 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), max(1.0, kernel_size / 8))
    flattened = cv2.divide(gray, np.maximum(background, 1), scale=255)
    # Estimate narrow-stroke contrast separately from the broad illumination
    # field. A large closing alone mistakes pale show-through blobs for ink.
    # A window narrower than a pale stroke treats the stroke as paper and can
    # erase it. The smart filter uses a slightly wider, resolution-scaled
    # window while the other filters retain their existing appearance.
    divisor, limit = (45, 51) if preserve_medium_strokes else (65, 31)
    stroke_window = max(5, min(limit, (min(gray.shape) // divisor) | 1))
    local_background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke_window, stroke_window)))
    local_flattened = cv2.divide(gray, np.maximum(local_background, 1), scale=255)
    # Keep genuinely dark broad strokes which do not fit inside the small
    # closing window, using the illumination-corrected large-scale image.
    flattened = np.where(flattened < 145, np.minimum(local_flattened, flattened), local_flattened)
    white_point = 237 if preserve_medium_strokes else 242
    count, labels = cv2.connectedComponents((flattened < white_point).astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[np.unique(labels[flattened < 225])] = True
    keep[0] = False
    foreground = keep[labels]
    del labels
    # Soft grayscale mapping retains the pen's antialiasing instead of
    # turning medium gray edge pixels solid black and expanding the stroke.
    tone = np.clip((flattened.astype(np.float32) - 90.0) / (white_point - 90.0), 0, 1)
    clean = np.rint(255 * np.power(tone, 1.5)).astype(np.uint8)
    clean[~foreground] = 255
    # Restore strongly colored ink after the monochrome paper cleanup. Work in
    # HSV so dark blue/red handwriting can retain color without tinting paper.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1].astype(np.float32)
    colored = np.clip((saturation - 55.0) / 60.0, 0, 1)
    colored *= np.clip((235.0 - hsv[:, :, 2].astype(np.float32)) / 50.0, 0, 1)
    # Colored ink may be lighter than Otsu's dark-ink seed; compare it to the
    # estimated local paper instead of requiring it to survive that threshold.
    colored *= np.clip((background.astype(np.float32) - gray.astype(np.float32) - 8.0) / 20.0, 0, 1)
    gray_rgb = np.repeat(clean[:, :, None], 3, axis=2).astype(np.float32)
    # Correct colored pen exposure with a shared RGB gain; do not paste
    # shadow-darkened ink back onto the cleaned white paper.
    gain = np.clip(250.0 / np.maximum(background.astype(np.float32), 1), 1.0, 2.2)
    color_ink = np.clip(rgb.astype(np.float32) * gain[:, :, None], 0, 255)
    restored = gray_rgb * (1.0 - colored[:, :, None]) + color_ink * colored[:, :, None]
    if preserve_medium_strokes:
        from .scan_enhancement import restore_pale_pen_color
        restored = restore_pale_pen_color(rgb, restored)
    return Image.fromarray(np.rint(restored).astype(np.uint8), mode="RGB")


def _unsharp(image: Image.Image, amount: float) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    blurred = cv2.GaussianBlur(rgb, (0, 0), 1.15)
    sharpened = cv2.addWeighted(rgb, 1.0 + amount, blurred, -amount, 0)
    return Image.fromarray(sharpened, mode="RGB")


class ScanService:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)

    def upload(self, filename: str, data: bytes) -> dict[str, Any]:
        safe_name = Path(filename).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".webp"}:
            raise ValueError("请选择 JPG、PNG、HEIC、HEIF、BMP 或 WebP 图片。")
        source = decode_scan_image(data)
        scan_id = secrets.token_hex(8)
        scan_root = self.output_root / scan_id
        scan_root.mkdir(parents=True, exist_ok=False)
        source.save(scan_root / "original.png", format="PNG", optimize=True)
        corners, partial = _detect_page_geometry(source)
        metadata = {"filename": safe_name, "corners": corners, "partialCorners": partial, "size": list(source.size)}
        (scan_root / "scan.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        preview = source.copy()
        preview.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        preview.save(scan_root / "preview.webp", format="WEBP", quality=90, method=4)
        return {
            "scanId": scan_id,
            "filename": safe_name,
            "width": source.width,
            "height": source.height,
            "detected": bool(corners),
            "corners": corners,
            "processed": False,
            "warning": "未检测到清晰纸张边缘，扫描时会保留整张图片；可用校正纸面框选页面。" if not corners else "",
            "url": f"/output/scans/{scan_id}/preview.webp?v={secrets.token_hex(4)}",
        }

    def process(self, scan_id: str, options: dict[str, Any]) -> dict[str, Any]:
        scan_id = validate_scan_id(scan_id)
        if not isinstance(options, dict):
            raise ValueError("扫描设置格式不正确。")
        mode, orientation, rotation, crop = validate_scan_options(
            options.get("mode", "smart"),
            options.get("orientation", "auto"),
            options.get("rotation", 0),
            options.get("crop"),
        )
        scan_root = self._scan_root(scan_id)
        metadata_path = scan_root / "scan.json"
        source_path = scan_root / "original.png"
        if not metadata_path.is_file() or not source_path.is_file():
            raise ValueError("扫描图片不存在，请重新上传。")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        with Image.open(source_path) as opened:
            source = opened.convert("RGB")
        manual_corners = validate_page_corners(options.get("corners"))
        auto_corners, partial = metadata.get("corners"), metadata.get("partialCorners", False)
        if not auto_corners:
            auto_corners, partial = _detect_page_geometry(source)
        corners = manual_corners or auto_corners
        top_clip = partial.get("topClip") if isinstance(partial, dict) and not manual_corners else None
        result = process_scan_image(source, corners, mode, orientation, rotation, crop, clean_partial_border=bool(partial) and not manual_corners, top_clip=top_clip)
        aligned = process_scan_image(source, corners, "original", orientation, rotation, crop)
        aligned.save(scan_root / "aligned-original.png", format="PNG", optimize=True)
        (scan_root / "current-options.json").write_text(json.dumps({"mode": mode}), encoding="utf-8")
        response = self._save_result(scan_id, result, metadata, warning=not bool(corners))
        response["filterPipelineVersion"] = FILTER_PREVIEW_VERSION
        response["autoCorners"] = auto_corners
        response["alignedOriginalUrl"] = f"/output/scans/{scan_id}/aligned-original.png?v={secrets.token_hex(4)}"
        return response

    def filter_preview(self, scan_id: str, options: dict[str, Any]) -> dict[str, str]:
        """Render an isolated thumbnail without changing the export result.

        Enhance at source resolution, then downsample: applying thresholds to
        a small source would give a misleading impression of fine pen strokes.
        Originals are immutable; validated options and a pipeline version form
        the per-upload cache key. Cache writes are atomic for concurrent reads.
        """
        scan_root = self._scan_root(scan_id)
        if not isinstance(options, dict):
            raise ValueError("扫描设置格式不正确。")
        mode, orientation, rotation, crop = validate_scan_options(
            options.get("mode", "smart"), options.get("orientation", "auto"),
            options.get("rotation", 0), options.get("crop"),
        )
        if mode not in PREVIEW_MODES:
            raise ValueError("该滤镜尚未提供预览。")
        corners = validate_page_corners(options.get("corners"))
        metadata_path = scan_root / "scan.json"
        source_path = scan_root / "original.png"
        if not metadata_path.is_file() or not source_path.is_file():
            raise ValueError("扫描图片不存在，请重新上传。")
        key = hashlib.sha256(json.dumps(
            [FILTER_PREVIEW_VERSION, mode, orientation, rotation, crop, corners],
            separators=(",", ":"),
        ).encode()).hexdigest()[:24]
        filename = f"filter-{key}.webp"
        target = scan_root / filename
        if not target.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            with Image.open(source_path) as opened:
                source = opened.convert("RGB")
            auto_corners, partial = metadata.get("corners"), metadata.get("partialCorners", False)
            if not auto_corners:
                auto_corners, partial = _detect_page_geometry(source)
            top_clip = partial.get("topClip") if isinstance(partial, dict) and not corners else None
            selected = corners or auto_corners
            result = process_scan_image(source, selected, mode, orientation, rotation, crop, clean_partial_border=bool(partial) and not corners, top_clip=top_clip)
            result.thumbnail((FILTER_PREVIEW_EDGE, FILTER_PREVIEW_EDGE), Image.Resampling.LANCZOS)
            temporary = scan_root / f".filter-{secrets.token_hex(8)}.tmp"
            try:
                result.save(temporary, format="WEBP", quality=90, method=4)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return {"mode": mode, "url": f"/output/scans/{scan_id}/{filename}"}

    def restoration_preview(self, scan_id: str, marks: Any) -> dict[str, str]:
        scan_root = self._scan_root(scan_id)
        edit = normalize_scan_edits([{"marks": marks}], 1)[0]
        current = scan_root / "current.png"
        if not current.is_file():
            raise ValueError("请先扫描当前页面。")
        with Image.open(current) as opened:
            page = opened.convert("RGB")
        page = self._restore_scan_page(scan_id, page, edit["restorations"])
        key = hashlib.sha256(json.dumps([current.stat().st_mtime_ns, edit["restorations"]]).encode()).hexdigest()[:24]
        filename = f"restored-{key}.webp"
        page.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        page.save(scan_root / filename, format="WEBP", quality=90, method=4)
        return {"url": f"/output/scans/{scan_id}/{filename}"}

    def _restore_scan_page(self, scan_id: str, page: Image.Image, regions: list[list[float]]) -> Image.Image:
        if not regions:
            return page
        root = self._scan_root(scan_id)
        options_path = root / "current-options.json"
        if not options_path.is_file():
            raise ValueError("请重新扫描后再恢复原图内容。")
        # Retain the editable regions when switching filters, but apply them
        # only to handwriting removal. Geometry changes clear them in the UI.
        if json.loads(options_path.read_text())["mode"] != "remove_handwriting":
            return page
        source = root / "aligned-original.png"
        if not source.is_file():
            raise ValueError("恢复参照图不存在，请重新扫描。")
        with Image.open(source) as opened:
            return restore_regions(page, opened.convert("RGB"), regions)

    def export(self, scan_ids: Any, file_format: Any, edits: Any = None) -> dict[str, str]:
        if file_format not in SCAN_FORMATS:
            raise ValueError("扫描导出格式无效。")
        if not isinstance(scan_ids, list) or not 1 <= len(scan_ids) <= 30:
            raise ValueError("请选择 1 到 30 张图片导出。")
        ids = [validate_scan_id(scan_id) for scan_id in scan_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("导出列表中包含重复图片。")
        pages = []
        names = []
        for scan_id in ids:
            scan_root = self._scan_root(scan_id)
            metadata_path = scan_root / "scan.json"
            current_path = scan_root / "current.png"
            if not metadata_path.is_file() or not current_path.is_file():
                raise ValueError("部分扫描图片已失效，请重新上传后导出。")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            with Image.open(current_path) as opened:
                pages.append(opened.convert("RGB"))
            names.append(Path(metadata.get("filename", f"scan-{scan_id}")).stem[:60] or f"scan-{scan_id}")

        if edits is not None:
            normalized = normalize_scan_edits(edits, len(pages))
            pages = [draw_scan_marks(self._restore_scan_page(scan_id, page, edit["restorations"]), edit["marks"])
                     for scan_id, page, edit in zip(ids, pages, normalized)]
        export_id = secrets.token_hex(8)
        export_root = self.output_root / "exports"
        export_root.mkdir(parents=True, exist_ok=True)
        if file_format == "pdf":
            filename = f"scan-{export_id}.pdf"
            self._write_pdf(pages, export_root / filename)
            return {"url": f"/output/scans/exports/{filename}", "filename": "智能扫描结果.pdf"}
        if file_format == "docx":
            from docx import Document
            from docx.shared import Inches
            doc = Document()
            for index, page in enumerate(pages):
                if index:
                    doc.add_page_break()
                buffer = io.BytesIO()
                page.save(buffer, format="PNG")
                buffer.seek(0)
                section = doc.sections[0]
                available = section.page_width - section.left_margin - section.right_margin
                available_height = section.page_height - section.top_margin - section.bottom_margin
                width = min(available, int(available_height * page.width / page.height), Inches(page.width / 150))
                doc.add_picture(buffer, width=width)
            filename = f"scan-{export_id}.docx"
            doc.save(export_root / filename)
            return {"url": f"/output/scans/exports/{filename}", "filename": "智能扫描结果.docx"}
        if len(pages) == 1:
            filename = f"scan-{export_id}.{file_format}"
            output_path = export_root / filename
            if file_format == "jpg":
                pages[0].save(output_path, format="JPEG", quality=94, optimize=True)
            else:
                pages[0].save(output_path, format="PNG", optimize=True)
            return {"url": f"/output/scans/exports/{filename}", "filename": filename}
        filename = f"scan-{export_id}.zip"
        image_extension = "jpg" if file_format == "jpg" else "png"
        with zipfile.ZipFile(export_root / filename, "w", zipfile.ZIP_DEFLATED) as package:
            for index, (page, name) in enumerate(zip(pages, names), start=1):
                buffer = io.BytesIO()
                if file_format == "jpg":
                    page.save(buffer, format="JPEG", quality=94, optimize=True)
                else:
                    page.save(buffer, format="PNG", optimize=True)
                package.writestr(f"{index:02d}-{name}.{image_extension}", buffer.getvalue())
        return {"url": f"/output/scans/exports/{filename}", "filename": f"扫描图片-{image_extension.upper()}.zip"}

    def _scan_root(self, scan_id: str) -> Path:
        candidate = (self.output_root / validate_scan_id(scan_id)).resolve()
        candidate.relative_to(self.output_root.resolve())
        return candidate

    def _save_result(self, scan_id: str, result: Image.Image, metadata: dict[str, Any], warning: bool) -> dict[str, Any]:
        scan_root = self._scan_root(scan_id)
        result.save(scan_root / "current.png", format="PNG", optimize=True)
        preview = result.copy()
        preview.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        revision = secrets.token_hex(4)
        preview.save(scan_root / "preview.webp", format="WEBP", quality=90, method=4)
        return {
            "scanId": scan_id,
            "filename": metadata.get("filename", "扫描图片"),
            "width": result.width,
            "height": result.height,
            "detected": not warning,
            "processed": True,
            "warning": "未检测到清晰纸张边缘，已先增强整张图片；可用校正纸面调整范围。" if warning else "",
            "url": f"/output/scans/{scan_id}/preview.webp?v={revision}",
        }

    @staticmethod
    def _write_pdf(pages: Sequence[Image.Image], output_path: Path) -> None:
        pdf = canvas.Canvas(str(output_path), pageCompression=1)
        for page in pages:
            width_pt = page.width / 150 * 72
            height_pt = page.height / 150 * 72
            pdf.setPageSize((width_pt, height_pt))
            pdf.drawImage(ImageReader(page), 0, 0, width=width_pt, height=height_pt, preserveAspectRatio=False, mask="auto")
            pdf.showPage()
        pdf.save()
