#!/bin/sh
# Run the app as an unprivileged user, but let the container fix ownership of
# the data volume first. This keeps sandboxed work away from root.
set -e

if [ "$(id -u)" = "0" ]; then
  STORE="${REVERSEAI_STORE:-/data/jobs}"
  mkdir -p "$STORE"
  chown -R 10001:10001 /data "$STORE" 2>/dev/null || true
  exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi

exec "$@"
