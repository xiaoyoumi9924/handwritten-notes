import tempfile
import unittest
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops
from unittest.mock import patch

from markdown_to_handwrite.config import ReportConfig, mm_to_px
from markdown_to_handwrite.renderer import ReportRenderer, _RichLine
from markdown_to_handwrite.page_edits import save_pages_pdf
from markdown_to_handwrite.markdown_parser import parse_markdown


class RuledPaperExportTests(unittest.TestCase):
    def test_both_builtin_papers_have_detectable_rules(self):
        for name in ['提取的红线纸.png', '提取的绿线纸.png']:
            with self.subTest(name=name):
                config = ReportConfig()
                config.background.style = 'image'
                config.background.image = 'background/' + name
                renderer = ReportRenderer(config)
                self.assertGreater(len(renderer._paper_rules), 20)

    def test_actual_ink_bottom_stays_above_rule_and_top_row_is_blank(self):
        config = ReportConfig()
        config.background.style = 'image'
        config.background.image = 'background/提取的红线纸.png'
        renderer = ReportRenderer(config)
        image = Image.new('RGBA', (100, 80), (20, 30, 40, 255))
        line = _RichLine([(image, 65)], 100, 103, 65)
        renderer._position_on_paper_rule(line)
        self.assertEqual(renderer._paper_rules[1] - (renderer.y + 80), mm_to_px(.65, renderer.dpi))
        renderer.y += line.height
        renderer._position_on_paper_rule(line)
        self.assertEqual(renderer._paper_rules[2] - (renderer.y + 80), mm_to_px(.65, renderer.dpi))

    def test_variable_glyph_heights_and_paragraph_gaps_do_not_skip_rows(self):
        config = ReportConfig()
        config.background.style = 'image'
        config.background.image = 'background/提取的红线纸.png'
        renderer = ReportRenderer(config)
        baselines = []
        for height, baseline in [(70, 60), (55, 47), (65, 55), (62, 53)]:
            image = Image.new('RGBA', (100, height), (20, 30, 40, 255))
            line = _RichLine([(image, baseline)], 100, 104, baseline, font_size_px=67)
            renderer._position_on_paper_rule(line)
            baselines.append(renderer.y + line.baseline)
            self.assertEqual(renderer._last_paper_rule, len(baselines))
            renderer.y += line.height + mm_to_px(config.layout.paragraph_gap_mm, renderer.dpi)
        for index in range(1, len(baselines)):
            self.assertEqual(baselines[index] - baselines[index - 1],
                             renderer._paper_rules[index + 1] - renderer._paper_rules[index])

    def test_correction_probability_changes_ink_without_changing_layout(self):
        source = ("这个字体清秀工整，中英文字体风格统一，适合记录笔记。 English gyp 123\n\n"
                  "- 字迹规整，适合刷题和记公式 $x^2+y^2=1$。\n"
                  "- 清秀笔记体，文字自然地写在横线上方。\n\n") * 5
        for paper in ('plain', 'red'):
            for trajectories in (False, True):
                with self.subTest(paper=paper, trajectories=trajectories):
                    layouts, images = [], []
                    for probability in (0, 4, 10):
                        config = ReportConfig()
                        config.page.dpi = 96
                        config.handwriting.sdt_trajectory_enabled = trajectories
                        config.handwriting.prefer_handright = False
                        config.handwriting.correction_probability = probability
                        config.handwriting.position_disorder = 40
                        config.background.style = 'plain' if paper == 'plain' else 'image'
                        config.background.image = None if paper == 'plain' else 'background/提取的红线纸.png'
                        renderer = ReportRenderer(config)
                        positions = []
                        original = renderer._paste_rich_line

                        def capture(line, x, y, *args, **kwargs):
                            positions.append((len(renderer.pages), x, y + line.baseline, line.width, line.height))
                            return original(line, x, y, *args, **kwargs)

                        renderer._paste_rich_line = capture
                        renderer.render(parse_markdown(source))
                        layouts.append((len(renderer.pages), positions))
                        images.append(renderer.pages[0].tobytes())
                    self.assertEqual(layouts[0], layouts[1])
                    self.assertEqual(layouts[0], layouts[2])
                    self.assertNotEqual(images[0], images[2])

    def test_top_rule_remains_free_of_ink_on_every_page(self):
        config = ReportConfig()
        config.page.dpi = 96
        config.background.style = 'image'
        config.background.image = 'background/提取的红线纸.png'
        config.handwriting.correction_probability = 10
        renderer = ReportRenderer(config)
        top = renderer._paper_rules[0]
        background = renderer.pages[0].crop((0, 0, renderer.page_w, top + 1)).tobytes()
        renderer.render(parse_markdown("第一段文字测试。<newpage>第二页文字测试。"))
        self.assertEqual(len(renderer.pages), 2)
        for page in renderer.pages:
            self.assertEqual(page.crop((0, 0, renderer.page_w, top + 1)).tobytes(), background)

    def test_rewrites_use_empty_space_without_overlapping_text_or_each_other(self):
        config = ReportConfig()
        config.page.dpi = 120
        config.background.style = 'image'
        config.background.image = 'background/提取的红线纸.png'
        config.handwriting.correction_probability = 10
        renderer = ReportRenderer(config)
        source = ("原来你是问图片的对比，这两张其实是同一份内容的不同呈现形式。\n\n"
                  "- 如果只看文字内容的清晰度，中间的正文部分更好。\n"
                  "- 如果看整张图片的完整度，原始照片更好。\n\n") * 5
        before = []
        original = renderer._draw_pending_corrections

        def decorate():
            before.extend(page.copy() for page in renderer.pages)
            original()

        with patch.object(renderer, '_draw_pending_corrections', side_effect=decorate):
            renderer.render(parse_markdown(source))
        self.assertGreater(len(renderer._placed_corrections), 3)
        directions = set()
        for index, mark in enumerate(renderer._placed_corrections):
            x0, y0, x1, y1 = mark['original']
            a, b, c, d = mark['rewrite']
            self.assertTrue(c <= x0 or a >= x1 or d <= y0 or b >= y1)
            dx = max(x0 - c, a - x1, 0)
            dy = max(y0 - d, b - y1, 0)
            allowed_gap = max(2, mm_to_px(.25, renderer.dpi)) + (x1 - x0) * .06 + 1
            self.assertLessEqual((dx * dx + dy * dy) ** .5, allowed_gap)
            self.assertAlmostEqual(c - a, (x1 - x0) * .85, delta=max(2, (y1 - y0) * .12))
            self.assertAlmostEqual(d - b, (y1 - y0) * .85, delta=max(2, (x1 - x0) * .12))
            page_index = mark['page']
            background = renderer._make_background(page_index)
            ink = ImageChops.difference(before[page_index].convert('RGB'), background.convert('RGB'))
            self.assertIsNone(ink.crop(mark['rewrite']).getbbox())
            directions.add('above' if d <= y0 else 'below' if b >= y1 else 'side')
            for other in renderer._placed_corrections[:index]:
                if other['page'] != page_index:
                    continue
                e, f, g, h = other['rewrite']
                self.assertTrue(c <= e or a >= g or d <= f or b >= h)
        self.assertGreaterEqual(len(directions), 2)
        angles = [mark["angle"] for mark in renderer._placed_corrections]
        self.assertTrue(any(angle == 0 for angle in angles))
        self.assertTrue(any(1.5 <= abs(angle) <= 5 for angle in angles))

    def test_pdf_embeds_exact_rgb_pixels_and_page_size(self):
        page = Image.new('RGB', (120, 170), '#ad3b4f')
        with tempfile.TemporaryDirectory() as folder:
            path = save_pages_pdf([page], Path(folder) / 'test.pdf', 210, 297)
            with pymupdf.open(path) as pdf:
                self.assertAlmostEqual(pdf[0].rect.width, 210 / 25.4 * 72, places=3)
                pixmap = pymupdf.Pixmap(pdf, pdf[0].get_images()[0][0])
                self.assertEqual(pixmap.samples, page.tobytes())
