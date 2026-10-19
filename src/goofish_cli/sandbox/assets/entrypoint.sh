#!/bin/bash
set -euo pipefail
umask 077
mkdir -p "$HOME/.goofish-cli"
chmod 700 "$HOME/.goofish-cli"
# 显示器仅属于此容器；异常停止后不得让旧锁阻止重启。
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
children=()
cleanup() {
    if ((${#children[@]})); then
        kill -TERM "${children[@]}" 2>/dev/null || true
        wait "${children[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 0' TERM INT
Xvfb :1 -screen 0 1440x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
children+=("$!")
for attempt in $(seq 1 100); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then break; fi
    sleep 0.1
done
xdpyinfo -display :1 >/dev/null
fluxbox >/tmp/fluxbox.log 2>&1 &
children+=("$!")
x11vnc -display :1 -forever -shared -nopw -localhost -rfbport 5900 >/tmp/vnc.log 2>&1 &
children+=("$!")
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
children+=("$!")
wait -n "${children[@]}"
