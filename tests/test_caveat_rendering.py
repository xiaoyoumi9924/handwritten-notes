from pathlib import Path

from markdown_to_handwrite.config import config_from_dict
from markdown_to_handwrite.handwriting import HandwritingEngine
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import STATIC_ROOT, build_bootstrap


def test_caveat_preset_and_switching():
    presets = build_bootstrap()['presets']
    preset = presets['caveat']
    for key in ('font_path', 'latin_font_path', 'math_font_path'):
        assert preset['handwriting.' + key] == 'font/Latin-Caveat-Regular.ttf'
    assert preset['handwriting.handwritten_digit_one']
    assert preset['handwriting.latin_upright_correction_deg'] == 0
    assert not preset['handwriting.sdt_trajectory_enabled']
    assert all(set(preset) <= set(other) for other in presets.values())
    assert 'data-font-option="caveat"' in (STATIC_ROOT / 'index.html').read_text()


def test_caveat_one_text_math_and_example():
    preset = build_bootstrap()['presets']['caveat']
    settings = {key.split('.', 1)[1]: value for key, value in preset.items()}
    settings.update(perturb_theta_sigma=0, perturb_x_sigma_px=0,
                    perturb_y_sigma_px=0, math_perturb_y_sigma_ratio=0)
    config = config_from_dict({'handwriting': settings})
    engine = HandwritingEngine(config.handwriting)
    for math in (False, True):
        image = engine.render_line('1', 80, 400, math=math)
        left, top, right, bottom = image.getchannel('A').getbbox()
        assert right - left < (bottom - top) / 3
    config.page.dpi = 100
    config.background.auto_discover = False
    renderer = ReportRenderer(config)
    source = (Path(__file__).resolve().parents[1] / 'examples/Caveat-English.md').read_text()
    assert renderer.render(parse_markdown(source))
    assert not renderer.warnings
    assert engine._font_path_for_char('中', 40).endswith('1_SDT.ttf')


def test_caveat_list_formulas_and_code_remain_distinct():
    from markdown_to_handwrite.markdown_parser import CodeBlock, ListBlock
    source = (Path(__file__).resolve().parents[1] / 'examples/Caveat-English.md').read_text()
    blocks = parse_markdown(source)
    formulas = [part.text for block in blocks if isinstance(block, ListBlock)
                for item in block.items for part in item if part.kind == 'math']
    assert any(r'2r \frac{dr}{du}' in text for text in formulas)
    assert any(r'\sqrt{1 +' in text for text in formulas)
    assert any(isinstance(block, CodeBlock) and 'not a formula' in block.text for block in blocks)


def test_caveat_table_rules_use_opaque_body_ink():
    from unittest.mock import patch
    preset = build_bootstrap()['presets']['caveat']
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 300
    config.background.auto_discover = False
    report = ReportRenderer(config)
    with patch.object(report, '_rough_line') as draw:
        report._draw_table_row([100, 100], ([[], []], 60), 0, header=False)
    assert all(call.args[4] == report.engine.ink for call in draw.call_args_list)
    assert all(call.kwargs['width'] >= 4 for call in draw.call_args_list)


def test_list_bracket_math_keeps_list_and_leaves_unclosed_text_alone():
    from markdown_to_handwrite.markdown_parser import ListBlock
    source = '1. First\n\n    \\[\n    \\frac{1}{2}\n    \\]\n\n2. Next\n'
    blocks = parse_markdown(source)
    assert len(blocks) == 1 and isinstance(blocks[0], ListBlock)
    assert len(blocks[0].items) == 2
    assert any(p.kind == 'math' and p.text == r'\frac{1}{2}' for p in blocks[0].items[0])
    unclosed = parse_markdown('1. First\n\n    \\[\n    x+1\n\n2. Next\n')
    assert len(unclosed[0].items) == 2
    assert not any(p.kind == 'math' for p in unclosed[0].items[0])


def test_original_calculus_list_with_unindented_formula_closers():
    from markdown_to_handwrite.markdown_parser import ListBlock
    source = (Path(__file__).resolve().parents[1] / 'examples/Caveat-Calculus-Original.md').read_text()
    blocks = parse_markdown(source)
    numbered = [b for b in blocks if isinstance(b, ListBlock) and b.ordered]
    assert len(numbered) == 1 and len(numbered[0].items) == 7
    for item in numbered[0].items[1:]:
        assert any(part.kind == 'math' and ('\\frac' in part.text or '\\sqrt' in part.text) for part in item)
        assert not any(part.kind == 'text' and '\\frac' in part.text for part in item)
    values = {k.split('.', 1)[1]: v for k, v in build_bootstrap()['presets']['caveat'].items()}
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 100
    config.background.auto_discover = False
    renderer = ReportRenderer(config)
    assert renderer.render(blocks)
    assert not renderer.warnings


def test_caveat_english_corrections_and_disorder_are_effective():
    from PIL import ImageChops
    values = {k.split('.', 1)[1]: v for k, v in build_bootstrap()['presets']['caveat'].items()}
    values.update(seed=42, correction_probability=10, position_disorder=0)
    config = config_from_dict({'handwriting': values})
    text = 'The quick brown fox jumps over the lazy dog and writes another sentence with many words.'
    engine = HandwritingEngine(config.handwriting)
    original = engine.render_line(text, 60, 6000, corrections=True)
    assert original.info.get('correction_marks')
    config.handwriting.correction_probability = 0
    config.handwriting.position_disorder = 0
    normal = HandwritingEngine(config.handwriting).render_line(text, 60, 6000, corrections=True)
    config.handwriting.position_disorder = 80
    displaced = HandwritingEngine(config.handwriting).render_line(text, 60, 6000, corrections=True)
    assert normal.size != displaced.size or ImageChops.difference(normal, displaced).getbbox() is not None
    assert not normal.info.get('correction_marks')


def test_caveat_math_and_code_frame_use_body_ink():
    from unittest.mock import patch
    from markdown_to_handwrite.markdown_parser import CodeBlock
    values = {k.split('.', 1)[1]: v for k, v in build_bootstrap()['presets']['caveat'].items()}
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 300
    config.background.auto_discover = False
    renderer = ReportRenderer(config)
    assert config.handwriting.math_match_body_ink
    assert renderer.formula_renderer._stroke_width(75) >= renderer.engine.reference_stroke_weight
    with patch.object(renderer, '_rough_rect') as frame:
        renderer._draw_code(CodeBlock('a + b', 'text'))
    assert frame.call_args.args[4] == renderer.engine.ink
    assert frame.call_args.kwargs['width'] >= 4


def test_six_percent_reaches_rendered_pages():
    from PIL import ImageChops
    preset = build_bootstrap()['presets']['caveat']
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    values.update(correction_probability=6, position_disorder=0)
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 150
    config.background.auto_discover = False
    source = (Path(__file__).resolve().parents[1] / 'examples/Caveat-Calculus-Original.md').read_text()
    edited = ReportRenderer(config)
    output = edited.render(parse_markdown(source))
    assert edited._placed_corrections
    config.handwriting.correction_probability = 0
    plain = ReportRenderer(config).render(parse_markdown(source))
    assert ImageChops.difference(output[0].convert('RGB'), plain[0].convert('RGB')).getbbox()
    assert preset['handwriting.math_stroke_weight_scale'] == 1.25
