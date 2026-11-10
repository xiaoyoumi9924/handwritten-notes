# DocRes 本机初步评估

参照 [DocRes 官方实现](https://github.com/ZZZHANG-jx/DocRes) 的 appearance 和 deshadowing，使用[公开镜像权重](https://huggingface.co/presencesw/DocRes/blob/main/docres.pkl)在本机 CPU 试跑。下载权重的 SHA-256 是 `1d6a89d754fe1e58ffd1865eab0ef3f03344798d39197b2d9a77ce4fbc8c02fd`，与镜像元数据一致；这不证明它与作者原始发布文件逐字节相同。使用官方 Restormer 和对应 prompt，权重使用 `weights_only=True` 加载。

四张已有样本包括中文笔记、密集公式、彩色课程表和收据。输入长边限制为 768，三组图分别是原图、现有算法、DocRes；两种算法使用相同输入，没有执行自动裁边。四线程 CPU 推理单种任务约 4.8–6.6 秒，不含加载和前后处理。中文笔记另以原始尺寸 1080×784 推理，分别耗时 12.39 秒和 12.64 秒。

对比图位于 `output/docres-study/` 和 `output/docres-study-1200/`：`*-comparison.jpg` 中每组三列为原图、现有算法、DocRes；`*-appearance.png` 和 `*-deshadowing.png` 是单独的模型输出。768 测试图经缩小，不能证明原始分辨率下的细字保留质量。没有文字真值或干净图像真值。

观察到 appearance 能白化纸面，课程表的彩色填充比现有算法保留更多；公式页仍有浅文字，需要放大检查。deshadowing 保留颜色，但本次图片纸面仍偏灰。推理明显慢于现有滤镜，样本量不足以证明适合直接替换；没有接入应用，也无法据此声称达到扫描全能王效果。

复现：`PYTHONPATH=src .venv/bin/python scripts/evaluate_docres.py`。需要 torch、einops 和 OpenCV，实验目录内 `code/models/restormer_arch.py` 来自官方仓库，`weights/docres-mirror.pkl` 是上述镜像权重。可通过 `DOCRES_MAX_EDGE`、`DOCRES_SAMPLES`、`DOCRES_STUDY_DIR` 设置尺寸、逗号分隔样本及实验目录；输入读取 `output/scan-challenge/sources/`。脚本仅写入实验目录。

后续需要在原尺寸彩色图表上验证，并评估利用模型估计光照、保留原始高分辨率笔画的方案。中文混排去手写则需要标注样本衡量误删和残留。
