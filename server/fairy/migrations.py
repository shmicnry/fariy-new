"""Versioned, serialized bootstrap for legacy and new databases."""

from sqlalchemy import text

CURRENT_VERSION = 2


def migrate(engine, metadata):
    if engine.dialect.name != "postgresql":
        raise RuntimeError("postgresql_database_required")
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(731904211)"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
            )
        )
        version = (
            conn.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
            or 0
        )
        if version > CURRENT_VERSION:
            raise RuntimeError("database_schema_newer_than_application")
        if version < 1:
            metadata.create_all(conn)
        if version < 2:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_records_work_queue ON records(scope, kind, status, created_at)"
                )
            )
        conn.execute(
            text(
                "INSERT INTO schema_version(id,version) VALUES(1,:v) ON CONFLICT(id) DO UPDATE SET version=excluded.version"
            ),
            {"v": CURRENT_VERSION},
        )
        conn.execute(
            text(
                "INSERT INTO scope_locks(id,version) VALUES('owner',0) ON CONFLICT(id) DO NOTHING"
            )
        )
