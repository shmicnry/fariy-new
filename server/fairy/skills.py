"""Declarative built-in skill lifecycle. Installation never grants execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .mac_bridge import MacBridge
from .service import Service, fail
from .store import view

Permission = Literal[
    "mac.read_status",
    "mac.read_ax",
    "mac.open_app",
    "mac.write_file",
    "learning.read",
    "world.read",
    "autonomy.read",
]
Implementation = Literal[
    "mac_status",
    "mac_ax_tree",
    "mac_open_app",
    "mac_create_file",
    "learning_search",
    "world_query",
    "autonomy_suggest",
]


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    purpose: str = Field(min_length=1, max_length=500)
    implementation: Implementation
    permissions: list[Permission] = Field(min_length=1, max_length=4)


class SkillGrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    permissions: list[Permission] = Field(min_length=1, max_length=4)
    expires_minutes: int = Field(default=60, ge=1, le=1440)


class SkillInvokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=1000)
    path: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, max_length=65536)


BUILTINS = (
    {
        "key": "system.mac_open_allowed_app",
        "name": "Mac 启动允许应用",
        "version": "1.0.0",
        "purpose": "只启动所有者允许列表中的应用，不发送键入内容，不声称完成应用内任务。",
        "implementation": "mac_open_app",
        "permissions": ["mac.open_app"],
    },
    {
        "key": "system.mac_status",
        "name": "Mac 只读状态",
        "version": "1.0.0",
        "purpose": "读取系统版本、权限占位状态与应用目录清单，不执行输入注入或屏幕采集。",
        "implementation": "mac_status",
        "permissions": ["mac.read_status"],
    },
    {
        "key": "system.mac_create_file",
        "name": "Mac 创建允许文件",
        "version": "1.0.0",
        "purpose": "只在所有者允许目录中创建新文件，不覆盖已有文件，并在写入后校验字节和 SHA-256。",
        "implementation": "mac_create_file",
        "permissions": ["mac.write_file"],
    },
    {
        "key": "system.mac_ax_tree",
        "name": "Mac 只读界面结构",
        "version": "1.0.0",
        "purpose": "在所有者授权辅助功能后，读取指定运行中应用的限深 Accessibility Tree，不执行点击或键入。",
        "implementation": "mac_ax_tree",
        "permissions": ["mac.read_ax"],
    },
    {
        "key": "learning.search",
        "name": "学习资料检索",
        "version": "1.0.0",
        "purpose": "在仍有效的学习材料块中进行词法检索。",
        "implementation": "learning_search",
        "permissions": ["learning.read"],
    },
    {
        "key": "world.query",
        "name": "世界主张查询",
        "version": "1.0.0",
        "purpose": "返回带来源和冲突标记的世界知识主张。",
        "implementation": "world_query",
        "permissions": ["world.read"],
    },
    {
        "key": "autonomy.suggest",
        "name": "学习缺口候选",
        "version": "1.0.0",
        "purpose": "读取后台生成的自主学习候选，不启动联网或付费调用。",
        "implementation": "autonomy_suggest",
        "permissions": ["autonomy.read"],
    },
)


class SkillService(Service):
    def __init__(self, store):
        super().__init__(store)
        with self.db.tx() as session:
            existing = {
                json.loads(row.payload).get("key")
                for row in self.rows(session, "skill_package")
            }
            for item in BUILTINS:
                if item["key"] in existing:
                    continue
                manifest = dict(item)
                manifest.update(
                    installed=False,
                    enabled=False,
                    quarantined=False,
                    executable=True,
                    grant_ids=[],
                    digest=hashlib.sha256(
                        json.dumps(item, sort_keys=True).encode()
                    ).hexdigest(),
                )
                self.db.add(session, "owner", "skill_package", manifest)

    def _record(self, session, skill_id):
        return self.get(session, skill_id, "skill_package")

    def install(self, skill_id):
        with self.db.tx() as session:
            row = self._record(session, skill_id)
            data = json.loads(row.payload)
            data.update(
                installed=True,
                enabled=False,
                quarantined=False,
                installed_at=datetime.now(timezone.utc).isoformat(),
            )
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.emit(session, "owner", "skill.installed", {"id": skill_id})
            return view(row)

    def grant(self, skill_id, body):
        with self.db.tx() as session:
            row = self._record(session, skill_id)
            data = json.loads(row.payload)
            if not data["installed"]:
                fail(409, "skill_not_installed")
            if row.revision != body.revision:
                fail(409, "revision_conflict")
            requested = set(body.permissions)
            if not requested <= set(data["permissions"]):
                fail(422, "grant_exceeds_skill_permissions")
            expires = datetime.now(timezone.utc) + timedelta(
                minutes=body.expires_minutes
            )
            grant = self.db.add(
                session,
                "owner",
                "skill_grant",
                {
                    "skill_id": skill_id,
                    "permissions": sorted(requested),
                    "expires_at": expires.isoformat(),
                    "source": "owner_confirmation",
                },
            )
            data["grant_ids"] = data.get("grant_ids", []) + [grant.id]
            data["enabled"] = True
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.emit(
                session,
                "owner",
                "skill.granted",
                {"skill_id": skill_id, "grant_id": grant.id},
            )
            return {"skill": view(row), "grant": view(grant)}

    def disable(self, skill_id):
        with self.db.tx() as session:
            row = self._record(session, skill_id)
            data = json.loads(row.payload)
            data["enabled"] = False
            row.payload = json.dumps(data)
            row.revision += 1
            for grant in self.rows(session, "skill_grant"):
                if json.loads(grant.payload).get("skill_id") == skill_id:
                    grant.status = "revoked"
                    grant.revision += 1
            self.db.emit(session, "owner", "skill.disabled", {"id": skill_id})
            return view(row)

    def _active_grant(self, session, data):
        grants = [
            row
            for row in self.rows(session, "skill_grant")
            if row.id in data.get("grant_ids", [])
            and row.status == "active"
            and datetime.fromisoformat(json.loads(row.payload)["expires_at"])
            > datetime.now(timezone.utc)
        ]
        if not grants:
            fail(409, "skill_grant_required")
        return max(grants, key=lambda row: row.created_at)

    async def invoke(self, skill_id, body):
        with self.db.tx() as session:
            row = self._record(session, skill_id)
            data = json.loads(row.payload)
            if not data.get("installed") or not data.get("enabled"):
                fail(409, "skill_not_enabled")
            grant = self._active_grant(session, data)
            invocation = self.db.add(
                session,
                "owner",
                "skill_invocation",
                {
                    "skill_id": skill_id,
                    "implementation": data["implementation"],
                    "grant_id": grant.id,
                    "input_digest": hashlib.sha256(
                        json.dumps(body.model_dump(), sort_keys=True).encode()
                    ).hexdigest(),
                },
                "running",
            )
            invocation_id = invocation.id
        try:
            if data["implementation"] == "mac_status":
                result = await asyncio.to_thread(MacBridge(self).status)
            elif data["implementation"] == "mac_ax_tree":
                result = await asyncio.to_thread(
                    MacBridge(self).ax_tree, body.query.strip() or None
                )
            elif data["implementation"] == "mac_open_app":
                result = await asyncio.to_thread(
                    MacBridge(self).open_app, body.query.strip()
                )
            elif data["implementation"] == "mac_create_file":
                if body.content is None:
                    fail(422, "file_content_required")
                result = await asyncio.to_thread(
                    MacBridge(self).create_file,
                    body.path,
                    body.content,
                )
            elif data["implementation"] == "learning_search":
                from .cognition import relevance

                candidates = []
                with self.db.sessions() as session:
                    for chunk in self.rows(session, "learning_chunk"):
                        if chunk.status != "active":
                            continue
                        chunk_data = json.loads(chunk.payload)
                        if any(
                            not self.source_eligible(self.get(session, source_id))
                            for source_id in chunk_data["source_ids"]
                        ):
                            continue
                        score = relevance(body.query, chunk_data["text"])
                        candidates.append(
                            {
                                "id": chunk.id,
                                "text": chunk_data["text"],
                                "locations": chunk_data.get("locations", []),
                                "lexical_relevance": score,
                            }
                        )
                semantic = getattr(self, "semantic", None)
                results = None
                if semantic is not None and candidates:
                    reranked = await semantic.rerank(
                        body.query,
                        [
                            {"id": item["id"], "text": item["text"]}
                            for item in candidates[:200]
                        ],
                    )
                    if reranked is not None:
                        scores = {
                            item["id"]: item["semantic_relevance"]
                            for item in reranked
                        }
                        results = []
                        for item in candidates:
                            if item["id"] not in scores:
                                continue
                            item["semantic_relevance"] = scores[item["id"]]
                            item["relevance"] = round(
                                item["lexical_relevance"] * 0.55
                                + max(0.0, scores[item["id"]] - 0.35) * 0.45,
                                6,
                            )
                            if (
                                item["lexical_relevance"] > 0
                                or item["semantic_relevance"] >= 0.68
                            ):
                                results.append(item)
                        result = {
                            "results": sorted(
                                results,
                                key=lambda item: (-item["relevance"], item["id"]),
                            )[:20],
                            "semantic_available": True,
                            "retrieval_mode": "ollama_semantic_rerank",
                        }
                if results is None:
                    results = [
                        dict(item, relevance=item["lexical_relevance"])
                        for item in candidates
                        if item["lexical_relevance"] > 0
                    ]
                    result = {
                        "results": sorted(
                            results,
                            key=lambda item: (-item["relevance"], item["id"]),
                        )[:20],
                        "semantic_available": False,
                        "retrieval_mode": "local_character_vector_hybrid",
                    }
            elif data["implementation"] == "world_query":
                from .knowledge import KnowledgeService

                result = {"claims": KnowledgeService(self.db).world()}
            elif data["implementation"] == "autonomy_suggest":
                result = {
                    "candidates": [
                        row
                        for row in self.list("autonomy_candidate")
                        if row.get("status") == "proposed"
                    ]
                }
            else:
                fail(409, "skill_implementation_not_available")
            with self.db.tx() as session:
                # Re-validate the grant at completion: expiry or revocation
                # during execution must withhold the result.
                fresh_grant = self.get(session, grant.id, "skill_grant")
                if fresh_grant.status != "active" or datetime.fromisoformat(
                    json.loads(fresh_grant.payload)["expires_at"]
                ) <= datetime.now(timezone.utc):
                    fail(409, "skill_grant_expired")
                invocation = self.get(session, invocation_id, "skill_invocation")
                invocation.status = "completed"
                invocation.revision += 1
                invocation.payload = json.dumps(
                    {**json.loads(invocation.payload), "result": result}
                )
                invocation_result = view(invocation)
                self.db.emit(
                    session,
                    "owner",
                    "skill.invoked",
                    {"skill_id": skill_id, "invocation_id": invocation.id},
                )
            return {"invocation": invocation_result, "result": result}
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            error = (
                detail
                if isinstance(detail, str)
                and 0 < len(detail) <= 100
                and all(character.islower() or character.isdigit() or character == "_" for character in detail)
                else "skill_invocation_failed"
            )
            with self.db.tx() as session:
                invocation = self.get(session, invocation_id, "skill_invocation")
                invocation.status = "failed"
                invocation.revision += 1
                payload = json.loads(invocation.payload)
                payload.update(
                    error=error,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                invocation.payload = json.dumps(payload)
                self.db.emit(
                    session,
                    "owner",
                    "skill.invocation_failed",
                    {
                        "skill_id": skill_id,
                        "invocation_id": invocation.id,
                        "error": error,
                    },
                )
            raise
