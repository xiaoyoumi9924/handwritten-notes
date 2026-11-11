from pathlib import Path

from markdown_to_handwrite.config import config_from_dict
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import STATIC_ROOT, build_bootstrap


def test_kalam_preset_renders_calculus_example():
    presets = build_bootstrap()['presets']
    preset = presets['kalam']
    for key in ('font_path', 'latin_font_path', 'math_font_path'):
        assert preset['handwriting.' + key] == 'font/Latin-Kalam-Regular.ttf'
    assert all(set(preset) <= set(other) for other in presets.values())
    assert 'data-font-option="kalam"' in (STATIC_ROOT / 'index.html').read_text()
    config = config_from_dict({'handwriting': {k.split('.', 1)[1]: v for k, v in preset.items()}})
    config.page.dpi = 100
    config.background.auto_discover = False
    source = (Path(__file__).resolve().parents[1] / 'examples/Caveat-Calculus-Original.md').read_text()
    renderer = ReportRenderer(config)
    assert renderer.render(parse_markdown(source))
    assert not renderer.warnings


def test_kalam_controls_affect_exported_english():
    from PIL import ImageChops

    preset = build_bootstrap()['presets']['kalam']
    values = {k.split('.', 1)[1]: v for k, v in preset.items()}
    values.update(seed=42, correction_probability=5, position_disorder=0)
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 100
    config.background.auto_discover = False
    text = ('The quick brown fox jumps over the lazy dog and writes another sentence with many words.\n\n' * 16)
    renderer = ReportRenderer(config)
    corrected = renderer.render(parse_markdown(text))
    assert renderer._placed_corrections

    config.handwriting.correction_probability = 0
    normal_renderer = ReportRenderer(config)
    normal = normal_renderer.render(parse_markdown(text))
    assert not normal_renderer._placed_corrections
    assert ImageChops.difference(corrected[0], normal[0]).getbbox()

    config.handwriting.position_disorder = 80
    disordered = ReportRenderer(config).render(parse_markdown(text))
    assert ImageChops.difference(normal[0], disordered[0]).getbbox()
