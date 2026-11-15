#!/bin/sh
# The Fly volume is mounted owned by root. Hand it to the unprivileged app user, then drop root for good.
set -eu
mkdir -p /var/data
chown 10001:10001 /var/data
# Listen on IPv6 as well when the machine has it (Fly's own health checks arrive over IPv6); IPv4 still works.
if [ -e /proc/net/if_inet6 ]; then HOST="::"; else HOST="0.0.0.0"; fi
# Keep the environment: it carries this customer's configuration and secrets.
exec setpriv --reuid=10001 --regid=10001 --init-groups env HOME=/home/agent \
  python -m uvicorn app:app --host "$HOST" --port "${PORT:-8080}" --workers 1 --no-access-log \
  --limit-concurrency 100 --timeout-keep-alive 5 --timeout-graceful-shutdown 8
