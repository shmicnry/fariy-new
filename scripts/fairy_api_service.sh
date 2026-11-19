#!/bin/sh
set -eu

command_name="${1:-status}"
label="io.fairy.api"
domain="gui/$(id -u)"
repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
app_support="${FAIRY_APP_SUPPORT:-$HOME/Library/Application Support/Fairy}"
runtime="${FAIRY_API_RUNTIME:-$app_support/worker-runtime}"
state_dir="${FAIRY_STATE_DIR:-$app_support/state}"
database_url="${FAIRY_DATABASE_URL:-postgresql+psycopg://$USER@127.0.0.1:5432/fairy}"
port="${FAIRY_PORT:-8010}"
token_file="${FAIRY_API_TOKEN_FILE:-$app_support/api-token}"
wrapper="${FAIRY_API_WRAPPER:-$app_support/run-api.sh}"
plist="${FAIRY_API_PLIST:-$HOME/Library/LaunchAgents/$label.plist}"
log_dir="${FAIRY_LOG_DIR:-$HOME/Library/Logs/Fairy}"
dry_run="${FAIRY_LAUNCHD_DRY_RUN:-0}"
python_path="$runtime/.venv/bin/python"

if [ ! -x "$python_path" ]; then
    printf '%s\n' "Install the Fairy worker runtime first: scripts/fairy_worker_service.sh install" >&2
    exit 1
fi

ensure_token() {
    mkdir -p "$(dirname "$token_file")"
    if [ -n "${FAIRY_TOKEN:-}" ]; then
        umask 077
        printf '%s\n' "$FAIRY_TOKEN" >"$token_file"
    elif [ ! -f "$token_file" ]; then
        umask 077
        "$python_path" -c 'import secrets; print(secrets.token_urlsafe(32))' >"$token_file"
    fi
    chmod 600 "$token_file"
}

write_wrapper() {
    mkdir -p "$state_dir" "$log_dir"
    cat >"$wrapper" <<EOF
#!/bin/sh
set -eu
export FAIRY_TOKEN="\$(cat '$token_file')"
export FAIRY_STATE_DIR='$state_dir'
export FAIRY_DATABASE_URL='$database_url'
export FAIRY_MAC_BRIDGE_EXECUTABLE='$runtime/apps/mac-bridge/FairyMacBridge/.build/release/FairyMacBridge'
export FAIRY_WHISPER_CLI='${FAIRY_WHISPER_CLI:-}'
export FAIRY_WHISPER_MODEL='${FAIRY_WHISPER_MODEL:-}'
exec '$python_path' -m uvicorn fairy.asgi:app --host 127.0.0.1 --port '$port'
EOF
    chmod 700 "$wrapper"
}

write_plist() {
    mkdir -p "$(dirname "$plist")"
    python3 - "$plist" "$label" "$runtime" "$wrapper" "$log_dir" <<'PY'
import os
import plistlib
import sys

target, label, runtime, wrapper, logs = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [wrapper],
    "WorkingDirectory": runtime,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Interactive",
    "StandardOutPath": os.path.join(logs, "api.log"),
    "StandardErrorPath": os.path.join(logs, "api-error.log"),
    "ThrottleInterval": 5,
}
with open(target, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY
    chmod 600 "$plist"
    if command -v plutil >/dev/null 2>&1; then
        plutil -lint "$plist" >/dev/null
    fi
}

case "$command_name" in
    install)
        ensure_token
        write_wrapper
        write_plist
        if [ "$dry_run" = "1" ]; then
            printf '%s\n' "Dry run: generated $plist; token file: $token_file"
        else
            launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
            sleep 1
            launchctl bootstrap "$domain" "$plist"
            launchctl enable "$domain/$label"
            launchctl kickstart -k "$domain/$label"
            printf '%s\n' "Installed and started $label on 127.0.0.1:$port"
            printf '%s\n' "Owner token file: $token_file"
        fi
        ;;
    restart)
        launchctl kickstart -k "$domain/$label"
        printf '%s\n' "Restarted $label"
        ;;
    uninstall)
        launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
        rm -f "$plist" "$wrapper"
        printf '%s\n' "Stopped $label; the token and data files were retained"
        ;;
    status)
        launchctl print "$domain/$label" 2>/dev/null || true
        token="$(cat "$token_file")"
        curl -fsS -H "Authorization: Bearer $token" "http://127.0.0.1:$port/v2/capabilities" \
            | "$python_path" -m json.tool
        ;;
    logs)
        tail -n 80 "$log_dir/api.log" "$log_dir/api-error.log" 2>/dev/null || true
        ;;
    *)
        printf '%s\n' "Usage: $0 install|restart|uninstall|status|logs" >&2
        exit 2
        ;;
esac
