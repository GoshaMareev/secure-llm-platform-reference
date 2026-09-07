# Security policy

## Scope

Security reports may cover the reference API, ingestion pipeline, gateway client, logging boundaries, container configuration, or publication-safety checks.

This project is a demonstration and is not offered as a hardened production distribution. The Compose example places OAuth2 Proxy in front of the API and uses Microsoft Entra ID OIDC; production deployments must still validate proxy headers, tenant/group policy, TLS, and ingress controls.

## Reporting

Please use GitHub's private vulnerability reporting feature for this repository. Do not open a public issue containing credentials, private data, or exploit details.

Include the affected revision, impact, prerequisites, and a minimal reproduction that uses only synthetic data.

## Supported version

Only the latest revision on `main` is supported.

## Publication safety

Never commit real prompts, logs, documents, access tokens, customer identifiers, internal endpoints, or production configuration. Treat every example as public data from the moment it enters Git history.
