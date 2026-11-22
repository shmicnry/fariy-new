"""PostgreSQL backup and restore through the standard PG tools."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


TABLES = ("records", "events", "requests", "scope_locks", "schema_version")


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
            "--clean",
            "--if-exists",
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
        detail = (process.stderr or "").strip().splitlines()
        tail = detail[-1][:200] if detail else "no_stderr"
        raise ValueError("postgres_restore_failed: " + tail)
    return {
        "restored": True,
        "file": str(source),
        "credentials_included": False,
    }


def database_counts(database_url):
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return {
                table: connection.execute(
                    text(f"SELECT count(*) FROM {table}")
                ).scalar_one()
                for table in TABLES
            }
    finally:
        engine.dispose()


def restore_drill(source, database_url, expected_sha256, expected_counts=None):
    base = make_url(database_url)
    database_name = "fairy_restore_drill_" + uuid4().hex
    admin = psycopg.connect(native_url(database_url), autocommit=True)
    temporary_url = base.set(database=database_name).render_as_string(
        hide_password=False
    )
    try:
        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
        restore_database(source, temporary_url, expected_sha256)
        restored_counts = database_counts(temporary_url)
        if expected_counts is not None and restored_counts != expected_counts:
            raise ValueError("restore_drill_count_mismatch")
        return {"restored": True, "counts": restored_counts}
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )
        admin.close()


def status_path(directory):
    return Path(directory).absolute() / "backup-status.json"


def read_status(directory):
    try:
        return json.loads(status_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def health_status(directory, max_age_hours=36):
    status = read_status(directory)
    if status is None:
        return {
            "status": "missing",
            "healthy": False,
            "stale": True,
            "error": "backup_status_not_recorded",
        }
    result = dict(status)
    completed = result.get("completed_at")
    try:
        age = max(
            0,
            int(
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(completed)
                ).total_seconds()
            ),
        )
        result["age_seconds"] = age
        result["stale"] = age > max_age_hours * 3600
        result["healthy"] = bool(result.get("healthy")) and not result["stale"]
        if result["stale"]:
            result["status"] = "stale"
    except (TypeError, ValueError):
        result.update(status="invalid", healthy=False, stale=True)
    return result


def write_status(directory, payload):
    target = status_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except FileExistsError:
        # A stale or planted temp file (possibly a symlink) is removed by name,
        # never followed, then recreated exclusively once.
        temporary.unlink(missing_ok=True)
        descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_backup(database_url, directory):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    target = directory / ("fairy-" + timestamp.strftime("%Y%m%d-%H%M%S") + ".dump")
    status = {
        "started_at": timestamp.isoformat(),
        "database": make_url(database_url).database,
    }
    try:
        expected_counts = database_counts(database_url)
        report = backup_database(database_url, target)
        drill = restore_drill(
            target,
            database_url,
            report["sha256"],
            expected_counts=expected_counts,
        )
        status.update(
            report,
            status="healthy",
            healthy=True,
            completed_at=datetime.now(timezone.utc).isoformat(),
            expected_counts=expected_counts,
            restore_drill=drill,
            error=None,
        )
    except Exception as error:
        status.update(
            status="failed",
            healthy=False,
            completed_at=datetime.now(timezone.utc).isoformat(),
            file=str(target),
            error=str(error),
        )
        write_status(directory, status)
        raise
    write_status(directory, status)
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore", "run"])
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.action == "backup":
        result = backup_database(args.source, args.target)
    elif args.action == "run":
        result = run_backup(args.source, args.target)
    else:
        if not args.sha256:
            parser.error("restore requires --sha256 from backup report")
        result = restore_database(args.source, args.target, args.sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
