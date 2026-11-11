"""Restore selected original regions under scan annotations, without rerunning AI."""
import math
from typing import Any

from PIL import Image

from .page_edits import normalize_page_edits, _draw_marks


def draw_scan_marks(page: Image.Image, marks: list[dict]) -> Image.Image:
    """Apply the same ordinary text and annotation styling to scanned pages."""
    return _draw_marks(page, marks)


def normalize_scan_edits(value: Any, page_count: int) -> list[dict]:
    if not isinstance(value, list) or len(value) != page_count:
        raise ValueError("扫描编辑数据与页数不匹配。")
    ordinary, regions = [], []
    for page in value:
        if not isinstance(page, dict):
            raise ValueError("扫描编辑数据格式不正确。")
        marks = page.get("marks", [])
        if not isinstance(marks, list) or len(marks) > 150:
            raise ValueError("单页最多保存 150 条标注及恢复区域。")
        selected, annotations = [], []
        for mark in marks:
            if isinstance(mark, dict) and mark.get("kind") == "restore":
                rect = mark.get("rect")
                if not isinstance(rect, list) or len(rect) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect):
                    raise ValueError("恢复区域格式不正确。")
                x, y, width, height = map(float, rect)
                if x < 0 or y < 0 or width < .001 or height < .001 or x+width > 1.000001 or y+height > 1.000001:
                    raise ValueError("恢复区域必须位于页面内，且不能过小。")
                selected.append([x, y, width, height])
            else:
                annotations.append(mark)
        ordinary.append({**page, "marks": annotations})
        regions.append(selected)
    normalized = normalize_page_edits(ordinary, page_count)
    return [{**page, "restorations": rects} for page, rects in zip(normalized, regions)]


def restore_regions(processed: Image.Image, aligned_original: Image.Image, regions: list[list[float]]) -> Image.Image:
    if processed.size != aligned_original.size:
        raise ValueError("原图与扫描结果尺寸不一致，请重新扫描后再恢复。")
    result = processed.convert("RGB").copy()
    original = aligned_original.convert("RGB")
    for x, y, width, height in regions:
        left, top = math.floor(x*result.width), math.floor(y*result.height)
        right = min(result.width, math.ceil((x+width)*result.width))
        bottom = min(result.height, math.ceil((y+height)*result.height))
        box = (left, top, right, bottom)
        result.paste(original.crop(box), (left, top))
    return result
