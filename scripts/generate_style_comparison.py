from __future__ import annotations

import html
from pathlib import Path

from markdown_to_handwrite.config import ReportConfig
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import STYLE_PRESETS


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "style_comparison.md"
OUTPUT = ROOT / "output" / "style-comparison"
DPI = 180
PRESET_INFO = (
    ("formal", "墨序", "工整克制"),
    ("natural", "云笺", "自然均衡"),
    ("casual", "松风", "舒展随性"),
)


def apply_preset(config: ReportConfig, name: str) -> None:
    for path, value in STYLE_PRESETS[name].items():
        section, field_name = path.split(".", 1)
        setattr(getattr(config, section), field_name, value)


def build_gallery(results: list[dict[str, object]]) -> str:
    cards = []
    for result in results:
        title = html.escape(str(result["title"]))
        character = html.escape(str(result["character"]))
        slug = html.escape(str(result["slug"]))
        pages = int(result["pages"])
        image = f"{slug}-page-1.png"
        cards.append(
            f"""<article class="style-column">
  <header><h2>{title}</h2><p>{character}</p></header>
  <a class="page-link" href="{image}" target="_blank" rel="noreferrer">
    <img src="{image}" alt="{title} 笔迹方案样张第一页" />
  </a>
  <footer><span>共 {pages} 页</span><a href="{slug}.pdf">下载 PDF</a></footer>
</article>"""
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>三款笔迹方案对照</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; color: #202622; background: #e7e6df; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 28px; }}
    main {{ max-width: 1680px; margin: 0 auto; }}
    h1 {{ margin: 0; font-size: 25px; letter-spacing: .02em; }}
    .intro {{ margin: 8px 0 22px; color: #58625c; font-size: 14px; line-height: 1.6; }}
    .comparison {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; align-items: start; }}
    .style-column {{ min-width: 0; }}
    .style-column header {{ padding: 0 4px 10px; }}
    .style-column h2 {{ margin: 0; font-size: 19px; }}
    .style-column header p {{ margin: 4px 0 0; color: #68716b; font-size: 13px; }}
    .page-link {{ display: block; padding: 7px; border-radius: 4px; background: #fffdf6; box-shadow: 0 5px 22px rgba(24,30,26,.14); }}
    img {{ width: 100%; height: auto; display: block; }}
    footer {{ display: flex; justify-content: space-between; padding: 9px 3px; color: #58625c; font-size: 13px; }}
    footer a {{ color: #8b432f; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    @media (max-width: 900px) {{ body {{ padding: 18px; }} .comparison {{ grid-template-columns: 1fr; gap: 22px; }} .style-column {{ max-width: 620px; margin-inline: auto; }} }}
  </style>
</head>
<body><main>
  <h1>三款笔迹方案对照</h1>
  <p class="intro">同一份中英混排、行内与展示公式、表格样稿；仅切换笔迹方案。点击页面可查看原尺寸，PDF 可查看完整分页。</p>
  <section class="comparison">{''.join(cards)}</section>
</main></body>
</html>
"""


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    blocks = parse_markdown(source)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []

    for name, title, character in PRESET_INFO:
        config = ReportConfig()
        config.page.dpi = DPI
        config.handwriting.seed = "style-comparison-2026-11"
        apply_preset(config, name)
        renderer = ReportRenderer(config, base_dir=ROOT)
        pages = renderer.render(blocks)
        slug = {"formal": "moxu", "natural": "yun-jian", "casual": "song-feng"}[name]
        for stale_page in OUTPUT.glob(f"{slug}-page-*.png"):
            stale_page.unlink()
        pdf_path = renderer.save_pdf(OUTPUT / f"{slug}.pdf")
        for page_number, page in enumerate(pages, start=1):
            page.convert("RGB").save(OUTPUT / f"{slug}-page-{page_number}.png", optimize=True)
        results.append({"slug": slug, "title": title, "character": character, "pages": len(pages)})
        print(f"{title}: {len(pages)} page(s), {pdf_path}")
        if renderer.warnings:
            for warning in renderer.warnings:
                print(f"  formula warning: {warning}")

    gallery_path = OUTPUT / "index.html"
    gallery_path.write_text(build_gallery(results), encoding="utf-8")
    print(f"Comparison gallery: {gallery_path}")


if __name__ == "__main__":
    main()
