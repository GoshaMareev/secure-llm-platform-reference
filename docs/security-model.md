# Security model

## Protected assets

- prompts, answers, retrieved context, and user identity;
- integrity of metadata scope and citations;
- model credentials and provider routing;
- operational availability and audit completeness;
- separation between general telemetry and restricted audit data.

## Trust boundaries

| Boundary | Untrusted input | Enforced control |
| --- | --- | --- |
| caller → API | question, actor ID, metadata filters | size limits and typed request schema |
| API → retrieval | filter keys and values | exact metadata matching before ranking |
| retrieval → gateway | question and selected context | confidence gate and fixed operator configuration |
| application → operations | runtime event | schema omits prompt and answer fields |
| application → audit | audit event | separate path, volume, schema, and opt-in raw prompt |
| operator → model endpoint | base URL and credential | environment-only configuration; URL validation |

## Primary attacker stories

### Cross-scope retrieval

An authenticated caller attempts to retrieve documents for another audience or system. The reference applies metadata filters before scoring, so excluded chunks cannot be recovered through ranking.

Production deployments must derive allowed filters from authenticated identity and policy. This demo accepts filters from the caller and therefore demonstrates retrieval behavior, not authorization.

### Prompt leakage through logs

A maintainer with ordinary observability access attempts to recover prompt text. The operational schema never accepts prompt or answer fields, and Fluent Bit cannot mount the audit volume.

### Arbitrary model routing

A caller attempts to provide a model URL or credential. The API schema has no such fields. Gateway configuration is loaded only from the operator environment.

### Unsupported answer

A question has weak retrieval support. The confidence gate returns a refusal before model generation.

## Explicit limitations

- no authentication or authorization service is included;
- metadata filters are caller-provided in the demo;
- the deterministic vectorizer is for offline verification, not semantic quality;
- audit transport to SIEM is documented but intentionally not implemented;
- local JSONL files are not a tamper-evident audit store;
- no PII classifier, DLP service, malware scanner, or prompt-injection classifier is bundled;
- Docker Compose demonstrates boundaries but is not a production orchestrator.

## Secure production requirements

Before production use, add identity-derived authorization, encrypted audit transport, credential management, retention controls, rate limits, integrity-protected audit storage, dependency scanning, signed images, and deployment-specific threat modeling.

