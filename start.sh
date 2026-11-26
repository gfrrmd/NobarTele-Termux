#!/data/data/com.termux/files/usr/bin/bash
# Menjalankan bot dengan auto-restart + wake lock (HP tidak tidur)
cd "$(dirname "$0")"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
trap 'echo; echo "Bot dihentikan."; command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock; exit 0' INT TERM
while true; do
  python bot.py
  echo "⚠️ Bot berhenti (kode $?). Restart dalam 5 detik… (Ctrl+C untuk berhenti)"
  sleep 5
done
