from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import contextmanager
import json
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"
    id = Column(String, primary_key=True)
    scope = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="active")
    payload = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class Event(Base):
    __tablename__ = "events"
    seq = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class Request(Base):
    __tablename__ = "requests"
    id = Column(String, primary_key=True)
    scope = Column(String, nullable=False)
    key = Column(String, nullable=False)
    digest = Column(String, nullable=False)
    result = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("scope", "key"),)


class ScopeLock(Base):
    __tablename__ = "scope_locks"
    id = Column(String, primary_key=True)
    version = Column(Integer, nullable=False, default=0)


def view(r):
    result = {
        "id": r.id,
        "scope": r.scope,
        "kind": r.kind,
        "revision": r.revision,
        "status": r.status,
        "created_at": r.created_at,
    }
    result.update(json.loads(r.payload))
    return result


class Store:
    def __init__(self, url):
        if make_url(url).get_backend_name() != "postgresql":
            raise ValueError("postgresql_database_required")
        self.engine = create_engine(url, pool_pre_ping=True)

        from .migrations import migrate

        migrate(self.engine, Base.metadata)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def tx(self, scope="owner"):
        from sqlalchemy import update

        with self.sessions.begin() as s:
            # The row update serializes writers across API and worker processes.
            s.execute(
                update(ScopeLock)
                .where(ScopeLock.id == scope)
                .values(version=ScopeLock.version + 1)
            )
            yield s

    def add(self, s, scope, kind, data, status="active"):
        r = Record(
            id=uid(),
            scope=scope,
            kind=kind,
            revision=1,
            status=status,
            payload=json.dumps(data, ensure_ascii=False),
            created_at=now(),
        )
        s.add(r)
        return r

    def emit(self, s, scope, type, data):
        s.add(
            Event(
                scope=scope,
                type=type,
                payload=json.dumps(data, ensure_ascii=False),
                created_at=now(),
            )
        )
