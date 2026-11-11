"""Preview or remove explicitly selected generated jobs."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from output_usage import DEFAULT_ROOT, JOB_NAME, tree_size


def select_jobs(root: Path, job_ids: list[str]) -> list[tuple[Path, int]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("输出目录不存在或是符号链接。")
    if not job_ids or len(set(job_ids)) != len(job_ids):
        raise ValueError("请提供不重复的任务编号。")
    selected = []
    for job_id in job_ids:
        if not JOB_NAME.fullmatch(job_id):
            raise ValueError(f"无效的任务编号：{job_id}")
        job = root / job_id
        metadata = job / "metadata.json"
        if job.is_symlink() or not job.is_dir() or metadata.is_symlink() or not metadata.is_file():
            raise ValueError(f"任务不存在或不是可识别的生成任务：{job_id}")
        selected.append((job, tree_size(job)))
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="查看或清理指定的生成任务；对应的历史下载链接会失效。")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Web 输出目录；桌面版通常为 ~/妙笔工坊/output")
    parser.add_argument("--job", action="append", required=True, help="要处理的任务编号，可重复指定")
    parser.add_argument("--delete", action="store_true", help="删除所列任务；不加时仅预览。请先关闭妙笔工坊。")
    args = parser.parse_args()
    try:
        jobs = select_jobs(args.root.expanduser(), args.job)
    except ValueError as error:
        parser.error(str(error))
    for path, size in jobs:
        print(f"{path.name}  {size / (1024 * 1024):.1f} MiB")
    print(f"共 {len(jobs)} 个任务，{sum(size for _, size in jobs) / (1024 * 1024):.1f} MiB。对应历史下载链接将失效。")
    if not args.delete:
        print("仅预览，没有删除文件。需要删除时，请先关闭妙笔工坊，再添加 --delete。")
        return
    for path, _ in jobs:
        shutil.rmtree(path)
    print("已删除所列任务；浏览器中的历史记录不会自动移除。")


if __name__ == "__main__":
    main()
