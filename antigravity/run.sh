#!/bin/bash
set -euo pipefail
umask 077
mkdir -p /data/home/.local/bin /data/workspace
if [ ! -x /data/home/.local/bin/agy ]; then
    cp /opt/antigravity/agy /data/home/.local/bin/agy
fi
chown -R agent:agent /data
exec runuser -u agent -- /usr/local/bin/services.sh
