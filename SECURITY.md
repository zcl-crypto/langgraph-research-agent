# Security Policy

## Supported version

Only the latest version on the `main` branch is supported.

## Reporting a vulnerability

Do not disclose vulnerabilities in a public issue. Contact the repository owner
privately through the contact method on the GitHub profile and include reproduction
steps, affected components, and expected impact.

## Deployment notice

This repository is a local portfolio project, not a hardened public research
service. Before exposing it to untrusted users:

- keep model and search credentials in a secret manager;
- add external authentication, TLS, per-user quotas, and distributed rate limits;
- run webpage retrieval in an isolated network sandbox;
- add DNS rebinding protection, robots.txt handling, monitoring, and audit storage;
- move long-running jobs to a persistent queue with cancellation and recovery.

Never commit `.env`, API keys, raw production prompts, or private research data.
