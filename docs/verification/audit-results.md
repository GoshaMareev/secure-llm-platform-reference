# Durable local audit delivery

Native schema v2 identifies component, UUID event ID and request ID, with a strict bounded
metadata allowlist. Gateway/WebUI have separate active audit and operational files.
Prompts, responses, OCR/STT text, emails and credentials are excluded. Historical v1
records remain locally readable; the native shipper does not export their raw fields.

Audit append uses file and directory fsync before success; write/fsync failure blocks new
successful responses. Segments rotate at 10 MiB; spool capacity is 100 MiB. Only sealed,
fully acknowledged segments older than seven days can be removed. Unacknowledged events
remain, so exhaustion denies new successes. Operational logging failure degrades health
and metrics without replacing the original request outcome.

The local collector uses HTTPS TLS 1.2+, mandatory client certificates and SQLite WAL/FULL
commit before ACK. Shipper uses a fixed private endpoint, read-only spool and separately
persisted atomic checkpoints, retries and event-ID deduplication. Certificates/keys are
created in `.local`; the CA private key is not mounted. Loki has no audit-volume access.

| Exercise | Evidence |
|---|---|
| Collector outage, 20 committed events, rotation, recovery | [delivery report](audit-delivery-final.json) |
| Lost checkpoint, shipper restart and replay without duplicate rows | [delivery report](audit-delivery-final.json) |
| Missing client certificate | [delivery report](audit-delivery-final.json) |
| Wrong-CA certificate, certificate-specific TLS rejection plus valid positive control | [TLS report](audit-tls-final.json) |
| Discarded ACK body then identical retransmission, one durable row | [TLS report](audit-tls-final.json) |
| Fsync failure, spool capacity, event collision and rotation/inode changes | native audit/delivery unit regressions |

The video correlates one actual local request across both operational and audit components,
and verifies delivery of its event IDs in collector storage. Public alias `DEMO-01` replaces
the request ID; actual identifiers and event captures remain private.

This is a local transport demonstration of a future SIEM contract. Enterprise ingestion,
PKI renewal/operations, privileged-administrator history tampering and production retention
compliance have not been established. File-mode failures and quota exhaustion are isolated
integration probes; injected ENOSPC/fsync errors are unit evidence, not a full host disk test.
