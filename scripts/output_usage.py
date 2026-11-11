"""Report output storage use without changing any files."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "output" / "webui"
JOB_NAME = re.compile(r"[0-9a-f]{16}\Z")


def tree_size(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            file = Path(directory) / name
            try:
                if not file.is_symlink():
                    total += file.stat().st_size
            except FileNotFoundError:
                continue
    return total


def collect_usage(root: Path) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    jobs, other = [], []
    if not root.is_dir() or root.is_symlink():
        return jobs, other
    for entry in root.iterdir():
        if entry.is_symlink():
            continue
        target = jobs if entry.is_dir() and JOB_NAME.fullmatch(entry.name) and (entry / "metadata.json").is_file() else other
        target.append((entry.name, tree_size(entry)))
    return sorted(jobs, key=lambda item: item[1], reverse=True), sorted(other, key=lambda item: item[1], reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="统计手稿输出占用，不删除任何文件。")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Web 输出目录；桌面版通常为 ~/妙笔工坊/output")
    parser.add_argument("--top", type=int, default=10, help="显示占用最大的任务数量（默认 10 个）")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("显示数量不能为负数。")
    jobs, other = collect_usage(args.root.expanduser())
    mib = 1024 * 1024
    print(f"生成任务：{len(jobs)} 个，共 {sum(size for _, size in jobs) / mib:.1f} MiB")
    for name, size in jobs[:args.top]:
        print(f"  {name}  {size / mib:.1f} MiB")
    for name, size in other:
        print(f"其他：{name}  {size / mib:.1f} MiB")
    print("历史记录可能依赖这些输出文件；本工具不删除文件。")


if __name__ == "__main__":
    main()
