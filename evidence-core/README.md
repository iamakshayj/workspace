# Verifiable Evidence Core

An open, vendor-neutral core for collecting normalized compliance evidence, correlating security events, preserving document lineage, resolving the control version that applied at the time of an event, and exporting cryptographically verifiable evidence packs.

The project is intentionally separate from the commercial workspace application. It contains no tenant data, product credentials, proprietary model, or private deployment code.

## What is implemented

- Canonical evidence records with deterministic hashes.
- Time-aware, versioned control registry.
- Directed document and evidence lineage with cycle detection and multi-hop traversal.
- Explainable event correlation using identity, resource, session, trace, and time-window signals.
- Ed25519-signed evidence-pack manifests.
- Independently signed timestamp receipts and trust-key pinning.
- Full pack verification, undeclared-file detection, path-safety checks, and tamper detection.
- Normalizers for Azure SQL, Entra ID, Azure Key Vault, Kubernetes audit logs, and GitHub Actions.
- Synthetic healthcare reference data that contains no real patient information.
- Reproducible performance and accuracy benchmark.
- Append-only, hash-chained impact metrics ledger.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest

evidence-core generate-key --private signer.pem --public signer.pub.pem
evidence-core demo --output demo.evidence.zip --private-key signer.pem
evidence-core verify demo.evidence.zip --trusted-public-key signer.pub.pem
evidence-core normalize --source kubernetes --input kubernetes-audit.jsonl --output normalized.jsonl
evidence-core benchmark --output benchmark-result.json --incidents 250 --noise 1000 --seed 42
evidence-core ledger-add impact.jsonl --metric evidence_records_processed --value 1000 --source published-benchmark --evidence-url https://example.invalid/result
evidence-core ledger-verify impact.jsonl
```

The demo uses explicitly synthetic identities and resources. Never place secrets, raw access tokens, protected health information, or production database rows in a public benchmark.

## Evidence-pack trust model

An evidence pack contains canonical evidence and control snapshots, a manifest containing every file hash and a Merkle root, a detached Ed25519 signature, and—when configured—a separately signed timestamp receipt. Verification fails for modified, missing, duplicated, unsafe, or undeclared content.

The built-in timestamp authority is suitable for integration testing and private authorities. Public claims of independent timestamping require a genuinely independent timestamp service and preserved service receipts.

## Project status

Version 0.1 is an auditable reference implementation. Cloud normalizers accept exported/API response objects so the core has no cloud credential dependency. Production collectors should authenticate through workload identity and pass source objects to these normalizers.

See [SECURITY.md](SECURITY.md), [GOVERNANCE.md](GOVERNANCE.md), and the [technical paper](paper/architecture.md).
