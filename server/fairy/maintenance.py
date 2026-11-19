"""PostgreSQL backup and restore through the standard PG tools."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit


def native_url(database_url):
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme != "postgresql":
        raise ValueError("postgresql_database_required")
    return urlunsplit(parsed)


def tool(name):
    configured = shutil.which(name)
    if configured:
        return configured
    for directory in (Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    raise ValueError(f"{name}_required")


def backup_database(database_url, target):
    target = Path(target).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError("target_already_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=".fairy-backup-", suffix=".dump", dir=target.parent
    )
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        process = subprocess.run(
            [
                tool("pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(staging),
                native_url(database_url),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if process.returncode != 0:
            raise ValueError("postgres_backup_failed")
        os.chmod(staging, 0o600)
        os.link(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    return {
        "file": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "format": "postgresql_custom",
        "credentials_included": False,
    }


def restore_database(source, database_url, expected_sha256):
    source = Path(source).absolute()
    if not source.is_file() or source.is_symlink():
        raise ValueError("source_not_regular_backup")
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("backup_digest_mismatch")
    process = subprocess.run(
        [
            tool("pg_restore"),
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--dbname",
            native_url(database_url),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if process.returncode != 0:
        raise ValueError("postgres_restore_failed")
    return {
        "restored": True,
        "file": str(source),
        "credentials_included": False,
    }


def main():
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.action == "backup":
        result = backup_database(args.source, args.target)
    else:
        if not args.sha256:
            parser.error("restore requires --sha256 from backup report")
        result = restore_database(args.source, args.target, args.sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
