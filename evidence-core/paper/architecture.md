# Verifiable Evidence Packs for Cross-System Compliance Operations

**Author:** Akshay Jagadeesh
**Implementation:** Verifiable Evidence Core 0.1.0
**Status:** Technical preprint and reproducible reference implementation

## Abstract

Compliance evidence is commonly copied from identity, infrastructure, database, and delivery systems into screenshots and spreadsheets. That process loses lineage, obscures which control version applied at the time, and makes later tampering hard to detect. This paper specifies a dependency-light reference architecture that normalizes source events, correlates related activity with explainable rules, preserves directed lineage, binds evidence to time-valid control definitions, and freezes the result into a signed archive. The archive uses canonical JSON, SHA-256 content digests, a Merkle root, Ed25519 signatures, and an optional separately signed timestamp receipt. A deterministic synthetic-healthcare generator and benchmark measure throughput, query rate, pairwise correlation precision/recall, and verification cost without using patient information. The implementation proves integrity and provenance properties; it does not by itself establish legal admissibility, regulatory compliance, or the identity of an untrusted signer.

## 1. Problem and design goals

An evidence system should answer four questions after collection:

1. What exact bytes were reviewed?
2. Where did each item come from, and what was derived from it?
3. Which version of a control was in force when the event occurred?
4. Can another party detect later modification and verify the signer against a separately obtained trust anchor?

The design goals are deterministic encoding, source-neutral records, explainable correlation, time-aware controls, bidirectional lineage traversal, offline verification, bounded dependencies, and testable failure behavior. Non-goals include replacing a source system of record, asserting that an event is true merely because it is signed, hiding sensitive data, or operating as a qualified timestamp authority.

## 2. Canonical evidence model

Each immutable `EvidenceRecord` has an identifier, source, kind, observed and collected timestamps, payload, control references, parent references, document reference, and metadata. Canonical JSON sorts object keys, removes insignificant whitespace, emits UTC timestamps, rejects non-finite floats, and hashes the UTF-8 bytes with SHA-256. Normalization preserves the original source object in `payload`; common correlation fields live in metadata.

This separation prevents a connector from silently discarding source detail while still providing a stable cross-source query surface. It also permits new adapters without changing the pack format.

## 3. Explainable event correlation

The reference correlator compares events inside a configurable time window. It gives explicit weights to shared trace, session, workflow-run, identity, resource, and IP fields. Pairs above the threshold are joined into connected components. Every cluster exposes the signals used and the average pair score. This makes the result auditable and reproducible; it is not a probabilistic black box.

The method is intentionally conservative. Common identities or shared NAT addresses can create false positives, while absent trace context can create false negatives. Production deployments should tune thresholds on labeled organizational data, cap high-frequency identifiers, and measure drift. The benchmark therefore reports pair precision and recall against synthetic ground truth rather than presenting a generic “accuracy” claim.

## 4. Document and transformation lineage

Lineage is a directed acyclic graph. An edge records a parent, child, and relationship such as `derived_from`. Both ancestor and descendant traversal are supported with optional depth limits. A new edge is rejected if it would introduce a cycle. This represents raw export → normalized event → correlated finding → report or document while retaining reverse navigation from an output to all supporting inputs.

The graph proves declared relationships, not the truthfulness of an undisclosed transformation. Higher-assurance deployments should execute transformations in attested build environments and record tool version, configuration, and input digest on each derived object.

## 5. Control versioning

Controls are immutable versions with non-overlapping effective intervals. A snapshot resolves exactly one version of each referenced control at a specified instant. The version, requirements, effective range, metadata, and snapshot hash are included in the evidence pack. Consequently, a future control edit cannot silently change what an earlier pack claimed to test.

## 6. Cryptographically frozen evidence pack

### 6.1 Archive contents

An archive contains:

- one canonical JSON file per evidence record;
- one canonical JSON file per control version;
- `manifest.json`, listing paths and SHA-256 digests plus a Merkle root;
- `signature.json`, containing the Ed25519 signature, public key, and fingerprint; and
- optionally `timestamp.json`, a separately signed receipt over the manifest digest.

Entries use deterministic ZIP metadata. Verification rejects unsafe paths, duplicate paths, missing or undeclared files, non-canonical manifests, digest or Merkle mismatches, malformed signatures, untrusted signer keys, and invalid timestamp receipts.

### 6.2 Trust and timestamp semantics

A valid embedded signature proves only that the same private key signed the manifest. Signer identity is established only when the verifier supplies a public key acquired through an independent trusted channel. The built-in timestamp receipt is suitable for test and private authority deployments; public claims about existence at a time should use a qualified or otherwise independently trusted timestamp provider. RFC 8032 defines Ed25519, and RFC 3161 defines a widely used timestamp protocol. This version implements the former and a transparent signed-receipt abstraction for the latter integration point.

### 6.3 Threat model

Detected attacks include modifying, deleting, duplicating, or adding archive members; changing the manifest; substituting a signer when a trust anchor is provided; and modifying a signed timestamp receipt. Not prevented are compromise of the signing key, false data signed at collection, malicious source administrators, secrets inside payloads, denial of service, rollback to an older otherwise valid pack, and metadata leakage from unencrypted archives.

Recommended production controls are hardware-backed keys, key rotation and revocation, independent timestamping, least-privilege collectors, encryption outside this format, malware scanning, tenant separation, append-only pack registration, and dual control for export and deletion.

## 7. Source adapters

The reference normalizers cover Azure SQL audit rows, Microsoft Entra ID audit/sign-in exports, Azure Key Vault diagnostic logs, Kubernetes audit events, and GitHub Actions workflow runs. They accept already-authorized exports or API objects; they do not embed credentials. Azure SQL additionally supports a caller-provided PEP-249 connection. Production collectors should implement pagination, cursor checkpointing, retry with jitter, source-specific rate limits, schema drift monitoring, and least-privilege authentication outside the normalizer.

## 8. Synthetic healthcare reference

The generator creates fictional identities under `example.invalid`, documentation-range IP addresses, synthetic resources, and labeled cross-source incidents. It contains no patient identifiers, clinical records, or real organization data. The reference architecture shows how identity, vault, Kubernetes, CI/CD, and database audit events can support administrative safeguards without claiming HIPAA compliance. Any real healthcare deployment requires a risk assessment, business-associate analysis, data minimization, retention controls, incident procedures, and professional legal/security review.

## 9. Benchmark method

The benchmark fixes a random seed and records the synthetic incident/noise counts. It measures:

- generation and indexing records per second;
- deterministic indexed filter queries per second;
- correlation records per second;
- pairwise precision, recall, false-positive pairs, and false-negative pairs;
- evidence-pack creation and verification throughput; and
- archive size and verification status.

For publication, run at several scales, repeat each configuration, report median and tail latency, pin the Git commit, record CPU/RAM/OS/Python, and retain raw JSON. Cost and audit-hours-saved require an observed pilot. The output explicitly marks the manual comparison as model-only until a third party supplies a signed baseline. This avoids presenting modeled savings as empirical fact.

### 9.1 Initial author-run smoke result

An initial, non-independent run on macOS arm64 with CPython 3.12.14 processed 1,873 generated records. It measured 102,833 correlation records/second, 19,435 pack-creation records/second, 39,007 verification records/second, and 13,300 indexed filter queries/second. Pair precision and recall were both 1.0 on the deterministic fixture, with zero false-positive or false-negative pairs. The signed pack and trusted test timestamp verified successfully. These figures demonstrate the executable protocol and result schema only: the code was an uncommitted initial working tree, the dataset intentionally matches the reference correlation signals, and the run was not reproduced independently. The complete raw result and limitations are in `benchmark/results/author-smoke-2026-10-15.json`.

The benchmark also supports a transparent cost scenario with caller-supplied manual minutes, assisted minutes, reviewer hourly cost, and compute cost. Its output is always labeled modeled. Only pilot-observed inputs and supporting evidence can support an audit-hours-saved claim.

## 10. Reproducibility

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
evidence-core benchmark --output benchmark-result.json --incidents 250 --noise 1000 --seed 42
evidence-core generate-key --private signer.pem --public signer.pub.pem
evidence-core demo --output demo.evidence.zip --private-key signer.pem
evidence-core verify demo.evidence.zip --trusted-public-key signer.pub.pem
```

Private keys and generated packs may contain sensitive material and must not be committed. Reproducibility concerns the algorithm and synthetic dataset, not equality of wall-clock timings across hardware.

## 11. Limitations and future work

Current limitations include an in-memory reference index, quadratic worst-case correlation within dense windows, no source-side collectors or OAuth flows, no encrypted pack profile, no key revocation registry, no RFC 3161 client, no transparency log, and no independent audit. Planned work includes streaming correlation, pluggable durable storage, OpenTelemetry context, in-toto attestations, external timestamp providers, policy-as-code validation, differential privacy for aggregate metrics, and a blinded human baseline study.

## 12. Responsible claims

The project can claim that the released implementation detects the tested tampering cases and that published benchmark runs produced their attached raw results. It should not claim regulatory certification, legal admissibility, independent adoption, hours saved, external review, or competitive superiority without corresponding third-party evidence.

## References

1. S. Josefsson and I. Liusvaara, “Edwards-Curve Digital Signature Algorithm (EdDSA),” RFC 8032, 2017.
2. C. Adams et al., “Internet X.509 Public Key Infrastructure Time-Stamp Protocol (TSP),” RFC 3161, 2001.
3. National Institute of Standards and Technology, “Secure Hash Standard,” FIPS PUB 180-4.
4. in-toto project, “A framework to secure the integrity of software supply chains.”
