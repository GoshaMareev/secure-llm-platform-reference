# Semantic guardrail observations

The optional native layer calls a decision model **inside the existing LiteLLM gateway**. It evaluates
the redacted user question, scoped and screened RAG passages, and the buffered, redacted final answer.
It records observations only. A decision cannot grant document access, skip Presidio, approve a tool,
or change an answer. The deterministic API remains independent of hosted inference.

## Providers checked on 2026-10-03

| Candidate | Verified availability | Integration here |
|---|---|---|
| TypeSafe Jev | OpenRouter's decisions catalog lists `typesafe/jev-1.13` and the latest alias. A real SystemOne request succeeded. | Native shadow checks and live synthetic evaluation; use the version selector, reject unreviewed resolved-model drift. |
| Cloudflare Clef / Clef-flash | Official Workers AI endpoints and model cards exist. Neither appeared among the 10 models in the OpenRouter decisions catalog when checked. | Text-only Workers AI evaluation adapter, protocol-tested offline. No Cloudflare credentials supplied; no hosted Clef measurement. |
| OpenAI Decisions API | No entry found in the public official API documentation index or official-domain searches during this check. This does not rule out a private preview. | No speculative endpoint or model adapter. Connect after an accessible official schema and credentials are available. |

Primary sources: [OpenRouter Jev](https://openrouter.ai/docs/guides/community/jev),
[decision catalog](https://openrouter.ai/api/v1/models?output_modalities=decisions),
[Clef REST schema](https://developers.cloudflare.com/workers-ai/models/clef/),
[Clef-flash REST schema](https://developers.cloudflare.com/workers-ai/models/clef-flash/),
[Clef-flash model card](https://huggingface.co/Cloudflare/clef-flash),
[OpenAI public documentation index](https://developers.openai.com/api/docs/llms.txt).

The runtime requests `typesafe/jev-1.13` at `POST https://openrouter.ai/api/v1/systemone`. The measured
resolved model is `typesafe/jev-1.13-20260917`. Both exact identifiers are allowed; other returned models
produce `model_drift` rather than an apparent successful observation. The model selector is not a chat
model alias, and users cannot change it through their requests. Jev Router is a different product.

## Policy and boundaries

`semantic-shadow-1` has separate typed `noul` questions for attempted instruction override, requests for
secrets/private documents, injection in each passage, passage relevance, unsafe output and unsupported
answer claims. Questions and the experimental risk threshold **0.80** have a SHA-256 fingerprint.
Relevance is diagnostic and never produces `would_block`. Factual support is evaluated only when actual
authorized passages are present; an ungrounded chat does not get an invented support score.

The native filter binds the decision state and all non-system messages into its server-signed policy
token. Open WebUI adds the operator's system prompt after request filters, so the gateway screens system
messages independently. A modified signed state or conversation is rejected before either model call.
Client-supplied decision context is overwritten by the native filter. The gateway consumes the private
field before chat-provider routing and redacts its text again before the classifier call.

No provider key leaves the gateway. No decision endpoint is exposed to browser users. Events contain
request ID, actor hash, corpus version/manifest, policy fingerprint, model, numeric scores, `would_block`,
latency and reported cost. They contain no query, passage, answer, rationale or credentials. Runtime and
audit receive separate copies. Provider response bodies and network exceptions are never logged.

The client uses fixed HTTPS endpoints, refuses redirects, makes no retries, caps responses at 64 KiB,
and validates exact question IDs, answer types and finite probabilities in `[0,1]`. State is limited to
48,000 UTF-8 bytes and six passages. Oversized state is explicitly unavailable rather than silently
truncated. Four concurrent classifier calls are allowed; capacity exhaustion skips an observation.
The socket timeout is four seconds per call. This synchronous shadow layer adds latency before generation
and before delivering the complete answer. Each request normally makes two classifier calls.

Missing signed state, provider failure, malformed scores, model drift and limits produce an explicit
unavailable observation with `would_block: null`. They do not become approvals. In shadow mode they do
not affect the existing response. Presidio and access-control failures still block as before. Raw state
is retained only in a bounded in-memory map for output verification, removed on completion/failure,
and evicted on subsequent requests after a two-minute TTL.

## Enable or disable native observations

The public Compose default is `off`. Set `REFERENCE_DECISION_MODE=shadow` in the private full-stack
Compose environment file and recreate LiteLLM using the existing overlay command in
[the native walkthrough](openwebui.md). Run the operator bootstrap to install the current global filter.
Set the same variable to `off` and recreate LiteLLM to disable hosted decision calls. No mode switch is
available to regular users. `enforce` is deliberately unsupported until thresholds and failure behavior
are evaluated on a broader, representative dataset.

```bash
docker exec secure-llm-platform-reference-open-webui-1 \
  python /reference/verify-decisions.py --live
```

This smoke test uses both enrolled scopes and forged client state, checks the two observation stages,
server-selected provenance and the allowed telemetry fields. It does not expose identity information.

## Evaluation

The separate [32-case dataset](../evals/decision-cases.json) has English/Russian examples of direct and
indirect attacks, legitimate policy questions, quoted attack descriptions, infected/relevant/irrelevant
passages, supported answers, fabricated/contradictory answers and safe refusals. Its development and
holdout cases were assigned before inference. The risk threshold was fixed beforehand and has not been
tuned on these results. This is a small exploratory check, not proof of production robustness.

```bash
make decision-check PYTHON=.venv/bin/python  # validate fixtures; no inference

PYTHONPATH=.:apps/rag-assistant .venv/bin/python -m evals.decisions \
  --live --key-file .local/openrouter/api-key --report .local/decision-evaluation.json

# Optional Cloudflare evaluation with credentials supplied only to the operator process:
PYTHONPATH=.:apps/rag-assistant .venv/bin/python -m evals.decisions \
  --live --provider cloudflare --model clef-flash --report .local/decision-clef-flash.json
```

For Cloudflare, provide `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AUTH_TOKEN` to that operator process.
Use `--model clef` for the larger model. These credentials are not mounted into Open WebUI or included
in public Compose. Image/audio inspection is outside this implementation, despite Clef's media support.

Reports retain dataset/policy hashes, the corpus release, resolved models, per-question scores, confusion
counts, false-negative/false-positive rates, Brier score, latency and cost. Accuracy excludes unavailable
judgments and reports their count separately. The pattern-only baseline measures corresponding regex
checks; it does not represent the whole platform's ACL/PII protections. Pattern checks cannot assess
factual support, so their unsupported-answer predictions are always false.

See the [measured Jev results](decision-evaluation-jev.md) and [full JSON](decision-evaluation-jev.json).
CI validates fixtures and offline protocol/metric tests without hosted calls. Live model evaluation remains
an explicit operator action. Decision models themselves can be influenced by adversarial state; see
[TypeSafe's published limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
