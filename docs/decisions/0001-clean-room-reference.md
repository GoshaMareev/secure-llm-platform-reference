# ADR 0001: Build a clean-room reference instead of publishing private repositories

- Status: accepted
- Date: 2026-09-07

## Context

The production systems contain deployment-specific configuration, operational material, and code whose publication boundary differs from a portfolio repository.

## Decision

Write a new implementation with a new Git history. Transfer general architectural decisions, not files, identifiers, data, metrics, or history from private repositories.

## Consequences

- the public project can be audited independently;
- examples and tests use explicitly synthetic data;
- production parity is not implied;
- useful production details must be explained as patterns or limitations rather than copied artifacts.

