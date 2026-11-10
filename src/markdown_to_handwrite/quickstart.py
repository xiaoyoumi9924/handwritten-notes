"""Start the local web app, choosing a free port if the default is busy."""
from __future__ import annotations

import socket
import sys

from . import web


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(arg == '--port' or arg.startswith('--port=') for arg in args):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1', 8765))
            except OSError:
                print('默认端口已占用，正在选择可用端口。', flush=True)
                args.extend(['--port', '0'])
    return web.main(args)


if __name__ == '__main__':
    raise SystemExit(main())
