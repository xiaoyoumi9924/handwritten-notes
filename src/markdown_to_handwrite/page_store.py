"""Temporary, disk-backed pages used by the web renderer."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from PIL import Image


class DiskPages(Sequence[Image.Image]):
    def __init__(self, directory: Path):
        self.directory = directory
        self.paths: list[Path] = []
        self.active: Image.Image | None = None

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> Image.Image:
        index = range(len(self))[index]
        if index == len(self) - 1 and self.active is not None:
            return self.active
        with Image.open(self.paths[index]) as source:
            return source.convert("RGBA")

    def __iter__(self) -> Iterator[Image.Image]:
        for index in range(len(self)):
            yield self[index]

    def append(self, page: Image.Image) -> None:
        if self.active is not None:
            raise RuntimeError("Previous page must be saved before adding another.")
        self.paths.append(self.directory / f"page-{len(self.paths) + 1:06d}.png")
        self.active = page

    def save(self, index: int, page: Image.Image) -> None:
        page.save(self.paths[index], format="PNG", compress_level=3)

    def spill(self) -> None:
        if self.active is not None:
            self.save(len(self) - 1, self.active)
            self.active.close()
            self.active = None
