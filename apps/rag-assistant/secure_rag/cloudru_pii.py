"""Local Cloud.ru dry-run scanner; return aggregate observations, never originals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_TEXTS = 128
MAX_REQUEST_BYTES = 262_144
MAX_RESPONSE_BYTES = 1_048_576


class ScanUnavailable(Exception):
    """A bounded reason code, without service responses or sensitive text."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ScanSummary:
    text_count: int
    changed_text_count: int
    match_count: int
    data_types: tuple[int, ...]

    def event(self) -> dict:
        return {
            "status": "checked",
            "text_count": self.text_count,
            "changed_text_count": self.changed_text_count,
            "match_count": self.match_count,
            "data_types": list(self.data_types),
        }


class CloudruScanClient:
    def __init__(self, base_url: str = "http://cloudru-filter:9080", *, timeout_seconds: float = 2.0):
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"cloudru-filter", "127.0.0.1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            raise ValueError("Cloud.ru scan URL must name the private scanner or loopback with a port")
        self._url = base_url.rstrip("/") + "/v1/scan"
        self._timeout = timeout_seconds
        # Local sensitive text must not follow a redirect or an ambient HTTP proxy.
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def scan(self, texts: list[str]) -> ScanSummary:
        if not texts or len(texts) > MAX_TEXTS or any(not isinstance(text, str) for text in texts):
            raise ScanUnavailable("input_limit")
        payload = json.dumps({"texts": texts}, ensure_ascii=False).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ScanUnavailable("input_limit")
        request = Request(  # noqa: S310 - fixed local service allowlist, no redirects/proxies
            self._url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ScanUnavailable("response_limit")
            result = json.loads(body)
        except (URLError, TimeoutError, OSError):
            raise ScanUnavailable("service_unavailable") from None
        except (ValueError, UnicodeError):
            raise ScanUnavailable("invalid_response") from None
        if not isinstance(result, dict):
            raise ScanUnavailable("invalid_response")
        masked = result.get("masked_texts")
        placeholders = result.get("placeholders")
        data_types = result.get("triggered_data_types")
        if (
            not isinstance(masked, list)
            or len(masked) != len(texts)
            or any(not isinstance(text, str) for text in masked)
            or not isinstance(placeholders, list)
            or len(placeholders) > MAX_REQUEST_BYTES
            or any(not isinstance(item, dict) for item in placeholders)
            or not isinstance(data_types, list)
            or any(type(item) is not int or item not in range(1, 7) for item in data_types)
        ):
            raise ScanUnavailable("invalid_response")
        # /v1/scan includes original values. Deliberately discard all payload
        # fields except counts and numeric category IDs; no restoration state.
        return ScanSummary(
            len(texts), sum(before != after for before, after in zip(texts, masked, strict=True)),
            len(placeholders), tuple(sorted(set(data_types))),
        )
