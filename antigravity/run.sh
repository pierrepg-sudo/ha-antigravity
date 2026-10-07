#!/bin/bash
set -euo pipefail
umask 077
python3 /usr/local/bin/prepare_storage.py
# The CLI owns only its home and outputs; never recursively chown /data.
runuser -u agent -- mkdir -p /data/home/.local/bin
if [ ! -x /data/home/.local/bin/agy ]; then
    runuser -u agent -- cp /opt/antigravity/agy /data/home/.local/bin/agy
fi
cleanup() {
    trap - EXIT INT TERM
    kill "${files_pid:-}" "${services_pid:-}" "${proxy_pid:-}" 2>/dev/null || true
    wait || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM
runuser -u files -- setpriv --no-new-privs python3 /usr/local/bin/file_server.py &
files_pid=$!
runuser -u agent -- setpriv --no-new-privs /usr/local/bin/services.sh &
services_pid=$!
runuser -u files -- setpriv --no-new-privs nginx -c /etc/nginx/antigravity.conf -g 'daemon off;' &
proxy_pid=$!
wait -n "$files_pid" "$services_pid" "$proxy_pid"
exit 1
