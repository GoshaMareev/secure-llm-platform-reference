# Security model

## Native Open WebUI profile

The primary native profile adds its own boundary. Google authenticates both
normal users; an explicit enrollment assigns General to both and Engineering
only to the engineer. Private native Knowledge/file/vector handlers enforce
read permissions even when callers supply IDs directly. Operator RAG models fix
their Knowledge scope, so caller collection/mode changes cannot broaden it.

Open WebUI has no public backend port or provider key. The proxy strips caller
identity headers. A global filter binds verified identity to external reranking,
requires successful reranking, quarantines unsafe text and replaces the original
unscreened context. Only screened citations are emitted to the browser.
LiteLLM verifies a server-signed user JWT and requires signed filter context for
chat; lower-level proxy routes cannot skip the policy. Native proxy auth rejects
caller credentials/provider URLs before routing. Buffered final text passes
PII, prompt-echo and exfiltration checks before release; reasoning, annotations,
tool/media outputs are not exposed.

Operational and audit events in this profile contain verdicts and request IDs,
with salted actor hashes only in audit. Neither stream stores prompts, answers,
emails or tokens. Both services can write both volumes: this prevents ordinary
observability leakage, not a compromised application or host administrator.
Native audit v2 is delivered to a private local HTTPS collector with mTLS, durable acknowledgement and event-ID deduplication. This demonstrates a future SIEM contract, not an enterprise SIEM integration. Operational records remain separate; Loki cannot mount audit storage.
Ingress header trust also assumes the internal application network is trusted:
a compromised peer container could impersonate a user at Open WebUI's trusted
header endpoint. A hosted production design must enforce proxy provenance,
separate backend connectivity or use native verified OIDC at that boundary.

Embedding background work may use the internal gateway credential without a
user JWT; it grants no chat or document access. Text PII masking precedes
embedding/rerank provider calls. Inline images/audio are checked at the gateway
by a private CPU-only OCR/STT service without provider credentials or internet
access. Sensitive OCR text blocks the image; metadata is stripped from allowed
pixels. Audio is replaced by a locally transcribed, PII-redacted text part.
Recognition/PII failures deny the request. Remote URLs and video are rejected.
See [media policy, evaluation and limits](media-guardrails.md): this covers
recognized EN/RU text/speech under the operator-gated media policy, not faces, biometrics or all hidden visual text.
Native document or chat state can retain original
synthetic source text; model/citation redaction does not mean deletion from the
authorized document store. Remote-model quality and pattern-rule bypasses remain
limitations. See [ADR 0005](decisions/0005-native-openwebui-rag.md) and
[native checks](full-stack-validation.md).

The media inspector accepts only a bounded inline payload from the internal
platform network. It has no host port, no secrets, a read-only filesystem, a
temporary-memory OCR workspace, CPU/memory/process limits and one active task.
Only public model/package downloads occur during image build. Extracted text and
recordings are transient and never enter operational/audit events. Gateway
events carry media policy version, kind, redacted entity kinds and ASR revision.
OCR/STT confidence thresholds do not prove that all sensitive content was found.

The following sections describe the independent API control reference.

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
- enterprise SIEM integration is not implemented; the native profile includes local mTLS audit delivery;
- local JSONL files are not a tamper-evident audit store;
- deterministic EN/RU injection patterns cover fixed tests and can miss paraphrases; Jev is a supplemental shadow classifier, not an authorization boundary or malware scanner;
- Presidio requires EN/RU span union for Cyrillic input; recall and false positives depend on the pinned small NLP pipelines. The offline regex fallback misses names. Unknown multiword secret forms and ASR substitutions remain limitations;
- Docker Compose demonstrates boundaries but is not a production orchestrator.

## Secure production requirements

Before production use, validate real identity claims and proxy provenance, add encrypted audit transport, credential management, retention controls, rate limits, integrity-protected audit storage, dependency scanning, signed images, and deployment-specific threat modeling.

## Native request lifecycle

Both native chat aliases enforce capacity. A single model is accepted per request. Registered native background children are joined before response flushing or capacity release; disconnect and deadline cleanup joins them. Gateway chat capacity is four, with immediate 429 and no unbounded waiting queue. Text/media deadlines are 60/120 seconds. Blocking workers retain their slot until their bounded socket timeout completes. The adapter targets the pinned deployment without Redis. Native task IDs now reach the caller after processing: asynchronous cancellation UX must be assessed before adopting this adapter in other deployments.

Audit writes are acknowledged on local disk before success. Full/failed spool denies new successes; operational logging failures degrade health and metrics without replacing the original answer. Audit history can be changed by a privileged host administrator. See [security review](verification/security-review.md), [audit evidence](verification/audit-results.md), and [fault/load evidence](verification/load-results.md).
