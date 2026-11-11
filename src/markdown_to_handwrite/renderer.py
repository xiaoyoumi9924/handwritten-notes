from __future__ import annotations

import sys
import math
import random
import numpy as np
import cv2
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - optional until a PDF background is used
    fitz = None

from .config import ReportConfig, color, mm_to_px, pt_to_px
from .handwriting import HandwritingEngine, starts_with_forbidden_line_punctuation, wrap_text, transform_correction_marks
from .math_renderer import FormulaRenderer, LatexRenderError
from .markdown_parser import (
    Block,
    CodeBlock,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
    InlinePart,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    RuleBlock,
    TableBlock,
)
from .typography import westernize_punctuation
from .page_store import DiskPages

PROJECT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
BACKGROUND_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class _RichLine:
    visuals: list[tuple[Image.Image, int]]
    width: int
    height: int
    baseline: int
    wrapped: bool = False
    contains_math: bool = False
    font_size_px: int = 0


class ReportRenderer:
    def _punctuation(self, text: str) -> str:
        return text if self.config.handwriting.preserve_chinese_punctuation else westernize_punctuation(text)

    def __init__(self, config: ReportConfig, base_dir: str | Path = ".", *, max_total_pixels: int | None = None,
                 page_store_dir: Path | None = None):
        self.config = config
        self.max_total_pixels = max_total_pixels
        self.base_dir = Path(base_dir)
        self.dpi = config.page.dpi
        self.page_w = mm_to_px(config.page.width_mm, self.dpi)
        self.page_h = mm_to_px(config.page.height_mm, self.dpi)
        self.page_w_pt = config.page.width_mm / 25.4 * 72
        self.page_h_pt = config.page.height_mm / 25.4 * 72
        self.margin_left = mm_to_px(config.page.margin_left_mm, self.dpi)
        self.margin_right = mm_to_px(config.page.margin_right_mm, self.dpi)
        self.margin_top = mm_to_px(config.page.margin_top_mm, self.dpi)
        self.margin_bottom = mm_to_px(config.page.margin_bottom_mm, self.dpi)
        self.content_w = self.page_w - self.margin_left - self.margin_right
        footer_gap = config.layout.footer_gap_mm if config.layout.show_page_numbers else 0
        self.bottom_limit = self.page_h - self.margin_bottom - mm_to_px(footer_gap, self.dpi)
        self.background_path = self._resolve_background_path()
        self.background_pdf = self._open_background_pdf()
        self.engine = HandwritingEngine(
            config.handwriting,
            reference_size_px=pt_to_px(config.handwriting.body_font_pt, self.dpi),
            math_reference_size_px=pt_to_px(config.handwriting.math_font_pt, self.dpi),
        )
        self.formula_renderer = FormulaRenderer(self.engine, seed=config.handwriting.seed)
        self.pages = DiskPages(page_store_dir) if page_store_dir is not None else []
        self._page_rules: list[list[int]] = []
        self._pending_corrections: list[tuple[int, dict]] = []
        self._placed_corrections: list[dict] = []
        self.warnings: list[dict[str, str]] = []
        self._reported_formula_errors: set[tuple[str, str]] = set()
        self.page: Image.Image
        self.draw: ImageDraw.ImageDraw
        self.y = self.margin_top
        self.section_counters = [0, 0, 0, 0, 0, 0]
        self.figure_counter = 0
        self._new_page()

    def render(self, blocks: list[Block]) -> list[Image.Image]:
        self.warnings.clear()
        self._reported_formula_errors.clear()
        page_break_pending = False
        prepared_formula_images: dict[int, Image.Image] = {}
        skipped_formula_indices: set[int] = set()
        for index, block in enumerate(blocks):
            if index in skipped_formula_indices:
                continue
            if isinstance(block, PageBreakBlock):
                page_break_pending = True
                continue
            if page_break_pending:
                if self.y > self.margin_top:
                    self._new_page()
                page_break_pending = False
            if isinstance(block, HeadingBlock):
                self._draw_heading(
                    block,
                    trailing_height=self._estimate_heading_following_height(blocks, index),
                )
            elif isinstance(block, ParagraphBlock):
                formula_indices: list[int] = []
                next_index = index + 1
                while next_index < len(blocks) and isinstance(blocks[next_index], FormulaBlock):
                    formula_indices.append(next_index)
                    next_index += 1
                if formula_indices:
                    for formula_index in formula_indices:
                        formula_block = blocks[formula_index]
                        assert isinstance(formula_block, FormulaBlock)
                        prepared_formula_images[formula_index] = self._render_formula_image(
                            formula_block.text,
                            seed_extra=f"paragraph-following-formula:{formula_index}",
                        )
                    self._draw_rich_paragraph(
                        block.parts,
                        no_indent=block.no_indent,
                        trailing_height=sum(
                            self._formula_height(prepared_formula_images[formula_index])
                            for formula_index in (formula_indices[:1] if self._paper_rules else formula_indices)
                        ),
                    )
                else:
                    self._draw_rich_paragraph(block.parts, no_indent=block.no_indent)
            elif isinstance(block, FormulaBlock):
                formula_indices = [index]
                next_index = index + 1
                while next_index < len(blocks) and isinstance(blocks[next_index], FormulaBlock):
                    formula_indices.append(next_index)
                    next_index += 1
                images: dict[int, Image.Image] = {}
                for formula_index in formula_indices:
                    formula_block = blocks[formula_index]
                    assert isinstance(formula_block, FormulaBlock)
                    if formula_index in prepared_formula_images:
                        images[formula_index] = prepared_formula_images.pop(formula_index)
                    else:
                        images[formula_index] = self._render_formula_image(
                            formula_block.text,
                            seed_extra=f"formula-sequence:{formula_index}",
                        )
                sequence_height = sum(self._formula_height(images[item]) for item in formula_indices)
                page_capacity = self.bottom_limit - self.margin_top
                if not self._paper_rules and sequence_height <= page_capacity and self.y + sequence_height > self.bottom_limit:
                    self._new_page()
                for formula_index in formula_indices:
                    formula_block = blocks[formula_index]
                    assert isinstance(formula_block, FormulaBlock)
                    self._draw_formula(formula_block.text, image=images[formula_index])
                    if formula_index != index:
                        skipped_formula_indices.add(formula_index)
            elif isinstance(block, TableBlock):
                self._draw_table(block)
            elif isinstance(block, ImageBlock):
                self._draw_image_placeholder(block)
            elif isinstance(block, ListBlock):
                self._draw_list(block)
            elif isinstance(block, CodeBlock):
                self._draw_code(block)
            elif isinstance(block, RuleBlock):
                self._draw_rule()
        if self.config.layout.show_page_numbers:
            if isinstance(self.pages, DiskPages):
                self.pages.spill()
            self._draw_footers()
        elif isinstance(self.pages, DiskPages):
            self.pages.spill()
        self._draw_pending_corrections()
        return self.pages

    def save_pdf(self, output_path: str | Path, *, page_png_archive: str | Path | None = None) -> Path:
        from .page_edits import save_pages_pdf
        return save_pages_pdf(self.pages, output_path, self.config.page.width_mm, self.config.page.height_mm,
                              page_png_archive=page_png_archive)

    def _new_page(self) -> None:
        if self.max_total_pixels is not None and (len(self.pages) + 1) * self.page_w * self.page_h > self.max_total_pixels:
            raise ValueError("文稿页数或分辨率过大，请分段生成或降低 DPI。")
        if isinstance(self.pages, DiskPages):
            self.pages.spill()
        self.page = self._make_background()
        self.draw = ImageDraw.Draw(self.page)
        self.pages.append(self.page)
        self.y = self.margin_top
        self._paper_rules = self._detect_paper_rules()
        self._page_rules.append(list(self._paper_rules))
        self._last_paper_rule = -1
        self._last_rule_flow_end = self.margin_top

    def _detect_paper_rules(self) -> list[int]:
        if not self.background_path:
            if self.config.background.style == "lined":
                gap = max(1, mm_to_px(self.config.background.line_gap_mm, self.dpi))
                return list(range(self.margin_top, self.page_h - self.margin_bottom + 1, gap))
            return []
        # Detect colored horizontal rules on photographed paper. Keep the full
        # vertical resolution so positioning respects slightly irregular spacing.
        sample = self.page.convert("RGB").resize((384, self.page_h))
        pixels = np.asarray(sample, dtype=np.int16)[:, 38:-38]
        chroma = pixels.max(axis=2) - pixels.min(axis=2)
        rows = np.flatnonzero(((chroma > 36) & (pixels.min(axis=2) < 210)).mean(axis=1) > .45)
        if np.count_nonzero(np.diff(rows) > 1) < 3:
            # Some green paper assets have gray interior rules. Detect their
            # horizontal luminance dips against the local paper tone.
            tone = np.median(pixels.mean(axis=2), axis=1)
            window = max(5, mm_to_px(3, self.dpi) | 1)
            local = np.median(np.lib.stride_tricks.sliding_window_view(
                np.pad(tone, (window // 2, window // 2), mode="edge"), window), axis=1)
            rows = np.flatnonzero((local - tone > 5) & (np.arange(self.page_h) > self.page_h * .05))
        if not len(rows):
            return []
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
        rules = [int(group[0]) for group in groups]
        if len(rules) < 4:
            return []
        gaps = np.diff(rules)
        median = float(np.median(gaps))
        if median < mm_to_px(3, self.dpi) or np.mean(abs(gaps - median) < median * .2) < .8:
            return []
        return rules

    def _paper_rule_placement(self, line: _RichLine, y: int, last_rule: int, last_flow_end: int) -> tuple[int, int, int] | None:
        if not self._paper_rules or not line.visuals:
            return (y, last_rule, y + line.height)
        tops = [image.info.get("layout_ink_top", 0) + line.baseline - baseline
                for image, baseline in line.visuals]
        bottoms = [image.info.get("layout_ink_bottom", image.height) + line.baseline - baseline
                   for image, baseline in line.visuals]
        pitch = float(np.median(np.diff(self._paper_rules)))
        size = line.font_size_px or pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        gap = max(2, mm_to_px(.65, self.dpi))
        descent = max(round(size * .20), max(bottoms) - line.baseline)
        consecutive = last_rule >= 0 and y <= last_flow_end + pitch * .6
        start = max(1, last_rule + 1) if consecutive else 1
        for index in range(start, len(self._paper_rules)):
            baseline = self._paper_rules[index] - gap - descent
            origin = baseline - line.baseline
            if not consecutive and baseline < y + size * .8:
                continue
            previous = self._paper_rules[last_rule] if last_rule >= 0 else self._paper_rules[0]
            if origin + min(tops) < previous + gap:
                continue
            # The nominal line box includes leading below the visible ink.
            # Only the ink needs to fit inside the writable area.
            if origin + max(bottoms) > self.bottom_limit:
                break
            return origin, index, origin + line.height
        return None

    def _position_on_paper_rule(self, line: _RichLine) -> bool:
        if not self._paper_rules or not line.visuals:
            return False
        placement = self._paper_rule_placement(line, self.y, self._last_paper_rule, self._last_rule_flow_end)
        if placement is None and self.y > self.margin_top:
            self._new_page()
            placement = self._paper_rule_placement(line, self.y, self._last_paper_rule, self._last_rule_flow_end)
        if placement is not None:
            self.y, self._last_paper_rule, self._last_rule_flow_end = placement
            return True
        return False

    def _paper_rule_fit_count(self, lines: list[_RichLine]) -> int:
        y, last, end = self.y, self._last_paper_rule, self._last_rule_flow_end
        for index, line in enumerate(lines):
            placement = self._paper_rule_placement(line, y, last, end)
            if placement is None:
                return index
            y, last, end = placement
            y += line.height
        return len(lines)

    def _make_background(self, page_index: int | None = None) -> Image.Image:
        bg_config = self.config.background
        if self.background_path:
            image = self._read_background_page(len(self.pages) if page_index is None else page_index)
            return ImageOps.fit(image, (self.page_w, self.page_h), method=Image.Resampling.LANCZOS).convert("RGBA")

        page = Image.new("RGBA", (self.page_w, self.page_h), color(bg_config.paper_color, 255))
        draw = ImageDraw.Draw(page)
        line_color = color(bg_config.line_color, 160)
        style = bg_config.style.lower()
        if style == "lined":
            gap = mm_to_px(bg_config.line_gap_mm, self.dpi)
            for y in range(self.margin_top, self.page_h - self.margin_bottom + 1, gap):
                draw.line((self.margin_left // 2, y, self.page_w - self.margin_right // 2, y), fill=line_color, width=1)
        elif style == "grid":
            gap = mm_to_px(bg_config.grid_size_mm, self.dpi)
            for x in range(self.margin_left // 2, self.page_w - self.margin_right // 2 + 1, gap):
                draw.line((x, self.margin_top // 2, x, self.page_h - self.margin_bottom // 2), fill=line_color, width=1)
            for y in range(self.margin_top // 2, self.page_h - self.margin_bottom // 2 + 1, gap):
                draw.line((self.margin_left // 2, y, self.page_w - self.margin_right // 2, y), fill=line_color, width=1)
        elif style == "dot":
            gap = mm_to_px(bg_config.dot_gap_mm, self.dpi)
            radius = max(1, bg_config.dot_radius_px)
            for x in range(self.margin_left // 2, self.page_w - self.margin_right // 2 + 1, gap):
                for y in range(self.margin_top // 2, self.page_h - self.margin_bottom // 2 + 1, gap):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=line_color)
        if bg_config.draw_margin_line and style in {"lined", "grid", "dot"}:
            x = self.margin_left - mm_to_px(3.0, self.dpi)
            draw.line((x, self.margin_top // 2, x, self.page_h - self.margin_bottom // 2), fill=color(bg_config.margin_line_color, 150), width=2)
        return page

    def _resolve_background_path(self) -> Path | None:
        configured = self.config.background.image
        if configured:
            path = Path(configured)
            candidates = [path] if path.is_absolute() else [
                self.base_dir / path,
                Path.cwd() / path,
                PROJECT_ROOT / path,
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()
            raise FileNotFoundError(f"Background file not found: {configured}")
        # Generated paper styles must remain authoritative. Automatic asset
        # discovery is only meaningful when the user explicitly selects the
        # image-backed paper mode.
        if self.config.background.style.lower() != "image" or not self.config.background.auto_discover:
            return None
        checked: set[Path] = set()
        for directory in (
            self.base_dir / "background",
            Path.cwd() / "background",
            PROJECT_ROOT / "background",
        ):
            resolved = directory.resolve()
            if resolved in checked or not resolved.is_dir():
                continue
            checked.add(resolved)
            assets = sorted(
                (item for item in resolved.iterdir() if item.is_file() and item.suffix.lower() in BACKGROUND_EXTENSIONS),
                key=lambda item: item.name.casefold(),
            )
            if assets:
                return assets[0]
        return None

    def _open_background_pdf(self):
        if self.background_path is None or self.background_path.suffix.lower() != ".pdf":
            return None
        if fitz is None:
            raise RuntimeError("PDF backgrounds require PyMuPDF. Install it with: python -m pip install PyMuPDF")
        document = fitz.open(str(self.background_path))
        if document.page_count < 1:
            document.close()
            raise ValueError(f"PDF background has no pages: {self.background_path}")
        return document

    def _read_background_page(self, page_index: int) -> Image.Image:
        if self.background_pdf is None:
            return Image.open(self.background_path).convert("RGB")
        source_page = self.background_pdf.load_page(page_index % self.background_pdf.page_count)
        scale = self.dpi / 72.0
        pixmap = source_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    def _ensure_space(self, height: int) -> None:
        if self.y + height > self.bottom_limit:
            self._new_page()

    def _can_split_lines(self, lines: list[_RichLine]) -> bool:
        """Split only when at least two lines remain on each side of a page break."""
        available = self.bottom_limit - self.y
        used = 0
        fitting = 0
        for line in lines:
            if used + line.height > available:
                break
            used += line.height
            fitting += 1
        return fitting >= 2 and len(lines) - fitting >= 2

    def _draw_heading(self, block: HeadingBlock, trailing_height: int = 0) -> None:
        level = min(max(block.level, 1), 6)
        parts = list(block.parts)
        if self.config.layout.number_sections and level <= 3:
            parts.insert(0, InlinePart("text", f"{self._next_section_number(level)} "))
        font_pt = {
            1: self.config.handwriting.h1_font_pt,
            2: self.config.handwriting.h2_font_pt,
            3: self.config.handwriting.h3_font_pt,
        }.get(level, self.config.handwriting.body_font_pt)
        size = pt_to_px(font_pt, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        gap_before = mm_to_px(self.config.layout.heading_gap_before_mm if self.y > self.margin_top else 0, self.dpi)
        gap_after = mm_to_px(self.config.layout.heading_gap_after_mm, self.dpi)
        lines = self._layout_rich_parts(
            parts,
            size,
            self.content_w,
            line_h,
            seed_extra=f"heading:{len(self.pages)}:{self.y}",
        )
        total_h = gap_before + sum(line.height for line in lines) + gap_after
        page_capacity = self.bottom_limit - self.margin_top
        keep_height = total_h + trailing_height
        if keep_height > page_capacity:
            keep_height = total_h
        if keep_height <= page_capacity and self.y + keep_height > self.bottom_limit:
            self._new_page()
        else:
            self._ensure_space(total_h)
        if self.y == self.margin_top:
            gap_before = 0
        self.y += gap_before
        align = "center" if level == 1 else "left"
        for line in lines:
            self._position_on_paper_rule(line)
            self._paste_rich_line(line, self.margin_left, self.y, self.content_w, align=align)
            self.y += line.height
        self.y += gap_after

    def _estimate_heading_following_height(self, blocks: list[Block], heading_index: int) -> int:
        next_index = heading_index + 1
        if next_index >= len(blocks) or isinstance(blocks[next_index], PageBreakBlock):
            return 0
        next_block = blocks[next_index]
        page_capacity = self.bottom_limit - self.margin_top
        if isinstance(next_block, FormulaBlock):
            height = 0
            first_formula_height = 0
            while next_index < len(blocks) and isinstance(blocks[next_index], FormulaBlock):
                formula = blocks[next_index]
                assert isinstance(formula, FormulaBlock)
                image = self._render_formula_image(formula.text, seed_extra=f"heading-following:{next_index}")
                formula_height = self._formula_height(image)
                if not height:
                    first_formula_height = formula_height
                height += formula_height
                next_index += 1
            return height if height <= page_capacity else first_formula_height

        height = self._estimate_block_height(next_block, f"heading-following:{next_index}")
        if isinstance(next_block, ParagraphBlock):
            full_paragraph_height = height
            formula_height = 0
            formula_index = next_index + 1
            while formula_index < len(blocks) and isinstance(blocks[formula_index], FormulaBlock):
                formula = blocks[formula_index]
                assert isinstance(formula, FormulaBlock)
                image = self._render_formula_image(formula.text, seed_extra=f"heading-following:{formula_index}")
                formula_height += self._formula_height(image)
                formula_index += 1
            if full_paragraph_height <= page_capacity and full_paragraph_height + formula_height <= page_capacity:
                height += formula_height
            elif full_paragraph_height > page_capacity:
                size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
                height = max(1, round(size * self.config.handwriting.line_spacing))
        return min(height, page_capacity)

    def _estimate_block_height(self, block: Block, seed_extra: str) -> int:
        if isinstance(block, ParagraphBlock):
            size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
            line_h = round(size * self.config.handwriting.line_spacing)
            indent = 0 if block.no_indent else round(size * self.config.layout.first_line_indent_em)
            lines = self._layout_rich_parts(
                block.parts,
                size,
                self.content_w,
                line_h,
                seed_extra=seed_extra,
                first_line_width=max(1, self.content_w - indent),
            )
            return sum(line.height for line in lines) + mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        if isinstance(block, FormulaBlock):
            image = self._render_formula_image(block.text, seed_extra=seed_extra)
            return self._formula_height(image)
        if isinstance(block, ListBlock):
            if not block.items:
                return 0
            size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
            line_h = round(size * self.config.handwriting.line_spacing)
            indent = mm_to_px(self.config.layout.list_indent_mm, self.dpi)
            lines = self._layout_rich_parts(
                block.items[0], size, self.content_w - indent, line_h, seed_extra=seed_extra,
            )
            return sum(line.height for line in lines)
        if isinstance(block, TableBlock):
            if not block.headers and not block.rows:
                return 0
            size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
            line_h = round(size * self.config.handwriting.line_spacing)
            pad = mm_to_px(self.config.layout.table_cell_padding_mm, self.dpi)
            col_count = max(len(block.headers), *(len(row) for row in block.rows)) if block.rows else len(block.headers)
            widths = self._table_widths(block, col_count, size)
            height = 0
            if block.headers:
                _, header_height = self._table_row_layout(block.headers, widths, size, line_h, pad, f"{seed_extra}:header")
                height += header_height
            if block.rows:
                _, row_height = self._table_row_layout(block.rows[0], widths, size, line_h, pad, f"{seed_extra}:row")
                height += row_height
            return height + mm_to_px(self.config.layout.table_gap_mm, self.dpi)
        if isinstance(block, ImageBlock):
            return mm_to_px(self.config.layout.image_placeholder_height_mm + 9, self.dpi)
        if isinstance(block, CodeBlock):
            size = pt_to_px(self.config.handwriting.code_font_pt, self.dpi)
            line_h = round(size * self.config.handwriting.line_spacing)
            return line_h + mm_to_px(4, self.dpi)
        if isinstance(block, RuleBlock):
            return mm_to_px(4, self.dpi)
        return 0

    def _next_section_number(self, level: int) -> str:
        self.section_counters[level - 1] += 1
        for index in range(level, len(self.section_counters)):
            self.section_counters[index] = 0
        return ".".join(str(value) for value in self.section_counters[:level] if value)

    def _draw_paragraph(self, text: str) -> None:
        if not text:
            return
        parts: list[InlinePart] = []
        for index, line in enumerate(text.split("\n")):
            if index:
                parts.append(InlinePart("hardbreak"))
            parts.append(InlinePart("text", line))
        self._draw_rich_paragraph(parts)

    def _draw_rich_paragraph(
        self,
        parts: list[InlinePart],
        no_indent: bool = False,
        trailing_height: int = 0,
    ) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        normal_line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = 0 if no_indent else min(max(0, self.content_w - 1), round(size * self.config.layout.first_line_indent_em))
        lines = self._layout_rich_parts(
            parts,
            size,
            self.content_w,
            normal_line_h,
            seed_extra=f"paragraph:{len(self.pages)}:{self.y}",
            first_line_width=self.content_w - indent,
        )
        # Leading empty hard-break lines should not waste ruled rows at a page start.
        if self._paper_rules and self.y == self.margin_top:
            while lines and not lines[0].visuals:
                lines.pop(0)
            if not lines:
                return
        paragraph_height = sum(line.height for line in lines) + gap
        page_capacity = self.bottom_limit - self.margin_top
        keep_height = paragraph_height + trailing_height
        if keep_height > page_capacity:
            keep_height = paragraph_height
        if (keep_height <= page_capacity and self.y + keep_height > self.bottom_limit
                and (trailing_height > 0 or self.y + paragraph_height - gap > self.bottom_limit)
                and (trailing_height > 0 or (not self._paper_rules and not self._can_split_lines(lines)))):
            self._new_page()
        # Ruled pages may split a paragraph after any line that fits. This
        # leaves the greatest amount of usable paper for the user's content.
        for line_index, line in enumerate(lines):
            is_first = line_index == 0
            x = self.margin_left + (indent if is_first else 0)
            width = self.content_w - (indent if is_first else 0)
            positioned = self._position_on_paper_rule(line)
            if not positioned:
                self._ensure_space(line.height)
            self._paste_rich_line(
                line, x, self.y, width,
                justify=(
                    self.config.layout.justify_paragraphs
                    and line.wrapped
                    and line.width >= width * 0.78
                    and not line.contains_math
                ),
            )
            self.y += line.height
        self.y += gap

    def _layout_rich_parts(
        self,
        parts: list[InlinePart],
        size: int,
        max_width: int,
        normal_line_h: int,
        seed_extra: str,
        first_line_width: int | None = None,
    ) -> list[_RichLine]:
        """Lay out mixed handwriting and LaTeX for every inline-capable block."""
        # A group is a word/character/formula together with its closing
        # punctuation. It moves to the next line as a unit whenever possible.
        groups: list[list[tuple[str, object]]] = []
        for part_index, part in enumerate(parts):
            if part.kind in {"break", "hardbreak"}:
                groups.append([(part.kind, "")])
            elif part.kind == "math":
                try:
                    inline_size = max(1, round(size * max(0.5, min(2.0, self.config.handwriting.math_inline_scale))))
                    box = self.formula_renderer.render_inline(
                        part.text, inline_size, max(1, max_width),
                        seed_extra=f"{seed_extra}:math:{part_index}",
                    )
                except LatexRenderError as error:
                    self._report_formula_error(part.text, error)
                    box = self.formula_renderer.blank_inline(part.text, inline_size, max(1, max_width))
                groups.append([("math", box)])
            else:
                for unit in _inline_units(self._punctuation(part.text)):
                    if starts_with_forbidden_line_punctuation(unit) and groups and groups[-1][0][0] not in {"break", "hardbreak"}:
                        groups[-1].append(("text", unit))
                    else:
                        groups.append([("text", unit)])

        pending = deque(groups)
        lines: list[_RichLine] = []
        measurements: dict[str, float] = {}

        def measure(text: str) -> float:
            if text not in measurements:
                measurements[text] = self.engine.measure(text, size)
            return measurements[text]

        def nominal_width(items: list[tuple[str, object]]) -> float:
            width = 0.0
            buffer = ""
            for kind, value in items:
                if kind == "text":
                    buffer += str(value)
                else:
                    width += measure(buffer) + value.width
                    buffer = ""
            return width + measure(buffer)

        def flatten(selected):
            return [item for group in selected for item in group]

        def whitespace(group) -> bool:
            return all(kind == "text" and not str(value).strip() for kind, value in group)

        while pending:
            line_width = max(1, first_line_width if not lines and first_line_width is not None else max_width)
            selected: list[list[tuple[str, object]]] = []
            while pending:
                group = pending[0]
                if group[0][0] in {"break", "hardbreak"}:
                    break
                if not selected and whitespace(group):
                    pending.popleft()
                    continue
                if selected and nominal_width(flatten([*selected, group])) > line_width:
                    break
                selected.append(pending.popleft())
                if nominal_width(flatten(selected)) > line_width:
                    break
            while selected and whitespace(selected[-1]):
                selected.pop()
            if not selected:
                if pending and pending[0][0][0] in {"break", "hardbreak"}:
                    if pending.popleft()[0][0] == "hardbreak":
                        lines.append(_RichLine([], 0, normal_line_h, round(size * 0.76)))
                continue

            line_seed = f"{seed_extra}:line:{len(lines)}"
            items = flatten(selected)
            tail = ""
            if len(selected) == 1 and all(kind == "text" for kind, _ in items):
                text = "".join(str(value) for _, value in items)
                if len(text) > 32 and self.engine.corrected_line_width(text, size) > line_width:
                    low, high, cut = 1, len(text) - 1, 0
                    while low <= high:
                        middle = (low + high) // 2
                        if self.engine.corrected_line_width(text[:middle], size) <= line_width:
                            cut, low = middle, middle + 1
                        else:
                            high = middle - 1
                    cut = max(1, cut)
                    preferred = cut
                    while preferred > 0 and starts_with_forbidden_line_punctuation(text[preferred:]):
                        preferred -= 1
                    cut = preferred or cut
                    items, tail = [("text", text[:cut])], text[cut:]
            line = self._render_rich_items(items, size, line_width, normal_line_h, line_seed)
            # Font overhang, ink perturbations and image padding all contribute
            # to the visible width. Reflow using that width before pasting.
            while line.width > line_width and len(selected) > 1:
                pending.appendleft(selected.pop())
                while selected and whitespace(selected[-1]):
                    pending.appendleft(selected.pop())
                items = flatten(selected)
                line = self._render_rich_items(items, size, line_width, normal_line_h, line_seed)
            if line.width > line_width and all(kind == "text" for kind, _ in selected[0]):
                text = "".join(str(value) for _, value in items)
                # An overlong word must be splittable, including its first line.
                low, high, cut = 1, len(text) - 1, 0
                while low <= high:
                    middle = (low + high) // 2
                    candidate = self._render_rich_items([("text", text[:middle])], size, line_width, normal_line_h, line_seed)
                    if candidate.width <= line_width:
                        cut = middle
                        low = middle + 1
                    else:
                        high = middle - 1
                cut = max(1, cut)
                preferred = cut
                while preferred > 0 and starts_with_forbidden_line_punctuation(text[preferred:]):
                    preferred -= 1
                # A punctuation sequence longer than a whole line is an
                # unavoidable exception to the usual no-leading-punctuation rule.
                cut = preferred or cut
                if cut < len(text):
                    pending.appendleft([("text", text[cut:] + tail)])
                    tail = ""
                    line = self._render_rich_items([("text", text[:cut])], size, line_width, normal_line_h, line_seed)
            if tail:
                pending.appendleft([("text", tail)])
            if line.width > line_width:
                # A single formula or glyph may exceed even an empty line.
                line = self._fit_rich_line(line, line_width, normal_line_h)
            while pending and whitespace(pending[0]):
                pending.popleft()
            if pending and pending[0][0][0] in {"break", "hardbreak"}:
                pending.popleft()
            else:
                line.wrapped = bool(pending)
            lines.append(line)
        return lines

    def _render_rich_items(
        self, items: list[tuple[str, object]], size: int, max_width: int,
        normal_line_h: int, seed_extra: str,
    ) -> _RichLine:
        visuals: list[tuple[Image.Image, int]] = []
        text_buffer = ""

        def blank_space(text: str) -> None:
            if text:
                width = max(1, math.ceil(self.engine.measure(text, size)))
                visuals.append((Image.new("RGBA", (width, size)), round(size * 0.76)))

        def flush_text() -> None:
            nonlocal text_buffer
            if not text_buffer:
                return
            core = text_buffer.strip()
            if not core:
                blank_space(text_buffer)
            else:
                leading = len(text_buffer) - len(text_buffer.lstrip())
                trailing = len(text_buffer) - len(text_buffer.rstrip())
                blank_space(text_buffer[:leading])
                image, baseline = self.engine.render_line(
                    core, size, max_width,
                    seed_extra=f"{seed_extra}:text:{len(visuals)}", return_baseline=True, corrections=True,
                )
                visuals.append((image, baseline))
                if trailing:
                    blank_space(text_buffer[-trailing:])
            text_buffer = ""

        for kind, value in items:
            if kind == "text":
                text_buffer += str(value)
            else:
                flush_text()
                visuals.append((value.image, value.baseline))
        flush_text()
        baseline = max((base for _, base in visuals), default=round(size * 0.76))
        descent = max((image.height - base for image, base in visuals), default=normal_line_h - baseline)
        return _RichLine(
            visuals,
            sum(image.width for image, _ in visuals),
            max(normal_line_h, baseline + descent),
            baseline,
            contains_math=any(kind == "math" for kind, _ in items),
            font_size_px=size,
        )

    @staticmethod
    def _fit_rich_line(line: _RichLine, width: int, normal_line_h: int) -> _RichLine:
        if len(line.visuals) == 1:
            image = line.visuals[0][0]
        else:
            image = Image.new("RGBA", (line.width, line.height))
            x = 0
            marks = []
            for visual, baseline in line.visuals:
                image.alpha_composite(visual, (x, line.baseline - baseline))
                marks.extend(transform_correction_marks(visual.info.get("correction_marks", []), x, line.baseline - baseline))
                x += visual.width
            image.info["correction_marks"] = marks
        marks = image.info.get("correction_marks", [])
        scale = width / line.width
        image = image.resize((width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        image.info["correction_marks"] = transform_correction_marks(marks, scale_x=scale, scale_y=scale)
        baseline = max(1, round(line.baseline * scale))
        return _RichLine(
            [(image, baseline)],
            width,
            max(normal_line_h, image.height),
            baseline,
            contains_math=line.contains_math,
        )

    def _paste_rich_line(
        self,
        line: _RichLine,
        x: int,
        y: int,
        max_width: int,
        align: str = "left",
        justify: bool = False,
    ) -> None:
        if justify and align == "left" and line.width > 0 and 1.0 < max_width / line.width <= 1.18:
            image = Image.new("RGBA", (line.width, line.height))
            cursor_x = 0
            for visual, baseline in line.visuals:
                image.alpha_composite(visual, (cursor_x, line.baseline - baseline))
                self._queue_image_corrections(visual, x + cursor_x * max_width / line.width,
                                              y + line.baseline - baseline, scale_x=max_width / line.width)
                cursor_x += visual.width
            image = image.resize((max_width, line.height), Image.Resampling.BICUBIC)
            self.page.alpha_composite(image, (round(x), round(y)))
            return
        if align == "center":
            x += max(0, (max_width - line.width) // 2)
        elif align == "right":
            x += max(0, max_width - line.width)
        cursor_x = x
        for image, item_baseline in line.visuals:
            self.page.alpha_composite(image, (round(cursor_x), round(y + line.baseline - item_baseline)))
            self._queue_image_corrections(image, cursor_x, y + line.baseline - item_baseline)
            cursor_x += image.width

    def _queue_image_corrections(self, image, x, y, scale_x=1.0):
        marks = transform_correction_marks(image.info.get("correction_marks", []), x, y, scale_x)
        self._pending_corrections.extend((len(self.pages) - 1, mark) for mark in marks)

    def _draw_pending_corrections(self) -> None:
        if not self._pending_corrections:
            return
        gap = max(2, mm_to_px(.25, self.dpi))
        marks_by_page: dict[int, list[dict]] = {}
        for index, mark in self._pending_corrections:
            marks_by_page.setdefault(index, []).append(mark)
        for page_index in range(len(self.pages)):
            pending = marks_by_page.get(page_index, [])
            if not pending:
                continue
            page = self.pages[page_index]
            background = self._make_background(page_index).convert("RGB")
            difference = ImageChops.difference(page.convert("RGB"), background).convert("L")
            occupied = difference.point(lambda value: 255 if value > 2 else 0)
            occupied = Image.fromarray(cv2.dilate(
                np.asarray(occupied), np.ones((gap * 2 + 1, gap * 2 + 1), dtype=np.uint8)))
            rules = self._page_rules[page_index]
            top_limit = rules[0] + gap if rules else self.margin_top
            for mark in pending:
                x, y, width, height = mark["x"], mark["y"], mark["width"], mark["height"]
                rewrite = mark["rewrite"]
                angle = mark.get("angle", 0.0)
                if angle:
                    rewrite = rewrite.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
                    ink_bounds = rewrite.getchannel("A").getbbox()
                    if ink_bounds:
                        rewrite = rewrite.crop(ink_bounds)
                rw, rh = rewrite.size
                center_x, center_y = x + (width - rw) / 2, y + (height - rh) / 2
                candidates = [
                    (center_x, y - rh - gap), (center_x, y + height + gap),
                    (x - rw * .65, y - rh - gap), (x + width - rw * .35, y - rh - gap),
                    (x - rw * .65, y + height + gap), (x + width - rw * .35, y + height + gap),
                    (x - rw - gap, center_y), (x + width + gap, center_y),
                ]
                rng = random.Random(mark["seed"])
                # Rank nearby free positions, rather than snapping a rewrite
                # into another paper row. A tiny seeded bias keeps placement
                # varied while preserving a close connection to its source.
                ranked = []
                for cx, cy in candidates:
                    cx += rng.uniform(-.06, .06) * width
                    distance = math.hypot(cx + rw / 2 - x - width / 2,
                                          cy + rh / 2 - y - height / 2)
                    crosses_rule = any(cy < rule < cy + rh for rule in rules)
                    score = distance / max(1, math.hypot(width, height)) + rng.uniform(0, .16)
                    score += .025 if crosses_rule else 0
                    ranked.append((score, cx, cy))
                for _, cx, cy in sorted(ranked):
                    cx, cy = round(cx), round(cy)
                    box = (cx, cy, cx + rw, cy + rh)
                    if cx < max(0, self.margin_left - width) or box[2] > self.page_w - self.margin_right + width:
                        continue
                    if cy < top_limit or box[3] > self.bottom_limit:
                        continue
                    # The original's rectangle is excluded even if its strokes
                    # happen to leave a tempting hole inside the character.
                    if cx < x + width + gap and cx + rw > x - gap and cy < y + height + gap and cy + rh > y - gap:
                        continue
                    if occupied.crop(box).getbbox() is not None:
                        continue
                    page.alpha_composite(mark["strike"], (x, y))
                    page.alpha_composite(rewrite, (cx, cy))
                    # Reserve the whole replacement box, including its counters.
                    ImageDraw.Draw(occupied).rectangle((cx - gap, cy - gap, cx + rw + gap, cy + rh + gap), fill=255)
                    self._placed_corrections.append({"page": page_index, "original": (x, y, x + width, y + height),
                                                     "rewrite": box, "seed": mark["seed"], "angle": angle})
                    break
            if isinstance(self.pages, DiskPages):
                self.pages.save(page_index, page)
        self._pending_corrections.clear()

    def _render_formula_image(self, text: str, seed_extra: str) -> Image.Image:
        size = pt_to_px(self.config.handwriting.math_font_pt, self.dpi)
        try:
            return self.formula_renderer.render(
                text,
                size,
                self.content_w - mm_to_px(18, self.dpi),
                seed_extra=seed_extra,
            )
        except LatexRenderError as error:
            self._report_formula_error(text, error)
            return self.formula_renderer.blank_display(size)

    def _report_formula_error(self, latex: str, error: LatexRenderError) -> None:
        key = (latex, str(error))
        if key in self._reported_formula_errors:
            return
        self._reported_formula_errors.add(key)
        self.warnings.append({"formula": latex, "error": str(error)})
        compact = " ".join(latex.split())
        print(f"[latex-render-error] {compact} ({error})", file=sys.stderr)

    def _formula_height(self, image: Image.Image) -> int:
        gap = mm_to_px(self.config.layout.formula_gap_mm, self.dpi)
        rule_slack = 0
        if self.config.handwriting.math_display_left_aligned and len(self._paper_rules) > 1:
            rule_slack = int(np.median(np.diff(self._paper_rules)))
        return gap * 2 + image.height + rule_slack

    def _draw_formula(self, text: str, image: Image.Image | None = None) -> None:
        if not text:
            return
        gap = mm_to_px(self.config.layout.formula_gap_mm, self.dpi)
        image = image or self._render_formula_image(text, seed_extra=f"{len(self.pages)}:{self.y}")
        total_h = self._formula_height(image)
        self._ensure_space(total_h)
        self.y += gap
        if self.config.handwriting.math_display_left_aligned and self._paper_rules:
            # Place the bottom of the formula just above the next paper rule.
            # A formula taller than one ruled row may still span several rows.
            clearance = max(2, mm_to_px(0.5, self.dpi))
            rule = next((rule for rule in self._paper_rules
                         if rule - clearance >= self.y + image.height), None)
            if rule is not None and rule <= self.bottom_limit:
                self.y = rule - clearance - image.height
        if self.config.handwriting.math_display_left_aligned:
            # A modest paragraph-like indent avoids making every equation look
            # mechanically centered, while keeping long expressions on the page.
            indent = min(mm_to_px(10, self.dpi), max(0, self.content_w - image.width))
            x = self.margin_left + indent
        else:
            x = self.margin_left + (self.content_w - image.width) // 2
        self.page.alpha_composite(image, (x, self.y))
        self.y += image.height
        self.y += gap

    def _draw_list(self, block: ListBlock) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        normal_line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = mm_to_px(self.config.layout.list_indent_mm, self.dpi)
        for offset, item in enumerate(block.items):
            prefix = f"{block.start + offset}. " if block.ordered else "- "
            content_x = self.margin_left + indent
            content_width = self.content_w - indent
            lines = self._layout_rich_parts(
                item,
                size,
                content_width,
                normal_line_h,
                seed_extra=f"list:{len(self.pages)}:{self.y}:{offset}",
            )
            if not lines:
                lines = [_RichLine([], 0, normal_line_h, round(size * 0.76))]
            item_height = sum(line.height for line in lines)
            page_capacity = self.bottom_limit - self.margin_top
            if (item_height <= page_capacity and self.y + item_height > self.bottom_limit
                    and not self._can_split_lines(lines)):
                self._new_page()
            prefix_image, prefix_baseline = self.engine.render_line(
                prefix,
                size,
                indent,
                seed_extra=f"list-prefix:{len(self.pages)}:{self.y}:{offset}",
                return_baseline=True,
            )
            for line_index, line in enumerate(lines):
                positioning_line = (_RichLine(line.visuals + [(prefix_image, prefix_baseline)],
                                             line.width, line.height, line.baseline,
                                             font_size_px=line.font_size_px)
                                    if line_index == 0 else line)
                positioned = self._position_on_paper_rule(positioning_line)
                if not positioned:
                    self._ensure_space(line.height)
                if line_index == 0:
                    prefix_x = content_x - prefix_image.width
                    prefix_y = self.y + line.baseline - prefix_baseline
                    self.page.alpha_composite(prefix_image, (round(prefix_x), round(prefix_y)))
                self._paste_rich_line(line, content_x, self.y, content_width)
                self.y += line.height
        self.y += gap

    def _draw_code(self, block: CodeBlock) -> None:
        size = pt_to_px(self.config.handwriting.code_font_pt, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        pad = mm_to_px(2.0, self.dpi)
        lines: list[str] = []
        for raw in self._punctuation(block.text).splitlines() or [""]:
            lines.extend(wrap_text(self.engine, raw, size, self.content_w - 2 * pad))
        height = len(lines) * line_h + 2 * pad
        self._ensure_space(height + pad)
        x0 = self.margin_left
        y0 = self.y
        x1 = self.margin_left + self.content_w
        y1 = y0 + height
        uniform_ink = self.config.handwriting.uniform_table_ink
        frame_color = color(self.config.handwriting.ink_color, 255 if uniform_ink else 90)
        frame_width = max(1.0, pt_to_px(self.config.handwriting.body_font_pt, self.dpi) * 0.0675) if uniform_ink else 1
        self._rough_rect(x0, y0, x1, y1, frame_color, width=frame_width)
        self.y += pad
        for line in lines:
            self._paste_text(line, x0 + pad, self.y, size, self.content_w - 2 * pad)
            self.y += line_h
        self.y = y1 + pad

    def _draw_image_placeholder(self, block: ImageBlock) -> None:
        height = mm_to_px(self.config.layout.image_placeholder_height_mm, self.dpi)
        caption_h = mm_to_px(9.0, self.dpi)
        self._ensure_space(height + caption_h)
        x0 = self.margin_left
        y0 = self.y
        x1 = self.margin_left + self.content_w
        y1 = y0 + height
        if self.config.layout.image_placeholder_border:
            self._rough_rect(x0, y0, x1, y1, color(self.config.handwriting.ink_color, 90), width=1)
        self.figure_counter += 1
        title = block.alt or block.src or "插图空白"
        caption = f"图{self.figure_counter}：{title}" if self.config.layout.number_figures else title
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        self._paste_text(
            caption, x0, y1 + mm_to_px(1.5, self.dpi), size, self.content_w,
            align="center", preserve_punctuation=True,
        )
        self.y = y1 + caption_h

    def _draw_table(self, block: TableBlock) -> None:
        if not block.headers and not block.rows:
            return
        self.y += mm_to_px(self.config.layout.table_gap_mm / 2, self.dpi)
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        pad = mm_to_px(self.config.layout.table_cell_padding_mm, self.dpi)
        col_count = max(len(block.headers), *(len(row) for row in block.rows)) if block.rows else len(block.headers)
        widths = self._table_widths(block, col_count, size)
        header_spans = self._table_row_spans(block, 0, block.headers)
        header_rowspans = self._table_row_rowspans(block, 0, block.headers)
        header_layout = (
            self._table_row_layout(block.headers, widths, size, line_h, pad, "table:header", header_spans)
            if block.headers
            else None
        )
        header_height = header_layout[1] if header_layout else 0
        if block.headers:
            self._ensure_space(header_height + line_h)
            self._draw_table_row(widths, header_layout, pad, header=True, colspans=header_spans)

        body_rows = []
        for row_index, row in enumerate(block.rows):
            row_spans = self._table_row_spans(block, row_index + 1, row)
            row_rowspans = self._table_row_rowspans(block, row_index + 1, row)
            row_layout = self._table_row_layout(
                row,
                widths,
                size,
                line_h,
                pad,
                f"table:row:{row_index}",
                row_spans,
            )
            body_rows.append((row_layout, row_spans, row_rowspans))

        row_heights = [layout[1] for layout, _colspans, _rowspans in body_rows]
        for row_index, (layout, colspans, rowspans) in enumerate(body_rows):
            for column, span in enumerate(rowspans):
                if span <= 1 or column >= len(layout[0]):
                    continue
                end = min(len(body_rows), row_index + span)
                available_height = sum(row_heights[row_index:end]) - 2 * pad
                content_height = sum(line.height for line in layout[0][column])
                if content_height > available_height:
                    row_heights[row_index] += content_height - available_height
        body_rows = [
            ((layout[0], row_heights[index]), colspans, rowspans)
            for index, (layout, colspans, rowspans) in enumerate(body_rows)
        ]

        def group_end(start: int) -> int:
            end = start
            while True:
                expanded = end
                for row_index in range(start, end + 1):
                    _layout, _colspans, rowspans = body_rows[row_index]
                    for span in rowspans:
                        if span > 1:
                            expanded = max(expanded, min(len(body_rows) - 1, row_index + span - 1))
                if expanded == end:
                    return end
                end = expanded

        def skip_bottom_columns(row_index: int) -> set[int]:
            skipped: set[int] = set()
            for anchor_row in range(row_index + 1):
                _layout, colspans, rowspans = body_rows[anchor_row]
                for column, span in enumerate(rowspans):
                    if span > 1 and anchor_row <= row_index < anchor_row + span - 1:
                        colspan = colspans[column] if column < len(colspans) else 1
                        skipped.update(range(column, min(col_count, column + max(1, colspan))))
            return skipped

        def rowspan_heights(row_index: int) -> dict[int, int]:
            result: dict[int, int] = {}
            for column, span in enumerate(body_rows[row_index][2]):
                if span > 1:
                    end = min(len(body_rows), row_index + span)
                    result[column] = sum(row_heights[row_index:end])
            return result

        draw_top = not block.headers
        row_index = 0
        while row_index < len(body_rows):
            end = group_end(row_index)
            group_height = sum(row_heights[row_index:end + 1])
            if self.y + group_height > self.bottom_limit:
                self._new_page()
                if block.headers:
                    self._draw_table_row(widths, header_layout, pad, header=True, colspans=header_spans)
                draw_top = not block.headers
            while row_index <= end:
                row_layout, row_spans, row_rowspans = body_rows[row_index]
                self._draw_table_row(
                    widths,
                    row_layout,
                    pad,
                    header=False,
                    draw_top=draw_top,
                    colspans=row_spans,
                    rowspans=row_rowspans,
                    rowspan_heights=rowspan_heights(row_index),
                    skip_bottom_columns=skip_bottom_columns(row_index),
                )
                draw_top = False
                row_index += 1
        self.y += mm_to_px(self.config.layout.table_gap_mm, self.dpi)

    @staticmethod
    def _table_row_spans(block: TableBlock, row_index: int, row: list[list[InlinePart]]) -> list[int]:
        spans = block.header_colspans if row_index == 0 else (
            block.row_colspans[row_index - 1]
            if block.row_colspans is not None and row_index - 1 < len(block.row_colspans)
            else None
        )
        normalized = list(spans or [])[:len(row)]
        normalized.extend([1] * (len(row) - len(normalized)))
        return normalized

    @staticmethod
    def _table_row_rowspans(block: TableBlock, row_index: int, row: list[list[InlinePart]]) -> list[int]:
        spans = block.header_rowspans if row_index == 0 else (
            block.row_rowspans[row_index - 1]
            if block.row_rowspans is not None and row_index - 1 < len(block.row_rowspans)
            else None
        )
        normalized = list(spans or [])[:len(row)]
        normalized.extend([1] * (len(row) - len(normalized)))
        return normalized

    def _table_widths(self, block: TableBlock, col_count: int, size: int) -> list[int]:
        if col_count == 0:
            return []
        if self.content_w < col_count:
            raise ValueError("当前页面宽度不足以容纳这么多列，请减少列数或增大页面宽度。")
        pad = max(0, mm_to_px(self.config.layout.table_cell_padding_mm, self.dpi))
        minimum = [1.0 + 2 * pad] * col_count
        preferred = minimum.copy()
        formula_widths: dict[str, int] = {}
        text_widths: dict[str, float] = {}
        # Handwriting rasters retain four transparent pixels on each side;
        # include that footprint so a short header need not wrap by one pixel.
        ink_slack = max(12, math.ceil(size * 0.30))

        def text_width(text: str) -> float:
            if text not in text_widths:
                text_widths[text] = self.engine.measure(text, size) + (ink_slack if text.strip() else 0)
            return text_widths[text]

        def formula_width(latex: str) -> int:
            if latex not in formula_widths:
                # Measuring must not advance the live renderer's geometry or
                # ink RNGs. A fixed per-formula seed also makes column order
                # irrelevant to the width estimate.
                probe = FormulaRenderer(self.engine, seed=f"{self.config.handwriting.seed}:table:{latex}")
                inline_size = max(1, round(size * max(0.5, min(2.0, self.config.handwriting.math_inline_scale))))
                try:
                    box = probe.render_inline(latex, inline_size, self.content_w, seed_extra="table:measure")
                except LatexRenderError:
                    # The actual cell render reports the error once.
                    box = probe.blank_inline(latex, inline_size, self.content_w)
                formula_widths[latex] = box.width
            return formula_widths[latex]

        table_rows = [block.headers, *block.rows]
        for row_index, row in enumerate(table_rows):
            spans = self._table_row_spans(block, row_index, row)
            for index, cell in enumerate(row[:col_count]):
                span = spans[index] if index < len(spans) else 1
                if span <= 0:
                    continue
                span = min(span, col_count - index)
                cell_minimum = 1.0 + 2 * pad
                cell_preferred = cell_minimum
                line_width = 0.0
                text_buffer = ""

                def flush_text() -> None:
                    nonlocal text_buffer, line_width, cell_minimum
                    if text_buffer:
                        line_width += text_width(text_buffer)
                        for unit in _inline_units(text_buffer):
                            if unit.strip():
                                cell_minimum = max(cell_minimum, text_width(unit) + 2 * pad)
                        text_buffer = ""

                for part in cell:
                    if part.kind in {"break", "hardbreak"}:
                        flush_text()
                        cell_preferred = max(cell_preferred, line_width + 2 * pad)
                        line_width = 0.0
                    elif part.kind == "math":
                        flush_text()
                        width = formula_width(part.text)
                        line_width += width
                        cell_minimum = max(cell_minimum, width + 2 * pad)
                    else:
                        text_buffer += self._punctuation(part.text)
                flush_text()
                cell_preferred = max(cell_preferred, line_width + 2 * pad)
                # Keep short headers together before allocating space to long body text.
                header_text = "".join(part.text for part in cell if part.kind == "text").strip()
                if row_index == 0 and 1 < len(header_text) <= 6 and all(part.kind == "text" for part in cell):
                    cell_minimum = max(cell_minimum, cell_preferred)
                for target in range(index, index + span):
                    minimum[target] = max(minimum[target], cell_minimum / span)
                    preferred[target] = max(preferred[target], cell_preferred / span)

        # Demands wider than the whole table cannot be satisfied without
        # wrapping or scaling, and must not dominate the other columns.
        preferred = [min(self.content_w, max(want, need)) for want, need in zip(preferred, minimum)]
        minimum = [min(need, want) for need, want in zip(minimum, preferred)]
        base = mm_to_px(18, self.dpi)
        if base * col_count > self.content_w:
            base = max(1.0, self.content_w / (2 * col_count))
        widths = [min(float(base), want) for want in preferred]
        remaining = self.content_w - sum(widths)

        def grow_towards(targets: list[float]) -> None:
            nonlocal remaining
            active = [i for i in range(col_count) if targets[i] > widths[i] + 1e-9]
            while active and remaining > 1e-9:
                step = min(remaining / len(active), min(targets[i] - widths[i] for i in active))
                for i in active:
                    widths[i] += step
                remaining = max(0.0, remaining - step * len(active))
                active = [i for i in active if targets[i] > widths[i] + 1e-9]

        # Equal increments with satisfied columns frozen protect short fields
        # and formulas before spending the remaining room on long paragraphs.
        grow_towards(minimum)
        grow_towards(preferred)
        widths = [width + remaining / col_count for width in widths]
        rounded = [max(1, math.floor(width)) for width in widths]
        remainder = self.content_w - sum(rounded)
        order = sorted(range(col_count), key=lambda i: widths[i] - rounded[i], reverse=True)
        for i in order[:remainder]:
            rounded[i] += 1
        return rounded

    def _table_content_geometry(self, width: int, pad: int) -> tuple[int, int]:
        # Narrow tables sacrifice horizontal padding before squeezing their
        # content below one em. Layout and pasting must use the same budget.
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        horizontal_pad = min(max(0, pad), max(0, (width - min(width, size)) // 2))
        return horizontal_pad, max(1, width - 2 * horizontal_pad)

    def _table_row_layout(
        self,
        row: list[list[InlinePart]],
        widths: list[int],
        size: int,
        line_h: int,
        pad: int,
        seed_extra: str,
        colspans: list[int] | None = None,
    ) -> tuple[list[list[_RichLine]], int]:
        cells: list[list[_RichLine]] = []
        content_height = line_h
        spans = list(colspans or [])
        spans.extend([1] * (len(widths) - len(spans)))
        for index in range(len(widths)):
            span = spans[index]
            if span <= 0:
                cells.append([])
                continue
            span = min(span, len(widths) - index)
            width = sum(widths[index:index + span])
            cell = row[index] if index < len(row) else []
            _, available = self._table_content_geometry(width, pad)
            lines = self._layout_rich_parts(
                cell,
                size,
                available,
                line_h,
                seed_extra=f"{seed_extra}:cell:{index}",
            )
            cells.append(lines)
            content_height = max(content_height, sum(line.height for line in lines))
        return cells, content_height + 2 * pad

    def _draw_table_row(
        self,
        widths: list[int],
        layout: tuple[list[list[_RichLine]], int],
        pad: int,
        header: bool,
        draw_top: bool = True,
        colspans: list[int] | None = None,
        rowspans: list[int] | None = None,
        rowspan_heights: dict[int, int] | None = None,
        skip_bottom_columns: set[int] | None = None,
    ) -> None:
        cells, height = layout
        x_positions = [self.margin_left]
        for width in widths:
            x_positions.append(x_positions[-1] + width)
        spans = list(colspans or [])
        spans.extend([1] * (len(widths) - len(spans)))
        vertical_spans = list(rowspans or [])
        vertical_spans.extend([1] * (len(widths) - len(vertical_spans)))
        y0 = self.y
        y1 = self.y + height
        uniform_ink = self.config.handwriting.uniform_table_ink
        ink = color(self.config.handwriting.ink_color, 255 if uniform_ink else (200 if header else 170))
        # A fixed one-pixel rule nearly disappears when a 300 DPI page is
        # scaled down for preview. Match the rule width to the body font size.
        line_width = max(1.0, pt_to_px(self.config.handwriting.body_font_pt, self.dpi) * 0.0675) if uniform_ink else 1
        if draw_top:
            self._rough_line(x_positions[0], y0, x_positions[-1], y0, ink, width=line_width if uniform_ink else (2 if header else 1))
        skipped_bottom = skip_bottom_columns or set()
        segment_start = 0
        for boundary in range(len(widths)):
            if boundary in skipped_bottom:
                if segment_start < boundary:
                    self._rough_line(x_positions[segment_start], y1, x_positions[boundary], y1, ink, width=line_width)
                segment_start = boundary + 1
        if segment_start < len(widths):
            self._rough_line(x_positions[segment_start], y1, x_positions[-1], y1, ink, width=line_width)
        skip_boundaries = set()
        for index, span in enumerate(spans):
            if span > 1:
                skip_boundaries.update(range(index + 1, min(len(widths), index + span)))
        for boundary, x in enumerate(x_positions):
            if boundary not in skip_boundaries:
                self._rough_line(x, y0, x, y1, ink, width=line_width)
        for index in range(len(widths)):
            span = spans[index]
            rowspan = vertical_spans[index]
            if span <= 0 or rowspan <= 0:
                continue
            span = min(span, len(widths) - index)
            width = sum(widths[index:index + span])
            horizontal_pad, available = self._table_content_geometry(width, pad)
            cell_lines = cells[index]
            cell_content_height = sum(line.height for line in cell_lines)
            cell_height = (rowspan_heights or {}).get(index, height)
            row_content_height = max(0, cell_height - 2 * pad)
            y = y0 + pad + max(0, (row_content_height - cell_content_height) // 2)
            for line in cell_lines:
                self._paste_rich_line(
                    line,
                    x_positions[index] + horizontal_pad,
                    y,
                    available,
                    align="center",
                )
                y += line.height
        self.y = y1

    def _draw_rule(self) -> None:
        gap = mm_to_px(4.0, self.dpi)
        self._ensure_space(gap)
        self.y += gap

    def _paste_text(
        self,
        text: str,
        x: int,
        y: int,
        size: int,
        max_width: int,
        align: str = "left",
        math: bool = False,
        justify: bool = False,
        preserve_punctuation: bool = False,
    ) -> None:
        if not preserve_punctuation:
            text = self._punctuation(text)
        image = self.engine.render_line(text, size, max_width, seed_extra=f"{len(self.pages)}:{x}:{y}", math=math)
        if image.width > max_width:
            scale = max_width / image.width
            image = image.resize((max_width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        if justify and align == "left" and image.width > 1:
            stretch = max_width / image.width
            if 1.0 < stretch <= 1.18:
                image = image.resize((max_width, image.height), Image.Resampling.BICUBIC)
        if align == "center":
            x = x + max(0, (max_width - image.width) // 2)
        elif align == "right":
            x = x + max(0, max_width - image.width)
        self.page.alpha_composite(image, (round(x), round(y)))

    def _should_justify_paragraph_line(
        self,
        line: str,
        line_index: int,
        line_count: int,
        size: int,
        width: int,
    ) -> bool:
        if not self.config.layout.justify_paragraphs or line_index >= line_count - 1:
            return False
        measured = self.engine.measure(line, size)
        return measured >= width * 0.78

    def _rough_line(self, x0: int, y0: int, x1: int, y1: int, fill: tuple[int, ...], width: float = 1) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        if y0 == y1:
            self.formula_renderer.draw_horizontal_rule(
                self.page,
                x0,
                y0,
                x1,
                size,
                width=width,
                fill=fill,
                anchor_ends=True,
                variation_scale=0.7,
            )
            return
        self.formula_renderer.draw_rule(
            self.page,
            x0,
            y0,
            x1,
            y1,
            size,
            width=width,
            fill=fill,
            anchor_ends=True,
            variation_scale=0.7,
        )

    def _rough_rect(self, x0: int, y0: int, x1: int, y1: int, fill: tuple[int, ...], width: float = 1) -> None:
        self._rough_line(x0, y0, x1, y0, fill, width)
        self._rough_line(x1, y0, x1, y1, fill, width)
        self._rough_line(x1, y1, x0, y1, fill, width)
        self._rough_line(x0, y1, x0, y0, fill, width)

    def _draw_footers(self) -> None:
        size = pt_to_px(9.5, self.dpi)
        footer_y = self.page_h - mm_to_px(self.config.page.margin_bottom_mm / 2 + 2, self.dpi)
        for index, page in enumerate(self.pages, start=1):
            self.page = page
            label = f"- {index} -"
            image = self.engine.render_line(label, size, self.content_w, seed_extra=f"footer-{index}")
            x = (self.page_w - image.width) // 2
            page.alpha_composite(image, (x, footer_y))
            if isinstance(self.pages, DiskPages):
                self.pages.save(index - 1, page)


def _inline_units(text: str) -> list[str]:
    units: list[str] = []
    buffer = ""
    for char in text:
        if char.isspace():
            if buffer:
                units.append(buffer)
                buffer = ""
            units.append(" ")
        elif ord(char) < 128 and (char.isalnum() or char in "._-/^=+"):
            buffer += char
        else:
            if buffer:
                units.append(buffer)
                buffer = ""
            units.append(char)
    if buffer:
        units.append(buffer)
    return units
