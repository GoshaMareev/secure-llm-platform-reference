from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    id: str
    document_id: str
    title: str
    text: str
    source_path: str
    metadata: dict[str, str]
    tokens: tuple[str, ...]
    vector: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "title": self.title,
            "text": self.text,
            "source_path": self.source_path,
            "metadata": self.metadata,
            "tokens": list(self.tokens),
            "vector": list(self.vector),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> IndexedChunk:
        return cls(
            id=str(value["id"]),
            document_id=str(value["document_id"]),
            title=str(value["title"]),
            text=str(value["text"]),
            source_path=str(value["source_path"]),
            metadata={str(key): str(item) for key, item in dict(value["metadata"]).items()},
            tokens=tuple(str(item) for item in value["tokens"]),
            vector=tuple(float(item) for item in value["vector"]),
        )
