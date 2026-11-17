"""SQLite snapshot backup/restore. Restore always creates a new database, never overwrites."""

import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

from .migrations import CURRENT_VERSION


def copy_database(source, target, expected_sha256=None):
    source, target = Path(source).absolute(), Path(target).absolute()
    if not source.is_file() or source.is_symlink():
        raise ValueError("source_not_regular_database")
    if target.exists() or target.is_symlink():
        raise ValueError("target_already_exists")
    if (
        expected_sha256
        and hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256
    ):
        raise ValueError("backup_digest_mismatch")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("database_integrity_failed")
        try:
            version = db.execute(
                "SELECT version FROM schema_version WHERE id=1"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            version = 0
        if version > CURRENT_VERSION:
            raise ValueError("backup_schema_newer_than_application")
        fd, staging = tempfile.mkstemp(prefix=".fairy-backup-", dir=target.parent)
        os.close(fd)
        try:
            with sqlite3.connect(staging) as destination:
                db.backup(destination)
            # hard link creates destination exclusively; concurrent processes cannot overwrite it.
            os.link(staging, target)
        finally:
            os.unlink(staging)
    return {
        "file": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "credentials_included": False,
    }


def main():
    import json

    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["backup", "restore"])
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--sha256")
    args = p.parse_args()
    if args.action == "restore" and not args.sha256:
        p.error("restore requires --sha256 from backup report")
    print(json.dumps(copy_database(args.source, args.target, args.sha256)))


if __name__ == "__main__":
    main()
