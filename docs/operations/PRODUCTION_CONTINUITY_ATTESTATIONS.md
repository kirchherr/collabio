# Production Continuity Attestations

## Purpose

`production_continuity_deployment_gate.v2` authenticates operator evidence instead of relying on a self-hash alone.
A self-hash detects accidental corruption but can be recomputed by anyone who can replace a report. The v2 gate
therefore requires a canonical in-toto Statement v1 in a DSSE v1 envelope with three Ed25519 signatures.

The signed statement binds:

- the SHA-256 digest of `production_continuity_deployment_evidence.v1` as the immutable in-toto subject;
- the production deployment reference hash;
- the complete `backup_failover_policy.v4` hash and schema version;
- the hashed change, security and operations approval principals;
- the attestation issue time and the metadata-only/no-secrets contract.

References:

- in-toto Statement v1: <https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md>
- in-toto DSSE envelope guidance: <https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md>
- DSSE v1 specification: <https://github.com/secure-systems-lab/dsse>
- NIST FIPS 186-5 digital signatures and EdDSA: <https://csrc.nist.gov/pubs/fips/186-5/final>
- PyCA Ed25519 verification API: <https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ed25519/>

## Trust Boundary

The suite verifies signatures only. It contains no production signing endpoint, private-key model, key generator or
private-key persistence path. Each accountable function signs outside the Suite through its approved workstation,
HSM or KMS workflow.

`production_continuity_signer_policy.v1` is a separate deployment-controlled JSON document. It contains public keys,
SHA-256 key IDs, hashed principal references, one role per key, validity windows and revocation state. It must be
mounted read-only and independently from the evidence. Do not put private keys, certificates containing unnecessary
identity data, credentials or provider tokens in this policy.

The current threshold is exactly one valid signature for each role:

1. `change`
2. `security`
3. `operations`

The three key IDs and three principal hashes must be distinct. Every key ID is the SHA-256 digest of the 32-byte raw
Ed25519 public key. Unknown, expired, future-valid, revoked, duplicated or role-mismatched keys fail closed.

## Verification

The verifier accepts only:

- canonical JSON with no unknown fields;
- payload type `application/vnd.in-toto+json`;
- predicate type `https://collabio.eu/attestation/production-continuity/v1`;
- one named evidence subject with a lowercase SHA-256 digest;
- canonical base64 and a maximum decoded payload size of 64 KiB;
- exactly three DSSE signatures using trusted Ed25519 public keys;
- an issue time inside the evidence-age and signer-validity windows.

The gate embeds the metadata-only DSSE envelope and signer-policy hash in its own report. Runtime admission repeats
cryptographic verification against the independently mounted current signer policy. Recomputing `gate_hash`, copying
an attestation from another deployment, substituting evidence or removing a key from the trust policy cannot open the
runtime.

## Operator Flow

1. Produce and review the hash-only evidence bundle outside the repository.
2. Build the canonical in-toto Statement from the final evidence digest, deployment reference, policy hash and
   approval-principal hashes.
3. Let the change, security and operations functions sign the identical DSSE pre-authentication encoding through
   their independent approved key boundaries.
4. Assemble the three signatures into one DSSE JSON envelope.
5. Review the deployment-controlled public signer policy and its revocation state.
6. Mount evidence, envelope and signer policy read-only into the no-network gate container.
7. Publish a ready report only when the container exits successfully; retain all external approval and signing audit
   evidence according to policy.

```bash
docker compose --profile production-continuity run --rm \
  -v /secure/operator-evidence/production-continuity.json:/evidence/production-continuity.json:ro \
  -v /secure/operator-evidence/production-continuity.dsse.json:/evidence/production-continuity.dsse.json:ro \
  -v /secure/operator-trust/production-continuity-signers.json:/trust/production-continuity-signers.json:ro \
  production-continuity-deployment-gate
```

The API runtime additionally needs the same trust policy at the path configured by
`SUITE_PRODUCTION_CONTINUITY_SIGNER_POLICY_PATH`. Missing or unreadable policy configuration is not a warning; it is
an invalid gate state.

## Rotation And Revocation

Add a replacement public key with an overlapping validity period before retiring an old key. New evidence is signed
with the replacement key and produces a new report bound to the updated signer-policy hash. Revoke a compromised key
immediately and invalidate every report that references the previous policy. Because the runtime re-verifies against
the current policy, a revoked key closes admission even if the old report and its self-hash remain unchanged.

Emergency recovery never weakens the threshold. It requires new evidence and three signatures from valid keys; there
is no bypass flag.
