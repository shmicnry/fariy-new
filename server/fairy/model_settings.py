"""Owner-managed model profiles. Credentials never enter SQL or public responses."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .service import Service, fail


def cloud_endpoint(value):
    if not value:
        return value
    u = urlsplit(value)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
    ):
        raise ValueError("云模型地址必须是无凭证的 HTTPS 接口根地址")
    if u.hostname in ("localhost", "host.docker.internal") or u.hostname.endswith(
        ".localhost"
    ):
        raise ValueError("云模型地址不能是本机")
    try:
        address = ipaddress.ip_address(u.hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("云模型地址不能是私网 IP")
    try:
        u.port
    except ValueError:
        raise ValueError("无效端口")
    return value.rstrip("/")


def clean_key(value):
    if value is None:
        return None
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("密钥不能为空或包含控制字符")
    return value


def stripped_text(value):
    value = value.strip()
    if not value:
        raise ValueError("名称不能为空")
    return value


TASKS = ("chat", "reasoning", "code", "writing")


class ProfileBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    name: str = Field(min_length=1, max_length=60)

    @field_validator("id")
    @classmethod
    def reserved_id(cls, value):
        if value == "default":
            raise ValueError("档案 id 不能使用保留值 default")
        return value

    @field_validator("name")
    @classmethod
    def named(cls, value):
        return stripped_text(value)


class LocalProfile(ProfileBase):
    model: str = Field(min_length=1, max_length=160)
    context_window: int = Field(default=16384, ge=4096, le=65536)
    max_output_tokens: int = Field(default=1536, ge=128, le=4096)
    timeout_seconds: int = Field(default=90, ge=5, le=180)

    @field_validator("model")
    @classmethod
    def named_model(cls, value):
        return stripped_text(value)

    @model_validator(mode="after")
    def headroom(self):
        if self.max_output_tokens + 2048 >= self.context_window:
            raise ValueError("本地上下文窗口必须为输入留出空间")
        return self


class CloudProfile(ProfileBase):
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=160)
    enabled: bool = False
    timeout_seconds: int = Field(default=60, ge=5, le=120)
    max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    input_cents_per_million: int = Field(default=0, ge=0, le=10_000_000)
    output_cents_per_million: int = Field(default=0, ge=0, le=10_000_000)
    api_key: str | None = Field(
        default=None,
        max_length=4096,
        repr=False,
        exclude=True,
        json_schema_extra={"writeOnly": True},
    )
    clear_key: bool = False
    key_configured: bool = Field(
        default=False, exclude=True, json_schema_extra={"readOnly": True}
    )
    ready: bool = Field(
        default=False, exclude=True, json_schema_extra={"readOnly": True}
    )

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        return cloud_endpoint(value)

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        return clean_key(value)

    @model_validator(mode="after")
    def complete(self):
        if self.enabled and (not self.base_url or not self.model):
            raise ValueError("启用云档案前请填写地址与模型名")
        if self.clear_key and self.api_key:
            raise ValueError("不能同时保存与清除密钥")
        return self


class TaskRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local: str = "default"
    cloud: str = "default"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = Field(default="qwen3:4b", max_length=160)
    local_timeout_seconds: int = Field(default=90, ge=5, le=180)
    local_context_window: int = Field(default=16384, ge=4096, le=65536)
    local_max_output_tokens: int = Field(default=1536, ge=128, le=4096)
    memory_mode: Literal["review", "off"] = "review"
    cloud_enabled: bool = False
    cloud_base_url: str = Field(default="", max_length=500)
    cloud_model: str = Field(default="", max_length=160)
    cloud_context: Literal["question_only", "approved_memories"] = "question_only"
    cloud_timeout_seconds: int = Field(default=60, ge=5, le=120)
    cloud_max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    cloud_daily_request_limit: int = Field(default=10, ge=0, le=1000)
    cloud_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    cloud_input_cents_per_million: int = Field(default=0, ge=0, le=10_000_000)
    cloud_output_cents_per_million: int = Field(default=0, ge=0, le=10_000_000)
    cloud_daily_cost_limit_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    fallback_on: list[
        Literal[
            "capability_limit",
            "knowledge_gap",
            "local_unavailable",
            "local_timeout",
            "invalid_response",
        ]
    ] = Field(
        default_factory=lambda: [
            "capability_limit",
            "knowledge_gap",
            "local_unavailable",
            "local_timeout",
            "invalid_response",
        ],
        max_length=5,
    )
    cloud_api_key: str | None = Field(
        default=None,
        max_length=4096,
        repr=False,
        exclude=True,
        json_schema_extra={"writeOnly": True},
    )
    clear_cloud_key: bool = False
    local_profiles: list[LocalProfile] = Field(default_factory=list, max_length=8)
    cloud_profiles: list[CloudProfile] = Field(default_factory=list, max_length=8)
    task_routes: dict[Literal["chat", "reasoning", "code", "writing"], TaskRoute] = (
        Field(default_factory=lambda: {t: TaskRoute() for t in TASKS})
    )

    @field_validator("ollama_base_url")
    @classmethod
    def local_url(cls, value):
        u = urlsplit(value)
        if (
            u.scheme not in ("http", "https")
            or u.hostname not in ("localhost", "127.0.0.1", "::1")
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path not in ("", "/")
        ):
            raise ValueError("Ollama 必须是本机回环地址，且不包含凭证或路径")
        try:
            u.port
        except ValueError:
            raise ValueError("无效端口")
        return value.rstrip("/")

    @field_validator("cloud_base_url")
    @classmethod
    def cloud_url(cls, value):
        return cloud_endpoint(value)

    @field_validator("cloud_api_key")
    @classmethod
    def valid_key(cls, value):
        return clean_key(value)

    @model_validator(mode="after")
    def complete(self):
        if self.cloud_enabled and (not self.cloud_base_url or not self.cloud_model):
            raise ValueError("启用云副模型前请填写地址与模型名")
        if self.clear_cloud_key and self.cloud_api_key:
            raise ValueError("不能同时保存与清除密钥")
        if self.local_max_output_tokens + 2048 >= self.local_context_window:
            raise ValueError("本地上下文窗口必须为输入留出空间")
        if (
            self.cloud_daily_cost_limit_cents
            and not self.cloud_input_cents_per_million
            and not self.cloud_output_cents_per_million
            and not any(
                p.input_cents_per_million or p.output_cents_per_million
                for p in self.cloud_profiles
            )
        ):
            raise ValueError("设置云端金额上限前请填写 Token 单价")
        local_ids = [p.id for p in self.local_profiles]
        cloud_ids = [p.id for p in self.cloud_profiles]
        if len(set(local_ids)) != len(local_ids) or len(set(cloud_ids)) != len(
            cloud_ids
        ):
            raise ValueError("模型档案 id 不能重复")
        for route in self.task_routes.values():
            if route.local not in {"default", *local_ids}:
                raise ValueError("任务路由引用了不存在的本地档案")
            if route.cloud not in {"default", *cloud_ids}:
                raise ValueError("任务路由引用了不存在的云档案")
        return self


def classify_task(text):
    lowered = (text or "").lower()
    if "```" in lowered or any(
        w in lowered
        for w in (
            "代码",
            "编程",
            "函数",
            "脚本",
            "报错",
            "debug",
            "python",
            "javascript",
            "typescript",
            "sql",
            "正则",
            "bug",
        )
    ):
        return "code"
    if any(
        w in lowered
        for w in ("证明", "推导", "数学", "逻辑", "计算", "推理", "求解", "方程", "概率")
    ):
        return "reasoning"
    if any(
        w in lowered
        for w in ("写一篇", "写作", "作文", "润色", "总结", "摘要", "翻译", "改写", "文案")
    ):
        return "writing"
    return "chat"


def resolve_route(conf, task):
    """Overlay the task's profiles onto the global config; keys stay endpoint-bound."""
    resolved = dict(conf)
    route = (conf.get("task_routes") or {}).get(task) or {}
    local = next(
        (p for p in conf.get("local_profiles", []) if p["id"] == route.get("local")),
        None,
    )
    if local:
        resolved.update(
            ollama_model=local["model"],
            local_context_window=local.get("context_window", 16384),
            local_max_output_tokens=local.get("max_output_tokens", 1536),
            local_timeout_seconds=local.get("timeout_seconds", 90),
        )
    cloud = next(
        (p for p in conf.get("cloud_profiles", []) if p["id"] == route.get("cloud")),
        None,
    )
    if cloud:
        resolved.update(
            cloud_enabled=cloud.get("enabled", False),
            cloud_base_url=cloud.get("base_url", ""),
            cloud_model=cloud.get("model", ""),
            cloud_timeout_seconds=cloud.get("timeout_seconds", 60),
            cloud_max_output_tokens=cloud.get("max_output_tokens", 1024),
            cloud_input_cents_per_million=cloud.get("input_cents_per_million", 0),
            cloud_output_cents_per_million=cloud.get("output_cents_per_million", 0),
        )
        if cloud.get("credential_ref"):
            resolved["credential_ref"] = cloud["credential_ref"]
        else:
            resolved.pop("credential_ref", None)
    resolved["local_profile"] = local["name"] if local else "默认"
    resolved["cloud_profile"] = cloud["name"] if cloud else "默认"
    return resolved


class CredentialVault:
    """Immutable credential files; an orphan after DB rollback is never activated."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def put(self, endpoint, value):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            fail(503, "credential_store_unavailable")
        os.chmod(self.directory, 0o700)
        ref = "cloud_" + secrets.token_hex(16)
        path = self.directory / (ref + ".json")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"endpoint": endpoint, "key": value}, f)
            f.flush()
            os.fsync(f.fileno())
        return ref

    def read(self, ref, endpoint):
        if not ref or not re.fullmatch(r"cloud_[a-f0-9]{32}", ref):
            return None
        path = self.directory / (ref + ".json")
        try:
            if self.directory.is_symlink():
                return None
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd) as f:
                metadata = os.fstat(f.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                    return None
                data = json.load(f)
            return data["key"] if data.get("endpoint") == endpoint else None
        except (OSError, ValueError, KeyError):
            return None

    def delete(self, ref):
        if not ref or not re.fullmatch(r"cloud_[a-f0-9]{32}", ref):
            return
        if self.directory.is_symlink():
            raise OSError("invalid credential directory")
        (self.directory / (ref + ".json")).unlink(missing_ok=True)


class ModelSettings:
    def __init__(self, db, secrets_dir=None):
        self.db = db
        self.service = Service(db)
        self.vault = CredentialVault(
            secrets_dir or Path(os.getenv("FAIRY_STATE_DIR", "var")) / "credentials"
        )
        with db.tx() as s:
            if not self.service.rows(s, "model_config"):
                conf = ModelConfig(
                    revision=0,
                    ollama_base_url=os.getenv(
                        "FAIRY_OLLAMA_BASE_URL", "http://127.0.0.1:11434"
                    ),
                    ollama_model=os.getenv("FAIRY_OLLAMA_MODEL", "qwen3:4b"),
                    cloud_base_url=os.getenv("FAIRY_CLOUD_BASE_URL", ""),
                    cloud_model=os.getenv("FAIRY_CLOUD_MODEL", ""),
                )
                self.db.add(
                    s,
                    "owner",
                    "model_config",
                    conf.model_dump(exclude={"revision", "clear_cloud_key"}),
                )

    def record(self, s):
        return self.service.rows(s, "model_config")[0]

    def runtime(self):
        with self.db.sessions() as s:
            r = self.record(s)
            data = dict(json.loads(r.payload), id=r.id, revision=r.revision)
        data.setdefault("local_profiles", [])
        data.setdefault("cloud_profiles", [])
        data.setdefault(
            "task_routes",
            {t: {"local": "default", "cloud": "default"} for t in TASKS},
        )
        return data

    def credential(self, data):
        key = self.vault.read(data.get("credential_ref"), data["cloud_base_url"])
        if key:
            return key, "private_file"
        if data["cloud_base_url"] == os.getenv("FAIRY_CLOUD_BASE_URL", "").rstrip("/"):
            key = os.getenv("FAIRY_CLOUD_API_KEY")
            if key:
                return key, "environment"
        return None, None

    def public(self, data=None):
        data = dict(data or self.runtime())
        data.pop("credential_ref", None)
        runtime = self.runtime() if data.get("id") else data
        key, source = self.credential(runtime)
        data.pop("id", None)
        data.update(cloud_key_configured=bool(key), cloud_key_source=source)
        data["cloud_ready"] = bool(
            data["cloud_enabled"]
            and key
            and data["cloud_base_url"]
            and data["cloud_model"]
        )
        data.setdefault("local_profiles", [])
        data.setdefault(
            "task_routes",
            {t: {"local": "default", "cloud": "default"} for t in TASKS},
        )
        profiles = []
        for entry in data.get("cloud_profiles", []):
            entry = dict(entry)
            profile_ref = entry.pop("credential_ref", None)
            entry.pop("api_key", None)
            entry.pop("clear_key", None)
            profile_key, _ = self.credential(
                {
                    "credential_ref": profile_ref,
                    "cloud_base_url": entry.get("base_url", ""),
                }
            )
            entry["key_configured"] = bool(profile_key)
            entry["ready"] = bool(
                entry.get("enabled")
                and profile_key
                and entry.get("base_url")
                and entry.get("model")
            )
            profiles.append(entry)
        data["cloud_profiles"] = profiles
        return data

    def save(self, body: ModelConfig):
        with self.db.tx() as s:
            r = self.record(s)
            old = json.loads(r.payload)
            if r.revision != body.revision:
                fail(409, "revision_conflict")
            new = body.model_dump(exclude={"revision", "clear_cloud_key"})
            # A stored key is bound to the exact endpoint. Changing it requires a new key.
            ref = (
                old.get("credential_ref")
                if old["cloud_base_url"] == new["cloud_base_url"]
                else None
            )
            if body.clear_cloud_key:
                if self.credential(dict(new, credential_ref=None))[1] == "environment":
                    fail(409, "environment_key_requires_restart")
                ref = None
            if body.cloud_api_key:
                if not body.cloud_base_url:
                    fail(422, "cloud_endpoint_required_for_key")
                try:
                    ref = self.vault.put(
                        body.cloud_base_url, body.cloud_api_key.strip()
                    )
                except OSError:
                    fail(503, "credential_store_unavailable")
            new["credential_ref"] = ref
            if body.cloud_enabled and not self.credential(new)[0]:
                fail(422, "cloud_key_required")
            old_profiles = {p["id"]: p for p in old.get("cloud_profiles", [])}
            entries = []
            kept_refs = {ref} if ref else set()
            for profile in body.cloud_profiles:
                previous = old_profiles.get(profile.id, {})
                pref = (
                    previous.get("credential_ref")
                    if previous.get("base_url") == profile.base_url
                    else None
                )
                if profile.clear_key:
                    if (
                        self.credential(
                            {
                                "credential_ref": None,
                                "cloud_base_url": profile.base_url,
                            }
                        )[1]
                        == "environment"
                    ):
                        fail(409, "environment_key_requires_restart")
                    pref = None
                if profile.api_key:
                    if not profile.base_url:
                        fail(422, "cloud_endpoint_required_for_key")
                    try:
                        pref = self.vault.put(
                            profile.base_url, profile.api_key.strip()
                        )
                    except OSError:
                        fail(503, "credential_store_unavailable")
                entry = profile.model_dump(exclude={"clear_key"})
                entry["credential_ref"] = pref
                if profile.enabled and not self.credential(
                    dict(entry, cloud_base_url=entry["base_url"])
                )[0]:
                    fail(422, "cloud_profile_key_required")
                kept_refs.add(pref)
                entries.append(entry)
            new["cloud_profiles"] = entries
            r.payload = json.dumps(new)
            r.revision += 1
            self.db.emit(
                s,
                "owner",
                "models.configured",
                {"revision": r.revision, "cloud_enabled": body.cloud_enabled},
            )
        stale_refs = {old.get("credential_ref")}
        stale_refs.update(
            p.get("credential_ref") for p in old.get("cloud_profiles", [])
        )
        stale_refs -= kept_refs
        stale_refs.discard(None)
        for stale in sorted(stale_refs):
            try:
                self.vault.delete(stale)
            except OSError:
                with self.db.tx() as s:
                    self.db.emit(
                        s,
                        "owner",
                        "models.credential_cleanup_required",
                        {"revision": r.revision},
                    )
                break
        return self.public()
