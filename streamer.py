"""Mesin siaran: mengatur proses ffmpeg yang mengirim video ke RTMP Telegram."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

import config
from library import Movie

log = logging.getLogger("tgstream.streamer")

MAX_COPY_BITRATE = 4_500_000  # bps; di atas ini lebih aman di-transcode


class StreamError(Exception):
    """Error yang pesannya aman ditampilkan ke pengguna."""


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    vcodec: str = ""
    pix_fmt: str = ""
    bitrate: int = 0
    audio: list = field(default_factory=list)  # [(codec, bahasa)]


async def probe(path: Path) -> MediaInfo:
    info = MediaInfo()
    if not shutil.which("ffprobe"):
        return info
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 30)
        data = json.loads(out or b"{}")
    except (asyncio.TimeoutError, OSError, ValueError):
        return info
    fmt = data.get("format", {})
    info.duration = float(fmt.get("duration") or 0)
    info.bitrate = int(float(fmt.get("bit_rate") or 0))
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind == "video" and not info.vcodec and not s.get("disposition", {}).get("attached_pic"):
            info.vcodec = s.get("codec_name", "")
            info.pix_fmt = s.get("pix_fmt", "")
            info.width = int(s.get("width") or 0)
            info.height = int(s.get("height") or 0)
        elif kind == "audio":
            info.audio.append((s.get("codec_name", "?"), s.get("tags", {}).get("language", "")))
    return info


class Streamer:
    def __init__(self, store, on_finish: Callable[..., Awaitable[None]]):
        self.store = store
        self.on_finish = on_finish
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.movie: Optional[Movie] = None
        self.info: Optional[MediaInfo] = None
        self.mode = ""
        self.start_at = 0.0
        self.position = 0.0
        self.speed = ""
        self.started_at = 0.0
        self.stopping = False
        self.tail: deque = deque(maxlen=12)
        self._lock = asyncio.Lock()

    # -- status ------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def speed_value(self) -> float:
        try:
            return float(self.speed.rstrip("x"))
        except ValueError:
            return 0.0

    # -- rencana encode ----------------------------------------------------
    def _track(self, info: MediaInfo) -> int:
        track = int(self.store.get("audio_track") or 1)
        return max(1, min(track, len(info.audio))) if info.audio else 1

    def plan(self, info: MediaInfo):
        """Return ('copy', None) atau ('encode', nama_preset)."""
        quality = self.store.get("quality")
        if quality in config.QUALITY:
            return "encode", quality
        acodec = info.audio[self._track(info) - 1][0] if info.audio else None
        video_ok = (
            info.vcodec == "h264"
            and info.pix_fmt in ("yuv420p", "yuvj420p")
            and info.height <= 1080
            and (info.bitrate == 0 or info.bitrate <= MAX_COPY_BITRATE)
        )
        if video_ok and acodec in (None, "aac"):
            return "copy", None
        return "encode", "480p"

    def describe_mode(self, info: MediaInfo) -> str:
        kind, preset = self.plan(info)
        if kind == "copy":
            return "⚡ Copy langsung (tanpa re-encode, hemat baterai/CPU)"
        return f"🔄 Transcode {preset} (lebih berat di CPU)"

    @staticmethod
    def _encode_args(preset: str) -> list:
        height, vb, ab = config.QUALITY[preset]
        return [
            "-vf", f"scale=-2:'min({height},ih)'",
            "-c:v", "libx264", "-preset", config.X264_PRESET, "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-b:v", f"{vb}k", "-maxrate", f"{vb}k", "-bufsize", f"{vb * 2}k",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-c:a", "aac", "-b:a", f"{ab}k", "-ar", "44100", "-ac", "2",
        ]

    def build_cmd(self, movie: Optional[Movie], info: Optional[MediaInfo], start_at: float, test: bool, url: str):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-progress", "pipe:1", "-nostats"]
        if test:
            cmd += ["-re", "-f", "lavfi", "-i", "testsrc2=size=854x480:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "20"]
            cmd += self._encode_args("480p")
            mode = "🧪 Tes pola warna + nada (20 detik)"
        else:
            kind, preset = self.plan(info)
            if start_at > 0:
                cmd += ["-ss", f"{start_at:.2f}"]
            cmd += ["-re", "-i", str(movie.path), "-map", "0:v:0", "-map", f"0:a:{self._track(info) - 1}?", "-sn", "-dn"]
            if kind == "copy":
                cmd += ["-c", "copy"]
            else:
                cmd += self._encode_args(preset)
            mode = self.describe_mode(info)
        cmd += ["-flvflags", "no_duration_filesize", "-f", "flv", url]
        return cmd, mode

    # -- kontrol -----------------------------------------------------------
    async def start(self, movie: Optional[Movie], start_at: float = 0.0, test: bool = False) -> None:
        async with self._lock:
            if self.running:
                raise StreamError("Siaran sedang berjalan. Hentikan dulu atau tambahkan ke antrian.")
            if not self.store.configured:
                raise StreamError("RTMP URL / Stream Key belum diatur. Buka ⚙️ Pengaturan → Atur RTMP.")
            if not shutil.which("ffmpeg"):
                raise StreamError("ffmpeg belum terpasang. Jalankan di Termux: pkg install ffmpeg")
            info = None
            if not test:
                if not movie.path.exists():
                    raise StreamError("File film tidak ditemukan. Coba 🔄 Scan Ulang.")
                info = await probe(movie.path)
                if not info.vcodec:
                    raise StreamError("File ini tidak terbaca sebagai video (rusak atau belum selesai diunduh).")
                if start_at and info.duration and start_at >= info.duration:
                    raise StreamError("Waktu mulai melebihi durasi film.")
            url = self.store.full_url()
            cmd, mode = self.build_cmd(movie, info, start_at, test, url)
            log.info("Mulai siaran: %s (%s)", movie.title if movie else "tes", mode)

            self.tail.clear()
            self.stopping = False
            self.movie = movie
            self.info = info
            self.mode = mode
            self.start_at = start_at
            self.position = start_at
            self.speed = ""
            self.started_at = time.time()
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                raise StreamError(f"Gagal menjalankan ffmpeg: {exc}")
            asyncio.create_task(self._supervise(self.proc, movie))

    async def stop(self) -> bool:
        if not self.running:
            return False
        self.stopping = True
        try:
            self.proc.terminate()
            await asyncio.wait_for(self.proc.wait(), 6)
        except asyncio.TimeoutError:
            self.proc.kill()
        except ProcessLookupError:
            pass
        return True

    # -- internal ----------------------------------------------------------
    async def _read_stdout(self, proc):
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            text = line.decode("utf-8", "ignore").strip()
            if "=" not in text:
                continue
            key, _, value = text.partition("=")
            if key in ("out_time_us", "out_time_ms"):
                try:
                    self.position = self.start_at + int(value) / 1_000_000
                except ValueError:
                    pass
            elif key == "speed":
                self.speed = value.strip()

    async def _read_stderr(self, proc):
        secret = self.store.get("stream_key") or "\x00"
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "ignore").strip()
            if not text:
                continue
            text = text.replace(secret, "***")
            text = re.sub(r"rtmps?://\S+", "rtmp://***", text)
            self.tail.append(text)
            log.debug("ffmpeg: %s", text)

    async def _supervise(self, proc, movie):
        await asyncio.gather(self._read_stdout(proc), self._read_stderr(proc))
        rc = await proc.wait()
        if self.stopping:
            reason = "stopped"
        elif rc == 0:
            reason = "ended"
        else:
            reason = "error"
        log.info("Siaran selesai: %s (rc=%s)", reason, rc)
        try:
            await self.on_finish(reason, movie, rc, list(self.tail))
        except Exception:  # jangan sampai callback menjatuhkan task
            log.exception("on_finish gagal")
