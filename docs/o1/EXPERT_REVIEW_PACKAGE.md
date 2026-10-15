# Independent expert review package

Send the reviewer the tagged source release, paper, benchmark protocol and raw results, threat model, and a sample pack/public verification key. Do not supply a prewritten endorsement.

## Review questions

1. Are the canonicalization and signature boundaries unambiguous?
2. Does verification fail closed for modified, missing, duplicate, unsafe, or undeclared entries?
3. Are signer trust and timestamp trust represented accurately?
4. Are correlation metrics suitable, and where would false matches arise?
5. Does control versioning preserve the historical claim?
6. Can lineage be independently reconstructed?
7. Are benchmark claims reproducible and appropriately limited?
8. What would block production use in a regulated environment?
9. Which parts, if any, are technically original or practically significant?

Ask for a dated review in the reviewer’s own words, relevant credentials, methodology, disclosed relationship/conflicts, tested version, and permission to publish. Preserve critical reviews and remediation; credible disagreement is more valuable than manufactured praise.

## Request message

I am requesting an independent technical review of a small open-source evidence-integrity core. The review focuses on cryptographic boundaries, lineage, time-versioned controls, correlation methodology, and benchmark reproducibility. I will provide the exact release, raw results, and a review rubric. There is no expectation of a positive conclusion, and I will not publish your name or comments without written permission. Are you available to review it, or can you suggest an appropriate specialist?
