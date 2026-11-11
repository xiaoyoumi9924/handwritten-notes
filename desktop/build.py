"""Create a platform-specific application bundle with PyInstaller."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
        '--name', 'Miaobi', '--paths', 'src',
        '--collect-all', 'webview', '--collect-all', 'pillow_heif',
        '--add-data', 'src/markdown_to_handwrite/webui:markdown_to_handwrite/webui',
        '--add-data', 'src/markdown_to_handwrite/assets:markdown_to_handwrite/assets',
        '--add-data', 'background/提取的红线纸.png:background',
        '--add-data', 'background/提取的绿线纸.png:background',
        '--add-data', 'font/1_SDT.ttf:font',
        '--add-data', 'font/AnJingChenYingBiXingShu-2.ttf:font',
        '--add-data', 'font/PingFangShaoHuaTi-2.ttf:font',
        '--add-data', 'font/Latin-Caveat-Regular.ttf:font',
        '--add-data', 'font/Latin-Kalam-Regular.ttf:font',
        '--add-data', 'font/OFL-Caveat.txt:font',
        '--add-data', 'font/OFL-Kalam.txt:font',
        '--add-data', 'font_library/personal_v6:font_library/personal_v6',
        '--add-data', 'configs:configs', '--add-data', 'examples:examples',
        '--exclude-module', 'torch', '--exclude-module', 'tensorflow',
        'desktop/launcher.py']
subprocess.run(args, check=True)
