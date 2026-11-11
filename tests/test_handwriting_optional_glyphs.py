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


