# Reference architecture

## Purpose

This repository shows the minimum useful slice of a secure enterprise LLM platform without reproducing a real deployment. The demo is deliberately small enough to run locally while preserving the boundaries that matter in production.

## Request path

1. The API validates the question length, actor identifier, and metadata filters.
2. Retrieval applies exact metadata scope before ranking.
3. Query terms are expanded through a public synthetic glossary.
4. Hybrid ranking combines deterministic vector similarity and lexical overlap.
5. A reranked result is accepted only when it does not materially reduce query-term coverage.
6. Confidence below the configured threshold produces a grounded refusal.
7. Accepted context crosses the model-gateway boundary.
8. The response returns explicit source identifiers.

## Data flows

```mermaid
flowchart TB
    subgraph UserZone[User zone]
      User[API caller]
    end

    subgraph AppZone[Application plane]
      API[Validated API]
      Scope[Metadata scope]
      Rank[Hybrid rank + fallback]
      Gate[Confidence gate]
      Gateway[ModelGateway]
      Index[(Synthetic index)]
    end

    subgraph OpsZone[Operational telemetry]
      Runtime[(runtime.jsonl)]
      Fluent[Fluent Bit]
      Loki[Loki]
      Metrics[/metrics]
      Prometheus[Prometheus]
    end

    subgraph AuditZone[Restricted audit plane]
      Audit[(audit.jsonl)]
      FutureSIEM[Enterprise SIEM adapter]
    end

    User --> API --> Scope --> Rank --> Gate --> Gateway
    Scope --> Index
    API --> Runtime --> Fluent --> Loki
    API --> Metrics --> Prometheus
    API --> Audit
    Audit -. intentionally not implemented .-> FutureSIEM
```

## Separation guarantee

The operational event schema contains request ID, route, status, latency, retrieval count, and refusal state. It has no prompt or answer field. Fluent Bit mounts only the operational log volume.

Audit events go to another path and volume. By default they include a prompt hash and length, not prompt text. Setting `AUDIT_INCLUDE_PROMPT=true` is an explicit operator decision and does not change the operational schema.

This protects against accidental prompt leakage into general observability. It does not protect prompt data from a fully compromised application process or host administrator; see the security model.

## Production substitutions

| Reference component | Typical production substitution |
| --- | --- |
| deterministic vectorizer | approved local embedding endpoint |
| JSON index | ChromaDB, pgvector, Qdrant, or another controlled store |
| demo gateway | LiteLLM backed by approved local or compatible inference |
| JSONL audit spool | authenticated, encrypted SIEM transport |
| synthetic catalog | versioned enterprise content connector |

