#!/bin/bash
set -euo pipefail
export PATH="/data/home/.local/bin:$PATH"
export TERM=xterm-256color
cd /data/workspace
# A PTY keeps the interactive CLI alive when the setup browser disconnects.
tmux -f /dev/null new-session -d -s antigravity -x 120 -y 35 /usr/local/bin/session.sh
cleanup() {
    trap - EXIT INT TERM
    tmux kill-server 2>/dev/null || true
    kill "${terminal_pid:-}" "${proxy_pid:-}" "${signin_pid:-}" 2>/dev/null || true
    wait || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM
ttyd -i 127.0.0.1 -p 7681 -W tmux attach-session -t antigravity &
terminal_pid=$!
python3 /usr/local/bin/signin.py &
signin_pid=$!
nginx -c /etc/nginx/antigravity.conf -g 'daemon off;' &
proxy_pid=$!
wait -n "$terminal_pid" "$proxy_pid" "$signin_pid"
exit 1
