#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
app_support="${FAIRY_APP_SUPPORT:-$HOME/Library/Application Support/Fairy}"
export FAIRY_STATE_DIR="${FAIRY_STATE_DIR:-$app_support/state}"
if [ -z "${FAIRY_DATABASE_URL:-}" ]; then
    printf '%s\n' "Set FAIRY_DATABASE_URL to a PostgreSQL URL." >&2
    exit 2
fi
export FAIRY_TOKEN="${FAIRY_TOKEN:-}"

if [ -z "$FAIRY_TOKEN" ]; then
    printf '%s\n' "Set FAIRY_TOKEN in the environment before starting Fairy." >&2
    exit 2
fi

mkdir -p "$FAIRY_STATE_DIR"
exec "$repo_root/.venv/bin/python" -m uvicorn fairy.asgi:app \
    --host "${FAIRY_HOST:-127.0.0.1}" \
    --port "${FAIRY_PORT:-8010}"
