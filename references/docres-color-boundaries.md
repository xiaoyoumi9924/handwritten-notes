# 彩色区域与纸面偏色：第二轮验证

在上一轮模型光照图的基础上，候选先以 DocRes 恢复图的亮部估计纸面颜色，再比较局部颜色与纸面色差；将满足条件的相邻区域先闭合再筛选，避免上一轮的零碎色块。彩色区域使用模型估计的缓慢变化亮度来调整原始高分辨率像素，深色文字和线条优先保留现有去阴影结果。仅作为本地试验，尚未替换应用算法。

## 样本与观察

- 三张合成原稿分别为彩色表格、暖色纸张、黑白表格，加左暗右亮的合成阴影。只在预先指定的 8 个表格填充区域测 RGB 平均绝对误差；彩色表格从 46.80 变为 21.98（0–255 量纲）。其他两个样本没有触发颜色混合。纸面与浅线指定区域的误差本次没有变化；该指标不反映真实照片准确率或文字识别率。
- 原有 4 张真实照片中，课程表颜色填充比现有去阴影保留更多，且比首轮方案更连续。收据上蒙版平均值从 35.64% 降到约 0.3%（算法和文字保护均有变化，平均值不等于分类误差）。
- 追加笔记本和两张混排试卷作为检查，笔记本存在非纸面桌面，整图蒙版约 41.57%，该值包含桌面，不能解释成纸面误判率；彩色笔线有所保留。两张试卷分别约 2.92% 和 0%，其中一张是彩色批改文字。图片缺少分割真值，不能计算准确率。
- 按当前应用几何路径生成校正后的课程表和笔记对比；课程表颜色保留改善。笔记本自动角点检测失败，所以该图仍保留桌面；与实际自动流程一致。对比保存在 `output/docres-page-crop/`。
- 上一轮推理限制长边 768，在本机 CPU 每种模型处理约 5–7 秒，加上计算光照图、预览、批量图片与导出，耗时和内存仍需优化。此轮未评估整个 UI 的时间或并发。高分辨率边界、淡色填充、多色图片、手写与表格交叉仍缺少充分真实样本，不能声称达到商业扫描效果。

## 复现

脚本均只写本地实验目录。先按 `docres-local-evaluation.md` 准备源码、权重；运行 `scripts/create_docres_validation_samples.py` 后，用 `DOCRES_STUDY_DIR=output/docres-color-v2 DOCRES_SOURCE_DIR=output/docres-color-v2/synthetic/sources DOCRES_SAMPLES=color.png,tinted.png,mono.png PYTHONPATH=src .venv/bin/python scripts/evaluate_docres.py` 推理，再运行 `PYTHONPATH=src .venv/bin/python scripts/evaluate_docres_color_synthetic.py`。本记录中的数字对应本机最初生成的合成样本；生成脚本使用系统默认字体以便跨平台执行，重新生成的文字形状可能不同，指定填充、纸面和浅线区域不受字体影响。

真实图候选脚本为 `scripts/evaluate_docres_color_v2.py` 和 `scripts/evaluate_docres_independent.py`，输出及数据目录见上文；后三张和裁切样本分别需要 `output/docres-independent`、`output/docres-page-crop` 下已有来源和 DocRes 输出。没有根据少量样本将试验方案默认接入应用。
