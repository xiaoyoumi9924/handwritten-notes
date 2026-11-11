from markdown_to_handwrite.config import config_from_dict
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import build_bootstrap


def test_shaohua_preset_renders_numbers_formulas_and_table():
    presets = build_bootstrap()['presets']
    preset = presets['shaohua']
    assert preset['handwriting.font_path'] == 'font/PingFangShaoHuaTi-2.ttf'
    assert not preset['handwriting.sdt_trajectory_enabled']
    assert all(set(preset) <= set(other) for other in presets.values())
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    config = config_from_dict({'handwriting': values})
    config.page.dpi = 72
    config.background.auto_discover = False
    blocks = parse_markdown('数字 123.45，行内公式 $x_1=2$。\n\n$$\\frac{1}{2}+x^2=3$$\n\n| 项目 | 数值 | 公式 |\n| --- | --- | --- |\n| 测试 | 12.5 | $x_1=2$ |')
    renderer = ReportRenderer(config)
    pages = renderer.render(blocks)
    assert pages and pages[0].getbbox()
    assert not renderer.warnings
    assert preset["handwriting.math_inline_scale"] == 1.1


def test_shaohua_one_and_ink_are_consistent_across_rendering():
    from markdown_to_handwrite.handwriting import HandwritingEngine

    preset = build_bootstrap()['presets']['shaohua']
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    values.update(perturb_theta_sigma=0, perturb_x_sigma_px=0,
                  perturb_y_sigma_px=0, math_perturb_y_sigma_ratio=0)
    config = config_from_dict({'handwriting': values})
    assert config.handwriting.uniform_table_ink
    assert config.handwriting.ink_density_jitter == 0
    assert config.handwriting.dry_brush_probability == 0
    assert config.handwriting.stroke_weight_variation_sigma_ratio == 0
    engine = HandwritingEngine(config.handwriting)
    for math in (False, True):
        image = engine.render_line('1', 80, 400, math=math)
        left, top, right, bottom = image.getchannel('A').getbbox()
        assert right - left < (bottom - top) / 3


def test_shaohua_font_is_in_deployment_tree():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert (root / 'font/PingFangShaoHuaTi-2.ttf').is_file()


def test_table_rules_use_opaque_ink_and_scale_with_resolution():
    from unittest.mock import patch

    preset = build_bootstrap()['presets']['shaohua']
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    for dpi in (150, 300):
        config = config_from_dict({'handwriting': values})
        config.page.dpi = dpi
        config.background.auto_discover = False
        report = ReportRenderer(config)
        with patch.object(report, '_rough_line') as draw:
            report._draw_table_row([100, 100], ([[], []], 60), 0, header=False)
        assert all(call.args[4][3] == 255 for call in draw.call_args_list)
        assert all(call.kwargs['width'] == max(1.0, round(config.handwriting.body_font_pt * dpi / 72) * .0675) for call in draw.call_args_list)
