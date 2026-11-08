# Provenance notice

This repository is a clean-room reference implementation written for public portfolio use.

It intentionally excludes:

- source code copied from customer or employer repositories;
- customer names, brands, documents, prompts, logs, screenshots, and metrics;
- internal domains, IP addresses, registry locations, tenant identifiers, and network topology;
- production credentials, certificates, environment files, and CI/CD variables;
- proprietary detection rules, business rules, and deployment runbooks.

The design demonstrates general engineering patterns learned while building private systems: model-gateway boundaries, metadata-aware retrieval, grounded refusal, evaluation, operational telemetry, and a separate audit plane. Names, sample documents, events, identifiers, and results in this repository are fictional.

Contributors must run `python scripts/pre_publication_check.py` before committing and must independently confirm that they have the right to contribute every source file.

