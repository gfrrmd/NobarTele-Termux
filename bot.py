#!/usr/bin/env python3
"""Watch Party Stream Bot — siarkan film dari HP (Termux) ke Live Stream Telegram via RTMP."""
from __future__ import annotations

import asyncio
import logging
import math
import os
import platform
import shutil
import sys
import time
from functools import wraps
from logging.handlers import RotatingFileHandler

import config
from config import store
from library import Library, Movie
from streamer import MediaInfo, StreamError, Streamer, probe
from utils import fmt_size, fmt_time, h, parse_time, progress_bar, trunc

from telegram import BotCommand, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

log = logging.getLogger("tgstream")
HTML = ParseMode.HTML
PAGE_SIZE = 8

lib = Library(store)
queue: list[Movie] = []
APP: Application | None = None
notify_chat: int | None = None
skipping = False


# ───────────────────────────── notifikasi siaran selesai ─────────────────────────────
HINTS = [
    (("protocol not found",), "ffmpeg tidak mendukung rtmps. Jalankan <code>pkg upgrade ffmpeg</code> atau ganti URL jadi <code>rtmp://</code>."),
    (("connection refused", "input/output error", "server returned", "name or service", "timed out", "broken pipe", "end of file"),
     "Koneksi ke Telegram gagal. Cek: (1) URL & key benar, (2) di Telegram sudah membuka layar Live Stream / menekan <b>Start Streaming</b>, (3) key belum di-<i>revoke</i>, (4) internet stabil."),
    (("unknown encoder", "libx264"), "ffmpeg tidak punya encoder libx264. Pasang ulang: <code>pkg reinstall ffmpeg</code>."),
    (("no such file", "permission denied"), "File tidak bisa dibaca. Pastikan izin penyimpanan Termux aktif (<code>termux-setup-storage</code>)."),
]


async def on_finish(reason: str, movie: Movie | None, rc: int, tail: list) -> None:
    global skipping
    if APP is None or notify_chat is None:
        return
    title = movie.title if movie else "Tes koneksi"
    is_test = movie is None
    if reason == "stopped":
        text = f"⏹ Siaran dihentikan: <b>{h(title)}</b>"
    elif reason == "ended":
        text = f"✅ {'Tes selesai — koneksi RTMP berhasil.' if is_test else 'Selesai ditayangkan: <b>' + h(title) + '</b>'}"
    else:
        joined = "\n".join(tail[-6:])
        text = f"❌ <b>Siaran berhenti karena error</b> (kode {rc})\n🎞 {h(title)}\n"
        if joined:
            text += f"\n<pre>{h(trunc(joined, 700))}</pre>\n"
        low = joined.lower()
        for keys, hint in HINTS:
            if any(k in low for k in keys):
                text += f"\n💡 {hint}"
                break
    try:
        await APP.bot.send_message(notify_chat, text, parse_mode=HTML, reply_markup=kb_main_small())
    except TelegramError:
        log.exception("Gagal kirim notifikasi")

    # lanjut ke antrian
    go_next = (reason == "ended" and not is_test) or (reason == "stopped" and skipping)
    skipping = False
    if go_next and queue:
        nxt = queue.pop(0)
        try:
            await streamer.start(nxt)
            await APP.bot.send_message(
                notify_chat, f"⏭ Memutar berikutnya dari antrian:\n🔴 <b>{h(nxt.title)}</b>", parse_mode=HTML,
                reply_markup=kb_status(),
            )
        except StreamError as exc:
            await APP.bot.send_message(notify_chat, f"⚠️ Gagal memutar antrian: {h(exc)}", parse_mode=HTML)


streamer = Streamer(store, on_finish)


# ───────────────────────────── helper UI ─────────────────────────────
def admin_only(fn):
    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid = user.id if user else 0
        if uid not in config.ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("⛔ Akses ditolak", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Bot ini hanya untuk admin.\nID Telegram kamu: <code>{uid}</code>\n"
                    "Tambahkan ID itu ke <code>ADMIN_IDS</code> di file <code>.env</code> lalu restart bot.",
                    parse_mode=HTML,
                )
            return
        return await fn(update, context)
    return wrapper


async def show(update: Update, text: str, kb: Markup | None = None) -> None:
    q = update.callback_query
    try:
        if q:
            await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb, disable_web_page_preview=True)
        else:
            await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=kb, disable_web_page_preview=True)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def main_text() -> str:
    if streamer.running:
        status = f"🔴 <b>LIVE</b> — {h(streamer.movie.title if streamer.movie else 'Tes koneksi')}"
    else:
        status = "⚪ Tidak sedang menyiarkan"
    return (
        "🎬 <b>Watch Party Stream Bot</b>\n"
        "<i>Siarkan film dari HP ke Live Stream Telegram</i>\n\n"
        f"Status   : {status}\n"
        f"RTMP     : {'✅ siap' if store.configured else '❌ belum diatur (⚙️ Pengaturan)'}\n"
        f"Kualitas : <b>{store.get('quality')}</b>  ·  Audio track: <b>{store.get('audio_track')}</b>\n"
        f"Film     : <b>{len(lib)}</b> file di <code>{h(store.movie_dir)}</code>\n"
        f"Antrian  : <b>{len(queue)}</b> film"
    )


def kb_main() -> Markup:
    rows = [
        [Btn("🎬 Pilih Film", callback_data="libr"), Btn("📊 Status", callback_data="st")],
        [Btn("📋 Antrian", callback_data="queue"), Btn("⚙️ Pengaturan", callback_data="set")],
    ]
    rows.append([Btn("⏹ Hentikan Siaran", callback_data="stop")] if streamer.running
                else [Btn("🧪 Tes Koneksi", callback_data="test")])
    rows.append([Btn("❓ Bantuan", callback_data="help")])
    return Markup(rows)


def kb_main_small() -> Markup:
    return Markup([[Btn("🎬 Pilih Film", callback_data="libr"), Btn("🏠 Menu", callback_data="main")]])


def kb_status() -> Markup:
    return Markup([
        [Btn("🔄 Segarkan", callback_data="st"), Btn("⏹ Stop", callback_data="stop")],
        [Btn("⏭ Lewati", callback_data="skip"), Btn("🏠 Menu", callback_data="main")],
    ])


def kb_cancel() -> Markup:
    return Markup([[Btn("❌ Batal", callback_data="cancel")]])


def lib_screen(query: str | None, page: int):
    items = lib.search(query)
    pages = max(1, math.ceil(len(items) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    if not items:
        text = (
            "🎬 <b>Daftar Film</b>\n\n"
            + (f"Tidak ada hasil untuk <i>{h(query)}</i>." if query else
               f"Belum ada video di <code>{h(store.movie_dir)}</code>.\n"
               "Simpan film (mp4/mkv/…) di folder <b>Download</b> HP, lalu tekan 🔄 Scan Ulang.")
        )
    else:
        text = f"🎬 <b>Daftar Film</b>" + (f" — cari: <i>{h(query)}</i>" if query else "")
        text += f"\nHalaman {page + 1}/{pages} · {len(items)} file\n\nPilih judul:"
    rows = [[Btn(f"🎞 {trunc(m.title, 32)} · {fmt_size(m.size)}", callback_data=f"mv:{m.id}")] for m in chunk]
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"lib:{page - 1}"))
    nav.append(Btn(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"lib:{page + 1}"))
    rows.append(nav)
    tools = [Btn("🔎 Cari", callback_data="search"), Btn("🔄 Scan Ulang", callback_data="rescan")]
    if query:
        tools.insert(1, Btn("✖️ Hapus Filter", callback_data="libr"))
    rows.append(tools)
    rows.append([Btn("🏠 Menu", callback_data="main")])
    return text, Markup(rows), page


def status_text() -> str:
    s = streamer
    if not s.running:
        return "⚪ <b>Tidak ada siaran aktif.</b>\n\nPilih film dari 🎬 Pilih Film untuk mulai."
    dur = s.info.duration if s.info else 0
    title = s.movie.title if s.movie else "Tes koneksi"
    lines = ["🔴 <b>LIVE</b>", f"🎞 <b>{h(title)}</b>"]
    if dur:
        lines.append(f"{progress_bar(s.position / dur)}  {fmt_time(s.position)} / {fmt_time(dur)}")
    lines += [
        f"⚙️ {s.mode}",
        f"🚀 Kecepatan: {s.speed or '…'}   ⏱ On air: {fmt_time(time.time() - s.started_at)}",
        f"📋 Antrian: {len(queue)}",
    ]
    if 0 < s.speed_value < 0.95:
        lines.append("\n⚠️ Kecepatan di bawah 1x → video bisa patah-patah. Turunkan kualitas di ⚙️ Pengaturan.")
    return "\n".join(lines)


async def do_play(update: Update, movie: Movie, start_at: float = 0.0) -> str | None:
    """Mulai siaran. Return pesan error atau None bila sukses."""
    global notify_chat
    notify_chat = update.effective_chat.id
    try:
        await streamer.start(movie, start_at)
    except StreamError as exc:
        return str(exc)
    return None


# ───────────────────────────── perintah ─────────────────────────────
@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("await", None)
    if not lib.scanned_at:
        await asyncio.to_thread(lib.scan)
    await show(update, main_text(), kb_main())


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"ID Telegram kamu: <code>{update.effective_user.id}</code>", parse_mode=HTML)


@admin_only
async def cmd_film(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not lib.scanned_at:
        await asyncio.to_thread(lib.scan)
    query = " ".join(context.args).strip() or None
    context.user_data["query"], context.user_data["page"] = query, 0
    text, kb, _ = lib_screen(query, 0)
    await show(update, text, kb)


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show(update, status_text(), kb_status() if streamer.running else kb_main_small())


@admin_only
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stopped = await streamer.stop()
    if not stopped:
        await show(update, "⚪ Tidak ada siaran yang berjalan.", kb_main_small())


@admin_only
async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show(update, *queue_screen())


@admin_only
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show(update, *settings_screen())


@admin_only
async def cmd_rtmp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rtmp <url> [key]  — pesan dihapus otomatis demi keamanan key."""
    text = " ".join(context.args)
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
    parsed = store.parse_rtmp(text)
    if not parsed:
        await context.bot.send_message(update.effective_chat.id,
                                       "Format: <code>/rtmp rtmps://dc5-1.rtmp.t.me/s/ KEY</code>", parse_mode=HTML)
        return
    url, key = parsed
    store.set(rtmp_url=url, **({"stream_key": key} if key else {}))
    if key:
        await context.bot.send_message(update.effective_chat.id, "✅ RTMP & key tersimpan (pesanmu sudah dihapus).",
                                       reply_markup=kb_main_small())
    else:
        context.user_data["await"] = "rtmp_key"
        await context.bot.send_message(update.effective_chat.id, "✅ URL tersimpan. Sekarang kirim <b>Stream Key</b>:",
                                       parse_mode=HTML, reply_markup=kb_cancel())


@admin_only
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_test(update)


@admin_only
async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ffmpeg = shutil.which("ffmpeg")
    ver = ""
    if ffmpeg:
        proc = await asyncio.create_subprocess_exec(ffmpeg, "-version", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        ver = out.decode().splitlines()[0] if out else ""
    folder = store.movie_dir
    rows = [
        ("Python", platform.python_version(), True),
        ("ffmpeg", ver[:48] if ffmpeg else "TIDAK ADA → pkg install ffmpeg", bool(ffmpeg)),
        ("ffprobe", "ada" if shutil.which("ffprobe") else "TIDAK ADA", bool(shutil.which("ffprobe"))),
        ("Folder film", f"{folder} ({'ada' if folder.is_dir() else 'tidak ada → jalankan termux-setup-storage'})", folder.is_dir()),
        ("RTMP & key", "sudah diatur" if store.configured else "belum diatur", store.configured),
        ("Admin", f"{len(config.ADMIN_IDS)} orang", bool(config.ADMIN_IDS)),
    ]
    text = "🩺 <b>Cek Sistem</b>\n\n" + "\n".join(f"{'✅' if ok else '❌'} <b>{k}</b>: {h(v)}" for k, v, ok in rows)
    await show(update, text, kb_main_small())


HELP_TEXT = (
    "❓ <b>Bantuan</b>\n\n"
    "<b>Alur cepat</b>\n"
    "1. ⚙️ Pengaturan → <b>Atur RTMP &amp; Key</b> (dari Telegram: grup/channel → Live Stream → Start Live Stream With…)\n"
    "2. 🧪 Tes Koneksi untuk memastikan key benar\n"
    "3. 🎬 Pilih Film → pilih judul → ▶️ Putar\n\n"
    "<b>Perintah</b>\n"
    "/start — menu utama\n"
    "/film [kata] — daftar / cari film\n"
    "/status — status siaran\n"
    "/stop — hentikan siaran\n"
    "/antrian — antrian putar\n"
    "/setelan — pengaturan\n"
    "/rtmp &lt;url&gt; [key] — atur RTMP cepat\n"
    "/tes — siaran uji 20 detik\n"
    "/cek — cek ffmpeg &amp; folder\n"
    "/id — lihat ID Telegram kamu\n\n"
    "<b>Tips</b>: format MP4 (H.264 + AAC) disiarkan mode <i>Copy</i> — paling hemat baterai. "
    "Format lain otomatis di-transcode."
)


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show(update, HELP_TEXT, kb_main_small())


# ───────────────────────────── layar-layar ─────────────────────────────
def queue_screen():
    if not queue:
        text = "📋 <b>Antrian kosong.</b>\nTambah dari detail film dengan tombol ➕ Antrian."
    else:
        text = "📋 <b>Antrian putar</b>\n\n" + "\n".join(f"{i}. {h(m.title)}" for i, m in enumerate(queue, 1))
    rows = []
    if queue:
        rows.append([Btn("🗑 Kosongkan", callback_data="qclr")])
    rows.append([Btn("🎬 Pilih Film", callback_data="libr"), Btn("🏠 Menu", callback_data="main")])
    return text, Markup(rows)


def settings_screen():
    q = store.get("quality")
    a = int(store.get("audio_track") or 1)
    text = (
        "⚙️ <b>Pengaturan</b>\n\n"
        f"🔗 Server : <code>{h(store.get('rtmp_url') or '(kosong)')}</code>\n"
        f"🔑 Key    : <code>{h(store.masked_key())}</code>\n"
        f"📁 Folder : <code>{h(store.movie_dir)}</code>\n\n"
        "<b>Kualitas</b>: <i>Auto</i> = copy bila format cocok, selain itu transcode 480p.\n"
        "<b>Audio track</b>: pilih bila film punya beberapa bahasa.\n"
        "<i>Perubahan berlaku mulai film berikutnya.</i>"
    )
    mark = lambda cond, label: f"✅ {label}" if cond else label
    rows = [
        [Btn(mark(q == c, c.capitalize() if c == "auto" else c), callback_data=f"sq:{c}") for c in config.QUALITY_CHOICES],
        [Btn(mark(a == n, f"🔊 {n}"), callback_data=f"sa:{n}") for n in (1, 2, 3, 4)],
        [Btn("🔗 Atur RTMP & Key", callback_data="setup"), Btn("📁 Folder Film", callback_data="folder")],
        [Btn("🩺 Cek Sistem", callback_data="check"), Btn("🏠 Menu", callback_data="main")],
    ]
    return text, Markup(rows)


async def movie_detail(movie: Movie):
    info = await probe(movie.path)
    lines = [f"🎞 <b>{h(movie.title)}</b>", f"<code>{h(movie.path.name)}</code>", ""]
    meta = [f"💾 {fmt_size(movie.size)}"]
    if info.duration:
        meta.append(f"⏱ {fmt_time(info.duration)}")
    if info.height:
        meta.append(f"📐 {info.width}x{info.height}")
    if info.vcodec:
        meta.append(f"🎥 {info.vcodec}")
    lines.append("  ·  ".join(meta))
    if info.audio:
        lines.append("🔊 " + ", ".join(f"{i}) {c}{' ' + l if l else ''}" for i, (c, l) in enumerate(info.audio, 1)))
    if info.vcodec:
        lines.append(f"⚙️ {streamer.describe_mode(info)}")
    else:
        lines.append("⚠️ File tidak terbaca sebagai video.")
    kb = Markup([
        [Btn("▶️ Putar Sekarang", callback_data=f"play:{movie.id}")],
        [Btn("➕ Antrian", callback_data=f"qa:{movie.id}"), Btn("⏩ Mulai dari…", callback_data=f"seek:{movie.id}")],
        [Btn("⬅️ Kembali", callback_data="lib:back")],
    ])
    return "\n".join(lines), kb


async def run_test(update: Update):
    global notify_chat
    notify_chat = update.effective_chat.id
    try:
        await streamer.start(None, test=True)
    except StreamError as exc:
        await show(update, f"⚠️ {h(exc)}", kb_main_small())
        return
    await show(update, "🧪 <b>Tes dimulai</b> — pola warna + nada selama 20 detik.\n"
                       "Cek di Telegram apakah gambar muncul di live stream.", kb_status())


# ───────────────────────────── tombol ─────────────────────────────
@admin_only
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global skipping
    q = update.callback_query
    parts = (q.data or "").split(":")
    act, arg = parts[0], parts[1] if len(parts) > 1 else ""
    ud = context.user_data

    if act == "noop":
        return await q.answer()

    if act in ("main", "cancel"):
        ud.pop("await", None)
        await q.answer()
        return await show(update, main_text(), kb_main())

    if act in ("libr", "lib", "rescan"):
        if act == "rescan":
            count = await asyncio.to_thread(lib.scan)
            await q.answer(f"✅ {count} film ditemukan")
        else:
            await q.answer()
            if not lib.scanned_at:
                await asyncio.to_thread(lib.scan)
        if act == "libr":
            ud["query"], ud["page"] = None, 0
        elif act == "lib":
            ud["page"] = ud.get("page", 0) if arg == "back" else int(arg)
        text, kb, ud["page"] = lib_screen(ud.get("query"), ud.get("page", 0))
        return await show(update, text, kb)

    if act == "search":
        ud["await"] = "search"
        await q.answer()
        return await show(update, "🔎 Ketik <b>kata kunci judul</b> film:", kb_cancel())

    if act == "mv":
        movie = lib.get(arg)
        if not movie:
            return await q.answer("Daftar berubah, buka ulang menu film.", show_alert=True)
        await q.answer()
        text, kb = await movie_detail(movie)
        return await show(update, text, kb)

    if act == "play":
        movie = lib.get(arg)
        if not movie:
            return await q.answer("Film tidak ditemukan, coba Scan Ulang.", show_alert=True)
        if streamer.running:
            return await q.answer("Sedang LIVE. Hentikan dulu atau tambahkan ke ➕ Antrian.", show_alert=True)
        await q.answer("⏳ Menyiapkan siaran…")
        err = await do_play(update, movie)
        if err:
            return await show(update, f"⚠️ {h(err)}", kb_main_small())
        await asyncio.sleep(2.5)
        return await show(update, status_text(), kb_status() if streamer.running else kb_main_small())

    if act == "seek":
        movie = lib.get(arg)
        if not movie:
            return await q.answer("Film tidak ditemukan.", show_alert=True)
        ud["await"] = f"seek:{movie.id}"
        await q.answer()
        return await show(update, f"⏩ <b>{h(movie.title)}</b>\n\nKirim waktu mulai, contoh <code>25:30</code> atau <code>1:05:00</code>:", kb_cancel())

    if act == "qa":
        movie = lib.get(arg)
        if not movie:
            return await q.answer("Film tidak ditemukan.", show_alert=True)
        queue.append(movie)
        return await q.answer(f"➕ Masuk antrian (#{len(queue)})")

    if act in ("queue", "qclr"):
        if act == "qclr":
            queue.clear()
        await q.answer("🗑 Antrian dikosongkan" if act == "qclr" else None)
        return await show(update, *queue_screen())

    if act == "st":
        await q.answer()
        return await show(update, status_text(), kb_status() if streamer.running else kb_main_small())

    if act in ("stop", "skip"):
        if not streamer.running:
            await q.answer("Tidak ada siaran berjalan.")
            return await show(update, main_text(), kb_main())
        skipping = act == "skip"
        await q.answer("⏹ Menghentikan…" if act == "stop" else "⏭ Melewati…")
        await streamer.stop()
        if act == "stop":
            return await show(update, main_text(), kb_main())
        return

    if act == "test":
        await q.answer("🧪 Memulai tes…")
        return await run_test(update)

    if act == "set":
        await q.answer()
        return await show(update, *settings_screen())

    if act == "sq":
        store.set(quality=arg)
        await q.answer(f"Kualitas: {arg}")
        return await show(update, *settings_screen())

    if act == "sa":
        store.set(audio_track=int(arg))
        await q.answer(f"Audio track: {arg}")
        return await show(update, *settings_screen())

    if act == "setup":
        ud["await"] = "rtmp_url"
        await q.answer()
        return await show(update, (
            "🔗 <b>Atur RTMP</b>\n\n"
            "Di Telegram: buka grup/channel → Video Chat / Live Stream → <b>Start Live Stream With…</b> "
            "→ salin <b>Server URL</b> dan <b>Stream Key</b>.\n\n"
            "Kirim <b>Server URL</b> sekarang, contoh:\n<code>rtmps://dc5-1.rtmp.t.me/s/</code>\n\n"
            "💡 Boleh kirim URL + key sekaligus (dipisah spasi). Pesanmu akan otomatis dihapus."
        ), kb_cancel())

    if act == "folder":
        ud["await"] = "folder"
        await q.answer()
        return await show(update, (
            "📁 <b>Folder Film</b>\n\nKirim path folder, contoh:\n"
            "<code>~/storage/downloads/Film</code>\n"
            "atau ketik <code>download</code> untuk kembali ke folder Download bawaan."
        ), kb_cancel())

    if act == "check":
        await q.answer()
        return await cmd_check(update, context)

    if act == "help":
        await q.answer()
        return await show(update, HELP_TEXT, kb_main_small())

    await q.answer()


# ───────────────────────────── input teks ─────────────────────────────
@admin_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    mode = ud.pop("await", None)
    msg = update.effective_message
    text = (msg.text or "").strip()
    chat = update.effective_chat.id

    if not mode:
        return await msg.reply_text("Ketik /start untuk membuka panel kontrol.")

    if mode == "search":
        ud["query"], ud["page"] = text, 0
        t, kb, _ = lib_screen(text, 0)
        return await msg.reply_text(t, parse_mode=HTML, reply_markup=kb)

    if mode in ("rtmp_url", "rtmp_key"):
        try:
            await msg.delete()  # sembunyikan key dari riwayat chat
        except TelegramError:
            pass
        if mode == "rtmp_key":
            store.set(stream_key=text)
            return await context.bot.send_message(chat, "✅ Stream key tersimpan. Coba 🧪 Tes Koneksi.",
                                                  reply_markup=Markup([[Btn("🧪 Tes Koneksi", callback_data="test"), Btn("⚙️ Pengaturan", callback_data="set")]]))
        parsed = store.parse_rtmp(text)
        if not parsed:
            ud["await"] = "rtmp_url"
            return await context.bot.send_message(chat, "⚠️ URL harus diawali <code>rtmps://</code> atau <code>rtmp://</code>. Kirim ulang:",
                                                  parse_mode=HTML, reply_markup=kb_cancel())
        url, key = parsed
        store.set(rtmp_url=url, **({"stream_key": key} if key else {}))
        if key:
            return await context.bot.send_message(chat, "✅ RTMP & key tersimpan. Coba 🧪 Tes Koneksi.",
                                                  reply_markup=Markup([[Btn("🧪 Tes Koneksi", callback_data="test"), Btn("⚙️ Pengaturan", callback_data="set")]]))
        ud["await"] = "rtmp_key"
        return await context.bot.send_message(chat, "✅ URL tersimpan. Sekarang kirim <b>Stream Key</b>:",
                                              parse_mode=HTML, reply_markup=kb_cancel())

    if mode == "folder":
        path = text.strip()
        if path.lower() in ("download", "downloads", "default", "bawaan"):
            store.set(movie_dir="")
        else:
            real = os.path.expanduser(path)
            if not os.path.isdir(real):
                ud["await"] = "folder"
                return await msg.reply_text("⚠️ Folder tidak ditemukan. Kirim path lain atau tekan Batal.", reply_markup=kb_cancel())
            store.set(movie_dir=path)
        count = await asyncio.to_thread(lib.scan)
        return await msg.reply_text(f"✅ Folder diatur. {count} film ditemukan.", reply_markup=kb_main_small())

    if mode.startswith("seek:"):
        movie = lib.get(mode.split(":", 1)[1])
        start_at = parse_time(text)
        if not movie or start_at is None:
            if movie:
                ud["await"] = mode
            return await msg.reply_text("⚠️ Format waktu salah. Contoh: <code>25:30</code>", parse_mode=HTML, reply_markup=kb_cancel())
        if streamer.running:
            return await msg.reply_text("Sedang LIVE. Hentikan dulu.", reply_markup=kb_main_small())
        err = await do_play(update, movie, start_at)
        if err:
            return await msg.reply_text(f"⚠️ {h(err)}", parse_mode=HTML, reply_markup=kb_main_small())
        await asyncio.sleep(2.5)
        return await msg.reply_text(status_text(), parse_mode=HTML, reply_markup=kb_status())


# ───────────────────────────── start / stop aplikasi ─────────────────────────────
async def post_init(app: Application) -> None:
    global APP
    APP = app
    await app.bot.set_my_commands([
        BotCommand("start", "Menu utama"), BotCommand("film", "Daftar / cari film"),
        BotCommand("status", "Status siaran"), BotCommand("stop", "Hentikan siaran"),
        BotCommand("antrian", "Antrian putar"), BotCommand("setelan", "Pengaturan"),
        BotCommand("rtmp", "Atur RTMP & key"), BotCommand("tes", "Tes koneksi 20 detik"),
        BotCommand("cek", "Cek sistem"), BotCommand("id", "Lihat ID Telegram"), BotCommand("help", "Bantuan"),
    ])
    count = await asyncio.to_thread(lib.scan)
    me = await app.bot.get_me()
    log.info("Bot @%s aktif · %d film di %s", me.username, count, store.movie_dir)
    for admin in config.ADMIN_IDS:
        try:
            await app.bot.send_message(admin, f"✅ <b>Bot aktif</b> · {count} film terdeteksi.\nKetik /start untuk membuka panel.", parse_mode=HTML)
        except TelegramError:
            pass


async def post_shutdown(app: Application) -> None:
    await streamer.stop()


async def on_error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error handler", exc_info=context.error)


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        file_h = RotatingFileHandler(config.DATA_DIR / "bot.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
        file_h.setFormatter(fmt)
        root.addHandler(file_h)
    except OSError:
        pass
    # httpx mencetak URL request yang berisi token bot — bungkam
    for noisy in ("httpx", "httpcore", "telegram.ext"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    if not config.BOT_TOKEN:
        sys.exit("❌ BOT_TOKEN belum diisi. Jalankan ./install.sh atau edit file .env")
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS kosong. Kirim /id ke bot untuk melihat ID kamu, isi di .env, lalu restart.")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    private = filters.ChatType.PRIVATE
    for names, fn in [
        (["start", "menu"], cmd_start), (["film", "cari"], cmd_film), (["status"], cmd_status),
        (["stop"], cmd_stop), (["antrian"], cmd_queue), (["setelan", "settings"], cmd_settings),
        (["rtmp"], cmd_rtmp), (["tes", "test"], cmd_test), (["cek"], cmd_check), (["help", "bantuan"], cmd_help),
    ]:
        app.add_handler(CommandHandler(names, fn, filters=private))
    app.add_handler(CommandHandler("id", cmd_id, filters=private))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
