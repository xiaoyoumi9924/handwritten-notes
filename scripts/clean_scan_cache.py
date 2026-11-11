"""List or remove old, regenerable scan previews without touching exports."""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

SCAN_DIR = re.compile(r"[0-9a-f]{16}\Z")
CACHE_FILE = re.compile(r"(?:filter|restored)-[0-9a-f]{24}\.webp\Z")
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "output" / "webui" / "scans"


def clean_cache(root: Path, *, age_days: int = 7, delete: bool = False, now: float | None = None) -> tuple[int, int]:
    if age_days < 1:
        raise ValueError("保留天数必须至少为 1 天。")
    cutoff = (time.time() if now is None else now) - age_days * 86400
    count = size = 0
    if not root.is_dir() or root.is_symlink():
        return count, size
    for directory in root.iterdir():
        if not SCAN_DIR.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if not CACHE_FILE.fullmatch(entry.name) or entry.is_symlink() or not entry.is_file():
                continue
            try:
                stat = entry.stat()
                if stat.st_mtime >= cutoff:
                    continue
                if delete:
                    entry.unlink()
            except FileNotFoundError:
                continue
            count += 1
            size += stat.st_size
    return count, size


def main() -> None:
    parser = argparse.ArgumentParser(description="查看或清理过期的扫描预览缓存，不删除原图或导出文件。")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="扫描缓存目录；桌面版通常为 ~/妙笔工坊/output/scans")
    parser.add_argument("--days", type=int, default=7, help="保留最近多少天的预览（默认 7 天）")
    parser.add_argument("--delete", action="store_true", help="执行删除；不加时只显示可清理数量和大小")
    args = parser.parse_args()
    try:
        count, size = clean_cache(args.root.expanduser(), age_days=args.days, delete=args.delete)
    except ValueError as error:
        parser.error(str(error))
    action = "已清理" if args.delete else "可清理"
    print(f"{action} {count} 个扫描预览缓存，共 {size / 1024 / 1024:.1f} MiB。")


if __name__ == "__main__":
    main()
