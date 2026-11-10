# 五种扫描效果：调研与本轮验证（2026-11-08）

## 结论

能够继续改善，但目前没有证据表明已经达到扫描全能王。对方实现未公开，截图只能做视觉参考，不能用于推断其内部算法。当前四种增强是传统图像处理，去手写是本地 ISNet 模型；瓶颈分别是复杂纸面/照片区域识别，以及手写与印刷的语义区分。

本轮已修改生产处理路径和预览版本（14），没有接入付费云接口或新神经网络权重。后续最值得先验证 DocRes 的 appearance/deshadowing，再决定是否部署；去手写需要独立的中文混排试卷分割数据，不能用文档增强模型代替。

## 查阅资料与采用判断

| 一手来源 | 可借鉴内容 | 本项目判断 |
| --- | --- | --- |
| [DocRes，CVPR 2024](https://github.com/ZZZHANG-jx/DocRes) / [推理实现](https://github.com/ZZZHANG-jx/DocRes/blob/master/inference.py) | 统一支持去形变、阴影、外观恢复、去模糊和二值化；推理代码有 CPU 分支 | 优先候选，但本轮未下载权重或跑质量/速度测试。CPU 能运行不等于适合交互；也不支持直接区分并去除手写。 |
| [DocShadow-SD7K，ICCV 2023](https://github.com/CXH-Research/DocShadow-SD7K) / [论文](https://openaccess.thecvf.com/content/ICCV2023/papers/Li_High-Resolution_Document_Shadow_Removal_via_A_Large-Scale_Real-World_Dataset_and_ICCV_2023_paper.pdf) | 高频文字和低频阴影分开处理，配套高分辨率实拍数据及模型 | 复杂阴影候选；仓库已归档，仍要核对权重依赖、数据许可和实际推理成本。本轮未接入。 |
| [Color-Aware Background，CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/papers/Zhang_Document_Image_Shadow_Removal_Guided_by_Color-Aware_Background_CVPR_2023_paper.pdf) | 彩色背景不是阴影；简单统一白底会损失彩色内容 | 本轮在去阴影中加入彩色填块保护；这只是饱和度启发式，并非复现论文网络。 |
| [scikit-image：Niblack / Sauvola](https://scikit-image.org/docs/stable/auto_examples/segmentation/plot_niblack_sauvola.html) | 用局部均值和标准差求文档阈值 | 本轮黑白改为纸面归一化 + Sauvola；自行用 OpenCV 实现，无新增依赖；增加灰阶过渡保护笔画边缘。 |
| [aylar23/document-scanner](https://github.com/aylar23/document-scanner) | 将彩色曝光恢复与 Sauvola 黑白处理分开 | 借鉴职责划分，没有复制代码。 |
| [Inoob/HandwritingEraser](https://huggingface.co/Inoob/HandwritingEraser) | 当前项目已使用的本地像素分割权重 | 模型卡内容为空，没有训练覆盖和中文泛化证据。只能维持试用。 |
| [handwritingRemover](https://github.com/Jameskywalker/handwritingRemover) | 检测 → 掩码 → LaMa 修复 | 上游自称 pre-alpha；其默认 big-lama 权重声明非商业限制。不能直接作为成熟产品替换。 |

检索了文档扫描、阴影去除、Sauvola、去手写等技术分享，具体算法结论以上述作者仓库、论文与官方文档为依据，没有将转载博客中的效果图当成精度证据。

## 已落地改动

1. **智能高清**：继续保留原有灰块抑制和细线逻辑；对彩色笔迹使用统一 RGB 曝光补偿，避免白纸增强后仍贴回阴影中偏暗的原笔迹。纯黑白笔记基本沿用原有结果，本轮没有解决模糊、折痕和广泛浅字漏提取。
2. **去阴影**：高饱和度内容降低笔画提取混合权重，改用光照修正后的彩色结果，避免大块彩色表格内部被当成纸面漂白。规则不能可靠区分彩色纸张、桌面和图片；极暗处保留增益上限。
3. **增亮**：从固定 gamma 改为按图像亮度分位数选择曲线；统一 RGB 增益，并在通道剪切前限幅，保留色相比值、高光层次及黑色。
4. **黑白**：独立采用局部统计阈值，避免深色标题支配浅字；不再先经过智能高清的小窗口提取，减少中宽浅铅笔整段消失。第一版过宽灰阶过渡引出了纸纹，已收紧。仍有纹理与非纸张背景残留，不能恢复失焦字。
5. **去除手写**：小笔迹重试改用 768 像素重叠块和中心加权融合，避免原来的无重叠切块截断笔迹。保持原有绝对置信阈值、长直线保护、掩码外像素不变。没有降低阈值来扩大误删范围。

## 实测与限制

同一次运行、相同几何选区：5 张已有实拍样本 × 原图和4种增强，共25张修改前和25张修改后结果。原图包括用户中文笔记、公式页、收据、图表、记事本。样本少，没有像素级干净真值，不能据此报告准确率或百分比提升。

- 输出：`output/scan-upgrade-20261108/{before,after}/`。
- 每张实拍图的上下对照：`output/scan-upgrade-20261108/*-before-after.jpg`（上排修改前、下排修改后）。
- 本机、长边限制1600、仅处理阶段耗时范围：智能高清0.014–0.058秒，去阴影0.054–0.156秒，增亮0.010–0.035秒，黑白0.036–0.098秒。不是上传到导出的端到端耗时。
- 去手写5张原有样本：图表和收据保持逐像素不变；数学试卷指定的上方180行深色像素未改变。这只是少量负样本/指定区域验证，不能代表全页印刷内容安全。
- 额外2张增强参考截图，共7张图片前后擦除结果相同，因为没有触发细节重试。不能声称这7张清除率提高。
- 另2张 `output/reference-study/{1,2}-input.png` 触发分块：新旧确有差异，本机新处理约5.4–5.5秒；新结果更改像素更少，仍有大量残留。没有手写真值，无法判断整体精度更好，不把像素更改数量当清除率。对照为 `erasure-{1,2}-input.jpg`。
- 去手写仍不能恢复被笔迹遮挡的印刷文字；纯手写笔记仍不适用。

验证命令：

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/test_scan_enhancement.py tests/test_scanner_filters.py tests/test_handwriting_removal.py tests/test_scan_corners.py tests/test_scan_previews.py tests/test_scan_restoration.py -q
node --test tests/test_scan_state.cjs
PYTHONPATH=src .venv/bin/python scripts/evaluate_scan_filters.py --output output/scan-upgrade-20261108/after
PYTHONPATH=src .venv/bin/python scripts/evaluate_handwriting_removal.py --sources output/handwriting-removal/sources --output output/scan-upgrade-20261108/handwriting
```

本地服务已重启；真实 HTTP 上传后，五种处理均成功返回版本14，去手写能力已启用，记录见 `output/scan-upgrade-20261108/http-smoke.json`。刷新界面后重新扫描可获得新版结果，原有已生成的页面不会自动重算。

扫描测试50项及14个子测试通过，前端扫描状态测试通过。额外运行原有网页测试：17项通过，1项既有断言失败（`test_preset_buttons_have_no_secondary_labels` 禁止整个页面出现 `<small>`，与扫描状态和导出记录副标签冲突；本轮没有改动网页 HTML 或这项测试）。

## 接近参考效果的实施次序

1. 固定原始全分辨率实拍验证集，覆盖中文浅字、笔记、混排试卷、彩色图表、阴影、折痕、低光，保存扫描全能王对应导出图，避免用经过缩放的屏幕截图算指标。
2. 在隔离环境实测 DocRes appearance/deshadowing：先比较文字/公式是否改变，再比较纸面、阴影、CPU耗时和内存；通过后才加入可选后端。模型输出不能作为“凭空补清楚”的可靠文字真值。
3. 去手写单独准备中文混排掩码真值，评估印刷误删、笔迹漏删和表格保持；当前 ISNet 可用于实验起点，重叠分块只是上下文修复，不会补足模型的语义识别能力。
4. 书页弯曲用专门的去形变模型评估；现有四点透视只纠正平面，不应通过强行拉伸来抹平书脊。
