#!/bin/sh
# The Fly volume is mounted owned by root. Hand it to the unprivileged app user, then drop root for good.
set -eu
mkdir -p /var/data
chown 10001:10001 /var/data
# Keep the environment: it carries this customer's configuration and secrets.
exec setpriv --reuid=10001 --regid=10001 --init-groups env HOME=/home/agent python /app/serve.py
