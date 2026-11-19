#!/bin/sh
set -eu

command_name="${1:-status}"
label="io.fairy.backup"
domain="gui/$(id -u)"
app_support="${FAIRY_APP_SUPPORT:-$HOME/Library/Application Support/Fairy}"
runtime="${FAIRY_BACKUP_RUNTIME:-$app_support/worker-runtime}"
state_dir="${FAIRY_STATE_DIR:-$app_support/state}"
database="${FAIRY_DATABASE_URL:-postgresql+psycopg://$USER@127.0.0.1:5432/fairy}"
backup_dir="${FAIRY_BACKUP_DIR:-$app_support/backups}"
retention_days="${FAIRY_BACKUP_RETENTION_DAYS:-14}"
wrapper="${FAIRY_BACKUP_WRAPPER:-$app_support/run-backup.sh}"
plist="${FAIRY_BACKUP_PLIST:-$HOME/Library/LaunchAgents/$label.plist}"
log_dir="${FAIRY_LOG_DIR:-$HOME/Library/Logs/Fairy}"
python_path="$runtime/.venv/bin/python"
dry_run="${FAIRY_LAUNCHD_DRY_RUN:-0}"

if [ ! -x "$python_path" ]; then
    printf '%s\n' "Install the Fairy worker runtime first: scripts/fairy_worker_service.sh install" >&2
    exit 1
fi

write_wrapper() {
    mkdir -p "$backup_dir" "$log_dir"
    cat >"$wrapper" <<EOF
#!/bin/sh
set -eu
stamp=\$(date +%Y%m%d-%H%M%S)
target="$backup_dir/fairy-\$stamp.dump"
"$python_path" -m fairy.maintenance backup "$database" "\$target"
find "$backup_dir" -type f -name 'fairy-*.dump' -mtime +$retention_days -delete
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
    "RunAtLoad": False,
    "StartCalendarInterval": {"Hour": 3, "Minute": 0},
    "ProcessType": "Background",
    "StandardOutPath": os.path.join(logs, "backup.log"),
    "StandardErrorPath": os.path.join(logs, "backup-error.log"),
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
        write_wrapper
        write_plist
        if [ "$dry_run" = "1" ]; then
            printf '%s\n' "Dry run: generated $plist and $wrapper"
        else
            launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
            launchctl bootstrap "$domain" "$plist"
            launchctl enable "$domain/$label"
            printf '%s\n' "Installed $label; daily backup at 03:00"
        fi
        ;;
    run)
        "$wrapper"
        ;;
    status)
        launchctl print "$domain/$label" 2>/dev/null || true
        find "$backup_dir" -maxdepth 1 -type f -name 'fairy-*.dump' -print | sort | tail -n 20
        ;;
    uninstall)
        launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
        rm -f "$plist" "$wrapper"
        printf '%s\n' "Stopped $label; existing backups were retained"
        ;;
    *)
        printf '%s\n' "Usage: $0 install|run|status|uninstall" >&2
        exit 2
        ;;
esac
