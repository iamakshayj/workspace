# ADR 0002: Ed25519 signatures and explicit trust anchors

Status: accepted

Sign the canonical manifest with Ed25519 and embed the public key for self-contained integrity checking. Treat the embedded key as untrusted unless the verifier supplies an independently acquired public key. Keep timestamp authority trust separate from producer trust. This avoids conflating valid mathematics with verified identity.
