from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    index_path: Path
    gateway_mode: str
    min_confidence: float
    top_k: int
    runtime_log_path: Path
    audit_log_path: Path
    audit_include_prompt: bool
    audit_pseudonym_salt: str
    model_base_url: str
    model_name: str
    model_api_key: str
    require_auth_header: bool
    guardrails_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        top_k = int(os.getenv("RAG_TOP_K", "3"))
        confidence = float(os.getenv("RAG_MIN_CONFIDENCE", "0.34"))
        if not 1 <= top_k <= 10:
            raise ValueError("RAG_TOP_K must be between 1 and 10")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("RAG_MIN_CONFIDENCE must be between 0 and 1")
        audit_salt = os.getenv("AUDIT_PSEUDONYM_SALT") or secrets.token_urlsafe(32)
        if len(audit_salt) < 32:
            raise ValueError("AUDIT_PSEUDONYM_SALT must contain at least 32 characters")
        runtime_log_path = Path(os.getenv("RUNTIME_LOG_PATH", ".local/runtime/runtime.jsonl"))
        audit_log_path = Path(os.getenv("AUDIT_LOG_PATH", ".local/audit/audit.jsonl"))
        runtime_resolved = runtime_log_path.resolve()
        audit_resolved = audit_log_path.resolve()
        runtime_dir = runtime_resolved.parent
        audit_dir = audit_resolved.parent
        paths_overlap = (
            runtime_resolved == audit_resolved
            or runtime_resolved in audit_resolved.parents
            or audit_resolved in runtime_resolved.parents
            or runtime_dir in audit_dir.parents
            or audit_dir in runtime_dir.parents
        )
        if paths_overlap:
            raise ValueError("RUNTIME_LOG_PATH and AUDIT_LOG_PATH must be separate")
        return cls(
            index_path=Path(os.getenv("RAG_INDEX_PATH", ".local/index.json")),
            gateway_mode=os.getenv("RAG_GATEWAY_MODE", "demo").casefold(),
            min_confidence=confidence,
            top_k=top_k,
            runtime_log_path=runtime_log_path,
            audit_log_path=audit_log_path,
            audit_include_prompt=_bool_env("AUDIT_INCLUDE_PROMPT"),
            audit_pseudonym_salt=audit_salt,
            model_base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:4000/v1"),
            model_name=os.getenv("OPENAI_COMPATIBLE_MODEL", "local-model"),
            model_api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
            require_auth_header=_bool_env("REQUIRE_AUTH_HEADER"),
            guardrails_enabled=_bool_env("GUARDRAILS_ENABLED", default=True),
        )
