# Security and data-governance operating guide

The application now has repository-backed controls for tenant isolation, centralized authorization, field rules, guest restrictions, permission-filtered AI/search, DLP, classification, retention policy records, legal holds, audit integrity, residency routing, encrypted connector credentials, key references, and scoped service tokens.

## Administrator workflow

Use **Admin → Access policy** to create or simulate deny/allow rules. Explicit deny wins over base workspace and project roles. Rules can target a user, workspace role, reusable group, resource type or ID, fields, classifications, source types, and attributes.

Use **Admin → Data governance** for DLP, classification, retention, residency, legal holds, and encryption-key inventory. DLP returns metadata-only findings; matched secrets are neither returned nor written to audit details. Legal holds prevent supported destructive project/document cleanup and background artifact or stale-upload removal; maintenance reports how many records it preserved. A locked entity is served only by the matching deployment region, and an enforced residency policy cannot exclude that active region.

Use **Admin → Compliance evidence** to inspect implemented controls and download a permissioned NDJSON audit feed. Evidence clearly distinguishes repository implementation from operational assurance.

## Required production controls

- Store application, SMTP, model, database, storage, metrics, and internal API secrets in a managed secret store and rotate them.
- Terminate TLS at the ingress, enable HSTS, private networking, WAF/rate controls, database encryption, object versioning, and encrypted backups.
- Restrict metrics, internal provisioning, database, Redis, object storage, model inference, and malware scanner to private networks.
- Run retention deletion as a reviewed job that calls the shared legal-hold check before deletion. Record deletion manifests and approvals.
- Register customer-managed key references only after the external KMS identity and decrypt/encrypt probe succeeds in staging.
- Treat DLP patterns as a baseline. Add organization-specific identifiers and validate false-positive/false-negative rates with sanitized corpora.

## Operationally pending

The code does not claim penetration testing, SOC 2, ISO 27001, HIPAA, FedRAMP, external KMS validation, or production data residency. Those gates require deployed infrastructure, documented organizational processes, and independent evidence.
