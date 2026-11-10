# 验收样稿使用与记录

## 固定输入与生成方式

- 输入：`examples/acceptance_suite.md`
- 分页边界输入：`examples/pagination_boundary_suite.md`
- 配置：`examples/config.json`（Kalam 英文字体、10° 回正、CJK-Latin 间距 0.08 em、随机种子 42）
- 输出：`output/pdf/acceptance_suite.pdf`
- 分页边界输出：`output/pdf/pagination_boundary_suite.pdf`
- 预览：`output/acceptance_suite_page-*.png`
- 分页修复前的对照预览：`output/acceptance_suite_before_page-*.png`

在开发版根目录运行：

```bash
PYTHONPATH=src .venv/bin/python -m markdown_to_handwrite \
  examples/acceptance_suite.md -c examples/config.json --seed 42 \
  -o output/pdf/acceptance_suite.pdf
pdftoppm -png -r 120 output/pdf/acceptance_suite.pdf output/acceptance_suite_page
PYTHONPATH=src .venv/bin/python -m markdown_to_handwrite \
  examples/pagination_boundary_suite.md -c examples/config.json --seed 42 \
  -o output/pdf/pagination_boundary_suite.pdf
pdftoppm -png -r 100 output/pdf/pagination_boundary_suite.pdf output/pagination_boundary_page
```

比较不同版本时保持 Markdown、配置、字体文件、渲染版本和 seed 不变；一次只调整一个变量，并保留前后 PDF 与页面 PNG。

## 验收项

| 项目 | 检查内容 | 结果 |
| --- | --- | --- |
| 中英混排 | 中文与英文术语相邻时字距自然，英文倾斜适中 | 通过；本样稿中英文整体接近直立，字形仍有轻微个体倾斜 |
| 行内公式 | 句首、句中、句尾公式的基线和标点位置自然 | 基本通过；分数略高于正文，但上下结构清晰 |
| 行尾公式 | 靠近行尾的公式整体移动，不拆开、不被裁切 | 通过；长公式作为整体换到下一行 |
| 数学结构 | 分数、根式、上下标、求和、积分、矩阵、分段函数可辨 | 通过；本轮样例中的结构均可辨认 |
| 多行推导 | 等号列对齐，行间距足够，内容不超出正文宽度 | 通过；两组 aligned 推导等号列整齐 |
| 页面布局 | 标题不孤行，公式块完整，末段不被页脚裁切 | 通过；分页保护后，样稿中的长段落和说明+公式组合保持完整 |
| 页底压力 | 标题/正文、连续公式、列表项、表格靠近页底 | 通过；标题与正文、连续公式组、列表项、表格整体移至后页，表格带表头 |
| 可复现性 | 同一输入、配置和 seed 可重复生成相同版面 | 未做逐像素比较 |

## 本轮观察

基线版与分页修复版均生成 3 页主验收 PDF，并逐页查看 PNG。修复后，能放入一页的段落整体移动；紧邻块公式且组合可容纳时，说明段和公式一起移动。页底边界专项 PDF 共 9 页，逐页检查确认：标题未落单，说明段与公式同页，连续公式不被拆开，长列表项保持完整，表格及表头一起换页。超长段落仍按行分页。公式内容、等号对齐和近行尾行内公式保持正常。未做逐像素可复现性比较。

## WebUI 公式端到端验收（2026-11-06）

- 流程：在本地 WebUI 选择样稿，确认内容进入编辑器，生成预览并下载 PDF。
- `examples/formula_stress_test.md`：生成 3 页。逐页检查行内公式、二次根式、嵌套分式、求和与积分上下限、`bmatrix`、`cases`、两组 `aligned` 推导；未见公式裁切，等号列对齐正常。
- `examples/root_connections.md`：生成 1 页。检查行内/行间根号、分式根号、嵌套根号、高次根号及公式编号 `(5)`；结构完整。
- 两份导出均为 A4 PDF；浏览器控制台未报告错误。
- PDF 与网页预览文件：`output/webui/84b32b1bb4e6c781/`（公式压力样稿）和 `output/webui/b5e5f445e6de9dab/`（根号专项样稿）。
