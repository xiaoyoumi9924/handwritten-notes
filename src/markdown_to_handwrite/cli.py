from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config, validate_layout_options
from .docx_importer import import_docx
from .markdown_parser import parse_markdown
from .renderer import ReportRenderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a handwritten lab-report PDF from Markdown or a Word DOCX document.")
    parser.add_argument("input", help="Input Markdown or DOCX file.")
    parser.add_argument("-o", "--output", default="output/pdf/report.pdf", help="Output PDF path.")
    parser.add_argument("--save-markdown", help="Save the Markdown converted from a DOCX file for inspection.")
    parser.add_argument("-c", "--config", help="Optional JSON config file.")
    parser.add_argument("--background", choices=["plain", "lined", "grid", "dot", "image"], help="Override background style.")
    parser.add_argument("--background-image", help="Use an image as page background.")
    parser.add_argument("--font", help="Override handwriting font path.")
    parser.add_argument("--latin-font", help="Override handwriting font for Latin letters, digits, and ASCII punctuation in text.")
    parser.add_argument("--latin-upright", type=float, help="Reduce the selected Latin font's built-in slant by 0 to 10 degrees.")
    parser.add_argument("--cjk-latin-spacing", type=float, help="Extra spacing between adjacent CJK ideographs and Latin letters/digits (0 to 0.25 em).")
    parser.add_argument("--paper-color", help="Override paper color, e.g. #fffdf4.")
    parser.add_argument("--ink-color", help="Override ink color, e.g. #17233b.")
    parser.add_argument("--seed", help="Override random seed.")
    parser.add_argument("--dpi", type=int, help="Override render DPI.")
    parser.add_argument("--char-spacing", type=float, help="Character advance adjustment in output pixels (-12 to 24).")
    parser.add_argument("--spacing-jitter", type=float, help="Character advance jitter sigma as a font-size ratio (0 to 0.1; 0 disables it).")
    justification = parser.add_mutually_exclusive_group()
    justification.add_argument("--justify", dest="justify", action="store_true", help="Stretch eligible wrapped paragraph lines toward the right margin (up to 18%%).")
    justification.add_argument("--no-justify", dest="justify", action="store_false", help="Disable paragraph line stretching.")
    parser.set_defaults(justify=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    config = load_config(args.config)
    if args.background:
        config.background.style = args.background
        if not args.background_image:
            config.background.image = None
            config.background.auto_discover = False
    if args.background_image:
        config.background.image = args.background_image
        config.background.auto_discover = False
    if args.font:
        config.handwriting.font_path = args.font
    if args.latin_font:
        config.handwriting.latin_font_path = args.latin_font
    if args.latin_upright is not None:
        config.handwriting.latin_upright_correction_deg = args.latin_upright
    if args.cjk_latin_spacing is not None:
        config.handwriting.cjk_latin_spacing_em = args.cjk_latin_spacing
    if args.paper_color:
        config.background.paper_color = args.paper_color
    if args.ink_color:
        config.handwriting.ink_color = args.ink_color
    if args.seed is not None:
        config.handwriting.seed = args.seed
    if args.dpi:
        config.page.dpi = args.dpi
    if args.char_spacing is not None:
        config.handwriting.word_spacing_px = args.char_spacing
    if args.spacing_jitter is not None:
        config.handwriting.advance_jitter_sigma_ratio = args.spacing_jitter
    if args.justify is not None:
        config.layout.justify_paragraphs = args.justify
    if not 0.0 <= config.handwriting.latin_upright_correction_deg <= 10.0:
        parser.error("Latin upright correction must be between 0 and 10 degrees.")
    if not 0.0 <= config.handwriting.cjk_latin_spacing_em <= 0.25:
        parser.error("CJK-Latin spacing must be between 0 and 0.25 em.")
    try:
        validate_layout_options(config)
    except ValueError as error:
        parser.error(str(error))

    if input_path.suffix.lower() == ".docx":
        imported = import_docx(input_path)
        source = imported.markdown
        for warning in imported.warnings:
            print(f"DOCX import warning: {warning}")
        if args.save_markdown:
            markdown_path = Path(args.save_markdown)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(source, encoding="utf-8")
            print(f"Converted Markdown saved to {markdown_path}")
    else:
        source = input_path.read_text(encoding="utf-8")
        if args.save_markdown:
            parser.error("--save-markdown 仅适用于 DOCX 输入文件。")
    blocks = parse_markdown(source)
    renderer = ReportRenderer(config, base_dir=input_path.parent)
    pages = renderer.render(blocks)
    output = renderer.save_pdf(args.output)
    engine = (
        "sdt-trajectories"
        if renderer.engine.uses_sdt_trajectories
        else "handright"
        if renderer.engine.handright_available
        else "pillow-fallback"
    )
    font_chain = " -> ".join(renderer.engine.font_paths)
    print(
        f"Generated {output} ({len(pages)} page(s), engine={engine}, "
        f"fonts={font_chain}, latin_font={renderer.engine.latin_font_path or 'inherits'})"
    )
    return 0
