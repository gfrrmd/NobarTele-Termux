"""Pemindai folder film (default: Download Android)."""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config
from utils import clean_title

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".flv", ".wmv", ".mpg", ".mpeg"}


@dataclass(frozen=True)
class Movie:
    id: str
    path: Path
    title: str
    size: int


class Library:
    def __init__(self, store):
        self.store = store
        self._items: list[Movie] = []
        self._by_id: dict[str, Movie] = {}
        self.scanned_at: float = 0.0

    def __len__(self) -> int:
        return len(self._items)

    def scan(self) -> int:
        """Blocking; panggil lewat asyncio.to_thread."""
        root = self.store.movie_dir
        items: list[Movie] = []
        if root.is_dir():
            base_depth = len(root.parts)
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "Android"]
                if len(Path(dirpath).parts) - base_depth >= config.SCAN_DEPTH:
                    dirs[:] = []
                for name in files:
                    if os.path.splitext(name)[1].lower() not in VIDEO_EXT:
                        continue
                    path = Path(dirpath) / name
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    if size <= 0:
                        continue
                    mid = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
                    items.append(Movie(mid, path, clean_title(path.stem), size))
        items.sort(key=lambda m: m.title.casefold())
        self._items = items
        self._by_id = {m.id: m for m in items}
        self.scanned_at = time.time()
        return len(items)

    def search(self, query: Optional[str] = None) -> list[Movie]:
        if not query:
            return list(self._items)
        words = query.casefold().split()
        return [m for m in self._items if all(w in (m.title + " " + m.path.name).casefold() for w in words)]

    def get(self, movie_id: str) -> Optional[Movie]:
        return self._by_id.get(movie_id)
