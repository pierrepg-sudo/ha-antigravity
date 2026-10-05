#!/bin/bash
set -euo pipefail
# Upstream ttyd 1.7.7 release hashes, verified against its SHA256SUMS.
case "$(dpkg --print-architecture)" in
  arm64)
    asset=ttyd.aarch64
    checksum=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
    ;;
  amd64)
    asset=ttyd.x86_64
    checksum=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
    ;;
  *) echo "Unsupported ttyd architecture" >&2; exit 1 ;;
esac
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
curl --fail --location --retry 3 --connect-timeout 30 --max-time 300   "https://github.com/tsl0922/ttyd/releases/download/1.7.7/$asset" -o "$stage/ttyd"
printf '%s  %s\n' "$checksum" "$stage/ttyd" | sha256sum --check --strict
install -m 0755 "$stage/ttyd" /usr/local/bin/ttyd
/usr/local/bin/ttyd --version
