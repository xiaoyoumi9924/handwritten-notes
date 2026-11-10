> 已停用：智能扫描中的“去除手写”已由“反色”替换，应用不会加载此模型。下文仅保留历史实验记录。

# 去手写试用模型

默认模型位置：`models/handwriting/isnet5.pth`（权重不提交到 Git）。

- 来源：https://huggingface.co/Inoob/HandwritingEraser
- 文件：https://huggingface.co/Inoob/HandwritingEraser/resolve/main/isnet5.pth
- SHA-256：`d685cc76a8c4d6aebf9a82499b7771d13aaa27ebd90e933036bdd004db4beefa`
- 大小：176718414 bytes
- 模型仓库声明 Apache-2.0，未提供训练集和验证集详情。
- 架构：xuebinqin/DIS 的 ISNetDIS，Apache-2.0，代码及许可证位于 `src/markdown_to_handwrite/vendor/`。

安装可选依赖：`pip install '.[scan-ai]'`。放好权重后重启本地服务，界面自动启用“去除手写（试用）”。运行时只在本机推理，不自动联网下载或发送照片。

当前环境已放置并校验权重。推理前会再次校验 SHA-256，并使用 PyTorch 的 `weights_only=True` 加载。

适用于纸面较清晰的印刷试卷。仍可能残留红笔边缘、手画图形，也可能误删与印刷内容重叠的笔迹；照片、弯曲、阴影或纯手写笔记上的表现不能保证。请对比原图检查。

当前处理会先对模型输入校正光照；掩码由 0.35 候选区域和 0.8 强响应种子共同确定，部分低置信页面会分块重试。长直线被保护以减少表格线受损，手画的长直线也可能因此保留。擦除区域使用邻域修复，掩码外原始像素保持不变。该光照估计适用于浅色纸张，并不等于照片通用修复或书页展平。

扫描“去除手写”模式现在会在擦除后默认执行智能高清（版本16）。低层擦除依然保留蒙版外原图，但最终白底增强会改变整页像素。大图稀疏笔迹也可能触发分块重试，仍不能保证清除所有手写公式；本轮实测与候选模型局限见 `references/handwriting-erasure-followup.md`。
