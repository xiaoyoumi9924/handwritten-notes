# ✍️ 妙笔工坊

> 将 Markdown 和 Word 文档转换为手写风格的笔记，也可以扫描、整理纸质文档。

支持中文、英文和数学公式，可调整书体、纸张和排版，在本地浏览器中预览并导出。

![妙笔工坊文本转换界面](docs/images/workspace-example.png)

## 立即下载

| 系统 | 下载 |
| --- | --- |
| Windows 10 / 11（64 位） | [下载 Windows 版](https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/Miaobi-Windows.zip) |
| macOS（Apple 芯片） | [下载 macOS Apple 芯片版](https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/Miaobi-macOS-Apple-Silicon.zip) |
| macOS（Intel 芯片） | [下载 macOS Intel 版](https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/Miaobi-macOS-Intel.zip) |
| Ubuntu / Linux（64 位） | [下载 Linux 版](https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/Miaobi-Linux.tar.gz) |

下载并解压后，Windows 双击 `Miaobi.exe`；macOS 打开 `Miaobi.app`；Linux 运行 `Miaobi` 文件夹中的 `Miaobi`。程序在本机运行，无需另外安装 Python。

macOS 版尚未经过 Apple 公证，首次打开时可能需要在「系统设置 → 隐私与安全性」中允许打开。Windows 版需要系统安装 Microsoft Edge WebView2 运行时。Linux 版使用 Qt 界面，可能需要安装系统图形库。

## 功能

- **文本转换**：输入或导入 Markdown、Word（DOCX），保留标题、段落、列表、表格和常见公式的排版。
- **手写排版**：提供「纸间清风体」和「游丝细行体」，支持调整字号、字距、笔画和纸张背景。
- **页面预览**：逐页查看转换结果，可添加批注、高亮、下划线，以及裁剪页面。
- **智能扫描**：导入图片，裁切矫正纸面，使用智能高清、黑白、增亮、灰度或反色效果。
- **导出与记录**：文本转换和扫描结果支持导出图片、Word 或 PDF，可在导出记录中查看和筛选。

## 使用步骤

### 1. 打开程序

解压并打开上方下载的桌面应用。也可以按照[本地部署](#本地部署可选)从源码启动，然后在浏览器访问 <http://127.0.0.1:8765/>；源码方式使用期间请保持终端窗口打开。

### 2. 转换手写文稿

1. 在「文本转换」中选择 Markdown 或 Word 文件，也可以直接粘贴文字。
2. 选择正文书体、纸张背景和输出格式；展开「更多排版参数」可继续调整。
3. 点击「开始转换」，在右侧逐页预览；需要时添加批注、高亮或下划线。
4. 确认效果后点击导出，选择图片、Word 或 PDF。

### 3. 扫描纸质文档

1. 切换到「智能扫描」，上传文档照片，支持 JPG、PNG、HEIC/HEIF、BMP 和 WebP。
2. 调整纸面裁切范围，选择智能高清、黑白、增亮、灰度或反色等效果，点击「开始扫描」。
3. 逐页检查结果，可旋转或添加标记，再选择图片、Word 或 PDF 导出。

导出后可在「导出记录」中查看文件。编辑器草稿保存在浏览器本地，桌面版的预览和导出文件保存在用户目录下的 `妙笔工坊/output/`；源码版保存在项目的 `output/webui/`。

## 本地部署（可选）

如果希望在浏览器里使用 Web 版，可以在本地一键部署。先安装 [Node.js](https://nodejs.org/)、[Git](https://git-scm.com/downloads) 和 [Python 3.10+](https://www.python.org/downloads/)，然后在终端运行：

**macOS / Linux**

```bash
curl -fsSL https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/install.sh | bash
```

**Windows PowerShell**

```powershell
irm https://github.com/xiaoyoumi9924/handwritten-notes/releases/latest/download/install.ps1 | iex
```

第一次运行会下载源码、安装依赖并打开页面，同时安装 `miaobi` 命令；以后重新打开终端，运行 `miaobi` 即可启动。默认地址为 <http://127.0.0.1:8765/>；如果端口已被占用，程序会自动选择其他端口，并在终端显示地址。使用期间保持终端打开，按 `Ctrl+C` 停止。

> Web 版实际使用 Python 和 Git；Node.js 不参与当前版本的运行。Windows 安装 Python 时请保留 Python Launcher（`py`）。源码和生成文件保存在用户目录下的 `.miaobi/app/`，已有安装不会被覆盖。

## ✍️ 定制你的笔迹

想让生成的字更接近自己的笔迹？项目提供基于 [SDT](https://github.com/dailenson/SDT) 的个性化笔迹研究工具：收集并整理手写样本后，可使用 SDT 模型生成笔画轨迹，检查效果并探索制作自己的笔迹风格。

1. 准备清晰、无水印的手写样本，并整理成单字参考图。
2. 从 [SDT 项目](https://github.com/dailenson/SDT)获取源码并放到 `references/SDT/`，按其说明准备独立环境、数据和预训练权重；本仓库不包含这些源码、数据和权重。
3. 参考[笔迹研究记录](training/new_chinese_handwriting/README.md)运行样本处理和轨迹生成脚本，再检查生成字形的可读性。

> 个性化笔迹仍处于实验阶段，当前流程需要手动准备数据和环境，尚未集成到应用界面；静态照片不能直接替代 SDT 训练所需的在线笔迹轨迹，生成效果也需要逐字检查。本仓库不提供 SDT 源码，请从 [SDT 官方项目](https://github.com/dailenson/SDT)获取；训练和推理的具体要求请以原项目说明为准。

## 致谢

感谢以下开源项目和作者为妙笔工坊提供的代码、研究与灵感：

- [SDT](https://github.com/dailenson/SDT)：手写笔迹生成与个性化研究基础。
- [HandwriteCraft](https://github.com/Eyjafjallaaa/HandwriteCraft)：手写文稿生成和界面设计参考。
- [Handright](https://github.com/Gsllchb/Handright)：可选的手写文字渲染方案。
- [hfmath](https://github.com/LingDong-/hfmath)：数学公式排版思路参考。
- [DIS](https://github.com/xuebinqin/DIS)：手写擦除实验所用的模型架构代码。

## 许可

项目源代码采用 [MIT License](LICENSE)。字体、笔迹资源和第三方代码的授权信息见 [ASSET_LICENSES.md](ASSET_LICENSES.md)。
