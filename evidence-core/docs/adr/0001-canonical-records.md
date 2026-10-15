# ADR 0001: Canonical JSON records

Status: accepted

Use a narrow JSON-compatible model and deterministic UTF-8 encoding before hashing. This favors portable verification and auditable fixtures over preserving language-specific object types. Binary evidence should be stored as separately hashed files in a future format revision, not silently encoded inside payload JSON.
