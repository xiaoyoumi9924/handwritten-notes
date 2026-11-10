# 贴边纸张与浅色笔迹：2026-11-08 实现

## 已接入

- 在原有完整纸张和三边检测均失败后，增加两条相邻可见纸边的检测。要求长边位于外缘、近处和更远处的内外亮度差均成立、页面占比足够大，并验证贴着画面的两边仍是同一浅色纸面。四种旋转方向共享检测；看不到的边保持在照片边界，不补造画外内容。这不是曲面展平，纸张弯曲时仍可能出现比例误差。
- 智能高清保留现有白底与笔画提取，追加浅红、浅蓝笔迹保护：以局部纸底的Lab色差、原始色相及已有笔画证据共同判断，补偿曝光并适度增强低饱和颜色。高饱和笔迹继续使用原有映射。去阴影内部复用高清清理时也会获得该改善。没有接入新模型或图像生成接口。
- 预览处理版本从16更新到17，避免使用旧的滤镜缓存。

## 本次原图

1280×1707输入，原自动角点为空；新检测为归一化点：
`[[0,0],[0.719027,0],[0.909196,0.920441],[0,0.974073]]`。
结果为1167×1663。已去掉主要右侧杂页及底部桌面；顶端仍有窄小背景，部分浅红笔画仍有灰黑成分，纸面展平和保色均未达到商业参考。原图左上纸角出画，不能声称恢复真实纸张比例。

输出在 `output/camscanner-implementation-20261108/`：
- `result.png`：实际新处理流程结果。
- `comparison.jpg`：旧自动处理、新自动处理、商业截图参考。三者几何及采样不同，仅作视觉比较。
- `ink-detail.jpg`：相同几何选区下的笔迹前后对照。
- `regression/`：5张已有照片、25个滤镜输出及智能高清相同几何对照。
- `geometry-regression.json`：5张既有照片的新旧角点保持一致。
- `http-smoke.json`：运行中的8877服务实际上传、扫描、滤镜预览、PNG导出，确认处理版本17和新角点。

单图低饱和颜色增强仍是启发式。彩色纸面、轻微彩色噪声、失焦字和弯曲边缘仍须更多真实照片验证；未计算OCR准确率或像素真值指标。

## 验证

61项扫描相关测试和20个子测试通过；前端扫描状态、上传格式两项脚本检查通过。新增回归覆盖浅红蓝笔迹、暖/冷纸底上的中性铅笔、四方向贴边纸张，以及不能将纸内长线误认成纸边的负样本。此前测试暴露的纸内线误裁已用更远处的外部亮度验证修正。

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/test_scan_pale_ink.py tests/test_scan_enhancement.py tests/test_scanner_filters.py tests/test_scan_corners.py tests/test_scan_previews.py tests/test_scan_restoration.py tests/test_scan_formats.py tests/test_scan_erase_enhancement.py tests/test_handwriting_removal.py -q
node --test tests/test_scan_state.cjs tests/test_scan_upload_formats.cjs
PYTHONPATH=src .venv/bin/python scripts/evaluate_scan_filters.py --output output/camscanner-implementation-20261108/regression
```

实际网页服务已验证使用新版；刷新页面并重新扫描，或重新导入原图即可试用。旧导出图片不会自动更新。
