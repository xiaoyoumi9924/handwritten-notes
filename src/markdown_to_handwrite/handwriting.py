from __future__ import annotations

import hashlib
import math
import random
import re
import string
import sys
import unicodedata
from math import ceil as _ceil
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import HandwritingConfig, color
from .sdt_renderer import SdtTrajectoryStore, TrajectoryStyle, font_glyph_strokes, render_strokes

try:
    from handright import Template, handwrite
except Exception:  # pragma: no cover - dependency fallback
    Template = None
    handwrite = None


PROJECT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
DEFAULT_SYSTEM_FONT_CANDIDATES = (
    "C:/Windows/Fonts/simkai.ttf",
    "C:/Windows/Fonts/STKAITI.TTF",
    "C:/Windows/Fonts/simfang.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)
GLYPH_VERTICAL_ADJUSTMENTS: dict[str, float] = {}
FORBIDDEN_LINE_START_PUNCTUATION = frozenset(",.;:!?%)]}>\"'，。；：！？、）》】〉」』”’…")
DEFAULT_RENDER_DPI = 180.0
TEXT_STROKE_WEIGHT_SAMPLE = "永重力加速度ABC123"
MATH_STROKE_WEIGHT_SAMPLE = "xTgabcmn0123456789+-=()[]"
MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX = 1.0
MAX_STROKE_WEIGHT_ADJUSTMENT_PX = 2.0


def transform_correction_marks(marks, dx=0, dy=0, scale_x=1.0, scale_y=1.0):
    transformed = []
    for mark in marks:
        item = dict(mark)
        item["x"] = round(mark["x"] * scale_x + dx)
        item["y"] = round(mark["y"] * scale_y + dy)
        item["width"] = max(1, round(mark["width"] * scale_x))
        item["height"] = max(1, round(mark["height"] * scale_y))
        if scale_x != 1 or scale_y != 1:
            for key in ("rewrite", "strike"):
                bitmap = mark[key]
                item[key] = bitmap.resize((max(1, round(bitmap.width * scale_x)),
                                           max(1, round(bitmap.height * scale_y))), Image.Resampling.LANCZOS)
        transformed.append(item)
    return transformed


class HandwritingEngine:
    def __init__(
        self,
        config: HandwritingConfig,
        reference_size_px: int | None = None,
        math_reference_size_px: int | None = None,
    ):
        self.config = config
        self.reference_size_px = max(
            1,
            reference_size_px
            if reference_size_px is not None
            else round(config.body_font_pt / 72.0 * DEFAULT_RENDER_DPI),
        )
        self.math_reference_size_px = max(
            1,
            math_reference_size_px
            if math_reference_size_px is not None
            else round(config.math_font_pt / 72.0 * DEFAULT_RENDER_DPI),
        )
        if config.reference_glyph_path:
            for label, preferred in (("正文字体", config.font_path), ("备用字体", config.fallback_font_path),
                                     ("英文字体", config.latin_font_path), ("公式字体", config.math_font_path)):
                if preferred and not any(path.is_file() for path in _preferred_font_candidates(preferred)):
                    raise FileNotFoundError(f"{label}不存在: {preferred}")
        self.font_paths = _resolve_font_chain(config.font_path, config.fallback_font_path)
        self.font_path = self.font_paths[0]
        self.latin_font_path = _resolve_font(config.latin_font_path) if config.latin_font_path else None
        self.math_font_paths = (
            _resolve_font_chain(config.math_font_path, config.fallback_font_path)
            if config.math_font_path
            else self.font_paths
        )
        self.math_font_path = self.math_font_paths[0]
        self.fallback_font_path = self.font_paths[min(1, len(self.font_paths) - 1)]
        self.ink = color(config.ink_color, 255)
        self.reference_glyph_path = None
        if config.reference_glyph_path:
            reference_path = Path(config.reference_glyph_path).expanduser()
            if not reference_path.is_absolute():
                reference_path = PROJECT_ROOT / reference_path
            if not reference_path.is_dir():
                raise FileNotFoundError(f"照片字形目录不存在: {reference_path}")
            self.reference_glyph_path = reference_path
        self.trajectory_store = SdtTrajectoryStore(config.sdt_trajectory_path, PROJECT_ROOT)
        if config.sdt_trajectory_enabled and config.sdt_trajectory_path and not self.trajectory_store.available:
            raise FileNotFoundError(f"笔迹轨迹库不存在: {config.sdt_trajectory_path}")
        self.uses_sdt_trajectories = bool(config.sdt_trajectory_enabled and self.trajectory_store.available)
        self.handright_available = bool(config.prefer_handright and Template is not None and handwrite is not None)
        self.reference_stroke_weight = _font_optical_weight(
            self.font_path,
            self.reference_size_px,
            TEXT_STROKE_WEIGHT_SAMPLE,
        )
        self.math_reference_stroke_weight = _font_optical_weight(
            self.math_font_path,
            self.math_reference_size_px,
            MATH_STROKE_WEIGHT_SAMPLE,
        )

    def font(self, size_px: int, math: bool = False, fallback: bool = False) -> ImageFont.FreeTypeFont:
        paths = self.math_font_paths if math else self.font_paths
        index = min(1, len(paths) - 1) if fallback else 0
        return _load_font(paths[index], size_px)

    def measure(self, text: str, size_px: int, math: bool = False) -> float:
        """Return the nominal extent used by all character layout backends.

        Spacing advances the origin of the next character, so there is no
        trailing spacing after the final glyph. Measuring individual glyphs
        also avoids font kerning that our character renderers do not apply.
        """
        x = 0.0
        extent = 0.0
        previous_char: str | None = None
        for char in text:
            x += self._script_boundary_spacing(previous_char, char, size_px, math=math)
            extent = max(extent, x + self.character_advance(char, size_px, math=math, include_spacing=False))
            x += self.character_advance(char, size_px, math=math)
            previous_char = char
        return extent

    def corrected_line_width(self, text: str, size_px: int) -> int:
        """Width of a text line rendered with correction marks enabled."""
        return max(1, _ceil(self.measure(text, size_px)) + 2 * max(4, _ceil(size_px * .10)))

    def _script_boundary_spacing(
        self,
        previous_char: str | None,
        char: str,
        size_px: int,
        math: bool = False,
    ) -> float:
        if math or not previous_char:
            return 0.0
        if (_is_cjk_ideograph(previous_char) and _is_latin_word_character(char)) or (
            _is_latin_word_character(previous_char) and _is_cjk_ideograph(char)
        ):
            return max(0.0, size_px * self.config.cjk_latin_spacing_em)
        return 0.0

    def character_advance(
        self, char: str, size_px: int, math: bool = False, include_spacing: bool = True
    ) -> float:
        """Measure one glyph's advance, with the same space rule as rendering."""
        font_path = self._font_path_for_char(char, size_px, math=math)
        width = max(1.0, _character_width(font_path, size_px, char))
        if self.config.handwritten_quotes and not math and char in "“”":
            width = size_px * 0.43
        if self.config.handwritten_punctuation and not math and char in "。、":
            width = size_px * 0.40
        if char.isspace():
            return max(size_px * 0.35, width)
        return max(1.0, width + (self.config.word_spacing_px if include_spacing else 0.0))

    def _sample_character_advance(self, char: str, size_px: int, rand: random.Random, math: bool = False) -> float:
        advance = self.character_advance(char, size_px, math=math)
        if not char.isspace():
            advance += self._sample_position_offset(rand, self._advance_jitter_sigma(size_px, math_mode=math))
        return max(1.0, advance)

    def _line_canvas_width(self, text: str, size_px: int, pad: int, math_mode: bool = False) -> int:
        # A line may exceed the caller's width (an indivisible glyph, spacing,
        # or random advance); the caller must see all ink to lay it out safely.
        advance_pad = 3 * self._advance_jitter_sigma(size_px, math_mode=math_mode) * max(0, len(text) - 1)
        return max(16, math.ceil(self.measure(text, size_px, math=math_mode) + advance_pad + 3 * pad))

    def render_line(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed_extra: str = "",
        math: bool = False,
        weight_seed_extra: str | None = None,
        return_baseline: bool = False,
        corrections: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        text = text.rstrip()
        if not text:
            image = Image.new("RGBA", (1, max(1, round(size_px * self.config.line_spacing))), (0, 0, 0, 0))
            baseline = max(1, round(size_px * 0.75))
            return (image, baseline) if return_baseline else image
        seed = _stable_seed(self.config.seed, text, size_px, max_width, seed_extra)
        if self.uses_sdt_trajectories:
            image, baseline = self._render_with_trajectories(
                text,
                size_px,
                max_width,
                seed,
                math=math,
                return_baseline=True,
                corrections=corrections,
            )
        elif self.handright_available and not (self.config.handwritten_digit_one or self.config.handwritten_punctuation or self.config.uniform_ink_enabled) and not (corrections and (self.config.correction_probability > 0 or self.config.position_disorder > 0)):
            try:
                image = self._render_with_handright(text, size_px, max_width, seed, math=math)
            except Exception:
                image = self._render_with_pillow(text, size_px, max_width, seed, math=math, corrections=corrections)
            baseline = self._estimated_rendered_baseline(text, size_px, image, math=math)
        else:
            image = self._render_with_pillow(text, size_px, max_width, seed, math=math, corrections=corrections)
            baseline = self._estimated_rendered_baseline(text, size_px, image, math=math)
        image, baseline = self._apply_second_layer(
            image,
            size_px,
            _stable_seed(seed, "second-layer"),
            math_mode=math,
            reference_weight=self._reference_weight_for_text(text, size_px, math_mode=math),
            weight_seed=(
                _stable_seed(self.config.seed, "stroke-weight", weight_seed_extra)
                if weight_seed_extra is not None
                else None
            ),
            normalize_weight=not self.uses_sdt_trajectories,
            baseline_px=baseline,
            return_baseline=True,
        )
        if corrections and not math:
            # Keep logical text geometry fixed. Separate page decorations must
            # never become line height, baseline, or wrapping measurements.
            width = self.corrected_line_width(text, size_px)
            height = max(1, round(size_px * self.config.line_spacing))
            fixed_baseline = round(size_px * .96)
            fixed = Image.new("RGBA", (width, height))
            fixed.alpha_composite(image, ((width - image.width) // 2, fixed_baseline - baseline))
            fixed.info["correction_marks"] = transform_correction_marks(
                image.info.get("correction_marks", []),
                (width - image.width) // 2, fixed_baseline - baseline)
            fixed.info["layout_ink_top"] = fixed_baseline - round(size_px * .90)
            fixed.info["layout_ink_bottom"] = fixed_baseline + round(size_px * .20)
            image, baseline = fixed, fixed_baseline
        return (image, baseline) if return_baseline else image

    def _apply_second_layer(
        self,
        image: Image.Image,
        size_px: int,
        seed: int,
        math_mode: bool = False,
        reference_weight: float | None = None,
        weight_seed: int | None = None,
        normalize_weight: bool = True,
        baseline_px: int | None = None,
        return_baseline: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        """Perturb the rasterized ink mask after the character-level rendering pass."""
        if not self.config.second_layer_enabled or image.getchannel("A").getbbox() is None:
            baseline = baseline_px if baseline_px is not None else max(1, round(image.height * 0.76))
            return (image, baseline) if return_baseline else image

        geometry_rand = random.Random(_stable_seed(seed, "geometry"))
        ink_rand = random.Random(_stable_seed(seed, "ink"))
        variation_scale = self._math_jitter_scale() if math_mode else 1.0
        elastic_strength = max(0.0, size_px * self.config.elastic_strength_ratio * variation_scale)
        baseline_amplitude = max(0.0, size_px * self.config.baseline_wave_amplitude_ratio * variation_scale)
        random_weight_sigma = self._random_stroke_weight_sigma(math_mode=math_mode)
        pad = max(
            4,
            math.ceil(
                elastic_strength * 3
                + baseline_amplitude
                + MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX
                + 3 * random_weight_sigma
                + 2
            ),
        )
        padded = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
        padded.alpha_composite(image, (pad, pad))
        alpha = padded.getchannel("A")

        # Geometric resampling changes the apparent weight most strongly for
        # small math glyphs, so normalize only after the warp has completed.
        alpha = _warp_ink_mask(
            alpha,
            geometry_rand,
            elastic_strength=elastic_strength,
            elastic_smoothness=max(2.0, size_px * self.config.elastic_smoothness_ratio),
            baseline_amplitude=baseline_amplitude,
            baseline_wavelength=max(2.0, size_px * self.config.baseline_wave_length_em),
        )
        base_weight_adjustment = (
            self._base_stroke_weight_adjustment(
                alpha,
                math_mode=math_mode,
                reference_weight=reference_weight,
            )
            if normalize_weight
            else 0.0
        )
        weight_rand = random.Random(
            weight_seed if weight_seed is not None else _stable_seed(seed, "stroke-weight")
        )
        alpha = _adjust_stroke_weight(alpha, base_weight_adjustment)
        random_weight_adjustment = self._random_stroke_weight_adjustment(
            weight_rand,
            random_weight_sigma,
        )
        alpha = _adjust_stroke_weight(alpha, random_weight_adjustment)
        alpha = _vary_ink_density(
            alpha,
            ink_rand,
            jitter=self.config.ink_density_jitter * variation_scale,
            dry_brush_probability=self.config.dry_brush_probability * variation_scale,
            dry_brush_min_opacity=self.config.dry_brush_min_opacity,
        )

        result = Image.new("RGBA", padded.size, self.ink)
        result.putalpha(alpha)
        result.info["correction_marks"] = transform_correction_marks(
            image.info.get("correction_marks", []), pad, pad)
        cropped, _, crop_top = _crop_alpha_with_offset(result, pad=4)
        baseline = (
            round(baseline_px + pad - crop_top)
            if baseline_px is not None
            else max(1, round(cropped.height * 0.76))
        )
        return (cropped, baseline) if return_baseline else cropped

    def _base_stroke_weight_adjustment(
        self,
        alpha: Image.Image,
        math_mode: bool = False,
        reference_weight: float | None = None,
    ) -> float:
        """Normalize the mask toward its text- and font-specific optical weight."""
        optical_weight = _estimate_optical_stroke_weight(alpha)
        if reference_weight is None:
            reference_weight = (
                self.math_reference_stroke_weight
                if math_mode
                else self.reference_stroke_weight
            )
        base_scale = max(0.25, min(3.0, self.config.stroke_weight_base_scale))
        reference_weight *= base_scale * (max(0.5, min(2.0, self.config.math_stroke_weight_scale)) if math_mode else 1.0)
        if optical_weight <= 0 or reference_weight <= 0:
            return 0.0
        return _solve_stroke_weight_adjustment(
            alpha,
            target_weight=reference_weight,
            max_adjustment=MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX,
        )

    def _reference_weight_for_text(self, text: str, size_px: int, math_mode: bool = False) -> float:
        """Measure the same glyph mix at the configured reference size."""
        if math_mode and self.config.math_match_body_ink:
            return self.reference_stroke_weight
        runs = self._font_runs(text, size_px, math=math_mode)
        reference_size = self.math_reference_size_px if math_mode else self.reference_size_px
        fallback_sample = MATH_STROKE_WEIGHT_SAMPLE if math_mode else TEXT_STROKE_WEIGHT_SAMPLE
        weighted_total = 0.0
        total_width = 0.0
        for font_path, run in runs:
            sample = _compact_weight_sample(run, fallback_sample)
            run_width = max(1.0, _measure_text(_load_font(font_path, size_px), run))
            weighted_total += _font_optical_weight(font_path, reference_size, sample) * run_width
            total_width += run_width
        if total_width <= 0:
            return self.math_reference_stroke_weight if math_mode else self.reference_stroke_weight
        return weighted_total / total_width

    def _random_stroke_weight_sigma(self, math_mode: bool = False) -> float:
        """Return the per-edge Gaussian sigma at the shared reference size."""
        # The config describes the standard deviation of total stroke-width
        # variation. Morphology moves both edges, so each edge receives half.
        reference_size = (
            self.reference_size_px
            if self.uses_sdt_trajectories
            else self.math_reference_size_px
            if math_mode
            else self.reference_size_px
        )
        scale = self._math_jitter_scale() if math_mode else 1.0
        return max(0.0, reference_size * self.config.stroke_weight_variation_sigma_ratio * scale / 2)

    def _random_stroke_weight_adjustment(self, rand: random.Random, sigma: float) -> float:
        if sigma <= 0:
            return 0.0
        # A three-sigma clamp prevents rare Gaussian tails from closing dense
        # counters while retaining a continuous, zero-centered distribution.
        limit = 3.0 * sigma
        return min(limit, max(-limit, rand.gauss(0.0, sigma)))

    def grouped_stroke_weight_adjustment(self, group: str, math_mode: bool = False) -> float:
        """Return one reproducible edge-weight adjustment for a complete writing group."""
        if not self.config.second_layer_enabled:
            return 0.0
        return self._random_stroke_weight_adjustment(
            random.Random(_stable_seed(self.config.seed, "stroke-weight", group)),
            self._random_stroke_weight_sigma(math_mode=math_mode),
        )

    def uniform_pen_width_px(self) -> float:
        """Return the shared text, formula and generated-rule pen width."""
        canonical = max(1.0, self.config.sdt_stroke_width)
        return max(0.5, canonical * self.reference_size_px / 256.0)

    def _trajectory_style(self, math_mode: bool = False) -> TrajectoryStyle:
        jitter_scale = self._math_jitter_scale() if math_mode else 1.0
        return TrajectoryStyle(
            rotation_sigma_deg=self._glyph_rotation_sigma_degrees(math_mode=math_mode),
            coordinate_jitter=max(0.0, self.config.sdt_coordinate_jitter * jitter_scale),
            jitter_correlation=max(1.0, self.config.sdt_jitter_correlation),
            width_jitter=min(0.8, max(0.0, self.config.sdt_width_jitter * jitter_scale)),
            taper=min(0.8, max(0.0, self.config.sdt_taper)),
            supersample=max(1, min(6, self.config.sdt_supersample)),
        )

    def _math_jitter_scale(self) -> float:
        return min(1.0, max(0.0, float(self.config.math_jitter_scale)))

    def _glyph_rotation_sigma_degrees(self, math_mode: bool = False) -> float:
        scale = self._math_jitter_scale() if math_mode else 1.0
        base = max(0.0, math.degrees(self.config.perturb_theta_sigma) * scale)
        return math.hypot(base, max(0.0, min(4.0, self.config.math_character_rotation_deg))) if math_mode else base

    def _glyph_position_sigma(
        self,
        size_px: int,
        configured: float | None,
        math_mode: bool = False,
    ) -> float:
        """Use one position-jitter rule in SDT, Handright and Pillow modes."""
        base = max(0.0, configured) if configured is not None else size_px * 0.015
        if math_mode:
            return base * self._math_jitter_scale()
        return max(0.2, base)

    def _advance_jitter_sigma(self, size_px: int, math_mode: bool = False) -> float:
        scale = self._math_jitter_scale() if math_mode else 1.0
        return max(0.0, size_px * self.config.advance_jitter_sigma_ratio * scale)

    def _vertical_position_sigma(self, size_px: int, math_mode: bool = False) -> float:
        if math_mode:
            return max(0.0, size_px * self.config.math_perturb_y_sigma_ratio * self._math_jitter_scale())
        return self._glyph_position_sigma(size_px, self.config.perturb_y_sigma_px)

    @staticmethod
    def _sample_position_offset(rand: random.Random, sigma: float) -> float:
        """Sample a centered Gaussian offset while rejecting destructive tails."""
        sigma = max(0.0, float(sigma))
        if sigma == 0:
            return 0.0
        limit = 3.0 * sigma
        return min(limit, max(-limit, rand.gauss(0.0, sigma)))

    @staticmethod
    def _disorder_offset(seed: int, index: int, size_px: int, strength: float) -> tuple[float, float]:
        """Mix small and occasional larger independent offsets, without a periodic wave."""
        if strength <= 0:
            return 0.0, 0.0
        rng = random.Random(_stable_seed(seed, index, "position-disorder"))
        magnitude = rng.uniform(0.25, 0.8) if rng.random() < 0.7 else rng.uniform(0.8, 1.6)
        dx = rng.uniform(-1.0, 1.0) * size_px * 0.08 * strength * magnitude
        dy = rng.uniform(-1.0, 1.0) * size_px * 0.30 * strength * magnitude
        return dx, dy

    def _position_jitter_padding(self, x_sigma: float, y_sigma: float) -> int:
        """Reserve enough room for every accepted position-jitter sample."""
        return max(8, math.ceil(3.0 * max(0.0, x_sigma, y_sigma) + 4.0))

    def _estimated_rendered_baseline(
        self,
        text: str,
        size_px: int,
        image: Image.Image,
        math: bool = False,
    ) -> int:
        """Estimate a typographic baseline for fallback renderers after cropping."""
        ink_bbox = image.getchannel("A").getbbox()
        if ink_bbox is None:
            return max(1, round(size_px * 0.75))
        distances: list[int] = []
        for char in text:
            if char.isspace():
                continue
            font = _load_font(self._font_path_for_char(char, size_px, math=math), size_px)
            bbox = font.getbbox(char)
            if bbox is not None:
                distances.append(font.getmetrics()[0] - bbox[1] - self._glyph_vertical_adjustment(char, size_px))
        return max(1, round(ink_bbox[1] + max(distances, default=size_px * 0.75)))

    @lru_cache(maxsize=32)
    def _uniform_ink_target_weight(self) -> float:
        size = max(16, self.reference_size_px)
        # Calibrate against a constant-width handwritten stroke at the actual
        # output size, so antialiasing is included in the optical target.
        probe = render_strokes(
            (np.array([[0, 20], [12, 20], [12, 0], [12, 20], [35, 20]], dtype=np.float32),),
            size, max(16, round(size * 0.9)), self.uniform_pen_width_px(), self.ink,
            np.random.default_rng(0),
            TrajectoryStyle(rotation_sigma_deg=0, coordinate_jitter=0, width_jitter=0, taper=0, supersample=4),
            em_size=size,
        )
        return _estimate_optical_stroke_weight(probe.getchannel("A"))

    def _normalize_glyph_ink(self, glyph: Image.Image, *, preserve_weight: bool = False) -> Image.Image:
        if not self.config.uniform_ink_enabled:
            return glyph
        alpha = glyph.getchannel("A")
        peak = alpha.getextrema()[1]
        if not peak:
            return glyph
        # Equalize ink opacity without thresholding away antialiased boundaries.
        if peak < 255:
            gain = min(4.0, 255.0 / peak)
            alpha = alpha.point([min(255, round(value * gain)) for value in range(256)])
        if not preserve_weight:
            adjustment = _solve_stroke_weight_adjustment(
                alpha, self._uniform_ink_target_weight(), MAX_STROKE_WEIGHT_ADJUSTMENT_PX,
            )
            alpha = _adjust_stroke_weight(alpha, adjustment)
        normalized = Image.new("RGBA", glyph.size, self.ink)
        normalized.putalpha(alpha)
        return normalized

    @lru_cache(maxsize=2048)
    def _reference_glyph_mask(self, char: str) -> Image.Image | None:
        if self.reference_glyph_path is None:
            return None
        path = self.reference_glyph_path / f"{ord(char):04x}.png"
        if not path.is_file():
            return None
        with Image.open(path) as source:
            if source.mode == "RGBA" and source.getchannel("A").getextrema() != (255, 255):
                mask = source.getchannel("A").copy()
            else:
                gray = np.asarray(source.convert("L"), dtype=np.uint8)
                mask = Image.fromarray(255 - gray)
        bbox = mask.getbbox()
        return mask.crop(bbox) if bbox else None

    def _render_reference_glyph(self, char: str, width: int, height: int) -> Image.Image | None:
        mask = self._reference_glyph_mask(char)
        if mask is None:
            return None
        # Match the trajectory renderer's margin, retaining the source aspect ratio
        # and local ink thickness instead of redrawing it with a uniform pen.
        margin = max(1, round(min(width, height) * 0.045))
        inner_width, inner_height = max(1, width - 2 * margin), max(1, height - 2 * margin)
        scale = min(inner_width / mask.width, inner_height / mask.height)
        resized = mask.resize((max(1, round(mask.width * scale)), max(1, round(mask.height * scale))), Image.Resampling.LANCZOS)
        alpha = Image.new("L", (width, height), 0)
        alpha.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
        glyph = Image.new("RGBA", (width, height), self.ink)
        glyph.putalpha(alpha)
        return glyph

    def _render_with_trajectories(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed: int,
        math: bool = False,
        return_baseline: bool = False,
        corrections: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        """Compose SDT and derived symbol trajectories directly onto a text line."""
        rand = random.Random(seed)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px, math_mode=math)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        strength = self.config.position_disorder / 100.0 if corrections and not math else 0.0
        pad = max(
            round(size_px * 0.4),
            self._position_jitter_padding(x_sigma, y_sigma) + int(size_px * 0.48 * strength + 0.999),
        )
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        descent = max(_load_font(font_path, size_px).getmetrics()[1] for font_path, _ in runs)
        max_adjustment = max(self._glyph_vertical_adjustment(char, size_px) for char in text)
        line_height = max(round(size_px * self.config.line_spacing), reference_ascent + descent + 2 * pad + max_adjustment)
        width = self._line_canvas_width(text, size_px, pad, math_mode=math)
        image = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = float(pad)
        baseline = pad + reference_ascent
        style = self._trajectory_style(math_mode=math)
        pen_width = self.uniform_pen_width_px()
        for index, char in enumerate(text):
            if index:
                x += self._script_boundary_spacing(text[index - 1], char, size_px, math=math)
            font_path = self._font_path_for_char(char, size_px, math=math)
            font = _load_font(font_path, size_px)
            if char.isspace():
                x += self.character_advance(char, size_px, math=math)
                continue
            bbox = font.getbbox(char)
            if bbox is None:
                x += self._sample_character_advance(char, size_px, rand, math=math)
                continue
            if self.config.handwritten_quotes and not math and char in "“”":
                quote_width = max(4, round(size_px * 0.30))
                quote_height = max(4, round(size_px * 0.22))
                left = round(size_px * 0.055)
                top = font.getmetrics()[0] - round(size_px * 0.88)
                bbox = (left, top, left + quote_width, top + quote_height)
            if self.config.handwritten_punctuation and not math and char in "。、":
                left = round(size_px * 0.06)
                top = font.getmetrics()[0] - round(size_px * 0.22)
                symbol_size = max(5, round(size_px * (0.16 if char == "。" else 0.19)))
                bbox = (left, top, left + symbol_size, top + symbol_size)
            glyph_width = max(1, bbox[2] - bbox[0])
            glyph_height = max(1, bbox[3] - bbox[1])
            if char == "一" and self.config.natural_one and not math:
                inset = round(glyph_width * 0.12)
                bbox = (bbox[0] + inset, bbox[1], bbox[2] - inset, bbox[3])
                glyph_width = bbox[2] - bbox[0]
                extra_height = max(0, round(size_px * 0.16) - glyph_height)
                bbox = (bbox[0], bbox[1] - extra_height // 2, bbox[2], bbox[3] + extra_height - extra_height // 2)
                glyph_height = bbox[3] - bbox[1]
            glyph = self._render_reference_glyph(char, glyph_width, glyph_height) if not math or _is_cjk_ideograph(char) else None
            is_reference = glyph is not None
            strokes = self.trajectory_store.load(char) if glyph is None else None
            if glyph is None and strokes is None:
                strokes = font_glyph_strokes(font_path, char)
            if self.config.handwritten_quotes and not math and char in "“”":
                # Two short slanted pen strokes at the top of the character cell.
                direction = 1 if char == "“" else -1
                strokes = tuple(np.array([[x + direction * 0.12, 0.0], [x, 0.45], [x - direction * 0.08, 1.0]], dtype=np.float32) for x in (0.0, 0.8))
                glyph = None
            if self.config.handwritten_punctuation and not math and char in "。、":
                if char == "。":
                    # A small, slightly uneven loop with an imperfect join.
                    strokes = (np.array([[0.66, 0.08], [0.35, 0.10], [0.13, 0.29], [0.10, 0.58], [0.26, 0.83], [0.52, 0.91], [0.78, 0.77], [0.87, 0.51], [0.78, 0.29], [0.57, 0.18], [0.40, 0.25]], dtype=np.float32),)
                else:
                    strokes = (np.array([[0.0, 0.0], [0.32, 0.26], [0.65, 0.61], [0.8, 1.0]], dtype=np.float32),)
                glyph = None
            if char == "1" and self.config.handwritten_digit_one:
                strokes = (np.array([[0.14, 0.0], [0.12, 0.2], [0.09, 0.4], [0.06, 0.6], [0.03, 0.8], [0.0, 1.0]], dtype=np.float32),)
                glyph = None
            if char == "一" and self.config.natural_one and not math and strokes:
                strokes = tuple(stroke.copy() for stroke in strokes)
                for stroke in strokes:
                    span = max(float(np.ptp(stroke[:, 0])), 1.0)
                    t = (stroke[:, 0] - stroke[:, 0].min()) / span
                    stroke[:, 1] += span * (-0.06 * t - 0.035 * np.sin(np.pi * t))
            if glyph is not None:
                pass
            elif strokes:
                glyph = render_strokes(
                    strokes,
                    glyph_width,
                    glyph_height,
                    pen_width * (2.0 if char == "。" and self.config.handwritten_punctuation and not math else 1.0),
                    self.ink,
                    np.random.default_rng(_stable_seed(seed, index, char, "trajectory")),
                    style,
                    em_size=size_px,
                )
            else:
                glyph = Image.new("RGBA", (glyph_width, glyph_height), (0, 0, 0, 0))
                ImageDraw.Draw(glyph).text((-bbox[0], -bbox[1]), char, fill=self.ink, font=font)
            if not (char == "。" and self.config.handwritten_punctuation and not math):
                glyph = self._normalize_glyph_ink(glyph, preserve_weight=is_reference and self.config.reference_preserve_stroke_weight)
            glyph, shear_pad = self._correct_latin_slant(
                glyph,
                char,
                font_path,
                baseline_y=font.getmetrics()[0] - bbox[1],
                math_mode=math,
            )
            disorder_x, disorder_y = self._disorder_offset(seed, index, size_px, strength)
            glyph_x = round(x + bbox[0] - shear_pad + self._sample_position_offset(rand, x_sigma) + disorder_x)
            glyph_y = round(
                baseline
                - font.getmetrics()[0]
                + bbox[1]
                + self._glyph_vertical_adjustment(char, size_px)
                + self._sample_position_offset(rand, y_sigma) + disorder_y
            )
            image.alpha_composite(glyph, (glyph_x, glyph_y))
            if corrections and not math:
                self._draw_correction(image, glyph, glyph_x, glyph_y, char, size_px, seed, index)
            x += self._sample_character_advance(char, size_px, rand, math=math)
        cropped, _, crop_top = _crop_alpha_with_offset(image, pad=4)
        rendered_baseline = round(baseline - crop_top)
        return (cropped, rendered_baseline) if return_baseline else cropped

    def _render_with_handright(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False) -> Image.Image:
        rand = random.Random(seed)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px, math_mode=math)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        jitter_pad = self._position_jitter_padding(x_sigma, y_sigma)
        pad_x = max(jitter_pad, round(size_px * 0.35))
        pad_y = max(jitter_pad, round(size_px * 0.35))
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        max_shift = max(
            self._baseline_shift(font_path, size_px, reference_ascent) + self._run_vertical_adjustment(run, size_px)
            for font_path, run in runs
        )
        run_height = max(size_px + 2 * pad_y, round(size_px * self.config.line_spacing))
        line_height = run_height + 2 * pad_y + max_shift
        width = self._line_canvas_width(text, size_px, pad_x, math_mode=math)
        background = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = float(pad_x)
        # Handright advances by glyph bounding boxes, rather than font advances,
        # and uses a different space width. Let it draw glyphs while sharing the
        # same positioning as SDT/Pillow, including across fallback font runs.
        for index, char in enumerate(text):
            if index:
                x += self._script_boundary_spacing(text[index - 1], char, size_px, math=math)
            if char.isspace():
                x += self.character_advance(char, size_px, math=math)
                continue
            font_path = self._font_path_for_char(char, size_px, math=math)
            run_image = self._render_handright_run(
                char,
                size_px,
                max_width,
                _stable_seed(seed, index),
                font_path,
                math_mode=math,
            )
            run_image, shear_pad = self._correct_latin_slant(
                run_image,
                char,
                font_path,
                baseline_y=pad_y + _load_font(font_path, size_px).getmetrics()[0],
                math_mode=math,
            )
            y = (
                pad_y
                + self._baseline_shift(font_path, size_px, reference_ascent)
                + self._glyph_vertical_adjustment(char, size_px)
            )
            background.alpha_composite(run_image, (round(x - pad_x - shear_pad), y))
            x += self._sample_character_advance(char, size_px, rand, math=math)
        return _crop_alpha(background, pad=4)

    def _render_handright_run(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed: int,
        font_path: str,
        math_mode: bool = False,
    ) -> Image.Image:
        font = _load_font(font_path, size_px)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px, math_mode=math_mode)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math_mode)
        jitter_pad = self._position_jitter_padding(x_sigma, y_sigma)
        pad_x = max(jitter_pad, round(size_px * 0.35))
        pad_y = max(jitter_pad, round(size_px * 0.35))
        ascent, descent = font.getmetrics()
        line_height = max(ascent + descent + 2 * pad_y, round(size_px * self.config.line_spacing))
        width = max(size_px + 2 * pad_x, self._line_canvas_width(text, size_px, pad_x, math_mode=math_mode))
        background = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        template = Template(
            background=background,
            font=font,
            line_spacing=size_px,
            fill=self.ink,
            left_margin=pad_x,
            top_margin=pad_y,
            right_margin=pad_x,
            bottom_margin=0,
            word_spacing=0,
            word_spacing_sigma=0,
            font_size_sigma=0,
            line_spacing_sigma=0,
            perturb_x_sigma=x_sigma,
            perturb_y_sigma=y_sigma,
            perturb_theta_sigma=(
                self.config.perturb_theta_sigma * self._math_jitter_scale()
                if math_mode
                else self.config.perturb_theta_sigma
            ),
        )
        image = next(iter(handwrite(text, template, seed=seed))).convert("RGBA")
        return image

    def _render_with_pillow(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False, corrections: bool = False) -> Image.Image:
        rand = random.Random(seed)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px, math_mode=math)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        strength = self.config.position_disorder / 100.0 if corrections and not math else 0.0
        pad = max(
            round(size_px * 0.4),
            self._position_jitter_padding(x_sigma, y_sigma) + int(size_px * 0.48 * strength + 0.999),
        )
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        descent = max(_load_font(font_path, size_px).getmetrics()[1] for font_path, _ in runs)
        max_adjustment = max(self._glyph_vertical_adjustment(char, size_px) for char in text)
        line_height = max(round(size_px * self.config.line_spacing), reference_ascent + descent + 2 * pad + max_adjustment)
        width = self._line_canvas_width(text, size_px, pad, math_mode=math)
        image = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = pad
        baseline = pad + reference_ascent
        word_bounds = None
        word_start = 0
        for index, char in enumerate(text):
            if index:
                x += self._script_boundary_spacing(text[index - 1], char, size_px, math=math)
            font_path = self._font_path_for_char(char, size_px, math=math)
            font = _load_font(font_path, size_px)
            if char.isspace():
                x += self.character_advance(char, size_px, math=math)
                continue
            bbox = font.getbbox(char)
            if bbox is None:
                x += self._sample_character_advance(char, size_px, rand, math=math)
                continue
            char_w = max(1, bbox[2] - bbox[0])
            glyph = Image.new("RGBA", (char_w + 2 * pad, line_height), (0, 0, 0, 0))
            glyph_draw = ImageDraw.Draw(glyph)
            glyph_y = baseline - font.getmetrics()[0] + self._glyph_vertical_adjustment(char, size_px)
            if char == "1" and self.config.handwritten_digit_one:
                # A single vertical pen stroke, aligned with the original digit's
                # cap height and baseline in both ordinary text and formulas.
                center_x = pad + (bbox[0] + bbox[2]) / 2
                top = glyph_y + bbox[1]
                bottom = glyph_y + bbox[3] - 1
                pen = max(1, round(_font_optical_weight(self.font_path, size_px, TEXT_STROKE_WEIGHT_SAMPLE)))
                glyph_draw.line((center_x, top, center_x, bottom), fill=self.ink, width=pen)
            elif char == "." and self.config.legible_decimal_point:
                pen = max(2, round(_font_optical_weight(self.font_path, size_px, TEXT_STROKE_WEIGHT_SAMPLE) * 1.3))
                center_x = pad + (bbox[0] + bbox[2]) / 2
                center_y = glyph_y + bbox[3] - pen / 2
                glyph_draw.ellipse((center_x - pen / 2, center_y - pen / 2,
                                    center_x + pen / 2, center_y + pen / 2), fill=self.ink)
            elif self.config.handwritten_punctuation and not math and char in "。、":
                pen = max(1, round(_font_optical_weight(self.font_path, size_px, TEXT_STROKE_WEIGHT_SAMPLE)))
                left = pad + round(size_px * 0.08)
                bottom = baseline - round(size_px * 0.03)
                side = max(3, round(size_px * 0.13))
                if char == "。":
                    glyph_draw.ellipse((left, bottom - side, left + side, bottom), outline=self.ink, width=pen)
                else:
                    glyph_draw.line((left, bottom - side, left + side, bottom), fill=self.ink, width=pen)
            else:
                glyph_draw.text((pad, glyph_y), char, fill=self.ink, font=font)
                if self.config.uniform_ink_enabled and _is_latin_text_character(char) and char.isalnum():
                    # Match Latin letters and digits to the body font, without
                    # flattening the expressive variation of Chinese strokes.
                    alpha = glyph.getchannel("A")
                    target = _font_optical_weight(self.font_path, size_px, TEXT_STROKE_WEIGHT_SAMPLE)
                    adjustment = _solve_stroke_weight_adjustment(alpha, target, MAX_STROKE_WEIGHT_ADJUSTMENT_PX)
                    glyph.putalpha(_adjust_stroke_weight(alpha, adjustment))
            glyph, shear_pad = self._correct_latin_slant(
                glyph,
                char,
                font_path,
                baseline_y=pad + reference_ascent - bbox[1] + self._glyph_vertical_adjustment(char, size_px),
                math_mode=math,
            )
            angle = rand.gauss(0, self._glyph_rotation_sigma_degrees(math_mode=math))
            glyph = glyph.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
            disorder_x, disorder_y = self._disorder_offset(seed, index, size_px, strength)
            glyph_x = round(x - pad - shear_pad + self._sample_position_offset(rand, x_sigma) + disorder_x)
            glyph_y = round(self._sample_position_offset(rand, y_sigma) + disorder_y)
            image.alpha_composite(glyph, (glyph_x, glyph_y))
            if corrections and not math:
                self._draw_correction(image, glyph, glyph_x, glyph_y, char, size_px, seed, index)
                if self.config.latin_word_corrections and self.config.correction_probability > 0 and char.isascii() and char.isalpha():
                    box = glyph.getchannel("A").getbbox()
                    if box:
                        current = (glyph_x + box[0], glyph_y + box[1], glyph_x + box[2], glyph_y + box[3])
                        if word_bounds is None:
                            word_bounds = current
                            word_start = index
                        else:
                            word_bounds = (min(word_bounds[0], current[0]), min(word_bounds[1], current[1]),
                                           max(word_bounds[2], current[2]), max(word_bounds[3], current[3]))
                    next_is_letter = index + 1 < len(text) and text[index + 1].isascii() and text[index + 1].isalpha()
                    if not next_is_letter and word_bounds:
                        left, top, right, bottom = word_bounds
                        left, top = max(0, left), max(0, top)
                        right, bottom = min(image.width, right), min(image.height, bottom)
                        if right > left and bottom > top:
                            word = text[word_start:index + 1]
                            self._draw_correction(image, image.crop((left, top, right, bottom)), left, top,
                                                  word, size_px, seed, word_start, latin_word=True)
                        word_bounds = None
            x += self._sample_character_advance(char, size_px, rand, math=math)
        return _crop_alpha(image, pad=4)

    def _draw_correction(self, image: Image.Image, glyph: Image.Image, x: int, y: int,
                         char: str, size: int, seed: int, index: int, latin_word: bool = False) -> None:
        # Correct Chinese characters and whole Latin words; skip punctuation and numbers.
        if not latin_word and not _is_cjk_ideograph(char):
            return
        rand = random.Random(_stable_seed(seed, index, char, "correction"))
        if rand.random() >= self.config.correction_probability / 100:
            return
        box = glyph.getchannel("A").getbbox()
        if not box:
            return
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        # Prepare a full replacement at 85% size. Page-level placement chooses
        # a separate, unoccupied position after all text has been laid out.
        rewrite = glyph.crop(box)
        rewrite = rewrite.resize((max(1, round(width * .85)), max(1, round(height * .85))), Image.Resampling.LANCZOS)
        # Recover a little pen weight lost during downsampling, without changing
        # the ink color or opacity relative to the surrounding handwriting.
        rewrite.putalpha(_adjust_stroke_weight(rewrite.getchannel("A"), min(.45, size * .005)))
        strike = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(strike)
        thickness = max(1, round(size * .06))
        for _ in range(rand.randint(2, 3)):
            # Slightly uneven pen sweeps read as a quick crossing-out gesture.
            y_start = rand.uniform(.25, .75)
            y_end = min(.9, max(.1, y_start + rand.uniform(-.30, .30)))
            points = [(round(width * a), round(height * b)) for a, b in (
                (rand.uniform(-.02, .12), y_start),
                (rand.uniform(.40, .62), (y_start + y_end) / 2 + rand.uniform(-.08, .08)),
                (rand.uniform(.90, 1.04), y_end),
            )]
            draw.line(points, fill=self.ink, width=thickness, joint="curve")

        tilt_rng = random.Random(_stable_seed(seed, index, char, "rewrite-tilt"))
        angle = 0.0
        if tilt_rng.random() < .38:
            angle = tilt_rng.choice((-1, 1)) * tilt_rng.uniform(1.5, 5.0)

        # Keep decorations separate until the whole page is available. Future
        # letters and adjacent lines must participate in collision detection.
        image.info.setdefault("correction_marks", []).append({
            "x": x + left, "y": y + top, "width": width, "height": height,
            "rewrite": rewrite, "strike": strike, "angle": angle,
            "seed": _stable_seed(seed, index, char, "rewrite-position"),
        })

    def _font_runs(self, text: str, size_px: int, math: bool = False) -> list[tuple[str, str]]:
        runs: list[tuple[str, str]] = []
        for char in text:
            font_path = self._font_path_for_char(char, size_px, math=math)
            if (
                runs
                and runs[-1][0] == font_path
                and self._run_vertical_adjustment(runs[-1][1], size_px) == self._glyph_vertical_adjustment(char, size_px)
            ):
                runs[-1] = (font_path, runs[-1][1] + char)
            else:
                runs.append((font_path, char))
        return runs

    def _font_path_for_char(self, char: str, size_px: int, math: bool = False) -> str:
        paths = self.math_font_paths if math else self.font_paths
        if char.isspace():
            return paths[0]
        if not math and self.latin_font_path and _is_latin_text_character(char):
            if _has_glyph(self.latin_font_path, size_px, char):
                return self.latin_font_path
        for font_path in paths:
            if _has_glyph(font_path, size_px, char):
                return font_path
        return paths[-1]

    def _correct_latin_slant(
        self,
        image: Image.Image,
        char: str,
        font_path: str,
        baseline_y: int,
        math_mode: bool = False,
    ) -> tuple[Image.Image, int]:
        """Reduce a selected Latin font's built-in slant while preserving its baseline."""
        correction = self.config.latin_upright_correction_deg
        if (
            math_mode
            or (char == "1" and self.config.handwritten_digit_one)
            or (char == "." and self.config.legible_decimal_point)
            or not self.latin_font_path
            or font_path != self.latin_font_path
            or not _is_latin_text_character(char)
            or correction <= 0
        ):
            return image, 0

        shear = math.tan(math.radians(correction))
        left_pad = math.ceil(shear * max(0, baseline_y))
        right_pad = math.ceil(shear * max(0, image.height - baseline_y))
        if left_pad == 0 and right_pad == 0:
            return image, 0
        corrected = image.transform(
            (image.width + left_pad + right_pad, image.height),
            Image.Transform.AFFINE,
            (1, -shear, shear * baseline_y - left_pad, 0, 1, 0),
            resample=Image.Resampling.BICUBIC,
        )
        return corrected, left_pad

    def _reference_ascent(self, runs: list[tuple[str, str]], size_px: int) -> int:
        return max(_load_font(font_path, size_px).getmetrics()[0] for font_path, _ in runs)

    def _baseline_shift(self, font_path: str, size_px: int, reference_ascent: int) -> int:
        ascent = _load_font(font_path, size_px).getmetrics()[0]
        return max(0, reference_ascent - ascent)

    def _glyph_vertical_adjustment(self, char: str, size_px: int) -> int:
        return round(size_px * GLYPH_VERTICAL_ADJUSTMENTS.get(char, 0.0))

    def _run_vertical_adjustment(self, run: str, size_px: int) -> int:
        return self._glyph_vertical_adjustment(run[0], size_px) if run else 0


def wrap_text(
    engine: HandwritingEngine,
    text: str,
    size_px: int,
    max_width: int,
    math: bool = False,
    first_line_width: int | None = None,
) -> list[str]:
    """Wrap without discarding characters or letting a long word overflow.

    Prefer whole words. If a word cannot fit on an empty line, split it by
    character. Closing punctuation travels with its preceding character;
    only an indivisible character/punctuation cluster may exceed the width.
    """
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        remaining = "".join(_wrap_units(raw_line)).strip()
        if not remaining:
            lines.append("")
            continue
        while remaining:
            width = max(1, first_line_width if not lines and first_line_width is not None else max_width)
            fit = 0
            for end in range(1, len(remaining) + 1):
                if engine.measure(remaining[:end], size_px, math=math) > width:
                    break
                fit = end
            if fit == len(remaining):
                lines.append(remaining)
                break

            # Find the latest completed word or character unit that fits.
            boundary = 0
            cursor = 0
            for unit in _wrap_units(remaining):
                cursor += len(unit)
                if cursor > fit:
                    break
                boundary = cursor
            split = boundary or fit or 1
            # Move a preceding character to the next line instead of pushing
            # punctuation outside the right margin of the previous line.
            while split > 0 and starts_with_forbidden_line_punctuation(remaining[split:]):
                split -= 1
            if split == 0:
                # No legal break fits, e.g. a one-character-wide column with
                # a closing quote. Keep the smallest unbreakable cluster.
                split = 1
                while split < len(remaining) and starts_with_forbidden_line_punctuation(remaining[split:]):
                    split += 1
            lines.append(remaining[:split].rstrip())
            remaining = remaining[split:].lstrip()
    return lines


def starts_with_forbidden_line_punctuation(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and stripped[0] in FORBIDDEN_LINE_START_PUNCTUATION


def _wrap_units(text: str) -> list[str]:
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


@lru_cache(maxsize=128)
def _load_font(font_path: str, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size_px)


def _resolve_font(preferred: str | None) -> str:
    return _resolve_font_chain(preferred)[0]


def _resolve_font_chain(preferred: str | None, fallback: str | None = None) -> list[str]:
    paths: list[str] = []

    def add(candidate: Path) -> None:
        resolved = str(candidate.resolve())
        if candidate.is_file() and resolved not in paths:
            paths.append(resolved)

    if preferred:
        for candidate in _preferred_font_candidates(preferred):
            if candidate.is_file():
                add(candidate)
                break

    local_fonts = _local_font_candidates()
    if not paths and local_fonts:
        add(local_fonts[0])

    if fallback:
        for candidate in _preferred_font_candidates(fallback):
            if candidate.is_file():
                add(candidate)
                break

    for candidate in local_fonts:
        add(candidate)
    for candidate in DEFAULT_SYSTEM_FONT_CANDIDATES:
        add(Path(candidate))

    if paths:
        return paths
    raise FileNotFoundError(
        "No usable handwriting font found. Add numbered font files such as font/1.ttf and font/2.ttf, "
        "or set handwriting.font_path in config."
    )


def _preferred_font_candidates(preferred: str) -> list[Path]:
    path = Path(preferred)
    if path.is_absolute():
        return [path]
    return [Path.cwd() / path, PROJECT_ROOT / path]


def _is_latin_text_character(char: str) -> bool:
    if char.isspace():
        return False
    if char.isascii():
        return char.isalnum() or char in string.punctuation
    return unicodedata.name(char, "").startswith("LATIN ")


def _is_latin_word_character(char: str) -> bool:
    if not char.isalnum():
        return False
    return char.isascii() or unicodedata.name(char, "").startswith("LATIN ")


def _is_cjk_ideograph(char: str) -> bool:
    name = unicodedata.name(char, "")
    return name.startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-"))


def _local_font_candidates() -> list[Path]:
    directories = [Path.cwd() / "font", PROJECT_ROOT / "font"]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.iterdir(), key=_font_order_key):
            resolved = candidate.resolve()
            if candidate.is_file() and candidate.suffix.lower() in FONT_EXTENSIONS and resolved not in seen:
                candidates.append(candidate)
                seen.add(resolved)
    return candidates


def _font_order_key(path: Path) -> tuple:
    if path.stem.isdigit():
        return (0, int(path.stem), path.suffix.casefold())
    pieces = tuple(
        (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
        for piece in re.split(r"(\d+)", path.name)
        if piece
    )
    return (1, pieces)


def _measure_text(font: ImageFont.FreeTypeFont, text: str) -> float:
    if not text:
        return 0.0
    scratch = Image.new("L", (1, 1), 0)
    draw = ImageDraw.Draw(scratch)
    return draw.textlength(text, font=font)


@lru_cache(maxsize=8192)
def _character_width(font_path: str, size_px: int, char: str) -> float:
    """Reuse glyph metrics while line breaking measures growing prefixes."""
    return _measure_text(_load_font(font_path, size_px), char)


def _compact_weight_sample(text: str, fallback: str) -> str:
    sample = "".join(char for char in text if not char.isspace())[:32]
    return sample or fallback


@lru_cache(maxsize=512)
def _font_optical_weight(font_path: str, size_px: int, sample: str) -> float:
    font = _load_font(font_path, size_px)
    bbox = font.getbbox(sample)
    if bbox is None:
        return 0.0
    pad = max(4, round(size_px * 0.2))
    width = max(1, bbox[2] - bbox[0] + 2 * pad)
    height = max(1, bbox[3] - bbox[1] + 2 * pad)
    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    draw.text((pad - bbox[0], pad - bbox[1]), sample, fill=255, font=font)
    return _estimate_optical_stroke_weight(alpha)


def _estimate_stroke_width(alpha: Image.Image, threshold: int = 64) -> float:
    """Estimate mean stroke width from mask area lost after one-pixel erosion."""
    if alpha.width < 3 or alpha.height < 3:
        return 1.0 if alpha.getbbox() is not None else 0.0
    histogram = alpha.histogram()
    area = sum(histogram[threshold:])
    if area <= 0:
        return 0.0
    eroded_histogram = alpha.filter(ImageFilter.MinFilter(3)).histogram()
    inner_area = sum(eroded_histogram[threshold:])
    boundary_area = max(1, area - inner_area)
    return 2.0 * area / boundary_area


def _estimate_optical_stroke_weight(alpha: Image.Image) -> float:
    """Combine silhouette width and antialiased ink density into perceived weight."""
    stroke_width = _estimate_stroke_width(alpha)
    if stroke_width <= 0:
        return 0.0
    histogram = alpha.histogram()
    ink_pixels = sum(histogram[1:])
    if ink_pixels <= 0:
        return 0.0
    ink_mass = sum(value * count for value, count in enumerate(histogram))
    mean_opacity = ink_mass / (255.0 * ink_pixels)
    return stroke_width * math.sqrt(max(0.0, min(1.0, mean_opacity)))


def _solve_stroke_weight_adjustment(
    alpha: Image.Image,
    target_weight: float,
    max_adjustment: float,
) -> float:
    """Find the signed subpixel morphology amount closest to an optical target."""
    current_weight = _estimate_optical_stroke_weight(alpha)
    if current_weight <= 0 or target_weight <= 0 or abs(current_weight - target_weight) < 1e-4:
        return 0.0
    direction = 1.0 if current_weight < target_weight else -1.0
    low = 0.0
    high = max(0.0, max_adjustment)
    best_adjustment = 0.0
    best_error = abs(current_weight - target_weight)
    for _ in range(9):
        magnitude = (low + high) / 2
        adjustment = direction * magnitude
        candidate_weight = _estimate_optical_stroke_weight(
            _adjust_stroke_weight(alpha, adjustment)
        )
        error = abs(candidate_weight - target_weight)
        if error < best_error:
            best_adjustment = adjustment
            best_error = error
        if direction > 0:
            if candidate_weight < target_weight:
                low = magnitude
            else:
                high = magnitude
        elif candidate_weight > target_weight:
            low = magnitude
        else:
            high = magnitude
    endpoint_adjustment = direction * max_adjustment
    endpoint_error = abs(
        _estimate_optical_stroke_weight(_adjust_stroke_weight(alpha, endpoint_adjustment))
        - target_weight
    )
    return endpoint_adjustment if endpoint_error < best_error else best_adjustment


def _adjust_stroke_weight(alpha: Image.Image, adjustment_px: float) -> Image.Image:
    """Apply a signed, subpixel morphological weight adjustment to an ink mask."""
    if abs(adjustment_px) < 1e-6:
        return alpha
    amount = min(MAX_STROKE_WEIGHT_ADJUSTMENT_PX, abs(adjustment_px))
    morphology = ImageFilter.MaxFilter(3) if adjustment_px > 0 else ImageFilter.MinFilter(3)
    full_steps = math.floor(amount)
    adjusted = alpha
    for _ in range(full_steps):
        adjusted = adjusted.filter(morphology)
    fraction = amount - full_steps
    if fraction > 1e-6:
        next_step = adjusted.filter(morphology)
        adjusted = Image.blend(adjusted, next_step, fraction)
    return adjusted


def _warp_ink_mask(
    alpha: Image.Image,
    rand: random.Random,
    elastic_strength: float,
    elastic_smoothness: float,
    baseline_amplitude: float,
    baseline_wavelength: float,
) -> Image.Image:
    """Apply one smooth remap containing local elastic and line-level movement."""
    width, height = alpha.size
    if width <= 1 or height <= 1 or (elastic_strength <= 0 and baseline_amplitude <= 0):
        return alpha

    if elastic_strength > 0:
        dx = _smooth_random_field(width, height, elastic_smoothness, rand) * elastic_strength
        dy = _smooth_random_field(width, height, elastic_smoothness, rand) * elastic_strength
    else:
        dx = np.zeros((height, width), dtype=np.float32)
        dy = np.zeros((height, width), dtype=np.float32)

    if baseline_amplitude > 0:
        phase = rand.uniform(0.0, math.tau)
        x = np.arange(width, dtype=np.float32)
        wave = baseline_amplitude * np.sin(math.tau * x / baseline_wavelength + phase)
        dy += wave[np.newaxis, :]

    return Image.fromarray(_bilinear_remap(np.asarray(alpha, dtype=np.float32), dx, dy), mode="L")


def _smooth_random_field(
    width: int,
    height: int,
    smoothness: float,
    rand: random.Random,
) -> np.ndarray:
    """Create a deterministic, normalized low-frequency displacement field."""
    grid_step = max(2, round(smoothness))
    grid_width = max(3, math.ceil(width / grid_step) + 3)
    grid_height = max(3, math.ceil(height / grid_step) + 3)
    samples = np.fromiter(
        (rand.gauss(0.0, 1.0) for _ in range(grid_width * grid_height)),
        dtype=np.float32,
        count=grid_width * grid_height,
    ).reshape((grid_height, grid_width))
    field_image = Image.fromarray(samples, mode="F").resize((width, height), Image.Resampling.BICUBIC)
    field = np.asarray(field_image, dtype=np.float32)
    standard_deviation = float(field.std())
    if standard_deviation > 1e-6:
        field = field / standard_deviation
    return np.clip(field, -2.5, 2.5)


def _bilinear_remap(source: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Sample a grayscale image through a displacement field without OpenCV."""
    height, width = source.shape
    target_y, target_x = np.indices((height, width), dtype=np.float32)
    source_x = target_x + dx
    source_y = target_y + dy
    valid = (source_x >= 0) & (source_x <= width - 1) & (source_y >= 0) & (source_y <= height - 1)

    source_x = np.clip(source_x, 0, width - 1)
    source_y = np.clip(source_y, 0, height - 1)
    x0 = np.floor(source_x).astype(np.int32)
    y0 = np.floor(source_y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    x_weight = source_x - x0
    y_weight = source_y - y0

    top = source[y0, x0] * (1.0 - x_weight) + source[y0, x1] * x_weight
    bottom = source[y1, x0] * (1.0 - x_weight) + source[y1, x1] * x_weight
    remapped = top * (1.0 - y_weight) + bottom * y_weight
    remapped[~valid] = 0
    return np.clip(remapped, 0, 255).astype(np.uint8)


def _vary_ink_density(
    alpha: Image.Image,
    rand: random.Random,
    jitter: float,
    dry_brush_probability: float,
    dry_brush_min_opacity: float,
) -> Image.Image:
    """Add slow ink-flow variation and occasional directional dry-brush fading."""
    jitter = min(1.0, max(0.0, jitter))
    dry_brush_probability = min(1.0, max(0.0, dry_brush_probability))
    dry_brush_min_opacity = min(1.0, max(0.0, dry_brush_min_opacity))
    if jitter <= 0 and (dry_brush_probability <= 0 or dry_brush_min_opacity >= 1):
        return alpha

    values = np.asarray(alpha, dtype=np.float32).copy()
    height, width = values.shape
    if jitter > 0:
        phase = rand.uniform(0.0, math.tau)
        cycles = rand.uniform(0.5, 1.8)
        x = np.linspace(0.0, math.tau * cycles, width, dtype=np.float32)
        flow = 1.0 - jitter * (0.3 + 0.7 * (0.5 + 0.5 * np.sin(x + phase)))
        values *= flow[np.newaxis, :]

    if rand.random() < dry_brush_probability and dry_brush_min_opacity < 1:
        direction = rand.choice(("left", "right", "top", "bottom"))
        length = width if direction in {"left", "right"} else height
        gradient = np.linspace(dry_brush_min_opacity, 1.0, length, dtype=np.float32)
        if direction in {"right", "bottom"}:
            gradient = gradient[::-1]
        values *= gradient[np.newaxis, :] if direction in {"left", "right"} else gradient[:, np.newaxis]

    return Image.fromarray(np.clip(values, 0, 255).astype(np.uint8), mode="L")


@lru_cache(maxsize=4096)
def _has_glyph(font_path: str, size_px: int, char: str) -> bool:
    font = _load_font(font_path, size_px)
    missing = "\u0378"
    return (font.getbbox(char), bytes(font.getmask(char))) != (
        font.getbbox(missing),
        bytes(font.getmask(missing)),
    )


def _crop_alpha(image: Image.Image, pad: int = 0) -> Image.Image:
    return _crop_alpha_with_offset(image, pad)[0]


def _crop_alpha_with_offset(image: Image.Image, pad: int = 0) -> tuple[Image.Image, int, int]:
    """Crop transparent margins and retain the origin needed for baseline tracking."""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, image.height), (0, 0, 0, 0)), 0, 0
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(image.width, bbox[2] + pad)
    bottom = min(image.height, bbox[3] + pad)
    cropped = image.crop((left, top, right, bottom))
    if "correction_marks" in image.info:
        cropped.info["correction_marks"] = transform_correction_marks(
            image.info["correction_marks"], -left, -top)
    return cropped, left, top


def _stable_seed(*parts: object) -> int:
    joined = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)
