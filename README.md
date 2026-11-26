# 🎬 Watch Party Stream Bot

Siarkan film dari HP Android (Termux) ke **Live Stream grup/channel Telegram** lewat RTMP.
Film disimpan di folder **Download** HP, dan judulnya dipilih lewat bot Telegram.

```
Folder Download HP ──► Bot (Termux + ffmpeg) ──RTMP──► Live Stream Telegram ──► Penonton
        ▲                        ▲
        └──── kamu pilih judul & kontrol lewat chat pribadi dengan bot
```

## ✨ Fitur

| Fitur | Keterangan |
|---|---|
| 📂 Pilih film dari bot | Otomatis memindai folder Download (termasuk subfolder), ada halaman & pencarian |
| ⚡ Mode Copy otomatis | MP4 H.264 + AAC disiarkan tanpa re-encode → hemat baterai & CPU |
| 🔄 Transcode otomatis | Format lain (HEVC, MKV, MP3, dll.) otomatis dikonversi ke 480p |
| 🎚 Pilih kualitas | Auto / 360p / 480p / 720p |
| 🔊 Pilih audio track | Untuk film multi-bahasa (track 1–4) |
| ⏩ Mulai dari menit tertentu | Lanjutkan film dari `25:30`, dst. |
| 📋 Antrian putar | Film berikutnya jalan otomatis |
| 📊 Status live | Progress bar, durasi, kecepatan encode, peringatan bila lag |
| 🧪 Tes koneksi | Siaran uji 20 detik untuk memastikan URL & key benar |
| 🔐 Aman | Hanya admin; pesan berisi key dihapus otomatis; key disamarkan di log & pesan error |
| 🩺 Cek sistem | `/cek` memeriksa ffmpeg, folder, RTMP |
| 🔁 Auto-restart | Bot hidup terus di latar belakang (tmux + wake-lock) |

---

## 🚀 Panduan Deploy di Termux

### 0. Persiapan
- Pasang **Termux dari F-Droid** atau GitHub (versi Play Store sudah usang dan sering gagal install paket).
- Pastikan HP terhubung internet stabil (Wi-Fi disarankan).
- Matikan penghemat baterai untuk Termux: *Pengaturan → Aplikasi → Termux → Baterai → Tanpa batasan*.

### 1. Buat bot & ambil token
1. Buka **@BotFather** → `/newbot` → ikuti langkahnya → salin **token**.
2. (Opsional) Ambil ID Telegram kamu lewat **@userinfobot**. Bila belum tahu, kosongkan dulu; nanti bisa dicek dengan `/id` di bot.

### 2. Pindahkan ZIP ke Termux
Simpan `telegram-stream-bot.zip` ke folder **Download** HP, lalu di Termux:

```bash
termux-setup-storage          # tekan "Izinkan" pada popup
pkg install -y unzip
unzip ~/storage/downloads/telegram-stream-bot.zip -d ~
cd ~/telegram-stream-bot
```

### 3. Jalankan installer
```bash
bash install.sh
```
Installer akan memasang `python`, `ffmpeg`, `tmux`, library bot, lalu menanyakan **token** dan **ID admin**.

> Bila ID admin dikosongkan: jalankan bot, kirim `/id` ke bot, isi hasilnya di file `.env`
> (`nano .env` → `ADMIN_IDS=123456789`), lalu `./ctl.sh restart`.

### 4. Jalankan bot
```bash
./ctl.sh start
```
Bot berjalan di latar belakang (tmux) dan HP tidak masuk mode tidur. Perintah lain:

| Perintah | Fungsi |
|---|---|
| `./ctl.sh status` | Cek bot hidup/mati |
| `./ctl.sh logs` | Lihat log langsung (Ctrl+C untuk keluar) |
| `./ctl.sh restart` | Restart bot |
| `./ctl.sh stop` | Hentikan bot |
| `./ctl.sh attach` | Masuk ke sesi bot (keluar: `Ctrl+B` lalu `D`) |

### 5. Ambil RTMP URL & Stream Key dari Telegram
1. Buka **grup atau channel** tempat nonton bareng (kamu harus admin; aplikasi Telegram harus versi terbaru).
2. Grup: ketuk nama grup → **Video Chat / Live Stream**. Channel: ketuk ⋮ → **Start Live Stream**.
3. Pilih **Start Live Stream With…** (atau *Stream with…*). Telegram menampilkan:
   - **Server URL** → contoh `rtmps://dc5-1.rtmp.t.me/s/`
   - **Stream Key** → contoh `1234567890:AbCdEf…`
4. Biarkan layar itu terbuka (atau tekan **Start Streaming**) sambil melanjutkan langkah berikut.

### 6. Pakai bot
Buka chat **pribadi** dengan bot → `/start`:

1. **⚙️ Pengaturan → 🔗 Atur RTMP & Key** → kirim URL, lalu key (pesanmu otomatis dihapus bot).
   Cara cepat: `/rtmp rtmps://dc5-1.rtmp.t.me/s/ KEY`
2. **🧪 Tes Koneksi** → pola warna muncul di live stream = berhasil.
3. **🎬 Pilih Film** → pilih judul → **▶️ Putar Sekarang**.
4. Atur lewat **📊 Status** (segarkan, stop, lewati) dan **📋 Antrian**.

### 7. Simpan film
Taruh file film di folder **Download** HP (subfolder boleh, misal `Download/Film/`).
Setelah menambah file baru, tekan **🔄 Scan Ulang** di daftar film.
Mau pakai folder lain? **⚙️ Pengaturan → 📁 Folder Film**.

---

## 💡 Tips performa

- **Format terbaik:** MP4 dengan video **H.264** dan audio **AAC** → mode ⚡ Copy, hampir tanpa beban CPU.
- Film **MKV/HEVC/10-bit** akan di-transcode. Bila status menunjukkan kecepatan di bawah `1x` (lag), turunkan ke **360p**, atau ubah `X264_PRESET=ultrafast` di `.env`.
- Hindari 720p di HP kelas menengah ke bawah saat transcode.
- Colok charger & jaga HP tidak terlalu panas saat siaran panjang.
- Upload internet minimal ±2 Mbps untuk 480p, ±4 Mbps untuk 720p.

## 🛠 Pemecahan masalah

| Gejala | Solusi |
|---|---|
| `Akses ditolak` | ID kamu belum ada di `ADMIN_IDS` (cek dengan `/id`, edit `.env`, `./ctl.sh restart`) |
| Film tidak muncul | Jalankan `termux-setup-storage`, pastikan film ada di Download, tekan 🔄 Scan Ulang, atau cek `/cek` |
| Error `Protocol not found` / rtmps gagal | `pkg upgrade ffmpeg`, atau ganti URL menjadi `rtmp://…` |
| Koneksi gagal / `Input/output error` | Pastikan layar Live Stream di Telegram aktif, key belum di-*revoke*, internet stabil. Ambil key baru bila perlu |
| Video patah-patah | Turunkan kualitas, gunakan preset `ultrafast`, atau konversi film ke MP4 H.264+AAC |
| Suara bahasa salah | Ganti **Audio track** di ⚙️ Pengaturan (detail film menampilkan daftar track) |
| `pkg` gagal / mirror error | Jalankan `termux-change-repo`, pilih mirror lain, ulangi installer |
| Bot mati sendiri | Matikan optimasi baterai untuk Termux, jalankan lewat `./ctl.sh start` |

## 📁 Struktur proyek

```
bot.py          antarmuka Telegram (menu, tombol, perintah)
streamer.py     pengatur proses ffmpeg (copy/transcode, status, stop)
library.py      pemindai folder film
config.py       baca .env & simpan pengaturan (data/settings.json)
utils.py        fungsi bantu
install.sh      installer Termux     start.sh / ctl.sh   menjalankan & mengontrol bot
.env.example    contoh konfigurasi
```

## 🔒 Keamanan

- Jangan bagikan file `.env` dan `data/settings.json` (berisi token & key).
- Bila key bocor: di Telegram, buat ulang (*revoke*) key, lalu atur ulang di bot.
- Gunakan bot ini hanya untuk konten yang kamu berhak menayangkannya.

## 🧾 Daftar perintah

`/start` menu · `/film [kata]` cari film · `/status` · `/stop` · `/antrian` · `/setelan` · `/rtmp <url> [key]` · `/tes` · `/cek` · `/id` · `/help`
