# ADR-0075: GenOffice DOCX Fidelity Result Signing Ceremony

- Status: Accepted
- Date: 2026-08-13
- Scope: Synthetic Office Quick Edit fidelity result provenance
- Supersedes: none
- Extends: ADR-0072, ADR-0073, ADR-0074

## Context

ADR-0074 deliberately leaves each LibreOffice result unsigned. ADR-0072 accepts only an engine-specific Ed25519
envelope, and ADR-0073 verifies evidence only after that envelope has been authenticated. Importing a private key into
the worker, the Suite repository, Docker or `dev001` would collapse the separation between evidence production and
attestation.

## Decision

Collabio adds a private-key-free, no-network ceremony with four explicit operations:

1. Build one public signer policy containing exactly one active, purpose-specific key for Microsoft Word,
   LibreOffice and GenOffice in canonical engine order.
2. Validate one completed result against the immutable study plan and create a request valid for at most 72 hours.
3. Receive one externally generated detached Ed25519 response bound to the request hash, canonical message hash,
   engine, signer and key.
4. Verify the detached signature and assemble the existing ADR-0072 signed-result envelope write-once.

There is no key generator or signing operation in the ceremony. Private keys, DPAPI ciphertext, HSM sessions, KMS
credentials and provider tokens are prohibited from all Compose mounts. Public keys, requests, canonical messages,
detached responses, policies and envelopes are recoverable evidence.

The three engine identities are provenance domains, not human approval roles. During solo development one accountable
operator may custody three independently generated, purpose-separated keys outside Collabio. This does not establish
three-person or two-person control. A later production policy may move each key to an independent runner identity,
HSM or accountable function without changing the signed-result envelope contract.

Assembly revalidates the study plan, payload hash, assignment, policy hash, signer assignment, request validity,
message bytes and signature. It cannot mark referenced evidence as byte-verified. ADR-0073 remains a separate,
engine-free pass over the read-only evidence bundle.

## Consequences

- A compromised or malformed runner cannot silently self-sign its output.
- Key material can rotate per engine without changing evidence or result schemas.
- A valid signature proves origin and integrity of the result payload, not Office compatibility.
- Evidence verification, cross-engine completion, visual calibration, human review, tenant content and productive saves
  remain separate gates.
- Backup scope includes public trust material and detached signatures while excluding all private-key representations.

## Rejected Alternatives

- Giving the LibreOffice worker a signing key: evidence generation and attestation would share one compromise domain.
- Reusing the GenOffice founder admission key: it has a different purpose and authorization scope.
- Signing only a file hash without a request: signer, engine, policy, study plan and validity would not be bound.
- Treating three keys as three people: cryptographic separation does not prove organizational separation.

