#!/data/data/com.termux/files/usr/bin/bash
# Installer Watch Party Stream Bot untuk Termux
set -e
cd "$(dirname "$0")"

echo "════════════════════════════════════"
echo "  🎬 Watch Party Stream Bot — Setup"
echo "════════════════════════════════════"

echo "▶ [1/4] Memasang paket Termux (python, ffmpeg, tmux)…"
pkg update -y
pkg install -y python ffmpeg tmux

echo "▶ [2/4] Izin penyimpanan…"
if [ ! -d "$HOME/storage/downloads" ]; then
  termux-setup-storage || true
  echo "   Tekan IZINKAN pada popup. Menunggu…"
  for i in $(seq 1 30); do
    [ -d "$HOME/storage/downloads" ] && break
    sleep 1
  done
fi
if [ -d "$HOME/storage/downloads" ]; then
  echo "   ✅ Folder Download terhubung: ~/storage/downloads"
else
  echo "   ⚠️ Folder Download belum terhubung. Jalankan 'termux-setup-storage' lalu ulangi installer."
fi

echo "▶ [3/4] Memasang library Python…"
pip install -r requirements.txt

echo "▶ [4/4] Konfigurasi bot…"
if [ -f .env ] && grep -q '^BOT_TOKEN=.\+' .env; then
  echo "   .env sudah ada, dilewati. (hapus file .env bila ingin mengulang)"
else
  cp .env.example .env
  echo
  read -r -p "   Token bot dari @BotFather : " TOKEN
  read -r -p "   ID Telegram admin (kosongkan bila belum tahu): " ADMIN
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${TOKEN}|" .env
  sed -i "s|^ADMIN_IDS=.*|ADMIN_IDS=${ADMIN}|" .env
  chmod 600 .env
fi

chmod +x start.sh ctl.sh
echo
echo "✅ Selesai! Jalankan bot dengan:  ./ctl.sh start"
echo "   Lalu buka bot kamu di Telegram dan kirim /start"
