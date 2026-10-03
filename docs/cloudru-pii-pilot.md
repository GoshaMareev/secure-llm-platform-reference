# Cloud.ru Russian PII and secret scan pilot

The native LiteLLM callback optionally calls the local
[guardrails-llm-filter](https://github.com/cloud-ru-tech/guardrails-llm-filter)
`POST /v1/scan` API in **shadow** mode. It measures detections remaining after the
mandatory Presidio checks. It does not replace Presidio, change an answer, block
on a scanner outage, or restore personal data from retrieved documents.

## Scope and data handling

- Input observations run after identity verification, signed RAG-context checks,
  media inspection and mandatory text sanitization. They cover the complete
  outgoing text prompt, including retrieved context, and embedding/rerank text.
- Output observations run on buffered final text after the mandatory output
  policy. Binary images, raw audio, tools and reasoning are outside this scan.
- The scanner runs without provider credentials, host ports or persistent
  volumes, on an internal network shared only with LiteLLM. Its proxy listener
  and gRPC management listener bind to container loopback; UI and audit storage
  are disabled. The REST management port is accessible only to the gateway.
- The image is pinned to `sha256:c2365b1c67de00d588192b2bf15b1911f482c13fcff6abcc54aabf14c54e3bf6`.
  It currently publishes amd64 only; ARM hosts need Docker emulation.
- The scan API returns masked text **and original values**. The adapter discards
  both and emits only aggregate counts and numeric data-type IDs. No mapping,
  prompt text, masked text or original value enters application metadata or logs.
- Each scan has a two-second socket timeout, no retries, a 128-text / 256 KiB
  request limit and a 1 MiB response limit. Four observations may run concurrently
  per gateway process. Overflow, errors and malformed responses are explicitly
  `unavailable`; inputs are never silently truncated.

The event is `cloudru_pii_shadow`, with `stage=input_context|output`,
`scope=after_presidio`, `policy_version=cloudru-shadow-v1`, `status`,
`text_count`, `changed_text_count`, `match_count` and `data_types`.
Unavailable scans carry only a bounded `reason` code. Events use the existing
request ID and private audit transport. The stage latency histogram uses
`stage=cloudru_pii_shadow`. An audit-write failure retains the existing fail-closed
audit policy; an optional scanner outage alone does not disable Presidio.

## Enable the local pilot

Complete the [native stack setup](openwebui.md) first. Append the scanner overlay
after the native stack overlay and retain any other overlays already in use:

```bash
docker compose --env-file .local/google-sso/compose.env \
  --env-file .local/full-stack/compose.env \
  -f infra/docker-compose.yml -f infra/docker-compose.google.yml \
  -f infra/docker-compose.openwebui.yml -f infra/docker-compose.cloudru.yml \
  --profile openwebui up -d cloudru-filter

# Recreate only the gateway; the existing Web UI/database stay running.
docker compose --env-file .local/google-sso/compose.env \
  --env-file .local/full-stack/compose.env \
  -f infra/docker-compose.yml -f infra/docker-compose.google.yml \
  -f infra/docker-compose.openwebui.yml -f infra/docker-compose.cloudru.yml \
  --profile openwebui up -d --no-deps --wait litellm
```

With the overlay, mode is fixed to `shadow`. Without it the callback defaults to
`off`; request metadata cannot override the mode or scanner URL. `enforce` is
rejected at startup. For rollback, recreate LiteLLM using the original overlay
set without `docker-compose.cloudru.yml`, then stop only `cloudru-filter`.
Do not remove stack volumes.

The optional scanner is not a startup health dependency: a missing scanner is
reported as unavailable while mandatory privacy checks continue.

## Reproduce checks without hosted inference

The expanded [64-case comparison and fault checks](verification/cloudru-pii-results.md)
retain all misses and false positives. The original 12-case format smoke remains
a separate, narrower contract check. The comparison measures annotated values
and observes residual detections after the configured Presidio policy.

```bash
.venv/bin/python -m unittest tests.test_cloudru_pii -v
.venv/bin/python scripts/verify_full_stack_config.py
.venv/bin/python scripts/test_full_stack_boundaries.py
.venv/bin/python -m unittest tests.test_cloudru_comparison -v

# Inside the running pilot gateway; test only the callbacks and local services.
# Mount the script by stdin: no provider call or real user identity is needed.
docker compose --env-file .local/google-sso/compose.env \
  --env-file .local/full-stack/compose.env \
  -f infra/docker-compose.yml -f infra/docker-compose.google.yml \
  -f infra/docker-compose.openwebui.yml -f infra/docker-compose.cloudru.yml \
  --profile openwebui exec -T litellm python - < scripts/smoke_cloudru_pii.py

# Direct scanner evaluation; the report contains aggregates, not sample text.
docker run --rm --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --network secure-llm-platform-reference_cloudru-scan \
  --mount "type=bind,src=$PWD,dst=/reference,readonly" \
  python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea \
  python /reference/evals/cloudru_pii.py > .local/cloudru-pii-pilot.json
```

For the expanded comparison, give the disposable runner access to both private
service networks. This calls only local scanners and writes aggregate results:

```bash
mkdir -p .local/cloudru-eval
docker run --rm --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --network secure-llm-platform-reference_cloudru-scan \
  --network secure-llm-platform-reference_platform \
  --mount "type=bind,src=$PWD,dst=/reference,readonly" \
  --mount "type=bind,src=$PWD/.local/cloudru-eval,dst=/reports" \
  python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea \
  python /reference/evals/cloudru_comparison.py --report /reports/comparison.json
```

The synthetic-only evaluation adapter reads original replacement spans to check
full-value coverage, then drops the text from its report. Runtime `scan()` still
returns aggregates only. The report contains fingerprints and case IDs; it never
contains original or masked input values. An unavailable scanner fails the run;
observed coverage misses remain explicitly listed rather than waived.

On 2026-10-04 the pinned scanner passed **12/12 fixed synthetic cases**: full,
declined and initial-form Russian names, Russian phone, internal email, SNILS,
passport, address, public test card, synthetic private key and two benign
questions. This checks the live API contract and selected formats. It does not
measure production recall, OCR quality, model quality or jailbreak resistance.
The callback regressions cover authorized sanitized input/output, unchanged
content, scanner outage, identity denial and rejection of enforcement mode.
The local pilot is enabled. All seven live callback checks passed against the
actual Presidio and scanner services without inference: input/output, embeddings,
rerank, scanner outage, concurrency capacity, input size and identity denial.
Aggregate success and unavailable events reached the private mTLS collector.
The offline suite completed 175 tests
(29 environment-dependent skips), and 27 native boundary tests ran in the
pinned LiteLLM/Open WebUI images. Audit contract checks reject original-value
fields and malformed scan counters/categories before durable storage.

Before enforcement, use a separately reviewed representative Russian corpus,
evaluate omissions and false positives per entity, measure additional latency,
and decide which detections justify blocking or irreversible redaction. A zero
residual count does not prove the original input contained no personal data.
