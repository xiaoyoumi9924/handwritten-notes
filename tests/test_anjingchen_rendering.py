from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "font/AnJingChenYingBiXingShu-2.ttf").is_file(),
    reason="Optional locally supplied font is not distributed",
)

from markdown_to_handwrite.config import config_from_dict
from markdown_to_handwrite.handwriting import HandwritingEngine
from markdown_to_handwrite.web import build_bootstrap


def test_digit_one_is_a_single_vertical_stroke_in_text_and_math():
    preset = build_bootstrap()["presets"]["anjingchen"]
    values = {key.split('.', 1)[1]: value for key, value in preset.items()}
    values.update(second_layer_enabled=False, perturb_theta_sigma=0, perturb_x_sigma_px=0,
                  perturb_y_sigma_px=0, math_perturb_y_sigma_ratio=0)
    engine = HandwritingEngine(config_from_dict({"handwriting": values}).handwriting)
    for math in (False, True):
        image = engine.render_line("1", 80, 400, math=math)
        bbox = image.getchannel("A").getbbox()
        assert bbox is not None
        assert bbox[2] - bbox[0] < (bbox[3] - bbox[1]) / 3


def test_formula_weight_and_size_are_scoped_to_the_font_preset():
    from markdown_to_handwrite.math_renderer import FormulaRenderer
    presets = build_bootstrap()["presets"]
    settings = {key.split('.', 1)[1]: value for key, value in presets["anjingchen"].items()}
    handwriting = config_from_dict({"handwriting": settings}).handwriting
    assert handwriting.math_inline_scale == 1.15
    assert handwriting.math_font_pt == 20
    heavier = FormulaRenderer(HandwritingEngine(handwriting), seed=1)
    handwriting.math_stroke_weight_scale = 1.0
    normal = FormulaRenderer(HandwritingEngine(handwriting), seed=1)
    assert heavier.engine.config is handwriting  # distinct configs needed for comparison
    handwriting.math_stroke_weight_scale = 1.25
    thick = heavier._stroke_width(80)
    handwriting.math_stroke_weight_scale = 1.0
    assert thick > normal._stroke_width(80)
    for key in ("math_inline_scale", "math_font_pt", "math_stroke_weight_scale"):
        assert f"handwriting.{key}" in presets["formal"]


def test_long_formula_breaks_only_at_outer_operators():
    from markdown_to_handwrite.math_renderer import _split_display_operators, FormulaRenderer
    source = r"a=(b+c)+\frac{x+1}{y-2}-z+w"
    parts = _split_display_operators(source)
    assert "".join(parts) == source
    assert parts == ["a", "=(b+c)", r"+\frac{x+1}{y-2}", "-z", "+w"]
    preset = build_bootstrap()["presets"]["anjingchen"]
    settings = {key.split('.', 1)[1]: value for key, value in preset.items()}
    engine = HandwritingEngine(config_from_dict({"handwriting": settings}).handwriting)
    image = FormulaRenderer(engine, seed=10).render(source, 60, 260)
    assert image.width <= 260
    assert image.height > 100


def test_math_ink_uses_body_pen_weight():
    from markdown_to_handwrite.math_renderer import FormulaRenderer
    preset = build_bootstrap()["presets"]["anjingchen"]
    settings = {key.split('.', 1)[1]: value for key, value in preset.items()}
    engine = HandwritingEngine(config_from_dict({"handwriting": settings}).handwriting)
    assert engine.config.math_match_body_ink
    assert engine._reference_weight_for_text("x+2", 80, math_mode=True) == engine.reference_stroke_weight
    assert FormulaRenderer(engine)._stroke_width(80) == max(1.0, engine.reference_stroke_weight)
