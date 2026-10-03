# Portfolio implementation ledger

Historical 1.0.0 evidence and rejected trials are retained. Private synthetic traces, identities,
provider keys, certificates and physical speech fixtures stay in `.local`. Acceptance thresholds
remain those in the approved plan; infrastructure/policy-service failures are not abstentions.

| Stage | Delivered evidence | Result / limit |
|---|---|---|
| Baseline / evaluator | baseline-causes, baseline-environment, adversarial evaluator regressions | All 12 offline failures and one native failure explained; phrase evaluator limits disclosed |
| RAG quality | three native core runs, expanded run, offline core, source-based holdout review | 3×32/32; 125/128; holdout30/32; offline32/32; independent human review remains outstanding |
| Corpus | immutable manifests/snapshots; native lifecycle scenario | 1.0.0→1.1.0→1.0.0, interrupt/retry/hash/stale-model checks pass; glossary-only facts unchanged |
| Fault / load | isolated fault/load, actual file failures/cancellation, lifecycle probes | c4 p95<5 s; 14,916-request soak; no observed ownership/privacy failures; end resource snapshot only |
| EN/RU / media / Jev | pinned RU artifacts; bilingual11; natural64; native8; frozen Jev128 | Accepted media64/64; portable RU stress benign75% rejected; Jev six dev misses/two FP, shadow only |
| Audit delivery | durable v2 spool, mTLS collector/shipper/checkpoint, outage/replay/TLS tests | Recovery delivers all20 rotated events; replay no duplicates; host-admin tamper resistance excluded |
| SBOM / review | 13 CycloneDX inventories, artifact hashes, notices, immutable diff reviews | 33,970 component instances; 32,586 license entries unconfirmed; no universal redistribution/security claim |
| Video / site | 160-second safe evidence replay, captions/transcript, linked static case | Local desktop/mobile/keyboard/playback QA passed; production release status lives in the site PR/deployment |

Protocol deviations: an early offline smoke evaluated all128 before group filtering existed;
aggregate results ran, but no holdout case outcomes were used for tuning. Subsequent tuning used
core/development only. Holdout answers were reviewed against authorized sources by Codex, not an
independent human. Seven RU holdout answers use English; placeholder/citation limitations are
retained. Natural-voice media fixtures were safety-debugging evidence, not independent holdout.
The public video replays verified synthetic observations and is not a live session recording.

Excluded scope remains public interactive backend, real clients, enterprise Entra/SIEM,
faces/biometrics, arbitrary media privacy, on-prem inference sizing and privileged history tampering.
