#!/usr/bin/env python3
"""Build a tablet-friendly single-character reference sheet for SDT."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "training/new_chinese_handwriting/templates/sdt_style_capture_sheet.png"

CHARACTERS = list(
    "的一是不在人有我他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可她妈心爱笔风雨水山好"
)
COLS = 8
CELL_W = 145
CELL_H = 152
PAGE_W = COLS * CELL_W + 96
TOP_H = 250
PAGE_H = TOP_H + 7 * CELL_H + 96


def find_cjk_font() -> str:
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("No CJK font found for the capture sheet labels")


def main() -> None:
    if len(CHARACTERS) != 56:
        raise ValueError(f"Expected exactly 56 unique character prompts, got {len(CHARACTERS)}")
    font_path = find_cjk_font()
    image = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(font_path, 34, index=0)
    body_font = ImageFont.truetype(font_path, 18, index=0)
    label_font = ImageFont.truetype(font_path, 20, index=0)

    draw.text((48, 32), "SDT 笔迹风格采集表 · 56 字", font=title_font, fill="#20252b")
    instructions = [
        "建议在绘图软件中打开本图，另建透明图层，在每个方格中按左上角提示写一个字。",
        "保持日常写法，字写完整、居中；尽量用白底和稳定笔宽，避免纸纹、水印、阴影。",
        "完成后隐藏本模板图层，只导出透明书写图层 PNG。模板用于补充 SDT 风格参考，不是训练结果。",
    ]
    y = 91
    for line in instructions:
        draw.text((50, y), line, font=body_font, fill="#555e67")
        y += 31

    x0, y0 = 48, TOP_H
    grid = "#cbd3dc"
    for row in range(7):
        for col in range(COLS):
            x = x0 + col * CELL_W
            y = y0 + row * CELL_H
            draw.rounded_rectangle((x + 3, y + 3, x + CELL_W - 3, y + CELL_H - 3), radius=8, outline=grid, width=2)
            char = CHARACTERS[row * COLS + col]
            draw.text((x + 12, y + 8), char, font=label_font, fill="#8c98a5")
            # Faint center guide; the user can hide the template layer after writing.
            draw.line((x + CELL_W // 2, y + 36, x + CELL_W // 2, y + CELL_H - 10), fill="#edf0f3", width=1)
            draw.line((x + 10, y + CELL_H // 2 + 18, x + CELL_W - 10, y + CELL_H // 2 + 18), fill="#edf0f3", width=1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, optimize=True)
    print(f"Wrote {len(CHARACTERS)}-character SDT capture sheet to {OUTPUT}")


if __name__ == "__main__":
    main()
