"""Optimizations must preserve random draws and the original ink geometry."""
import math

import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.sdt_renderer import _smooth_noise
from markdown_to_handwrite.handwriting import (
    _adjust_stroke_weight, _estimate_optical_stroke_weight,
    _solve_stroke_weight_adjustment,
)


def test_noise_matches_original_interpolation_and_rng_state():
    for count in (1, 2, 7, 100, 501):
        for dimensions in (1, 2):
            for sigma in (0.0, 0.5):
                before = np.random.default_rng(2026)
                after = np.random.default_rng(2026)
                if sigma == 0:
                    expected = np.zeros((count, dimensions) if dimensions > 1 else (count,), dtype=np.float32)
                else:
                    knots = max(3, math.ceil(max(count - 1, 1) / 8.0) + 1)
                    values = before.normal(0, sigma, size=(knots, dimensions))
                    expected = np.stack([np.interp(np.arange(count), np.linspace(0, max(count - 1, 1), knots), values[:, axis]) for axis in range(dimensions)], axis=1)
                    if dimensions == 1:
                        expected = expected[:, 0]
                np.testing.assert_array_equal(_smooth_noise(after, count, sigma, 8.0, dimensions), expected)
                assert before.random() == after.random()


def test_weight_search_matches_uncached_morphology():
    alpha = Image.new('L', (60, 70))
    draw = ImageDraw.Draw(alpha)
    draw.line((8, 12, 44, 55), fill=190, width=5)
    draw.ellipse((15, 15, 50, 60), outline=255, width=2)
    # Reference search applies fresh morphology to every candidate mask.
    for target in (0.5, 2.0, 4.0, 8.0):
        current = _estimate_optical_stroke_weight(alpha)
        direction = 1 if current < target else -1
        low, high, best, error = 0.0, 3.0, 0.0, abs(current - target)
        for _ in range(9):
            magnitude = (low + high) / 2
            weight = _estimate_optical_stroke_weight(_adjust_stroke_weight(alpha, direction * magnitude))
            if abs(weight - target) < error:
                best, error = direction * magnitude, abs(weight - target)
            if (direction > 0 and weight < target) or (direction < 0 and weight > target):
                low = magnitude
            else:
                high = magnitude
        endpoint = direction * 3.0
        if abs(_estimate_optical_stroke_weight(_adjust_stroke_weight(alpha, endpoint)) - target) < error:
            best = endpoint
        assert _solve_stroke_weight_adjustment(alpha, target, 3.0) == best


def test_fast_morphology_matches_pillow_including_edges_and_thin_masks():
    from PIL import ImageFilter
    from markdown_to_handwrite.handwriting import _morph_ink_mask
    rng = np.random.default_rng(42)
    for width, height in ((1, 1), (1, 30), (30, 1), (2, 2), (3, 5), (67, 83), (1800, 100)):
        image = Image.fromarray(rng.integers(0, 256, (height, width), dtype=np.uint8))
        for dilate in (False, True):
            original = ImageFilter.MaxFilter(3) if dilate else ImageFilter.MinFilter(3)
            assert _morph_ink_mask(image, dilate=dilate).tobytes() == image.filter(original).tobytes()
    # Preserve the old behavior if a caller supplies a multichannel image.
    rgb = image.convert('RGB')
    assert _morph_ink_mask(rgb, dilate=True).tobytes() == rgb.filter(ImageFilter.MaxFilter(3)).tobytes()


def test_prepared_glyph_cache_preserves_randomness_and_invalidates_on_settings():
    from unittest.mock import patch
    from markdown_to_handwrite.config import HandwritingConfig
    from markdown_to_handwrite.handwriting import HandwritingEngine
    config = HandwritingConfig(sdt_trajectory_enabled=False, prefer_handright=False,
                               uniform_ink_enabled=True)
    cached = HandwritingEngine(config)
    reference = HandwritingEngine(HandwritingConfig(**vars(config)))
    prepare = reference._prepared_pillow_glyph

    def uncached(*args, **kwargs):
        reference._pillow_glyphs.clear()
        reference._pillow_glyph_bytes = 0
        return prepare(*args, **kwargs)

    images = []
    with patch.object(reference, '_prepared_pillow_glyph', side_effect=uncached):
        for correction in (0.0, 12.0):
            cached.config.latin_upright_correction_deg = correction
            reference.config.latin_upright_correction_deg = correction
            for seed in ('first', 'second'):
                actual = cached.render_line('测试 Test 111. Test 测试。', 48, 1200, seed_extra=seed, corrections=True)
                expected = reference.render_line('测试 Test 111. Test 测试。', 48, 1200, seed_extra=seed, corrections=True)
                assert actual.size == expected.size
                assert actual.tobytes() == expected.tobytes()
                images.append(actual.tobytes())
    assert images[0] != images[1]
    assert cached._pillow_glyph_bytes <= 8 * 1024 * 1024
    assert len(cached._pillow_glyphs) <= 512


def test_prepared_glyph_cache_evicts_large_glyphs():
    from markdown_to_handwrite.config import HandwritingConfig
    from markdown_to_handwrite.handwriting import HandwritingEngine
    engine = HandwritingEngine(HandwritingConfig(sdt_trajectory_enabled=False, prefer_handright=False))
    for index, char in enumerate('ABCDEFGHIJKL'):
        font_path = engine._font_path_for_char(char, 48)
        bbox = engine.font(48).getbbox(char)
        engine._prepared_pillow_glyph(char, font_path, 48, 48, 3000, 100, 60, False, bbox)
        assert engine._pillow_glyph_bytes <= 8 * 1024 * 1024
    assert len(engine._pillow_glyphs) < 12
