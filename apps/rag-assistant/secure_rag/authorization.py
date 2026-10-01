"""Operator-owned mapping from authenticated subjects to document audiences."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    audiences: frozenset[str] = frozenset({"all"})

    def allows(self, metadata: dict[str, str]) -> bool:
        # Unknown/missing classifications never become public by accident.
        return metadata.get("audience", "").casefold() in self.audiences


PUBLIC_SCOPE = RetrievalScope()


class IdentityPolicy:
    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("subjects"), dict):
            raise ValueError("Invalid identity policy")
        self._subjects: dict[str, RetrievalScope] = {}
        for subject, audiences in payload["subjects"].items():
            if (
                not isinstance(subject, str)
                or not subject
                or len(subject) > 128
                or not isinstance(audiences, list)
                or not audiences
                or any(not isinstance(item, str) or not item or item == "*" for item in audiences)
            ):
                raise ValueError("Invalid identity policy subject or audiences")
            self._subjects[subject] = RetrievalScope(frozenset(item.casefold() for item in audiences))

    def scope_for(self, subject: str) -> RetrievalScope:
        try:
            return self._subjects[subject]
        except KeyError as error:
            raise PermissionError("Identity has no document access policy") from error
