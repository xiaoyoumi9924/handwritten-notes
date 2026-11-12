from __future__ import annotations

import argparse
import base64
import binascii
import io
import ipaddress
import json
import math
import mimetypes
import re
import secrets
import shutil
import threading
import tempfile
import webbrowser
import sys
import zipfile
from dataclasses import asdict, fields, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image, ImageColor

from .config import ReportConfig, config_from_dict, validate_layout_options
from .docx_importer import import_docx_bytes
from .docx_exporter import export_pages_as_docx
from .markdown_parser import parse_markdown
from .page_edits import apply_page_edits, comment_image, normalize_page_edits, save_pages_pdf
from .page_store import DiskPages
from .renderer import PROJECT_ROOT, ReportRenderer
from .scanner import MAX_SCAN_BYTES, ScanService, validate_scan_id


STATIC_ROOT = Path(__file__).resolve().parent / "webui"
OUTPUT_ROOT = PROJECT_ROOT / "output" / "webui"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_DOCX_BYTES = 5 * 1024 * 1024
MAX_SCAN_REQUEST_BYTES = (MAX_SCAN_BYTES * 4 // 3) + (256 * 1024)
MAX_HTTP_CONNECTIONS = 24


class LimitedHTTPServer(ThreadingHTTPServer):
    """Bound the number of request threads, including slow clients."""

    def __init__(self, *args: Any, max_connections: int = MAX_HTTP_CONNECTIONS, **kwargs: Any):
        if max_connections < 1:
            raise ValueError("并发连接数必须大于 0。")
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


def _range(
    path: str,
    label: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: str = "",
    help_text: str = "",
) -> dict[str, Any]:
    return {
        "path": path,
        "label": label,
        "control": "range",
        "min": minimum,
        "max": maximum,
        "step": step,
        "unit": unit,
        "help": help_text,
    }


def _toggle(path: str, label: str, help_text: str = "") -> dict[str, Any]:
    return {"path": path, "label": label, "control": "toggle", "help": help_text}


def _text(path: str, label: str, help_text: str = "", control: str = "text") -> dict[str, Any]:
    return {"path": path, "label": label, "control": control, "help": help_text}


def _nullable_range(
    path: str,
    label: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: str = "px",
    help_text: str = "",
) -> dict[str, Any]:
    item = _range(path, label, minimum, maximum, step, unit, help_text)
    item["control"] = "nullable-range"
    return item


CONFIG_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "page",
        "title": "页面与分辨率",
        "eyebrow": "PAGE",
        "description": "纸张尺寸、输出精度与四周留白",
        "fields": [
            _range("page.width_mm", "纸张宽度", 120, 420, 1, "mm"),
            _range("page.height_mm", "纸张高度", 120, 594, 1, "mm"),
            _range("page.dpi", "输出 DPI", 96, 600, 12, "dpi", "DPI 越高越清晰，也会显著增加生成时间。"),
            _range("page.margin_top_mm", "上边距", 0, 90, 1, "mm"),
            _range("page.margin_bottom_mm", "下边距", 0, 90, 1, "mm"),
            _range("page.margin_left_mm", "左边距", 0, 70, 1, "mm"),
            _range("page.margin_right_mm", "右边距", 0, 70, 1, "mm"),
        ],
    },
    {
        "id": "background",
        "title": "纸张与背景",
        "eyebrow": "PAPER",
        "description": "底色、纸面纹理与参考背景",
        "fields": [
            {
                "path": "background.style",
                "label": "纸张样式",
                "control": "select",
                "options": [
                    {"value": "plain", "label": "纯色纸"},
                    {"value": "lined", "label": "横线纸"},
                    {"value": "grid", "label": "方格纸"},
                    {"value": "dot", "label": "点阵纸"},
                    {"value": "image", "label": "背景素材"},
                ],
                "help": "纯色、横线、方格和点阵由程序绘制；选择背景素材时才读取背景文件或自动发现素材。",
            },
            _text("background.image", "背景文件", "选择文件后自动切换到“背景素材”；留空时可使用自动发现。", "background-path"),
            _toggle("background.auto_discover", "自动发现背景", "仅在纸张样式为“背景素材”且未指定文件时搜索 background/ 目录。"),
            _text("background.paper_color", "纸张底色", control="color"),
            _text("background.line_color", "辅助线颜色", control="color"),
            _text("background.margin_line_color", "页边线颜色", control="color"),
            _range("background.line_gap_mm", "横线间距", 3, 20, 0.5, "mm"),
            _range("background.grid_size_mm", "方格尺寸", 3, 20, 0.5, "mm"),
            _range("background.dot_gap_mm", "点阵间距", 2, 15, 0.5, "mm"),
            _range("background.dot_radius_px", "点阵半径", 1, 6, 1, "px"),
            _toggle("background.draw_margin_line", "绘制页边线"),
        ],
    },
    {
        "id": "typography",
        "title": "字体、字号与字距",
        "eyebrow": "TYPE",
        "description": "调整字号、字符间距和间距变化，选择字体",
        "fields": [
            _text("handwriting.font_path", "正文字体", "SDT 中文不使用其轮廓；该字体负责排版度量，以及英文、数字和缺失符号的中心线形状。", "font-path"),
            _text("handwriting.latin_font_path", "英文字体", "只用于正文中的拉丁字母、数字和 ASCII 标点；留空时沿用正文字体。公式仍使用数学字体。", "font-path"),
            _range("handwriting.latin_upright_correction_deg", "英文倾斜回正", 0, 10, 0.5, "°", "抵消英文字体自带的右倾；0 表示保留原字体斜度，不改变汉字或公式。"),
            _range("handwriting.cjk_latin_spacing_em", "中英文衔接留白", 0, 0.25, 0.01, "em", "只在汉字与拉丁字母/数字直接相邻时增加少量距离；输入已有空格时不重复添加。"),
            _text("handwriting.math_font_path", "数学字体", "只决定数学符号的排版度量与中心线形状；留空时沿用正文字体。", "font-path"),
            _text("handwriting.fallback_font_path", "回退字体", "仅在首选字体缺少字符时补齐字形。", "font-path"),
            _range("handwriting.body_font_pt", "正文字号", 7, 32, 0.5, "pt", "控制正文字符边界框与排版尺寸，不改变统一基础笔宽。"),
            _range("handwriting.math_font_pt", "数学字号", 7, 36, 0.5, "pt", "控制公式主字符尺寸；上下标由公式布局按比例缩放，笔宽保持统一。"),
            _range("handwriting.code_font_pt", "代码字号", 6, 28, 0.5, "pt", "只控制代码字符尺寸。"),
            _range("handwriting.h1_font_pt", "一级标题", 12, 48, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.h2_font_pt", "二级标题", 10, 40, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.h3_font_pt", "三级标题", 9, 34, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.line_spacing", "行距倍率", 1.0, 2.5, 0.01, "×", "只控制行框高度，不改变字符形状或笔画粗细。"),
            _range("handwriting.word_spacing_px", "字符间距", -12, 24, 0.5, "px", "在非空格字符的前进量上增减输出像素；负值更紧，正值更疏，不改变空格本身的宽度。"),
            _range("handwriting.advance_jitter_sigma_ratio", "字距随机扰动 σ", 0, 0.1, 0.001, "em", "实际标准差为当前字号乘以该比例；默认 0.01，设为 0 可关闭字符前进量的随机变化。"),
        ],
    },
    {
        "id": "sdt-trajectories",
        "title": "SDT · 轨迹渲染",
        "eyebrow": "STROKE",
        "description": "直接重绘在线笔迹，并统一正文、标题、公式与表格线的笔宽",
        "fields": [
            _toggle("handwriting.sdt_trajectory_enabled", "启用 SDT 轨迹引擎", "中文优先读取 SDT 轨迹；缺失符号自动提取字体中心线。"),
            _text("handwriting.sdt_trajectory_path", "轨迹库路径", "留空时使用项目内置的 6763 字轨迹包。"),
            _range("handwriting.sdt_stroke_width", "统一基础笔宽", 6, 22, 0.5, "SDT", "唯一的 SDT 基础粗细参数；按正文字号换算后，同样用于标题、公式字符、分数线和表格线。"),
            _range("handwriting.sdt_supersample", "抗锯齿采样", 1, 5, 1, "×", "只影响边缘质量和生成速度，不改变布局、形状和目标笔宽。"),
        ],
    },
    {
        "id": "first-layer",
        "title": "字形扰动",
        "eyebrow": "GLYPH",
        "description": "只改变字符和笔画的几何形状，不改变墨色与基础笔宽",
        "fields": [
            _range("handwriting.position_disorder", "文字位置凌乱度", 0, 100, 10, "%", "随机调整文字的上下和左右位置；默认 10%，0% 关闭额外扰动。"),
            _range("handwriting.correction_probability", "随机勾画涂改概率", 0, 10, 1, "%", "按概率划掉文字并在附近重写；英文按单词处理。"),
            _toggle("handwriting.prefer_handright", "优先使用 Handright", "仅在关闭或无法加载 SDT 轨迹引擎时生效。"),
            _range("handwriting.perturb_theta_sigma", "字符旋转标准差", 0, 0.06, 0.001, "rad", "所有引擎统一按弧度解释；默认配置为 0.008 rad，正式预设为 0.003 rad（约 0.17°）。"),
            _range("handwriting.math_jitter_scale", "公式扰动强度", 0, 1, 0.01, "×", "只缩放公式字符和公式线条的随机变化；正文笔迹不受影响。0 为完全关闭公式扰动，0.2 为默认轻微变化。"),
            _nullable_range("handwriting.perturb_x_sigma_px", "字符水平偏移", 0, 12, 0.1, "px", "自动时统一使用当前字号的 1.5%。"),
            _nullable_range("handwriting.perturb_y_sigma_px", "正文字符垂直偏移", 0, 12, 0.1, "px", "只控制正文、标题、列表编号和页码字符；自动时使用当前字号的 1.5%。"),
            _range("handwriting.math_perturb_y_sigma_ratio", "公式字符垂直偏移 σ", 0, 0.10, 0.001, "em", "实际标准差等于当前公式字符字号乘以该比例；主字符、上下标及分式组件分别按各自字号计算，不移动分数线或根号线。"),
            _range("handwriting.sdt_coordinate_jitter", "笔画路径扰动", 0, 2.0, 0.05, "SDT", "应用于所有轨迹字符；SDT 汉字与字体中心线符号会先按弧长统一采样。"),
            _range("handwriting.sdt_jitter_correlation", "路径扰动平滑长度", 2, 30, 0.5, "采样点", "越大越平缓；统一采样后不再受原始轨迹点数影响。"),
            _range("handwriting.elastic_strength_ratio", "行内弹性形变", 0, 0.1, 0.001, "em", "栅格化后对整行文字或整组公式施加局部形变。"),
            _range("handwriting.elastic_smoothness_ratio", "弹性平滑尺度", 0.1, 2.0, 0.01, "em", "控制弹性位移场的变化尺度。"),
            _range("handwriting.baseline_wave_amplitude_ratio", "基线起伏", 0, 0.08, 0.001, "em", "正式预设为 0.005 em；统一作用于正文行和公式字符图块。"),
            _range("handwriting.baseline_wave_length_em", "基线波长", 2, 24, 0.5, "em", "越大时整行起伏越舒缓。"),
            _range("handwriting.math_rule_tilt_ratio", "生成线条倾斜", 0, 0.12, 0.001, "em", "只改变分数线、根号横线和表格线的方向。"),
            _range("handwriting.math_rule_wobble_ratio", "生成线条弯曲", 0, 0.05, 0.001, "em", "为公式线和表格线加入低频平缓弯曲。"),
            _range("handwriting.math_rule_jitter_ratio", "生成线条抖动", 0, 0.1, 0.001, "em", "为生成线条加入细小路径扰动；不改变墨色或基础笔宽。"),
            _text("handwriting.seed", "随机种子", "统一控制字形、笔压、墨色和公式线条；相同种子可复现。"),
        ],
    },
    {
        "id": "second-layer",
        "title": "墨迹扰动",
        "eyebrow": "INK",
        "description": "只改变笔压、整体粗细与墨色；同样作用于字符和生成线条",
        "fields": [
            _text("handwriting.ink_color", "统一墨水颜色", "正文、标题、公式字符和生成线条共用。", control="color"),
            _range("handwriting.sdt_width_jitter", "沿笔画笔压变化", 0, 0.35, 0.01, "", "统一作用于 SDT 汉字、中心线符号、公式线和表格线。"),
            _range("handwriting.sdt_taper", "起收笔渐细", 0, 0.6, 0.01, "", "控制每条轨迹及生成线条首尾的收尖程度。"),
            _toggle("handwriting.second_layer_enabled", "启用栅格墨迹后处理", "控制整体字重随机、墨色波动和飞白；关闭时仍保留上面的轨迹级笔压与收笔。"),
            _range("handwriting.stroke_weight_base_scale", "回退字体基础字重", 0.6, 1.6, 0.01, "×", "仅在 Handright/Pillow 回退模式下生效；SDT 模式只使用“统一基础笔宽”。"),
            _range("handwriting.stroke_weight_variation_sigma_ratio", "整体粗细扰动 σ", 0, 0.03, 0.0005, "em", "零均值正态分布的标准差；0 表示关闭。同一公式的字符、分数线、根号线与重音线共享一次连续粗细扰动。"),
            _range("handwriting.ink_density_jitter", "墨水浓淡波动", 0, 0.5, 0.01, "", "统一作用于字符墨迹、公式线与表格线。"),
            _range("handwriting.dry_brush_probability", "飞白概率", 0, 1, 0.01, "", "字符和生成线条使用同一概率。"),
            _range("handwriting.dry_brush_min_opacity", "飞白最低浓度", 0.1, 1, 0.01, "", "值越低，触发飞白时的墨迹越淡。"),
        ],
    },
    {
        "id": "footer",
        "title": "页脚与页码",
        "eyebrow": "FOOTER",
        "description": "控制页面底部页码及其独立预留空间",
        "fields": [
            _toggle("layout.show_page_numbers", "显示底部页码", "关闭后不绘制页码，也不为页脚预留空间。"),
            _range("layout.footer_gap_mm", "页码区域高度", 0, 24, 0.5, "mm", "仅在显示底部页码时参与正文分页。"),
        ],
    },
    {
        "id": "layout",
        "title": "文档布局",
        "eyebrow": "LAYOUT",
        "description": "标题与插图编号、段落节奏、表格与图片留白",
        "fields": [
            _toggle("layout.number_sections", "自动编号章节"),
            _toggle("layout.number_figures", "自动编号插图", "按文档图片顺序从 1 编号，显示“图1：图片标题”；关闭时只显示图片标题。"),
            _toggle("layout.justify_paragraphs", "拉伸至右侧对齐", "够满的纯文字折行最多拉伸 18%；含行内公式的行保留公式比例，同段纯文字行仍可拉伸。"),
            _range("layout.paragraph_gap_mm", "段后间距", 0, 12, 0.1, "mm"),
            _range("layout.heading_gap_before_mm", "标题前间距", 0, 18, 0.5, "mm"),
            _range("layout.heading_gap_after_mm", "标题后间距", 0, 14, 0.5, "mm"),
            _range("layout.formula_gap_mm", "公式上下间距", 0, 14, 0.5, "mm"),
            _range("layout.table_gap_mm", "表格上下间距", 0, 16, 0.5, "mm"),
            _range("layout.table_cell_padding_mm", "单元格内边距", 0, 8, 0.25, "mm"),
            _range("layout.first_line_indent_em", "首行缩进", 0, 6, 0.25, "em"),
            _range("layout.list_indent_mm", "列表缩进", 0, 24, 0.5, "mm"),
            _range("layout.image_placeholder_height_mm", "图片占位高度", 10, 160, 1, "mm"),
            _toggle("layout.image_placeholder_border", "图片占位边框"),
        ],
    },
]


_DEFAULT_HANDWRITING = ReportConfig().handwriting


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "formal": {
        "handwriting.math_jitter_scale": 0.08,
        "handwriting.perturb_theta_sigma": 0.003,
        "handwriting.math_perturb_y_sigma_ratio": 0.008,
        "handwriting.sdt_coordinate_jitter": 0.25,
        "handwriting.sdt_jitter_correlation": 16.0,
        "handwriting.elastic_strength_ratio": 0.001,
        "handwriting.elastic_smoothness_ratio": 0.75,
        "handwriting.baseline_wave_amplitude_ratio": 0.005,
        "handwriting.baseline_wave_length_em": 18.0,
        "handwriting.math_rule_tilt_ratio": 0.015,
        "handwriting.math_rule_wobble_ratio": 0.003,
        "handwriting.math_rule_jitter_ratio": 0.020,
        "handwriting.sdt_width_jitter": 0.06,
        "handwriting.sdt_taper": 0.22,
        "handwriting.stroke_weight_variation_sigma_ratio": 0.0020,
        "handwriting.ink_density_jitter": 0.025,
        "handwriting.dry_brush_probability": 0.01,
        "handwriting.dry_brush_min_opacity": 0.90,
    },
    "natural": {
        "handwriting.math_jitter_scale": _DEFAULT_HANDWRITING.math_jitter_scale,
        "handwriting.perturb_theta_sigma": _DEFAULT_HANDWRITING.perturb_theta_sigma,
        "handwriting.math_perturb_y_sigma_ratio": _DEFAULT_HANDWRITING.math_perturb_y_sigma_ratio,
        "handwriting.sdt_coordinate_jitter": _DEFAULT_HANDWRITING.sdt_coordinate_jitter,
        "handwriting.sdt_jitter_correlation": _DEFAULT_HANDWRITING.sdt_jitter_correlation,
        "handwriting.elastic_strength_ratio": _DEFAULT_HANDWRITING.elastic_strength_ratio,
        "handwriting.elastic_smoothness_ratio": _DEFAULT_HANDWRITING.elastic_smoothness_ratio,
        "handwriting.baseline_wave_amplitude_ratio": _DEFAULT_HANDWRITING.baseline_wave_amplitude_ratio,
        "handwriting.baseline_wave_length_em": _DEFAULT_HANDWRITING.baseline_wave_length_em,
        "handwriting.math_rule_tilt_ratio": _DEFAULT_HANDWRITING.math_rule_tilt_ratio,
        "handwriting.math_rule_wobble_ratio": _DEFAULT_HANDWRITING.math_rule_wobble_ratio,
        "handwriting.math_rule_jitter_ratio": _DEFAULT_HANDWRITING.math_rule_jitter_ratio,
        "handwriting.sdt_width_jitter": _DEFAULT_HANDWRITING.sdt_width_jitter,
        "handwriting.sdt_taper": _DEFAULT_HANDWRITING.sdt_taper,
        "handwriting.stroke_weight_variation_sigma_ratio": _DEFAULT_HANDWRITING.stroke_weight_variation_sigma_ratio,
        "handwriting.ink_density_jitter": _DEFAULT_HANDWRITING.ink_density_jitter,
        "handwriting.dry_brush_probability": _DEFAULT_HANDWRITING.dry_brush_probability,
        "handwriting.dry_brush_min_opacity": _DEFAULT_HANDWRITING.dry_brush_min_opacity,
    },
    "casual": {
        "handwriting.math_jitter_scale": 0.45,
        "handwriting.perturb_theta_sigma": 0.014,
        "handwriting.math_perturb_y_sigma_ratio": 0.028,
        "handwriting.sdt_coordinate_jitter": 0.95,
        "handwriting.sdt_jitter_correlation": 7.0,
        "handwriting.elastic_strength_ratio": 0.006,
        "handwriting.elastic_smoothness_ratio": 0.40,
        "handwriting.baseline_wave_amplitude_ratio": 0.036,
        "handwriting.baseline_wave_length_em": 8.0,
        "handwriting.math_rule_tilt_ratio": 0.078,
        "handwriting.math_rule_wobble_ratio": 0.022,
        "handwriting.math_rule_jitter_ratio": 0.082,
        "handwriting.sdt_width_jitter": 0.24,
        "handwriting.sdt_taper": 0.38,
        "handwriting.stroke_weight_variation_sigma_ratio": 0.0045,
        "handwriting.ink_density_jitter": 0.10,
        "handwriting.dry_brush_probability": 0.10,
        "handwriting.dry_brush_min_opacity": 0.58,
    },
}


def _config_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if not is_dataclass(value):
        return paths
    for field_info in fields(value):
        field_value = getattr(value, field_info.name)
        path = f"{prefix}.{field_info.name}" if prefix else field_info.name
        if is_dataclass(field_value):
            paths.update(_config_paths(field_value, path))
        else:
            paths.add(path)
    return paths


# 内部笔迹配置保留给本地配置使用，不单独显示在侧栏。
INTERNAL_CONFIG_PATHS = frozenset({
    "handwriting.reference_glyph_path", "handwriting.reference_glyph_overrides_path", "handwriting.reference_override_weight_match", "handwriting.uniform_ink_enabled",
    "handwriting.reference_preserve_stroke_weight", "handwriting.reference_punctuation_font", "handwriting.reference_rotation_sigma_deg", "handwriting.reference_scale_sigma_ratio", "handwriting.reference_glyph_exclude", "handwriting.reference_latin_f_outline", "handwriting.math_inline_scale",
    "handwriting.math_stroke_weight_scale", "handwriting.math_display_left_aligned",
    "handwriting.math_wrap_long", "handwriting.math_character_rotation_deg",
    "handwriting.math_match_body_ink",
    "handwriting.natural_one", "handwriting.handwritten_quotes",
    "handwriting.handwritten_punctuation", "handwriting.preserve_chinese_punctuation",
    "handwriting.handwritten_digit_one", "handwriting.latin_word_corrections", "handwriting.uniform_table_ink", "handwriting.legible_decimal_point",
})


def schema_paths() -> set[str]:
    return {item["path"] for section in CONFIG_SECTIONS for item in section["fields"]}


def available_assets() -> dict[str, list[dict[str, str]]]:
    fonts = []
    seen_fonts: set[Path] = set()
    for root, directory in ((Path.cwd(), Path.cwd() / "font"), (PROJECT_ROOT, PROJECT_ROOT / "font")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*")):
            resolved = path.resolve()
            if not path.is_file() or path.suffix.lower() not in {".ttf", ".otf", ".ttc"} or resolved in seen_fonts:
                continue
            seen_fonts.add(resolved)
            try:
                value = path.relative_to(root).as_posix()
            except ValueError:
                value = str(resolved)
            fonts.append({"label": path.name, "value": value})

    backgrounds = []
    candidates = list((PROJECT_ROOT / "background").glob("*"))
    candidates.extend(path for path in PROJECT_ROOT.iterdir() if path.is_file())
    for path in sorted(set(candidates)):
        if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            backgrounds.append({"label": path.name, "value": path.relative_to(PROJECT_ROOT).as_posix()})
    return {"fonts": fonts, "backgrounds": backgrounds}


def available_examples() -> list[dict[str, str]]:
    examples = []
    for path in sorted((PROJECT_ROOT / "examples").glob("*.md")):
        examples.append({"label": path.stem, "value": path.name})
    return examples


def _font_presets() -> dict[str, dict[str, Any]]:
    presets = {name: dict(values) for name, values in STYLE_PRESETS.items()}
    path = PROJECT_ROOT / "configs" / "personal_v6_test.json"
    if path.is_file() and (PROJECT_ROOT / "font_library/personal_v6/trajectories.zip").is_file():
        handwriting = json.loads(path.read_text(encoding="utf-8"))["handwriting"]
        presets["personal_v6"] = {f"handwriting.{key}": value for key, value in handwriting.items()}
        for key in handwriting:
            presets["formal"].setdefault(f"handwriting.{key}", getattr(_DEFAULT_HANDWRITING, key))
    font_path = "font/AnJingChenYingBiXingShu-2.ttf"
    if (PROJECT_ROOT / font_path).is_file():
        # Each font preset owns these fields so switching away restores the
        # appropriate renderer instead of inheriting a previous font's settings.
        font_fields = {
            "font_path": font_path,
            "latin_font_path": "font/Latin-Caveat-Regular.ttf",
            "math_font_path": "font/Latin-Caveat-Regular.ttf",
            "math_wrap_long": True,
            "math_match_body_ink": True,
            "math_character_rotation_deg": 1.3,
            "math_font_pt": 20.0,
            "math_display_left_aligned": True,
            "math_inline_scale": 1.15,
            "math_stroke_weight_scale": 1.0,
            "math_jitter_scale": 0.55,
            "fallback_font_path": None,
            "sdt_trajectory_enabled": False,
            "sdt_trajectory_path": None,
            "reference_glyph_path": None,
            "uniform_ink_enabled": True,
            "uniform_table_ink": True,
            "handwritten_digit_one": True,
            "handwritten_punctuation": True,
            "preserve_chinese_punctuation": True,
            "correction_probability": 0.0,
        }
        presets["anjingchen"] = {
            **{key: getattr(_DEFAULT_HANDWRITING, key.split(".", 1)[1])
               for key in presets.get("personal_v6", {})},
            **STYLE_PRESETS["formal"],
            **{f"handwriting.{key}": value for key, value in font_fields.items()},
        }
        for name in ("formal", "personal_v6"):
            if name in presets:
                for key in font_fields:
                    presets[name].setdefault(f"handwriting.{key}", getattr(_DEFAULT_HANDWRITING, key))
    shaohua_path = "font/PingFangShaoHuaTi-2.ttf"
    if (PROJECT_ROOT / shaohua_path).is_file():
        # Start from a complete font preset so switching fonts also resets
        # formula and trajectory settings inherited from the previous choice.
        fields = dict(presets.get("anjingchen", presets["formal"]))
        fields.update({
            "handwriting.font_path": shaohua_path,
            "handwriting.latin_font_path": "font/Latin-Caveat-Regular.ttf",
            "handwriting.math_font_path": "font/Latin-Caveat-Regular.ttf",
            "handwriting.math_wrap_long": True,
            "handwriting.math_match_body_ink": False,
            "handwriting.math_character_rotation_deg": 0.0,
            "handwriting.math_font_pt": 18.0,
            "handwriting.math_display_left_aligned": False,
            "handwriting.math_inline_scale": 1.1,
            "handwriting.math_stroke_weight_scale": 1.0,
            "handwriting.fallback_font_path": None,
            "handwriting.sdt_trajectory_enabled": False,
            "handwriting.sdt_trajectory_path": None,
            "handwriting.reference_glyph_path": None,
            "handwriting.uniform_ink_enabled": True,
            "handwriting.handwritten_digit_one": True,
            "handwriting.legible_decimal_point": True,
            "handwriting.uniform_table_ink": True,
            "handwriting.ink_density_jitter": 0.0,
            "handwriting.dry_brush_probability": 0.0,
            "handwriting.stroke_weight_variation_sigma_ratio": 0.0,
            "handwriting.handwritten_punctuation": False,
            "handwriting.preserve_chinese_punctuation": True,
        })
        presets["shaohua"] = fields
        for name, preset in presets.items():
            if name != "shaohua":
                for key in fields:
                    preset.setdefault(key, getattr(_DEFAULT_HANDWRITING, key.split(".", 1)[1]))
    for preset_name, english_path in (("caveat", "font/Latin-Caveat-Regular.ttf"),
                                      ("kalam", "font/Latin-Kalam-Regular.ttf")):
        if not (PROJECT_ROOT / english_path).is_file():
            continue
        # An English-first preset uses the same face for body and math, with
        # a bundled CJK font available when mixed-language text is supplied.
        fields = dict(presets.get("shaohua", presets.get("anjingchen", presets["formal"])))
        fields.update({
            "handwriting.font_path": english_path,
            "handwriting.latin_font_path": english_path,
            "handwriting.math_font_path": english_path,
            "handwriting.fallback_font_path": "font/1_SDT.ttf",
            "handwriting.latin_upright_correction_deg": 0.0,
            "handwriting.sdt_trajectory_enabled": False,
            "handwriting.sdt_trajectory_path": None,
            "handwriting.reference_glyph_path": None,
            "handwriting.uniform_ink_enabled": False,
            "handwriting.uniform_table_ink": True,
            "handwriting.handwritten_digit_one": True,
            "handwriting.latin_word_corrections": True,
            "handwriting.legible_decimal_point": True,
            "handwriting.handwritten_punctuation": False,
            "handwriting.preserve_chinese_punctuation": True,
            "handwriting.second_layer_enabled": False,
            "handwriting.correction_probability": 0.0,
            "handwriting.math_wrap_long": True,
            "handwriting.math_match_body_ink": True,
            "handwriting.math_character_rotation_deg": 0.0,
            "handwriting.math_font_pt": 18.0,
            "handwriting.math_display_left_aligned": False,
            "handwriting.math_inline_scale": 1.1,
            "handwriting.math_stroke_weight_scale": 1.0,
        })
        if preset_name == "caveat":
            fields["handwriting.math_stroke_weight_scale"] = 1.25
        presets[preset_name] = fields
        for name, preset in presets.items():
            if name != preset_name:
                for key in fields:
                    preset.setdefault(key, getattr(_DEFAULT_HANDWRITING, key.split(".", 1)[1]))
    v3_config = PROJECT_ROOT / "configs" / "personal_v3_uniform_test.json"
    v3_assets = ("font_library/personal_v3_uniform/glyphs", "font_library/personal_v3_uniform/fallback_trajectories.zip",
                 "font_library/personal_v3_corrections", "font/AnJingChenYingBiXingShu-2.ttf",
                 "font/1_SDT.ttf", "font/Latin-Caveat-Regular.ttf")
    if v3_config.is_file() and all((PROJECT_ROOT / path).exists() for path in v3_assets):
        handwriting = json.loads(v3_config.read_text(encoding="utf-8"))["handwriting"]
        keys = {key for preset in presets.values() for key in preset if key.startswith("handwriting.")}
        keys.update(f"handwriting.{key}" for key in handwriting)
        fields = {key: getattr(_DEFAULT_HANDWRITING, key.split(".", 1)[1]) for key in keys}
        fields.update({f"handwriting.{key}": value for key, value in handwriting.items()})
        presets["moxu"] = fields
        for name, preset in presets.items():
            if name != "moxu":
                for key in handwriting:
                    preset.setdefault(f"handwriting.{key}", getattr(_DEFAULT_HANDWRITING, key))
    return presets


def build_bootstrap() -> dict[str, Any]:
    return {
        "scanCapabilities": {"invert": True},
        "config": asdict(ReportConfig()),
        "sections": CONFIG_SECTIONS,
        "presets": _font_presets(),
        "assets": available_assets(),
        "examples": available_examples(),
    }


def validate_config(config: ReportConfig) -> None:
    validate_layout_options(config)
    if not 0.0 <= config.handwriting.latin_upright_correction_deg <= 10.0:
        raise ValueError("英文倾斜回正必须在 0 到 10 度之间。")
    if not 0.0 <= config.handwriting.cjk_latin_spacing_em <= 0.25:
        raise ValueError("中英文衔接留白必须在 0 到 0.25 em 之间。")
    if not 4.0 <= config.handwriting.sdt_stroke_width <= 32.0:
        raise ValueError("SDT 统一笔画粗细必须在 4 到 32 之间。")
    if not 1 <= config.handwriting.sdt_supersample <= 8:
        raise ValueError("SDT 抗锯齿采样必须在 1 到 8 之间。")
    if not 0.25 <= config.handwriting.stroke_weight_base_scale <= 3.0:
        raise ValueError("基础字重倍率必须在 0.25 到 3.0 之间。")
    if not 0.0 <= config.handwriting.stroke_weight_variation_sigma_ratio <= 0.1:
        raise ValueError("整体粗细扰动 σ 必须在 0 到 0.1 em 之间。")
    if not 0.0 <= config.handwriting.math_perturb_y_sigma_ratio <= 0.25:
        raise ValueError("公式字符垂直偏移 σ 必须在 0 到 0.25 em 之间。")
    if not 0.0 <= config.handwriting.math_jitter_scale <= 1.0:
        raise ValueError("公式扰动强度必须在 0 到 1 之间。")
    if not 72 <= config.page.dpi <= 1200:
        raise ValueError("DPI 必须在 72 到 1200 之间。")
    if config.page.width_mm <= 0 or config.page.height_mm <= 0:
        raise ValueError("页面宽高必须大于 0。")
    if config.page.margin_left_mm + config.page.margin_right_mm >= config.page.width_mm:
        raise ValueError("左右边距之和不能超过页面宽度。")
    if config.page.margin_top_mm + config.page.margin_bottom_mm >= config.page.height_mm:
        raise ValueError("上下边距之和不能超过页面高度。")
    if config.background.style not in {"plain", "lined", "grid", "dot", "image"}:
        raise ValueError("不支持的背景样式。")
    for value in (
        config.background.paper_color,
        config.background.line_color,
        config.background.margin_line_color,
        config.handwriting.ink_color,
    ):
        ImageColor.getrgb(value)
    for path in _config_paths(config):
        section_name, field_name = path.split(".", 1)
        value = getattr(getattr(config, section_name), field_name)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"参数 {path} 不是有限数值。")


class RenderBusyError(RuntimeError):
    pass


def _save_page_images(pages: list[Image.Image], output: Path, *, page_pngs: list[bytes] | None = None) -> Path:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, page in enumerate(pages, start=1):
            name = f"handwritten-page-{index:03d}.png"
            if page_pngs is None:
                with archive.open(zipfile.ZipInfo(name), "w") as target, page.convert("RGB") as rgb:
                    rgb.save(target, format="PNG", compress_level=3)
            else:
                archive.writestr(name, page_pngs[index - 1], compress_type=zipfile.ZIP_STORED)
    return output


def _formula_warnings(markdown: str, warning: dict[str, str]) -> list[dict[str, Any]]:
    formula = warning["formula"]
    error = warning["error"]
    target = formula.strip()
    positions: list[int] = []
    if target:
        offset = 0
        while (position := markdown.find(target, offset)) >= 0:
            positions.append(position)
            offset = position + len(target)
    lines = list(dict.fromkeys(markdown.count("\n", 0, position) + 1 for position in positions)) or [None]
    unsupported = re.match(r"Unsupported command: (\\[A-Za-z]+)", error)
    if unsupported:
        detail = f"公式不支持命令 {unsupported.group(1)}"
    else:
        detail = f"公式无法完整渲染：{error}"
    return [
        {
            "line": line,
            "formula": formula,
            "message": f"第 {line} 行{detail}。" if line is not None else f"{detail}。",
        }
        for line in lines
    ]


class RenderService:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.output_root = output_root
        self.lock = threading.Lock()

    def render(self, markdown: str, config_data: dict[str, Any]) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise RenderBusyError("已有文档正在生成，请稍候。")
        created_job_root = None
        page_temp = None
        try:
            config = config_from_dict(config_data)
            validate_config(config)
            blocks = parse_markdown(markdown)
            page_temp = tempfile.TemporaryDirectory(prefix="miaobi-pages-")
            renderer = ReportRenderer(config, base_dir=PROJECT_ROOT, page_store_dir=Path(page_temp.name))
            pages = renderer.render(blocks)
            warnings = [
                item
                for warning in renderer.warnings
                for item in _formula_warnings(markdown, warning)
            ]

            job_id = secrets.token_hex(8)
            job_root = self.output_root / job_id
            job_root.mkdir(parents=True, exist_ok=False)
            created_job_root = job_root
            image_path = _save_page_images(pages, job_root / "handwritten-pages.zip")
            pdf_path = renderer.save_pdf(job_root / "markdown-to-handwrite.pdf", page_png_archive=image_path)
            docx_path = export_pages_as_docx(
                pages,
                job_root / "markdown-to-handwrite.docx",
                config.page.width_mm,
                config.page.height_mm,
                page_png_archive=image_path,
            )
            (job_root / "metadata.json").write_text(
                json.dumps({
                    "page_width_mm": config.page.width_mm,
                    "page_height_mm": config.page.height_mm,
                    "page_count": len(pages),
                    "paper_color": config.background.paper_color,
                    "handwriting": asdict(config.handwriting),
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            preview_urls = []
            for index, page in enumerate(pages, start=1):
                preview = page.convert("RGB")
                preview.thumbnail((1280, 1810), resample=Image.Resampling.LANCZOS)
                preview_name = f"page-{index}.webp"
                preview.save(job_root / preview_name, "WEBP", quality=90, method=4)
                preview_urls.append(f"/output/{job_id}/{preview_name}")
            return {
                "jobId": job_id,
                "pageCount": len(pages),
                "pages": preview_urls,
                "pdf": f"/output/{job_id}/{pdf_path.name}",
                "docx": f"/output/{job_id}/{docx_path.name}",
                "image": f"/output/{job_id}/{image_path.name}",
                "warnings": warnings,
            }
        except Exception:
            if created_job_root is not None:
                shutil.rmtree(created_job_root, ignore_errors=True)
            raise
        finally:
            try:
                if page_temp is not None:
                    page_temp.cleanup()
            finally:
                self.lock.release()

    def edit_pages(self, job_id: str, edit_data: Any) -> dict[str, Any]:
        if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{16}", job_id):
            raise ValueError("手稿任务不存在，请重新生成页面。")
        if not self.lock.acquire(blocking=False):
            raise RenderBusyError("已有文档正在生成，请稍候。")
        page_temp = None
        try:
            job_root = _safe_child(self.output_root, job_id)
            if job_root is None or not job_root.is_dir():
                raise ValueError("手稿任务不存在，请重新生成页面。")
            metadata_path = job_root / "metadata.json"
            source_docx = job_root / "markdown-to-handwrite.docx"
            if not metadata_path.is_file() or not source_docx.is_file():
                raise ValueError("手稿原始页面不存在，请重新生成页面。")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            page_count = int(metadata["page_count"])
            edits = normalize_page_edits(edit_data, page_count)

            edit_config = config_from_dict({"handwriting": metadata.get("handwriting", {})})
            handwriting = edit_config.handwriting
            page_temp = tempfile.TemporaryDirectory(prefix="miaobi-edits-")
            pages = DiskPages(Path(page_temp.name))
            revision = secrets.token_hex(4)
            page_urls = []
            export_page_urls = []
            comment_images = []
            with zipfile.ZipFile(source_docx) as package:
                for index, item in enumerate(edits, start=1):
                    try:
                        with package.open(f"word/media/page-{index}.png") as image:
                            source = Image.open(image).convert("RGB")
                    except (KeyError, OSError, zipfile.BadZipFile) as error:
                        raise ValueError("手稿原始页面无法读取，请重新生成页面。") from error
                    page = apply_page_edits(source, item, handwriting)
                    preview = apply_page_edits(source, {**item, "marks": []}, handwriting)
                    preview.thumbnail((1280, 1810), resample=Image.Resampling.LANCZOS)
                    preview_name = f"page-{index}-preview.webp"
                    preview.save(job_root / preview_name, "WEBP", quality=90, method=4)
                    page_urls.append(f"/output/{job_id}/{preview_name}?v={revision}")
                    export_preview = page.copy()
                    export_preview.thumbnail((1280, 1810), resample=Image.Resampling.LANCZOS)
                    export_name = f"page-{index}-export.webp"
                    export_preview.save(job_root / export_name, "WEBP", quality=90, method=4)
                    export_page_urls.append(f"/output/{job_id}/{export_name}?v={revision}")
                    entries = {}
                    for mark_index, mark in enumerate(item["marks"]):
                        if mark["kind"] == "comment":
                            bitmap = comment_image(source, mark, handwriting)
                            buffer = io.BytesIO()
                            bitmap.save(buffer, format="PNG")
                            entries[str(mark_index)] = {
                                "url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
                                "width": bitmap.width / source.width, "height": bitmap.height / source.height,
                            }
                    comment_images.append(entries)
                    pages.append(page)
                    pages.spill()
                    source.close()
                    preview.close()
                    export_preview.close()
            width_mm = float(metadata["page_width_mm"])
            height_mm = float(metadata["page_height_mm"])
            image_path = _save_page_images(pages, job_root / "handwritten-pages.zip")
            pdf_path = save_pages_pdf(pages, job_root / "markdown-to-handwrite.pdf", width_mm, height_mm,
                                      page_png_archive=image_path)
            is_edited = any(item["rotation"] or item["crop"] is not None or item["marks"] for item in edits)
            edited_docx = job_root / "markdown-to-handwrite-edited.docx"
            if is_edited:
                docx_path = export_pages_as_docx(pages, edited_docx, width_mm, height_mm, page_png_archive=image_path)
            else:
                edited_docx.unlink(missing_ok=True)
                docx_path = source_docx
            return {
                "jobId": job_id,
                "pageCount": page_count,
                "commentImages": comment_images,
                "pages": page_urls,
                "exportPages": export_page_urls,
                "pdf": f"/output/{job_id}/{pdf_path.name}?v={revision}",
                "docx": f"/output/{job_id}/{docx_path.name}?v={revision}",
                "image": f"/output/{job_id}/{image_path.name}?v={revision}",
            }
        finally:
            try:
                if page_temp is not None:
                    page_temp.cleanup()
            finally:
                self.lock.release()


def _safe_child(root: Path, relative: str) -> Path | None:
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root.resolve())
        return candidate
    except (OSError, ValueError):
        return None


class WebApp:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.csrf_token = secrets.token_urlsafe(32)
        self.render_service = RenderService(output_root)
        self.scan_service = ScanService(output_root / "scans")

    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HandwrittenReport/0.2"

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(30)

            def do_GET(self) -> None:  # noqa: N802
                if not self._valid_request():
                    return
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                if path == "/api/health":
                    self._send_json({"status": "ok"})
                elif path == "/api/bootstrap":
                    self._send_json({**build_bootstrap(), "csrfToken": app.csrf_token})
                elif path.startswith("/api/examples/"):
                    self._serve_example(path.removeprefix("/api/examples/"))
                elif path.startswith("/output/"):
                    self._serve_output(path.removeprefix("/output/"))
                elif path == "/paper/red-lined.png":
                    paper = PROJECT_ROOT / "background" / "提取的红线纸.png"
                    if paper.is_file():
                        self._send_bytes(paper.read_bytes(), "image/png")
                    else:
                        self._send_json({"error": "横线纸背景不存在。"}, HTTPStatus.NOT_FOUND)
                elif path == "/paper/green-lined.png":
                    paper = PROJECT_ROOT / "background" / "提取的绿线纸.png"
                    if paper.is_file():
                        self._send_bytes(paper.read_bytes(), "image/png")
                    else:
                        self._send_json({"error": "绿线纸背景不存在。"}, HTTPStatus.NOT_FOUND)
                elif path == "/handwriting-font.ttf":
                    font = PROJECT_ROOT / "font" / "1_SDT.ttf"
                    if font.is_file():
                        self._send_bytes(font.read_bytes(), "font/ttf")
                    else:
                        self._send_json({"error": "字体不存在。"}, HTTPStatus.NOT_FOUND)
                else:
                    self._serve_static("index.html" if path in {"/", ""} else path.lstrip("/"))

            def do_POST(self) -> None:  # noqa: N802
                if not self._valid_request():
                    return
                token = self.headers.get("X-Miaobi-Token", "")
                if not token.isascii() or not secrets.compare_digest(token, app.csrf_token):
                    self._send_json({"error": "会话已过期，请刷新页面。"}, HTTPStatus.FORBIDDEN)
                    return
                if self.headers.get_content_type() != "application/json":
                    self._send_json({"error": "请求必须使用 JSON 格式。"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                    return
                path = urlparse(self.path).path
                if path == "/api/background/upload":
                    try:
                        payload = self._read_json()
                        encoded = payload.get("data")
                        if not isinstance(encoded, str) or not encoded:
                            raise ValueError("请选择背景图片。")
                        data = base64.b64decode(encoded, validate=True)
                        if len(data) > 5 * 1024 * 1024:
                            raise ValueError("背景图片不能超过 5 MB。")
                        with Image.open(io.BytesIO(data)) as source:
                            if source.format not in {"PNG", "JPEG", "WEBP"} or source.width * source.height > 40_000_000:
                                raise ValueError("请选择不超过 4000 万像素的 PNG、JPG 或 WebP 图片。")
                            image = source.convert("RGBA")
                            canvas_image = Image.new("RGBA", image.size, "white")
                            canvas_image.alpha_composite(image)
                            folder = app.render_service.output_root / "backgrounds"
                            folder.mkdir(parents=True, exist_ok=True)
                            target = folder / f"{secrets.token_hex(12)}.png"
                            canvas_image.convert("RGB").save(target, "PNG")
                        self._send_json({"path": str(target.resolve()), "url": f"/output/backgrounds/{target.name}"})
                    except (ValueError, TypeError, OSError, binascii.Error, Image.DecompressionBombError) as error:
                        self._send_json({"error": str(error) or "背景图片无法读取。"}, HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/scan/upload":
                    try:
                        payload = self._read_json(MAX_SCAN_REQUEST_BYTES)
                        filename = payload.get("filename", "")
                        encoded = payload.get("data", "")
                        if not isinstance(filename, str) or not isinstance(encoded, str) or not encoded:
                            raise ValueError("没有收到图片内容。")
                        try:
                            image_data = base64.b64decode(encoded, validate=True)
                        except (binascii.Error, ValueError) as error:
                            raise ValueError("图片数据无法读取。") from error
                        if len(image_data) > MAX_SCAN_BYTES:
                            raise ValueError("单张图片不能超过 18 MB。")
                        self._send_json(app.scan_service.upload(filename, image_data))
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:  # pragma: no cover - final HTTP boundary
                        print(f"[web-scan-upload-error] {error}")
                        self._send_json({"error": "图片扫描失败，请检查图片后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path in {"/api/scan/process", "/api/scan/filter-preview"}:
                    try:
                        payload = self._read_json()
                        scan_id = validate_scan_id(payload.get("scanId", ""))
                        options = {
                            "mode": payload.get("mode", "smart"),
                            "orientation": payload.get("orientation", "auto"),
                            "rotation": payload.get("rotation", 0),
                            "crop": payload.get("crop"),
                            "corners": payload.get("corners"),
                        }
                        if path == "/api/scan/filter-preview":
                            self._send_json(app.scan_service.filter_preview(scan_id, options))
                        else:
                            self._send_json(app.scan_service.process(scan_id, options))
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:  # pragma: no cover - final HTTP boundary
                        print(f"[web-scan-process-error] {error}")
                        self._send_json({"error": "图片增强失败，请调整扫描选项后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path == "/api/scan/restore-preview":
                    try:
                        payload = self._read_json()
                        self._send_json(app.scan_service.restoration_preview(payload.get("scanId", ""), payload.get("marks", [])))
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:
                        print(f"[web-scan-restore-error] {error}")
                        self._send_json({"error": "恢复预览失败，请稍后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path == "/api/scan/export":
                    try:
                        payload = self._read_json()
                        self._send_json(app.scan_service.export(payload.get("scanIds"), payload.get("format", "pdf"), payload.get("edits")))
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:  # pragma: no cover - final HTTP boundary
                        print(f"[web-scan-export-error] {error}")
                        self._send_json({"error": "扫描文件导出失败，请稍后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path == "/api/import-docx":
                    try:
                        payload = self._read_json()
                        filename = payload.get("filename", "")
                        encoded = payload.get("data", "")
                        if not isinstance(filename, str) or not filename.lower().endswith(".docx"):
                            raise ValueError("请选择 DOCX 格式的 Word 文档。")
                        if not isinstance(encoded, str) or not encoded:
                            raise ValueError("没有收到 DOCX 文件内容。")
                        try:
                            data = base64.b64decode(encoded, validate=True)
                        except (binascii.Error, ValueError) as error:
                            raise ValueError("DOCX 文件数据无法读取。") from error
                        if len(data) > MAX_DOCX_BYTES:
                            raise ValueError("DOCX 文件不能超过 5 MB。")
                        imported = import_docx_bytes(data)
                        self._send_json({"markdown": imported.markdown, "warnings": imported.warnings})
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:  # pragma: no cover - final HTTP boundary
                        print(f"[web-import-error] {error}")
                        self._send_json({"error": "Word 文档导入失败，请确认文件没有损坏。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path == "/api/edit":
                    try:
                        payload = self._read_json()
                        result = app.render_service.edit_pages(payload.get("jobId", ""), payload.get("edits"))
                        self._send_json(result)
                    except RenderBusyError as error:
                        self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                    except (TypeError, ValueError, KeyError, OSError) as error:
                        self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                    except Exception as error:  # pragma: no cover - final HTTP boundary
                        print(f"[web-edit-error] {error}")
                        self._send_json({"error": "页面编辑失败，请重新生成手稿后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if path != "/api/render":
                    self._send_json({"error": "接口不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    payload = self._read_json()
                    markdown = payload.get("markdown", "")
                    if not isinstance(markdown, str) or not markdown.strip():
                        raise ValueError("请输入要生成的 Markdown 内容。")
                    result = app.render_service.render(markdown, payload.get("config", {}))
                    self._send_json(result)
                except RenderBusyError as error:
                    self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                except (TypeError, ValueError, KeyError, OSError) as error:
                    self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                except Exception as error:  # pragma: no cover - final HTTP boundary
                    print(f"[web-render-error] {error}")
                    self._send_json({"error": "生成失败，请检查内容、字体和背景配置。"}, HTTPStatus.INTERNAL_SERVER_ERROR)

            def _read_json(self, maximum_bytes: int = MAX_REQUEST_BYTES) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > maximum_bytes:
                    raise ValueError(f"请求内容为空或超过 {maximum_bytes // (1024 * 1024)} MB。")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是 JSON 对象。")
                return payload

            def _valid_request(self) -> bool:
                host = self.headers.get("Host", "")
                address, port = self.server.server_address[:2]
                allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
                local_address = self.connection.getsockname()[0]
                allowed.add(f"{local_address}:{port}")
                if address not in {"0.0.0.0", "::"}:
                    allowed.add(f"{address}:{port}")
                origin = self.headers.get("Origin")
                if host.lower() not in allowed or (origin is not None and origin != f"http://{host}"):
                    self._send_json({"error": "请求来源无效。"}, HTTPStatus.FORBIDDEN)
                    return False
                return True

            def _serve_example(self, name: str) -> None:
                path = _safe_child(PROJECT_ROOT / "examples", name)
                if path is None or path.suffix.lower() != ".md" or not path.is_file():
                    self._send_json({"error": "示例不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes(path.read_bytes(), "text/markdown; charset=utf-8")

            def _serve_output(self, relative: str) -> None:
                path = _safe_child(app.render_service.output_root, relative)
                if path is None or not path.is_file():
                    self._send_json({"error": "文件不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                headers = {}
                if path.suffix.lower() == ".pdf":
                    if relative.startswith("scans/exports/"):
                        headers["Content-Disposition"] = "attachment; filename=\"smart-scan-result.pdf\"; filename*=UTF-8''%E6%99%BA%E8%83%BD%E6%89%AB%E6%8F%8F%E7%BB%93%E6%9E%9C.pdf"
                    else:
                        headers["Content-Disposition"] = 'attachment; filename="markdown-to-handwrite.pdf"'
                elif path.suffix.lower() == ".docx":
                    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if relative.startswith("scans/exports/"):
                        headers["Content-Disposition"] = "attachment; filename=\"smart-scan-result.docx\"; filename*=UTF-8''%E6%99%BA%E8%83%BD%E6%89%AB%E6%8F%8F%E7%BB%93%E6%9E%9C.docx"
                    else:
                        headers["Content-Disposition"] = 'attachment; filename="markdown-to-handwrite.docx"'
                self._send_bytes(path.read_bytes(), content_type, headers)

            def _serve_static(self, relative: str) -> None:
                path = _safe_child(STATIC_ROOT, relative)
                if path is None or not path.is_file():
                    self._send_json({"error": "页面不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._send_bytes(path.read_bytes(), content_type)

            def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8", status=status)

            def _send_bytes(
                self,
                body: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
                status: HTTPStatus = HTTPStatus.OK,
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string: str, *args: object) -> None:
                if sys.stdout is not None:
                    print(f"[web] {self.address_string()} - {format_string % args}")

        return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the MarkdownToHandwrite WebUI.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the UI in the default browser.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        is_loopback = args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise SystemExit("为保护文稿和本机文件，服务仅允许监听本机地址。")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    app = WebApp()
    server = LimitedHTTPServer((args.host, args.port), app.handler_class())
    url = f"http://{args.host}:{server.server_port}"
    print(f"MarkdownToHandwrite WebUI: {url}")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWebUI stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
