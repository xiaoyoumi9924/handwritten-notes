from __future__ import annotations

import math
import json
import re
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import HandwritingConfig
from .handwriting import HandwritingEngine


_EDIT_TOOLS = {"pen", "highlight", "underline", "comment"}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_page_edits(value: Any, page_count: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != page_count:
        raise ValueError("页面编辑数据与手稿页数不匹配。")
    return [_normalize_one_page(item) for item in value]


def _normalize_one_page(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("页面编辑数据格式不正确。")
    rotation = value.get("rotation", 0)
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation not in {0, 90, 180, 270}:
        raise ValueError("页面旋转角度无效。")

    crop = value.get("crop")
    if crop is not None:
        if not isinstance(crop, list) or len(crop) != 4:
            raise ValueError("裁切范围格式不正确。")
        crop = [_finite_number(item, "裁切范围") for item in crop]
        x, y, width, height = crop
        if x < 0 or y < 0 or width < 0.02 or height < 0.02 or x + width > 1.0001 or y + height > 1.0001:
            raise ValueError("裁切范围必须位于页面内。")

    marks = value.get("marks", [])
    if not isinstance(marks, list) or len(marks) > 150:
        raise ValueError("单页最多保存 150 条标注。")
    normalized_marks = [_normalize_mark(mark) for mark in marks]
    return {"rotation": rotation, "crop": crop, "marks": normalized_marks}


def _normalize_mark(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("标注数据格式不正确。")
    kind = value.get("kind")
    if kind not in _EDIT_TOOLS:
        raise ValueError("标注工具类型无效。")
    color = value.get("color")
    if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
        raise ValueError("标注颜色无效。")
    width = _finite_number(value.get("width"), "标注笔宽")
    if not 0.001 <= width <= 0.08:
        raise ValueError("标注笔宽超出范围。")
    points = value.get("points")
    minimum_points = 1 if kind == "comment" else 2
    if not isinstance(points, list) or not minimum_points <= len(points) <= 600:
        raise ValueError("批注需要一个定位点，笔迹标注需要 2 到 600 个路径点。")
    normalized_points = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("标注路径点格式不正确。")
        x, y = (_finite_number(item, "标注路径点") for item in point)
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("标注路径点必须位于页面内。")
        normalized_points.append([x, y])
    if kind == "comment" and len(normalized_points) != 1:
        raise ValueError("批注需要一个定位点。")
    if kind == "underline" and len(normalized_points) != 2:
        raise ValueError("下划线需要一条直线路径。")
    result = {"kind": kind, "color": color, "width": width, "points": normalized_points}
    if kind == "comment":
        text = value.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 240:
            raise ValueError("批注文字不能为空，且不能超过 240 个字符。")
        result["text"] = text.strip()
    return result


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}必须是有效数值。")
    return float(value)


def apply_page_edits(
    original: Image.Image,
    edits: dict[str, Any],
    handwriting: HandwritingConfig | None = None,
) -> Image.Image:
    base = original.convert("RGB")
    base_size = base.size
    rotation = edits["rotation"]
    if rotation == 90:
        base = base.transpose(Image.Transpose.ROTATE_270)
    elif rotation == 180:
        base = base.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        base = base.transpose(Image.Transpose.ROTATE_90)
    base = _contain_on_page(base, base_size, original.convert("RGB").getpixel((0, 0)))

    crop = edits["crop"]
    if crop is not None:
        x, y, width, height = crop
        left = max(0, min(base.width - 1, round(x * base.width)))
        top = max(0, min(base.height - 1, round(y * base.height)))
        right = max(left + 1, min(base.width, round((x + width) * base.width)))
        bottom = max(top + 1, min(base.height, round((y + height) * base.height)))
        base = _contain_on_page(base.crop((left, top, right, bottom)), base_size, base.getpixel((0, 0)))

    return _draw_marks(base, edits["marks"], handwriting)


def _contain_on_page(image: Image.Image, size: tuple[int, int], background: tuple[int, int, int]) -> Image.Image:
    fitted = ImageOps.contain(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    page = Image.new("RGB", size, background)
    page.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return page


def _draw_marks(page: Image.Image, marks: list[dict[str, Any]], handwriting: HandwritingConfig | None = None) -> Image.Image:
    if not marks:
        return page
    result = page.convert("RGBA")
    width_scale = page.width
    for mark in marks:
        layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        if mark["kind"] == "comment":
            _draw_comment(layer, page, mark, handwriting)
            result = Image.alpha_composite(result, layer)
            continue
        points = [(round(x * (page.width - 1)), round(y * (page.height - 1))) for x, y in mark["points"]]
        width = max(2, round(mark["width"] * width_scale))
        red, green, blue = tuple(bytes.fromhex(mark["color"][1:]))
        alpha = 96 if mark["kind"] == "highlight" else 255
        draw.line(points, fill=(red, green, blue, alpha), width=width, joint="curve")
        if mark["kind"] in {"pen", "highlight"} and len(points) > 1:
            radius = width // 2
            for x, y in (points[0], points[-1]):
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(red, green, blue, alpha))
        result = Image.alpha_composite(result, layer)
    return result.convert("RGB")


@lru_cache(maxsize=128)
def _render_comment(text: str, size: int, text_width: int, config_json: str) -> Image.Image:
    config = HandwritingConfig(**json.loads(config_json))
    engine = HandwritingEngine(config, reference_size_px=size)
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = ""
        for char in paragraph:
            if line and engine.measure(line + char, size) > text_width:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    rendered = [engine.render_line(line, size, text_width, seed_extra=f"comment:{i}") for i, line in enumerate(lines)]
    gap = max(2, round(size * .2))
    total_height = sum(image.height for image in rendered) + gap * max(0, len(rendered) - 1)
    result = Image.new("RGBA", (min(text_width, max(image.width for image in rendered)), max(1, total_height)))
    y = 0
    for image in rendered:
        result.alpha_composite(image, (0, y))
        y += image.height + gap
    return result


def comment_image(page: Image.Image, mark: dict[str, Any],
                  handwriting: HandwritingConfig | None = None) -> Image.Image:
    page_width, page_height = page.size
    size = max(12, round(mark["width"] * page_width))
    config = replace(handwriting or HandwritingConfig(), ink_color=mark["color"])
    text_width = min(page_width, max(size * 4, round(page_width * 0.48)))
    config_json = json.dumps(asdict(config), sort_keys=True, ensure_ascii=False)
    return _render_comment(mark["text"], size, text_width, config_json)


def _draw_comment(layer: Image.Image, page: Image.Image, mark: dict[str, Any],
                  handwriting: HandwritingConfig | None = None) -> None:
    page_width, page_height = page.size
    image = comment_image(page, mark, handwriting)
    x = max(0, min(round(mark["points"][0][0] * (page_width - 1)), page_width - image.width))
    y = max(0, min(round(mark["points"][0][1] * (page_height - 1)), page_height - image.height))
    layer.alpha_composite(image, (x, y))


def save_pages_pdf(
    pages: Sequence[Image.Image],
    output_path: str | Path,
    page_width_mm: float,
    page_height_mm: float,
) -> Path:
    if not pages:
        raise ValueError("没有可导出的手稿页面。")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    width_pt = page_width_mm / 25.4 * 72
    height_pt = page_height_mm / 25.4 * 72
    # PyMuPDF embeds the RGB pixels losslessly, avoiding ReportLab's costly
    # Python ASCII85 encoding of every full-resolution page.
    import pymupdf
    with pymupdf.open() as pdf:
        for page in pages:
            rgb = page.convert("RGB")
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, rgb.width, rgb.height, rgb.tobytes(), False)
            target = pdf.new_page(width=width_pt, height=height_pt)
            target.insert_image(target.rect, pixmap=pixmap)
        pdf.save(output, deflate=True)
    return output
