# Security review scope and disposition

The security-diff-scan reviewed immutable `0f47fa2..1b03896`, with independent architecture,
audit/delivery and identity/privacy passes and a completed plugin report. Two low-severity
availability/bounding findings were confirmed: the native chat alias omitted WebUI admission,
and native background work could outlive the admitted ASGI request. Neither finding
established an authorization or gateway PII bypass. The local authenticated synthetic threat
model excludes a public interactive backend, privileged host administrators and real clients.

The supplemental immutable `1b03896..4aa3909` review inspected all 16 changed files. Both
aliases are now bounded, multi-model fanout is denied, native child tasks are owned/joined,
and repeated cancellation retains bounded workers until cleanup finishes. Regression tests
cover buffered background completion, deadline cleanup and repeated cancellation. A real
isolated native lifecycle probe complements source/unit evidence.

The supplemental `4aa3909..a62acc4` review inspected all ten changed files, including
operator-gated RU media, metrics scraping and private verification tools. It confirmed
closure of colon/equal-labelled multiword credential tails. It also caught a test-evidence
bug: generic OSError/HTTP400 could falsely count as wrong-certificate rejection. The test
now sends a valid synthetic event, requires a certificate-specific SSL alert and performs
a successful authorized control plus deduplication check. The original collector already
required client certificates; no collector authentication bypass was established.

Residual limitations are published: pattern/recognition recall, conservative false blocks,
unsupported secret forms, RU NER false positives, imperfect source/language fidelity, shadow
classifier misses, trust in private ingress networks and administrator mutability. Native
HTTP task IDs arrive after processing; the adapter is for the pinned no-Redis deployment.
Adding Redis requires ownership across the upstream helper's persistence await. Source
review is not a promise of safe behavior under untested deployments or independent
penetration testing. No runtime or acceptance threshold was changed using holdout results.

Final supplemental `a62acc4..5ddb270` reviewed all four operator verification files and
confirmed certificate-proof closure with no additional actionable security findings. Actual
TLS alert was `TLSV1_ALERT_UNKNOWN_CA`; authorized control200, durable replay and one stored row.
Storage permission, bilingual11 and native lifecycle evidence remain bounded fixture tests,
not actual host-disk exhaustion, language recall or WebSocket/Stop-action verification.

The sole operator probe in `5ddb270..2e48da0` was also reviewed: private paths, fixed loopback
route, bounded WAV, metadata-only output and scoped assertions; no actionable finding.
The public capacity report adds the retained WAV hash.

Final API extractor review `375c2a7..07754aa` identified a partial-answer hole: generic
masked-prefix removal could omit substantive imperatives. Closure was confirmed across both
files in `07754aa..2421193`: complete recognized contact/card grammar only, with EN/RU budget
refusal regressions. No scope/PII bypass or new actionable issue was found. This change affects
the independent extractive API only; native/media/audit measurements keep their original source.
