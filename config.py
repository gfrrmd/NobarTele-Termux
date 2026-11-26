"""Konfigurasi: membaca .env dan menyimpan pengaturan (RTMP, kualitas, dll)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", os.getenv("ADMIN_IDS", "")) if x.strip().isdigit()}
DEFAULT_MOVIE_DIR = os.getenv("MOVIE_DIR", "~/storage/downloads").strip() or "~/storage/downloads"
X264_PRESET = os.getenv("X264_PRESET", "veryfast").strip() or "veryfast"
SCAN_DEPTH = int(os.getenv("SCAN_DEPTH", "4") or 4)

# kualitas: tinggi (px), bitrate video (kbps), bitrate audio (kbps)
QUALITY = {
    "360p": (360, 600, 96),
    "480p": (480, 1100, 128),
    "720p": (720, 2500, 128),
}
QUALITY_CHOICES = ["auto", "360p", "480p", "720p"]


class Store:
    """Pengaturan yang bisa diubah dari bot, disimpan di data/settings.json."""

    DEFAULTS = {
        "rtmp_url": "",
        "stream_key": "",
        "quality": "auto",
        "audio_track": 1,
        "movie_dir": "",
    }

    def __init__(self, path: Path = DATA_DIR / "settings.json"):
        self.path = path
        self._d = dict(self.DEFAULTS)
        if path.exists():
            try:
                self._d.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    # -- dasar -------------------------------------------------------------
    def get(self, key: str):
        return self._d.get(key, self.DEFAULTS.get(key))

    def set(self, **kwargs) -> None:
        self._d.update(kwargs)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._d, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    # -- folder film -------------------------------------------------------
    @property
    def movie_dir(self) -> Path:
        raw = self.get("movie_dir") or DEFAULT_MOVIE_DIR
        return Path(os.path.expanduser(raw))

    # -- RTMP --------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.get("rtmp_url") and self.get("stream_key"))

    def full_url(self) -> str:
        return f"{self.get('rtmp_url').rstrip('/')}/{self.get('stream_key').strip().lstrip('/')}"

    def masked_key(self) -> str:
        key = self.get("stream_key") or ""
        if not key:
            return "(kosong)"
        return key[:4] + "•" * 6 + key[-3:] if len(key) > 10 else "•" * len(key)

    @staticmethod
    def parse_rtmp(text: str):
        """Terima 'URL', 'URL KEY', atau 'URL/KEY' penuh. Return (url, key|None) atau None."""
        tokens = text.split()
        if not tokens or not re.match(r"^rtmps?://", tokens[0], re.I):
            return None
        if len(tokens) >= 2:
            return tokens[0], tokens[1]
        m = re.match(r"^(rtmps?://[^/]+/s/)(.+)$", tokens[0], re.I)
        if m:
            return m.group(1), m.group(2)
        return tokens[0], None


store = Store()
