# Reference architecture

## Purpose

This repository shows the minimum useful slice of a secure enterprise LLM platform without reproducing a real deployment. The demo is deliberately small enough to run locally while preserving the boundaries that matter in production.

## Request path

1. In Compose, OAuth2 Proxy authenticates the caller with Microsoft Entra ID and forwards a trusted user header.
2. The API validates the question, authenticated actor header, and bounded metadata filters.
3. The input guardrail blocks injection attempts and redacts personal data.
4. Retrieval applies exact metadata scope before ranking.
5. Query terms are expanded through a public synthetic glossary.
6. Hybrid ranking combines deterministic vector similarity and lexical overlap.
7. A reranked result is accepted only when it does not materially reduce query-term coverage.
8. The context guardrail quarantines retrieved chunks that contain instructions or exfiltration requests.
9. Confidence below the configured threshold, computed on the remaining context, produces a grounded refusal.
10. Accepted context crosses the model-gateway boundary.
11. The output guardrail blocks prompt echo and relayed instructions and redacts personal data.
12. The response returns explicit source identifiers and the policy verdicts that fired.

## Data flows

```mermaid
flowchart TB
    subgraph UserZone[User zone]
      User[Enterprise user]
    end

    subgraph AppZone[Application plane]
      API[Validated API]
      Auth[OAuth2 Proxy + Entra ID]
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

    User --> Auth --> API --> Scope --> Rank --> Gate --> Gateway
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
