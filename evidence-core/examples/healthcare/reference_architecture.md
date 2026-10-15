# Synthetic healthcare reference architecture

This example demonstrates evidence processing for a fictional healthcare software company. It uses no patient or production data and is not a compliance certification.

## Scenario

A release to a fictional clinical scheduling service is reviewed from identity through database access:

```text
Entra sign-in ─┐
Key Vault read ├─ trace/session correlation ─ finding ─ control snapshot ─ signed evidence pack
Kubernetes API ┤                         │
GitHub Actions ┤                         └─ bidirectional lineage
Azure SQL audit┘
```

The reference generator emits only:

- `example.invalid` identities;
- RFC 5737 documentation IP addresses;
- fictional service and resource names;
- synthetic control labels; and
- explicit `synthetic: true` metadata.

## Deployment boundary

Run collectors in a dedicated evidence account with read-only, source-scoped credentials. Send normalized events to a tenant-isolated queue. Store immutable raw exports separately from the query index. Keep signing keys in HSM/KMS custody. Register every completed pack digest in an append-only log and send its digest to an independent timestamp provider.

## Validation checklist

- Confirm source permissions expose only required audit fields.
- Document the lawful purpose and retention period for identity metadata.
- Redact or tokenize unnecessary personal data before packing.
- Test tenant isolation and restore procedures.
- Rotate and revoke collector and signing credentials.
- Verify packs from a separate environment with an out-of-band public key.
- Have privacy, security, compliance, and legal owners approve production use.

Generate a test dataset with `evidence_core.synthetic.healthcare_dataset`. The benchmark uses the same deterministic generator and hidden incident labels.
