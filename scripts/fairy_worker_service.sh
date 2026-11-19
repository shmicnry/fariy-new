#!/bin/sh
set -eu

command_name="${1:-status}"
repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
label="io.fairy.worker"
domain="gui/$(id -u)"
plist="${FAIRY_LAUNCHD_PLIST:-$HOME/Library/LaunchAgents/$label.plist}"
app_support="${FAIRY_APP_SUPPORT:-$HOME/Library/Application Support/Fairy}"
runtime="${FAIRY_WORKER_RUNTIME:-$app_support/worker-runtime}"
state_dir="${FAIRY_STATE_DIR:-$app_support/state}"
database_url="${FAIRY_DATABASE_URL:-postgresql+psycopg://$USER@127.0.0.1:5432/fairy}"
interval="${FAIRY_WORKER_INTERVAL:-2}"
log_dir="${FAIRY_LOG_DIR:-$HOME/Library/Logs/Fairy}"
dry_run="${FAIRY_LAUNCHD_DRY_RUN:-0}"
source_python="${FAIRY_PYTHON:-$repo_root/.venv/bin/python}"
installed_python="$runtime/.venv/bin/python"

if [ ! -x "$source_python" ]; then
    printf '%s\n' "Python environment not found: $source_python" >&2
    exit 1
fi

sync_runtime() {
    mkdir -p "$runtime" "$state_dir"
    helper_binary="$repo_root/apps/mac-bridge/FairyMacBridge/.build/release/FairyMacBridge"
    helper_source="$repo_root/apps/mac-bridge/FairyMacBridge/Sources/FairyMacBridge/main.swift"
    if command -v swift >/dev/null 2>&1 \
        && { [ ! -x "$helper_binary" ] || [ "$helper_source" -nt "$helper_binary" ]; }; then
        (cd "$repo_root/apps/mac-bridge/FairyMacBridge" && swift build -c release)
    fi
    ditto "$repo_root/.venv" "$runtime/.venv"
    ditto "$repo_root/server" "$runtime/server"
    ditto "$repo_root/apps/web" "$runtime/apps/web"
    ditto "$repo_root/pyproject.toml" "$runtime/pyproject.toml"
    if [ -x "$repo_root/apps/mac-bridge/FairyMacBridge/.build/release/FairyMacBridge" ]; then
        mkdir -p "$runtime/apps/mac-bridge/FairyMacBridge/.build/release"
        ditto "$repo_root/apps/mac-bridge/FairyMacBridge/.build/release/FairyMacBridge" \
            "$runtime/apps/mac-bridge/FairyMacBridge/.build/release/FairyMacBridge"
    fi
    for editable in "$runtime"/.venv/lib/python*/site-packages/__editable__.*.pth; do
        [ -f "$editable" ] && printf '%s\n' "$runtime/server" >"$editable"
    done
    if [ ! -d "$state_dir/credentials" ] && [ -d "$repo_root/var/credentials" ]; then
        ditto "$repo_root/var/credentials" "$state_dir/credentials"
    fi
}

install_plist() {
    mkdir -p "$(dirname "$plist")" "$state_dir" "$log_dir"
    python3 - "$plist" "$label" "$runtime" "$installed_python" "$database_url" "$state_dir" "$interval" "$log_dir" <<'PY'
import os
import plistlib
import sys

target, label, repo, python, database, state, interval, logs = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [
        python,
        "-m",
        "fairy.worker",
        "--interval",
        str(interval),
    ],
    "WorkingDirectory": repo,
    "EnvironmentVariables": {
        "FAIRY_DATABASE_URL": database,
        "FAIRY_STATE_DIR": state,
    },
    "RunAtLoad": True,
    "KeepAlive": {
        "SuccessfulExit": False,
    },
    "ProcessType": "Background",
    "StandardOutPath": os.path.join(logs, "worker.log"),
    "StandardErrorPath": os.path.join(logs, "worker-error.log"),
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

bootstrap() {
    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
    sleep 1
    launchctl bootstrap "$domain" "$plist"
    launchctl enable "$domain/$label"
    launchctl kickstart -k "$domain/$label"
}

case "$command_name" in
    install)
        if [ "$dry_run" != "1" ]; then
            launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
            sync_runtime
        fi
        install_plist
        if [ "$dry_run" = "1" ]; then
            printf '%s\n' "Dry run: generated $plist"
        else
            bootstrap
            printf '%s\n' "Installed and started $label"
        fi
        ;;
    restart)
        launchctl kickstart -k "$domain/$label"
        printf '%s\n' "Restarted $label"
        ;;
    uninstall)
        if [ "$dry_run" = "1" ]; then
            printf '%s\n' "Dry run: would unload $label and remove $plist"
        else
            launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
            rm -f "$plist"
            printf '%s\n' "Stopped and removed $label"
        fi
        ;;
    status)
        launchctl print "$domain/$label" 2>/dev/null || true
        if [ -x "$installed_python" ]; then
            FAIRY_STATE_DIR="$state_dir" "$installed_python" -m fairy.worker --status --state-dir "$state_dir"
        else
            FAIRY_STATE_DIR="$state_dir" "$source_python" -m fairy.worker --status --state-dir "$state_dir"
        fi
        ;;
    logs)
        tail -n 80 "$log_dir/worker.log" "$log_dir/worker-error.log" 2>/dev/null || true
        ;;
    *)
        printf '%s\n' "Usage: $0 install|restart|uninstall|status|logs" >&2
        exit 2
        ;;
esac
