"""Fungsi bantu kecil: format ukuran, waktu, teks."""
from __future__ import annotations

import html
import re


def h(text) -> str:
    """Escape teks untuk parse_mode HTML Telegram."""
    return html.escape(str(text), quote=False)


def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fmt_time(sec: float) -> str:
    sec = int(max(0, sec or 0))
    hh, rest = divmod(sec, 3600)
    mm, ss = divmod(rest, 60)
    return f"{hh:d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"


def parse_time(text: str):
    """'90' -> 90 detik, '25:30' -> 1530, '1:02:03' -> 3723. None bila tidak valid."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def progress_bar(fraction: float, width: int = 12) -> str:
    fraction = min(max(fraction, 0.0), 1.0)
    filled = round(fraction * width)
    return "▰" * filled + "▱" * (width - filled)


def trunc(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def clean_title(stem: str) -> str:
    """'Film.Bagus_2023.720p' -> 'Film Bagus 2023 720p'."""
    return re.sub(r"\s+", " ", re.sub(r"[._]+", " ", stem)).strip() or stem
