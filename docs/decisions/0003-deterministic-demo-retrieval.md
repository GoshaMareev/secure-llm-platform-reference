# ADR 0003: Use deterministic offline retrieval for the public demo

- Status: accepted
- Date: 2026-09-07

## Context

A portfolio reference should run without customer data, API credentials, hosted model calls, or an implicit model download.

## Decision

Use a transparent hashing vectorizer plus lexical overlap for the default demo. Keep the model gateway and future embedding backend replaceable.

## Consequences

- CI and local tests are deterministic and offline;
- the code demonstrates retrieval controls and evaluation plumbing;
- the included quality figures must not be presented as production semantic-search performance.

