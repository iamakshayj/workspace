# Security Policy

## Supported version

The latest minor release receives security fixes. Version 0.1 is a reference implementation and must be independently reviewed before use as a system of record.

## Reporting

Do not open a public issue for an undisclosed vulnerability. Send a minimal report to the repository owner's private security contact, including affected version, reproduction, impact, and suggested embargo. A public advisory and credit will be published after remediation unless the reporter requests anonymity.

## Security properties

- Evidence payloads are hashed using SHA-256 over canonical JSON.
- Packs are signed with Ed25519.
- Verification can pin an expected signer fingerprint.
- Archive paths, duplicates, missing files, undeclared files, record hashes, Merkle roots, signatures, and timestamp receipts are verified.
- Private keys are never embedded in packs.

## Non-goals

The core does not provide key custody, user authentication, authorization, malware scanning, regulatory certification, or a public timestamp authority. Production deployments must supply those controls.
