#!/usr/bin/env bash
set -euo pipefail

exec 3<>/dev/tcp/127.0.0.1/9080
printf 'GET /api/v1/health/live HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
IFS= read -r status_line <&3

case "$status_line" in
  HTTP/*" 200 "*) exit 0 ;;
  *) exit 1 ;;
esac
