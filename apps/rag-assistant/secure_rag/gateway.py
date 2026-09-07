from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .retrieval import SearchResult


class ModelGateway(Protocol):
    def answer(self, question: str, context: list[SearchResult]) -> str: ...


class DemoGateway:
    """Deterministic, offline answer generation for tests and portfolio demos."""

    def answer(self, question: str, context: list[SearchResult]) -> str:
        del question
        if not context:
            return "I do not have enough grounded context to answer."
        first = context[0].chunk.text.split(". ", maxsplit=1)[0].strip()
        if first and not first.endswith("."):
            first += "."
        return f"According to {context[0].chunk.title}: {first}"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleGateway:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        invalid = (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        )
        if invalid:
            raise ValueError(
                "Model base URL must be HTTP(S), include a host, and exclude embedded credentials"
            )

    def answer(self, question: str, context: list[SearchResult]) -> str:
        evidence = "\n\n".join(
            f"SOURCE {item.chunk.document_id} — {item.chunk.title}\n{item.chunk.text}" for item in context
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the supplied sources. "
                        "If they are insufficient, refuse. Cite source IDs."
                    ),
                },
                {"role": "user", "content": f"QUESTION\n{question}\n\nSOURCES\n{evidence}"},
            ],
        }
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        request = Request(  # noqa: S310 - URL scheme and credential form validated above
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-controlled URL
            body = json.load(response)
        return str(body["choices"][0]["message"]["content"])
