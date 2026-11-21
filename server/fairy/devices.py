"""Paired device tokens. The owner master secret bootstraps; device tokens are revocable.

Only the SHA-256 hash of a device token is stored. The plaintext token is shown
once at pairing time and never persisted (including the idempotency cache).
"""

import hashlib
import json
import secrets

from .service import fail
from .store import view


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _public(r):
    data = view(r)
    data.pop("token_hash", None)
    return data


class DeviceService:
    def __init__(self, store, service):
        self.db = store
        self.service = service

    def pair(self, name, key):
        name = (name or "").strip()
        if not name or len(name) > 64:
            fail(422, "device_name_required")
        token = "fd_" + secrets.token_urlsafe(32)
        with self.db.tx() as s:
            body = {"kind": "device", "name": name}
            cached = self.service.replay(s, key, body)
            if cached is not None:
                # A replay never re-discloses the token; pair again with a new key.
                return {**cached, "token": None}
            r = self.db.add(
                s, "owner", "device", {"name": name, "token_hash": _hash(token)}
            )
            self.db.emit(s, "owner", "device.paired", {"id": r.id, "name": name})
            result = _public(r)
            self.service.remember_result(s, key, body, result)
            return {**result, "token": token}

    def list(self):
        with self.db.sessions() as s:
            return [
                _public(r)
                for r in self.service.rows(s, "device")
                if r.status != "deleted"
            ]

    def revoke(self, id):
        with self.db.tx() as s:
            r = self.service.get(s, id, "device")
            if r.status != "revoked":
                r.status = "revoked"
                r.revision += 1
                self.db.emit(s, "owner", "device.revoked", {"id": id})
            return _public(r)

    def authenticate(self, token):
        if not token.startswith("fd_"):
            return None
        digest = _hash(token)
        with self.db.sessions() as s:
            for r in self.service.rows(s, "device"):
                if r.status != "active":
                    continue
                if secrets.compare_digest(
                    json.loads(r.payload).get("token_hash", ""), digest
                ):
                    return r.id
        return None

    def active(self, id):
        with self.db.sessions() as s:
            from .store import Record

            r = s.get(Record, id)
            return bool(r and r.kind == "device" and r.status == "active")
