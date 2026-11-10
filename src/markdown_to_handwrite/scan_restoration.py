"""Restore selected original regions under scan annotations, without rerunning AI."""
import math
from typing import Any

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from .page_edits import normalize_page_edits, _draw_marks


def draw_scan_marks(page: Image.Image, marks: list[dict]) -> Image.Image:
    """Draw scan annotations in Song type; other tools retain their styling."""
    result = page
    for mark in marks:
        if mark['kind'] != 'comment':
            result = _draw_marks(result, [mark])
            continue
        candidates = ['/System/Library/Fonts/Supplemental/Songti.ttc',
                      'C:/Windows/Fonts/simsun.ttc',
                      '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc']
        font_path = next((p for p in candidates if Path(p).is_file()), None)
        if not font_path:
            raise ValueError('未找到宋体或思源宋体，无法导出扫描批注。')
        size = max(12, round(mark['width'] * result.width))
        # macOS Songti.ttc starts with Black, not Regular.
        font = ImageFont.truetype(font_path, size, index=4 if font_path.endswith('/Songti.ttc') else 0)
        result = result.copy()
        draw = ImageDraw.Draw(result)
        x = round(mark['points'][0][0] * (result.width - 1))
        y = round(mark['points'][0][1] * (result.height - 1))
        max_width = min(round(result.width * .48), result.width-x)
        line = ''
        for char in mark['text'] + '\n':
            if char == '\n' or (line and draw.textlength(line+char, font=font) > max_width):
                draw.text((x,y), line, font=font, fill=mark['color'], anchor='lt')
                y += round(size*1.22)
                line = ''
            if char != '\n':
                line += char
    return result


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
