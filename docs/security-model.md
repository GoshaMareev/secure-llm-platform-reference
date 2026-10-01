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
| user → OAuth2 Proxy | Entra ID authorization response | OIDC token validation, tenant issuer, optional allowed group |
| OAuth2 Proxy → API | forwarded identity headers | Compose keeps API off the host and API requires `X-Forwarded-User` |
| caller → API | question, actor ID, metadata filters | size limits, typed request schema, injection block, PII redaction |
| API → retrieval | filter keys and values | server-owned audience authorization, then exact narrowing filters before ranking |
| retrieval → gateway | question and selected context | context quarantine, confidence gate and fixed operator configuration |
| gateway → caller | model answer | prompt-echo and relayed-instruction block, PII redaction |
| application → operations | runtime event | schema omits prompt and answer fields |
| application → audit | audit event | separate path, volume, schema, and opt-in raw prompt |
| operator → model endpoint | base URL and credential | environment-only configuration; URL validation |
| gateway → model | prompts from every application | LiteLLM Presidio `pre_call` masking, SSN block; `post_call` masking of responses |

## Primary attacker stories

### Cross-scope retrieval

An authenticated caller attempts to retrieve documents for another audience or system. The reference applies metadata filters before scoring, so excluded chunks cannot be recovered through ranking.

Direct local mode uses a fixed operator-selected identity and ignores caller identity claims. Protected Compose mode requires the subject forwarded by OAuth2 Proxy and resolves it through the operator-owned identity policy. Unknown subjects receive HTTP 403; documents without an allowed audience are excluded before ranking. Caller filters only narrow this scope and cannot grant access. The default policy contains two fictional subjects; real Entra subject mapping must be provided by the operator.

The API is unpublished and forwarded-header trust relies on controlled backend networks. A compromised container with backend connectivity can spoof those headers; production deployments must enforce proxy provenance or validate a signed token at the API. The loopback walkthrough simulates the trusted proxy and does not verify Entra login.

### Prompt leakage through logs

A maintainer with ordinary observability access attempts to recover prompt text. The operational schema never accepts prompt or answer fields, and Fluent Bit cannot mount the audit volume.

### Arbitrary model routing

A caller attempts to provide a model URL or credential. The API schema has no such fields. Gateway configuration is loaded only from the operator environment.

### Direct prompt injection

A caller asks the assistant to ignore its rules, reveal its system prompt, or switch persona, possibly with zero-width or full-width characters. The input checkpoint normalizes the text and blocks the request before retrieval, so the refusal reveals nothing about the corpus.

### Indirect prompt injection

An external document in the corpus contains instructions addressed to the model or the reader, such as a fake `SYSTEM:` line asking users to send their API token. The synthetic `vendor-integration-notes` document plays this role. Retrieved chunks that match injection or exfiltration rules are quarantined before generation and are not cited.

### Personal data in prompts and answers

A caller pastes names, contact or payment details, or a retrieved document contains them. Two layers call the same Presidio services. The RAG API replaces names, e-mail addresses, phone numbers, validated card numbers, IBANs, US SSNs and IP addresses with typed placeholders before retrieval, in all outgoing context/citation fields, and in the answer. The LiteLLM gateway masks the same entities in every prompt before it reaches a model and in every response, for all applications behind it. If Presidio is unavailable, requests are blocked rather than passed unchecked. The regex fallback covers e-mail, card and phone only.

### Unsupported answer

A question has weak retrieval support. The confidence gate returns a refusal before model generation.

## Explicit limitations

- direct local mode has no authentication; Compose includes the OAuth2 Proxy/Entra ID boundary;
- filters are caller-provided narrowing constraints; document audiences are granted only by server-owned identity policy;
- the deterministic vectorizer is for offline verification, not semantic quality;
- audit transport to SIEM is documented but intentionally not implemented;
- local JSONL files are not a tamper-evident audit store;
- injection guardrails are English-only pattern rules (ADR 0004): they cover common phrasings and obfuscations and are bypassable by paraphrase or other languages; no trained prompt-injection classifier or malware scanner is bundled;
- PII redaction is English-only; its recall depends on the configured spaCy model, and the regex fallback misses names entirely;
- Docker Compose demonstrates boundaries but is not a production orchestrator.

## Secure production requirements

Before production use, validate real identity claims and proxy provenance, add encrypted audit transport, credential management, retention controls, rate limits, integrity-protected audit storage, dependency scanning, signed images, and deployment-specific threat modeling.
