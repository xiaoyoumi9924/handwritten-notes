from PIL import Image, ImageChops

from markdown_to_handwrite.config import HandwritingConfig
from markdown_to_handwrite.page_edits import apply_page_edits, comment_image
from markdown_to_handwrite.scan_restoration import draw_scan_marks


def test_comments_use_same_plain_font_across_handwriting_presets():
    page = Image.new('RGB', (800, 1100), 'white')
    mark = {'kind': 'comment', 'text': '普通批注 English 123\n第二行', 'width': .04,
            'color': '#123456', 'points': [[.2, .2]]}
    first = comment_image(page, mark, HandwritingConfig(font_path='font/Latin-Caveat-Regular.ttf'))
    second = comment_image(page, mark, HandwritingConfig(font_path='font/PingFangShaoHuaTi-2.ttf'))
    assert first.getchannel('A').getbbox()
    assert first.size == second.size
    assert ImageChops.difference(first.getchannel('A'), second.getchannel('A')).getbbox() is None
    assert set(first.convert('RGB').getdata()) <= {(0, 0, 0), (18, 52, 86)}
    edits = {'rotation': 0, 'crop': None, 'marks': [mark]}
    report = apply_page_edits(page, edits)
    scan = draw_scan_marks(page, [mark])
    assert ImageChops.difference(report, scan).getbbox() is None
    assert ImageChops.difference(report, page).getbbox() is not None


def test_comment_wrap_and_color():
    page = Image.new('RGB', (500, 700), 'white')
    mark = {'kind': 'comment', 'text': '这是用于换行的批注文字' * 5, 'width': .04,
            'color': '#ff0000', 'points': [[0, 0]]}
    image = comment_image(page, mark)
    assert image.height > 50
    assert image.width <= round(page.width * .48) + 2 * max(2, round(20 * .08))
