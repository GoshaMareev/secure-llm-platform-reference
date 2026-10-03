# ADR 0005: Native Open WebUI RAG and one model gateway

Status: accepted for the portfolio reference.

## Decision

Use native Open WebUI Knowledge, groups, file permissions and pgvector retrieval
for the primary demonstration. Route chat, image/audio/video input, embeddings
and reranking through LiteLLM to OpenRouter. Keep provider credentials only at
the gateway. Keep the original RAG API as an independent deterministic control
reference and evaluation harness.

The UI must not choose provider URLs or grant its own document scope. Operator
model configuration attaches private Knowledge collections. Two normal users
receive different groups; a separate operator provisions the demo. Model and
document authorization remain enforced by native API handlers.

Use a mandatory native filter around retrieval and a mandatory gateway callback
around inference. Bind authenticated user identity with a signed JWT. Require
the filter's signed context for every chat request, including plain chat aliases,
so direct OpenAI proxy endpoints cannot skip the policy path. Buffer final text
to finish output checks before sending it to the UI. Preserve separate metadata
only operational and audit events with a common request ID.

## Consequences

This adds real semantic embeddings/reranking and a familiar enterprise UI without
maintaining a second custom retrieval implementation. The native RAG path has
its own live checks; the deterministic API's evaluation figures are not reused
as evidence of hosted model quality.

The pinned version needs a narrow compatibility shim for verified rerank users,
fail-closed remote reranking, replacement of old context and buffered citation
events. Tests run in pinned images without credentials or network. Upgrade the
pin only after repeating these regressions and the two-account walkthrough.

Presidio handles text redaction. English pattern rules are transparent controls
with documented limitations. A trained classifier can be evaluated later.
OpenRouter Guardrails may add model/provider allowlists and budgets, but its
input-only PII checks and timeout behavior do not replace mandatory local
input/context/output policy. Guardrails AI is optional when a specific validator
is justified; adding another framework does not itself improve coverage.

See [OpenRouter Guardrails](https://openrouter.ai/docs/guides/features/guardrails/overview)
and [its sensitive-information checks](https://openrouter.ai/docs/guides/features/guardrails/sensitive-info).
