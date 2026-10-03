# Versioned portfolio verification

Historical 1.0.0 reports remain in their original locations. Candidate evidence is
kept under `docs/verification`; synthetic raw answers, OCR/STT and operator state
are restricted to `.local`. Report acceptance is independent of whether a script
completed. Transport, capacity, policy-service and audit errors are never credited
as successful answers or grounded abstentions.

## Reproduce without provider keys

```sh
python3 scripts/verification_environment.py
docker compose -p portfolio-verification --env-file .local/verification/compose.env \
  -f infra/docker-compose.yml -f infra/docker-compose.google.yml \
  -f infra/docker-compose.openwebui.yml -f infra/docker-compose.verification.yml \
  --profile openwebui up -d --wait litellm open-webui
python3 scripts/verify_fault_load.py --report .local/verification/load-new.json
```

The fresh project has separate PostgreSQL, WebUI database, logs, audit spool and
synthetic identities. Only operator loopback ports 4089/8089 are published. The
control bridge permits host access; model URLs are fixed to `test-model` and no
paid credential is present. Fault controls are read from an operator-mounted file,
not request parameters. Stop it with the same Compose arguments and `down --volumes`.

Run `scripts/verify_corpus_lifecycle.py` inside this WebUI (copy the script into its
writable data directory). It creates 1.0.0, interrupts the 1.1.0 upload, retries,
checks stale metadata, verifies changed-byte rejection and rolls back. Retired
collections have no user grants but their bytes remain available to the operator.

```sh
python3 scripts/verify_frozen_suites.py
python3 -m unittest discover -s tests
python3 scripts/test_full_stack_boundaries.py
python3 scripts/test_media_boundaries.py
python3 scripts/test_expanded_media.py --output .local/media-espeak-new
```

The portable eSpeak fixture generator is a deliberately difficult ASR stress set.
A separately versioned fixture set uses the installed macOS Milena voice for RU
and eSpeak for EN: add `--russian-voice milena`. It requires macOS `say` and ffmpeg
at the documented Homebrew path. Physical hashes and generation platform are
recorded before inference. The fixed questions, labels and thresholds are shared;
recognition quality and privacy are reported independently. Generated Milena
speech stays private and is not redistributed in the public video.

## Native boundaries and request lifecycle

Gateway chat capacity is four with immediate HTTP 429; media inspection has one
active job. Responses are buffered until output checks and durable audit finish.
Text/media response deadlines are 60/120 seconds. Cancellation joins bounded
blocking work before freeing its slot: sockets remain limited by their stage
timeouts. Policy codes come from server request context, never upstream error
strings. Errors expose a generic message, stable code and request ID. No identity,
request ID or text appears in metric labels. `/reference/metrics` and
`/reference/health` remain operator-only on unpublished native services.

EN is always analyzed; Cyrillic text additionally requires RU analysis. Pure
Cyrillic PERSON spans from English NER are ignored in favor of the mandatory
Russian pipeline. Mixed spans are merged before masking. Language is an internal
choice and cannot disable checks. Russian media remains gated by the operator
flag until the frozen candidate suite passes; uncertain sensitive speech blocks.
Cleaned OCR/STT can be observed by Jev as untrusted input, never as RAG evidence.
Jev is shadow only, with separately reported unavailable decisions and cost.

## Audit contract

Native v2 events contain UUID event/request IDs and component, with a strict
metadata allowlist. Gateway and WebUI have independent active files. Writes are
fsynced before successful response release. Segments rotate at 10 MiB; the spool
is limited to 100 MiB. Only sealed, fully acknowledged segments older than seven
days can be removed. Unacknowledged events remain; full/failed audit denies new
successes. Historical v1 events remain readable locally but are not shipped.

```sh
python3 scripts/audit_certificates.py
# Add infra/docker-compose.audit.yml and --profile audit-delivery to native Compose.
python3 scripts/verify_audit_delivery.py --report .local/audit-delivery-new.json
```

The private HTTPS collector requires client certificates, commits SQLite with
FULL durability before acknowledgement, and deduplicates by event ID. Checkpoint
state uses another volume. Shipper has read-only spool access; Loki has none.
Operational write failures increment metrics and degrade health without replacing
the original request result. Administrative history tampering is out of scope.

## Hosted budget and measurements

`run_hosted_verification.py` reserves $1 from the remaining $5 total before each
native run, monitors spend and terminates its owned worker near the run cap.
`run_decision_benchmark.py` performs a budget check before each shadow call.
Provider keys stay in `.local` and gateway/operator tooling, never WebUI.
CI uses no paid provider. Accepted native reports require three complete core
runs, the frozen expanded suite and source review of all 32 holdout answers.

## Delivery inventory

Syft 1.54.0 CycloneDX JSON inventories and `licenses.csv` enumerate pinned images.
The application inventory explicitly supplements `.lock` packages that Syft's
directory cataloger did not recognize. Unknown license evidence is marked
`UNCONFIRMED`; an SBOM is not a vulnerability scan or a redistribution approval.
Model/language-pack artifact notices accompany the final evidence index.
