from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from markdown_to_handwrite.config import HandwritingConfig
from markdown_to_handwrite.handwriting import HandwritingEngine

def test_photo_glyph_is_used_for_chinese_in_text_and_math():
    with TemporaryDirectory() as directory:
        image = Image.new('L', (30, 30), 'white')
        ImageDraw.Draw(image).rectangle((10, 5, 15, 25), fill='black')
        image.save(Path(directory) / '4e0a.png')
        config = HandwritingConfig(reference_glyph_path=directory, uniform_ink_enabled=True)
        engine = HandwritingEngine(config)
        with patch.object(engine, '_render_reference_glyph', wraps=engine._render_reference_glyph) as render:
            engine._render_with_trajectories('上', 60, 400, 42)
            assert render.call_count == 1
            engine._render_with_trajectories('上', 60, 400, 42, math=True)
            assert render.call_count == 2
            engine._render_with_trajectories('x', 60, 400, 42, math=True)
            assert render.call_count == 2
        assert engine._reference_glyph_mask('上').getbbox()
        assert engine._reference_glyph_mask('下') is None


def test_reference_punctuation_preserves_font_outline(tmp_path):
    config = HandwritingConfig(reference_glyph_path=str(tmp_path), uniform_ink_enabled=True,
                               reference_punctuation_font=True)
    engine = HandwritingEngine(config)
    with patch('markdown_to_handwrite.handwriting.font_glyph_strokes', side_effect=AssertionError('punctuation should use font outline')):
        with patch.object(engine, '_normalize_glyph_ink', wraps=engine._normalize_glyph_ink) as normalize:
            image = engine._render_with_trajectories('。', 60, 400, 42)
    assert image.getchannel('A').getbbox()
    assert normalize.call_args.kwargs['preserve_weight'] is True


def test_reference_rotation_is_opt_in_and_reproducible(tmp_path):
    image = Image.new('L', (60, 60), 'white')
    ImageDraw.Draw(image).polygon([(8, 8), (16, 8), (49, 50), (42, 50)], fill='black')
    image.save(tmp_path / '4e0a.png')
    config = HandwritingConfig(reference_glyph_path=str(tmp_path), reference_rotation_sigma_deg=2)
    engine = HandwritingEngine(config)
    first = engine._render_with_trajectories('上上', 60, 400, 42)
    second = engine._render_with_trajectories('上上', 60, 400, 42)
    assert first.tobytes() == second.tobytes()
    unrotated = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path)))
    assert first.tobytes() != unrotated._render_with_trajectories('上上', 60, 400, 42).tobytes()


def test_reference_scale_is_opt_in_and_reproducible(tmp_path):
    image = Image.new('L', (60, 60), 'white')
    ImageDraw.Draw(image).rectangle((10, 8, 48, 52), fill='black')
    image.save(tmp_path / '4e0a.png')
    engine = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path), reference_scale_sigma_ratio=0.03))
    first = engine._render_with_trajectories('上上上', 100, 600, 42)
    assert first.tobytes() == engine._render_with_trajectories('上上上', 100, 600, 42).tobytes()
    default = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path)))
    assert first.tobytes() != default._render_with_trajectories('上上上', 100, 600, 42).tobytes()


def test_reference_exclusion_uses_fallback_and_f_uses_font_outline(tmp_path):
    image = Image.new('L', (30, 30), 'white')
    ImageDraw.Draw(image).rectangle((10, 5, 15, 25), fill='black')
    image.save(tmp_path / '4e0a.png')
    engine = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path),
        reference_glyph_exclude='上', reference_latin_f_outline=True, uniform_ink_enabled=True))
    assert engine._reference_glyph_mask('上') is None
    with patch('markdown_to_handwrite.handwriting.font_glyph_strokes', side_effect=AssertionError('f should use font outline')):
        with patch.object(engine, '_normalize_glyph_ink', wraps=engine._normalize_glyph_ink) as normalize:
            result = engine._render_with_trajectories('f', 60, 400, 42, math=True)
    assert result.getchannel('A').getbbox()
    assert normalize.call_args.kwargs['preserve_weight'] is True


def test_corrected_glyphs_override_original_including_math(tmp_path):
    original = tmp_path / 'original'
    overrides = tmp_path / 'overrides'
    original.mkdir()
    overrides.mkdir()
    for directory, x in ((original, 4), (overrides, 18)):
        image = Image.new('L', (30, 30), 'white')
        ImageDraw.Draw(image).rectangle((x, 4, x + 3, 23), fill='black')
        image.save(directory / '4e0a.png')
    Image.open(overrides / '4e0a.png').save(overrides / '0066.png')
    engine = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(original),
        reference_glyph_overrides_path=str(overrides), reference_latin_f_outline=True))
    with patch('markdown_to_handwrite.handwriting.Image.open', wraps=Image.open) as opened:
        assert engine._reference_glyph_mask('上') is not None
        assert str(opened.call_args.args[0]).startswith(str(overrides))
        assert engine._render_with_trajectories('f', 60, 400, 42, math=True).getchannel('A').getbbox()
        assert str(opened.call_args.args[0]).endswith('0066.png')


def test_corrected_glyph_weight_matching_is_limited(tmp_path):
    import markdown_to_handwrite.handwriting as handwriting

    image = Image.new('L', (40, 40), 'white')
    ImageDraw.Draw(image).rectangle((8, 5, 30, 34), fill='black')
    image.save(tmp_path / '4e0a.png')
    engine = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path),
        reference_glyph_overrides_path=str(tmp_path), reference_override_weight_match=True,
        reference_preserve_stroke_weight=True, uniform_ink_enabled=True))
    with patch.object(handwriting, '_solve_stroke_weight_adjustment', wraps=handwriting._solve_stroke_weight_adjustment) as solve:
        assert engine._render_with_trajectories('上', 60, 400, 42).getchannel('A').getbbox()
    assert any(call.args[2] == 0.3 for call in solve.call_args_list)


def test_reference_chinese_period_has_open_center(tmp_path):
    engine = HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path),
        reference_punctuation_font=True, uniform_ink_enabled=True))
    alpha = engine._render_with_trajectories('。', 100, 400, 42).getchannel('A')
    x0, y0, x1, y1 = alpha.getbbox()
    assert alpha.getpixel(((x0 + x1) // 2, (y0 + y1) // 2)) < 128


def test_ruled_paragraph_uses_all_available_lines_before_page_break():
    from markdown_to_handwrite.config import ReportConfig
    from markdown_to_handwrite.markdown_parser import InlinePart
    from markdown_to_handwrite.renderer import ReportRenderer, _RichLine

    config = ReportConfig()
    config.page.dpi = 96
    config.background.auto_discover = False
    config.background.style = 'lined'
    renderer = ReportRenderer(config)
    glyph = Image.new('RGBA', (20, 16), (0, 0, 0, 255))
    line = _RichLine([(glyph, 13)], 20, 22, 13, font_size_px=20)
    lines = [line] * 4
    while renderer._paper_rule_fit_count(lines) > 3:
        renderer._position_on_paper_rule(line)
        renderer.y += line.height
    assert renderer._paper_rule_fit_count(lines) == 3
    pages = []
    with patch.object(renderer, '_layout_rich_parts', return_value=lines), patch.object(
        renderer, '_paste_rich_line', side_effect=lambda *args, **kwargs: pages.append(len(renderer.pages))
    ):
        renderer._draw_rich_paragraph([InlinePart('text', '测试')])
    assert pages == [1, 1, 1, 2]


def test_explicit_missing_personal_assets_raise_clear_error(tmp_path):
    import pytest

    missing = str(tmp_path / 'missing')
    with pytest.raises(FileNotFoundError, match='照片字形目录不存在'):
        HandwritingEngine(HandwritingConfig(reference_glyph_path=missing))
    with pytest.raises(FileNotFoundError, match='笔迹轨迹库不存在'):
        HandwritingEngine(HandwritingConfig(sdt_trajectory_path=missing))


def test_personal_profile_rejects_missing_explicit_math_font(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError, match="公式字体不存在"):
        HandwritingEngine(HandwritingConfig(reference_glyph_path=str(tmp_path), math_font_path=str(tmp_path / "missing.ttf")))


