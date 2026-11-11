"""Desktop window for the local application."""
from __future__ import annotations

import argparse
import json
import threading
import tempfile
import sys
from pathlib import Path
from urllib.request import urlopen

from markdown_to_handwrite.web import LimitedHTTPServer, WebApp


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
            with tempfile.TemporaryDirectory() as temp:
                app = WebApp(Path(temp))
                result = app.render_service.render('中文 test $x^2$', {'page': {'dpi': 96}})
                assert result['pdf'] and result['docx'] and result['image']
            if sys.stdout is not None:
                print('Desktop smoke test passed')
            return
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.create_window('妙笔工坊', url, width=1440, height=900, min_size=(900, 650))
        webview.start()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
