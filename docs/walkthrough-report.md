# Synthetic HTTP walkthrough

Run `make walkthrough` to regenerate this report. No external model or Entra account is needed.

The loopback test server simulates trusted proxy subjects. This verifies authorization and API behavior; it does not verify Entra token validation or the live proxy. The offline gateway extracts source sentences.

| Scenario | Identity | HTTP | Refused | Blocked | Sources |
|---|---|---|---|---|---|
| Grounded answer | `engineer-demo` | 200 | False | False | access-control, on-call-roster, incident-response |
| Unknown topic | `engineer-demo` | 200 | True | False | none |
| Reader without filters | `reader-demo` | 200 | True | False | none |
| Filter escalation denied | `reader-demo` | 200 | True | True | none |
| Injection blocked | `engineer-demo` | 200 | True | True | none |

## Grounded response

```json
{
  "request_id": "00000000-0000-4000-8000-000000000001",
  "answer": "According to Production access policy: Emergency break-glass access requires approval from the incident commander and one platform owner.",
  "confidence": 0.718,
  "refused": false,
  "blocked": false,
  "policy_verdicts": [
    "context_pii_redacted"
  ],
  "citations": [
    {
      "source_id": "access-control",
      "title": "Production access policy",
      "path": "documents/access-control.md"
    },
    {
      "source_id": "on-call-roster",
      "title": "Platform on-call roster",
      "path": "documents/on-call-roster.md"
    },
    {
      "source_id": "incident-response",
      "title": "AI service incident response",
      "path": "documents/incident-response.md"
    }
  ]
}
```

## Correlated operational and audit events

IDs and timestamps below are normalized for display; runtime correlation is verified first. Operational events contain metadata only. Audit events add keyed hashes and source IDs. Raw prompts are disabled; SIEM transport and tamper-evident storage remain roadmap items.

Operational event:

```json
{
  "timestamp": "2026-10-02T00:00:00+00:00",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "route": "/v1/ask",
  "status_code": 200,
  "latency_ms": "measured at runtime",
  "retrieved_chunks": 3,
  "refused": false,
  "policy_verdicts": [
    "context_pii_redacted"
  ]
}
```

Audit event:

```json
{
  "schema_version": 1,
  "timestamp": "2026-10-02T00:00:00+00:00",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "actor_pseudonym": "341a66ee6b931f54f139718f7b50d428cf45b071aaf9f357168cf41243ccf18f",
  "prompt_sha256": "305c0c0cc6a72b6f6b4331e4475cc9bba0e3fc950f1d22b500e63c57a1749bf3",
  "prompt_characters": 44,
  "confidence": 0.718,
  "source_ids": [
    "access-control",
    "on-call-roster",
    "incident-response"
  ],
  "refused": false,
  "policy_verdicts": [
    "context_pii_redacted"
  ]
}
```
