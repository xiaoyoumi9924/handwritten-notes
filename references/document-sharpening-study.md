# 用增强锐化替换去阴影入口

## 已接入

扫描界面“去阴影”已换成“增强锐化”，内部模式 `sharp`、预览版本18。已有智能高清、反色、增亮和黑白不变。旧 `shadow` 后端处理保留兼容历史调用，不再出现在可选滤镜和预览列表。

增强锐化是一条独立文档处理流程：估计纸面光照；用亮部纸面做整体白平衡和统一RGB亮度增益（上限2.8倍）；柔和调整黑白点；轻量保边降噪；仅在Lab亮度通道做小半径锐化，并把增强后的亮度限制在邻域既有范围，减少过冲和光晕。不做文字识别、笔迹膨胀或AI生成。不会恢复严重失焦或源图缺失的细节。

智能高清主要按局部笔画提取清理背景；增强锐化则保留连续灰阶和更广的颜色信息，再提高边缘对比。两者都可能白化纸面，但用途和取舍不同。彩色阴影和折痕仍可能残留，部分浅笔迹和透字也可能被增强。

## 资料依据

- [scikit-image Unsharp masking](https://scikit-image.org/docs/stable/auto_examples/filters/plot_unsharp_mask.html)：差分锐化原理和参数。官方说明多颜色通道独立锐化可能带来颜色问题，因此本实现将细节增强限制在亮度通道。
- [OpenCV edge-preserving / detail enhancement](https://docs.opencv.org/4.x/df/dac/group__photo__render.html)：保边滤波与细节增强的用途；本实现使用已有OpenCV运算，没有增加依赖，也没有直接使用面向风格化的detailEnhance来模拟扫描。
- [Document Enhancement Using Visibility Detection，CVPR 2018](https://openaccess.thecvf.com/content_cvpr_2018/papers/Kligler_Document_Enhancement_Using_CVPR_2018_paper.pdf)：文档增强中的照明、可读性与颜色保留问题。仅作为方向参考，未复现该论文算法。

## 与用户参考对照

六张截图是三组输入/增强锐化配对，来自 `IMG_4384/4383`、`4386/4387`、`4388/4389`。按各组显示页面的位置裁切，保留页面中的界面叠加，因此不当作干净图像真值。截图经过缩放，无法判断原始全分辨率的笔画细节，也无法推断扫描全能王内部算法。

`output/document-sharp-study/{1,2,3}-comparison.jpg` 的四列依次是输入截图、现有智能高清、新增强锐化、用户参考增强锐化。白底、红色批注和较细线条可见保留，但文字浓度、纸面残影等仍与参考有差异，不能声称完全一致。

另对已有记事本、密集公式、收据、彩色表格和中文笔记5张实拍照片运行全部当前滤镜，共30个结果，保存在 `output/document-sharp-study/real/`。本机三张截图裁片单张增强运算约0.116–0.197秒（像素尺寸1126×913至1126×1717），不包括上传、裁边、存储或端到端时间。这些样本不是充分的质量验证集。

第一轮实拍检查发现逐通道局部背景归一化会漂白彩色表格填充，已改成整体纸色白平衡和统一亮度增益；新增对应回归测试。

## 验证

扫描相关58项与20个子测试通过，前端扫描状态与上传格式检查通过。新增5项针对白底、红蓝笔迹、单像素细线、模糊边缘、空白纸面噪声、彩色填充、旋转裁切及预览与PNG导出一致的检查。真实HTTP验证上传、增强锐化、缩略图及PNG/JPG/PDF/Word导出；浏览器实际上传参考裁片并选择增强锐化、扫描，确认新入口、结果和导出按钮可用。服务已更新，刷新并重新扫描可使用。

复现：`PYTHONPATH=src .venv/bin/python scripts/evaluate_document_sharp.py`（需要六张本机参考截图），`PYTHONPATH=src .venv/bin/python scripts/evaluate_scan_filters.py --output output/document-sharp-study/real`。
