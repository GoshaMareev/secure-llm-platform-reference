# ADR 0002: Separate operational telemetry from prompt audit

- Status: accepted
- Date: 2026-09-07

## Context

General operational logs are broadly accessible and optimized for reliability troubleshooting. Prompt data has a narrower audience, stricter retention, and different security controls.

## Decision

Use separate schemas, files, Docker volumes, and consumers. The operational event type cannot represent a prompt or answer. Raw prompt inclusion in audit events is disabled by default.

## Consequences

- accidental prompt disclosure through the logging pipeline is less likely;
- audit delivery and operational telemetry can fail independently;
- production deployments still require authenticated transport and tamper-resistant storage.

