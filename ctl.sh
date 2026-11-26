#!/data/data/com.termux/files/usr/bin/bash
# Kontrol bot: ./ctl.sh start|stop|restart|status|logs|attach
cd "$(dirname "$0")"
S=tgstream
case "$1" in
  start)
    if tmux has-session -t $S 2>/dev/null; then echo "Bot sudah berjalan."; exit 0; fi
    tmux new-session -d -s $S "bash start.sh"
    echo "✅ Bot berjalan di latar belakang. Lihat log: ./ctl.sh logs" ;;
  stop)
    tmux kill-session -t $S 2>/dev/null && echo "⏹ Bot dihentikan." || echo "Bot tidak berjalan."
    pkill -f "ffmpeg.*rtmp" 2>/dev/null
    command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock ;;
  restart) "$0" stop; sleep 1; "$0" start ;;
  status)
    tmux has-session -t $S 2>/dev/null && echo "🟢 Bot berjalan" || echo "🔴 Bot mati" ;;
  logs) tail -n 60 -f data/bot.log ;;
  attach) tmux attach -t $S ;;
  *) echo "Pemakaian: ./ctl.sh {start|stop|restart|status|logs|attach}" ;;
esac
