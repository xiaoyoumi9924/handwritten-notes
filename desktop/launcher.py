"""Desktop window for the local application."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import tempfile
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

from markdown_to_handwrite.web import LimitedHTTPServer, WebApp


class DesktopExport:
    def __init__(self, output: Path):
        self.output = output.resolve()
        self.window = None

    def save_export(self, url: str, filename: str) -> dict:
        import webview

        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/output/'):
            raise ValueError('导出文件地址无效。')
        relative = unquote(parsed.path.removeprefix('/output/'))
        source = (self.output / relative).resolve()
        if not source.is_relative_to(self.output) or not source.is_file():
            raise ValueError('导出文件不存在，请重新生成。')
        name = Path(filename).name
        if name != filename or not name or Path(name).suffix.lower() != source.suffix.lower():
            raise ValueError('导出文件名无效。')
        destination = self.window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        if not destination:
            return {'cancelled': True}
        target = Path(destination[0] if isinstance(destination, (list, tuple)) else destination)
        if target.resolve() == source:
            return {'name': target.name}
        # Copy alongside the destination before replacing it to avoid partial files.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.miaobi-', delete=False) as stream:
                temporary = Path(stream.name)
                with source.open('rb') as original:
                    shutil.copyfileobj(original, stream)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {'name': target.name}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    args = parser.parse_args()
    output = Path.home() / '妙笔工坊' / 'output'
    output.mkdir(parents=True, exist_ok=True)
    server = LimitedHTTPServer(('127.0.0.1', 0), WebApp(output).handler_class())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        if args.smoke_test:
            with urlopen(url + '/api/bootstrap', timeout=30) as response:
                data = json.load(response)
                assert data.get('presets'), 'presets are missing'
            with urlopen(url, timeout=30) as response:
                assert b'<!doctype html' in response.read().lower()
            markdown = "# 桌面版自检\n\n公式 $x_1$"
            with tempfile.TemporaryDirectory() as temp:
                app = WebApp(Path(temp))
                result = app.render_service.render(markdown, {'page': {'dpi': 96}})
                assert result['pdf'] and result['docx'] and result['image']
            if sys.stdout is not None:
                print('Desktop smoke test passed')
            return
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        api = DesktopExport(output)
        api.window = webview.create_window('妙笔工坊', url, js_api=api, width=1440, height=900, min_size=(900, 650))
        webview.start()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
