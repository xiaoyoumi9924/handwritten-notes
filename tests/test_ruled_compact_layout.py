from unittest.mock import patch

from PIL import Image

from markdown_to_handwrite.config import ReportConfig
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer


def renderer_for_paper(style):
    c = ReportConfig()
    c.page.dpi = 96
    c.background.style = style
    c.background.auto_discover = False
    return ReportRenderer(c)


def test_empty_hard_breaks_at_page_top_do_not_waste_ruled_rows():
    placements = []
    for source in ('正文。', '<p><br></p>\n<p><br></p>\n<p>正文。</p>'):
        renderer = renderer_for_paper('lined')
        with patch.object(renderer, '_paste_rich_line', wraps=renderer._paste_rich_line) as paste:
            renderer.render(parse_markdown(source))
            placements.append((paste.call_args.args[2], renderer._last_paper_rule))
    assert placements[0] == placements[1]


def test_ruled_paper_splits_formula_sequence_at_page_boundary():
    renderer = renderer_for_paper('lined')
    image = Image.new('RGBA', (30, 20), (0, 0, 0, 255))
    block_height = renderer._formula_height(image)
    renderer.y = renderer.bottom_limit - block_height - 1
    positions = []
    original = renderer._draw_formula
    def draw(text, image=None):
        original(text, image=image)
        positions.append(len(renderer.pages))
    with patch.object(renderer, '_render_formula_image', return_value=image), patch.object(renderer, '_draw_formula', side_effect=draw):
        renderer.render(parse_markdown('$$\na=1\n$$\n\n$$\nb=2\n$$'))
    assert positions == [1, 2]


def test_final_rule_accepts_ink_when_only_empty_line_leading_extends_past_margin():
    renderer = renderer_for_paper('lined')
    rule = renderer._paper_rules[-1]
    renderer.bottom_limit = rule + 2
    renderer._last_paper_rule = len(renderer._paper_rules) - 2
    renderer._last_rule_flow_end = rule - 10
    image = Image.new('RGBA', (20, 20), (0, 0, 0, 255))
    from markdown_to_handwrite.renderer import _RichLine
    line = _RichLine([(image, 16)], 20, 70, 16, font_size_px=30)
    placement = renderer._paper_rule_placement(line, rule - 10, renderer._last_paper_rule, renderer._last_rule_flow_end)
    assert placement is not None
    assert placement[1] == len(renderer._paper_rules) - 1
    assert placement[0] + image.height <= renderer.bottom_limit
    assert placement[0] + line.height > renderer.bottom_limit
