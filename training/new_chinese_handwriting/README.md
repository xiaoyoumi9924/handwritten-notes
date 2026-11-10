# 新中文手写体

本工作区用于开发第二种中文优先的手写风格。原有“纸间清风体”、字体文件和 SDT 轨迹库保持原样；本阶段的生成结果仍是实验素材，没有接入应用。

## 当前进度

- 11 张同一笔迹的手写页照片已保存在本机 `source/`，原图未修改。页面有红线、水印和透视/弯曲；OCR 与单字标签仍是候选，不能直接作为训练真值。
- 风格参考集已扩到 49 个不同汉字，来自 3 页较清晰的行文。按比例放大到 64×64 输入画布，墨迹最大边为 56 像素；参考图只提供风格条件，不直接作为输出字形。
- 已取得 SDT 官方中文预训练权重，文件为本机 `checkpoints/checkpoint-iter199999.pth`，大小 273,587,031 字节，SHA-256 为 `e23ae03af8099c9fa09bc4f1b80dad3f3457cc73e651e4f6e23ff6aa1e41aa89`。权重不纳入 Git。
- 从 SDT 官方中文数据包中只提取了 `character_dict.pkl` 和 `Chinese_content.pkl`；没有下载约 6 GB 的整套 CASIA 训练数据。两个文件在 `prepared/sdt_inputs/CASIA_CHINESE/`，随 `prepared/` 一起忽略，不会提交。
- `.venv` 已装 PyTorch 2.15.0、torchvision 0.29.2 及 SDT 推理依赖。新增的 MPS 推理入口是 `scripts/generate_sdt_style_trajectories.py`；本地 SDT 代码只为生成采样器补了设备适配。
- macOS 环境可用 `python -m pip install -r training/new_chinese_handwriting/requirements-sdt-macos.txt` 安装独立的 SDT 依赖。
- 已按 SDT 官方流程用 49 张风格参考图生成同一组 12 个汉字。对比了原样、二值化、放大到接近官方训练样本占用范围、腐蚀和 Zhang-Suen 细化。二值化和放大没有改善；细化能让部分生成字更好辨认，但也会丢失笔画粗细特征，结构仍不准。所有结果均未通过质量门槛。对照图在 `generated/pilot-comparison-12-v3.png`。这一步没有更新模型权重，也没有接入应用。
- 扩充参考图时发现并修复了文件筛选问题：联系表图片曾被误当成风格样本；现在只读取编号单字图。之前 15 张的试跑没有受这个问题影响，49 张的首次试跑和第一次粗细对照已作废并重跑。
- SDT 作者说明，训练数据的均匀笔画与真实手写宽度差异会令生成风格趋于平均，并建议适配/微调；社区也报告纸面噪点会加重潦草问题，见[作者讨论](https://github.com/dailenson/SDT/issues/43)和[噪点讨论](https://github.com/dailenson/SDT/issues/59)。简单做阈值、膨胀或细化都不能替代模型适配。
- 已生成一张 56 字单字采集模板：`templates/sdt_style_capture_sheet.png`。可在绘图软件中把模板放底层、另建透明书写层，逐格自然书写，完成后隐藏底图，仅导出透明 PNG。它用于补充干净的风格参考，不会被误当成训练完成。
- 新增 `source/page_012.png` 采集页，逐格识别出 56 字。压制红线并检查裁切后，9 格因水印遮挡而排除，另有 12 字与旧 49 字参考重复；本轮仅新增 35 个不重复字形。和旧 49 张合并后共 84 张，使用相同 SDT 预训练权重跑了相同 12 字。输出仍严重失真，未通过可读性检查；新增参考没有解决模型质量问题。并排对照：`generated/pilot-page012-vs-49.png`。本轮没有微调权重、没有生成可发布新字体，也没有改动应用字体。

## 接下来的研发步骤

1. 从 11 页中挑出可辨认、无遮挡的字符，校对文本标签与裁切；低置信度和水印覆盖的样本先排除。
2. 若方便，按采集模板补一组无水印、干净背景的单字图；先只作 SDT 风格参考，再跑同一组 12 字对照，确认图像域是不是主要原因。
3. 如果干净参考图仍不能通过质量门槛，停止继续堆叠预处理技巧，设计适用于静态图的域适配/离线到离线路线。SDT 官方完整训练器需要在线笔迹轨迹及配套数据；当前 11 页照片不能直接当成轨迹监督数据。
4. 先通过一批常用字的可读性、结构和风格验收；质量通过后再扩展到完整中文字库，并生成独立轨迹包供应用选择。
5. 英文、数字、公式继续单独评估覆盖；当前中文 SDT 词表不等于完整英文/公式支持。现有公式渲染方案不受影响。

真正的新增字体会来自模型学习到的笔迹风格后所预测并通过检查的字形/轨迹，不会把照片裁片拼进 TTF。当前 SDT 试跑还未达到可用质量。此前的直接裁片描摹 TTF 仅作为弃用的导出诊断文件留在 `prepared/prototype/`。

## 文件

- `manifest.json`：样本来源、许可确认、模型状态和检查结果。
- `source/`：原始照片；`.gitignore` 保护。
- `prepared/normalized/`：红线抑制副本与墨迹候选掩码；原图保持不变。
- `prepared/glyph-candidates/`：待校对的单字裁片与检查表。
- `prepared/sdt-style-samples/`：49 张 SDT 风格参考图及来源清单。
- `prepared/sdt_inputs/CASIA_CHINESE/`：官方 SDT 内容字形与字符表，仅作为推理输入。
- `prepared/sdt_inputs/train_style_1146.pkl`：官方训练样本的临时对照素材，不用于新字体。
- `checkpoints/`：本地 SDT 权重，`.gitignore` 保护。
- `generated/`：模型试跑输出，`.gitignore` 保护；当前试跑未通过审阅。
- `references/SDT/`：需自行克隆的官方 SDT 源码；上游版本使用 CUDA，CPU / MPS 需要自行适配。
- `scripts/prepare_sdt_style_samples.py`：提取/缩放风格参考图。
- `scripts/generate_sdt_style_trajectories.py`：生成独立 SDT 轨迹包与预览。
- `scripts/normalize_sdt_style_strokes.py`：创建保留连通性的细笔画风格参考变体。
- `scripts/prepare_sdt_capture_page.py`：从 7×8 采集页生成带标签的单字审核裁片，标记水印风险。
- `scripts/build_sdt_capture_sheet.py`：生成 56 字数字化参考采集模板。
