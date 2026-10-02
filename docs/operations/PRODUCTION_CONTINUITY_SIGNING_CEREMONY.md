# Production Continuity Offline Signing Ceremony

## Boundary

The ceremony turns a reviewed `production_continuity_deployment_evidence.v1` bundle into the DSSE envelope required
by `production_continuity_deployment_gate.v2`. It has two operations only:

- `prepare` emits canonical bytes for three external signers;
- `assemble` accepts three detached responses, verifies every signature, and emits the DSSE envelope.

There is deliberately no `sign`, key-generation, private-key, HSM-session, KMS-credential, provider-token, network or
API operation. Never mount private keys, HSM sockets, provider credentials or cloud identity tokens into the ceremony
container. Each accountable function signs through its independently approved external boundary.

Both operations run in a read-only, capability-free, no-network Compose service. Input files are mounted read-only.
Output files are created with mode `0600` and existing files are never overwritten.

## Prepare

Choose exactly one current public key for each role from the independently controlled
`production_continuity_signer_policy.v1`. Supply the three SHA-256 key IDs explicitly:

```bash
docker compose --profile production-continuity run --rm \
  -v /secure/operator-evidence/production-continuity.json:/inputs/evidence.json:ro \
  -v /secure/operator-trust/production-continuity-signers.json:/inputs/signers.json:ro \
  -v /secure/operator-ceremony/request-output:/output \
  production-continuity-attestation-ceremony prepare \
  --policy /workspace/docs/operations/backup_failover_policy.json \
  --evidence /inputs/evidence.json \
  --signer-policy /inputs/signers.json \
  --key-id sha256:CHANGE_KEY_ID \
  --key-id sha256:SECURITY_KEY_ID \
  --key-id sha256:OPERATIONS_KEY_ID \
  --output /output/production-continuity-signing-request.json
```

`production_continuity_attestation_signing_request.v1` binds the exact evidence, deployment, backup policy, signer
policy, approval-principal hashes, issue and expiry times, canonical in-toto payload, and DSSE pre-authentication
encoding. Assignments are normalized to `change`, `security`, `operations`; CLI key order grants no role.

The command rejects stale or future-dated evidence, cross-deployment evidence, unknown or repeated keys, revoked or
inactive keys, principal mismatches, missing roles, oversized input, and an existing output path. It performs no
signature creation and reports `private_key_ingestion_allowed=false`.

## External Signatures

Each accountable function receives the same immutable request through the approved transfer channel and independently
checks at least:

1. `request_hash` against the approved change record;
2. evidence, deployment, policy and validity hashes;
3. its assigned role, key ID and hashed principal;
4. the human-readable evidence held in the external approval system;
5. that the signing system receives only the base64-decoded `pre_authentication_encoding_base64` bytes.

The external HSM, KMS or workstation returns one strict JSON document. No provider credentials or private material are
included:

```json
{
  "request_hash": "sha256:REQUEST_HASH",
  "role": "change",
  "key_id": "sha256:CHANGE_KEY_ID",
  "signature_base64": "BASE64_ED25519_SIGNATURE",
  "algorithm": "ed25519",
  "content_included": false,
  "secrets_included": false,
  "private_key_included": false,
  "schema_version": "production_continuity_external_signature_response.v1"
}
```

Security and operations return separate documents with their own assigned role and key ID. A copied response, changed
request hash, role substitution, unknown key or malformed signature is invalid.

## Assemble

Mount the immutable request and all three responses read-only. Use a separate empty output directory:

```bash
docker compose --profile production-continuity run --rm \
  -v /secure/operator-evidence/production-continuity.json:/inputs/evidence.json:ro \
  -v /secure/operator-trust/production-continuity-signers.json:/inputs/signers.json:ro \
  -v /secure/operator-ceremony/approved-request.json:/inputs/request.json:ro \
  -v /secure/operator-ceremony/change-signature.json:/inputs/change-signature.json:ro \
  -v /secure/operator-ceremony/security-signature.json:/inputs/security-signature.json:ro \
  -v /secure/operator-ceremony/operations-signature.json:/inputs/operations-signature.json:ro \
  -v /secure/operator-ceremony/envelope-output:/output \
  production-continuity-attestation-ceremony assemble \
  --policy /workspace/docs/operations/backup_failover_policy.json \
  --evidence /inputs/evidence.json \
  --signer-policy /inputs/signers.json \
  --request /inputs/request.json \
  --signature /inputs/change-signature.json \
  --signature /inputs/security-signature.json \
  --signature /inputs/operations-signature.json \
  --output /output/production-continuity.dsse.json
```

Assembly reconstructs the request from the current evidence and policies, checks its hash and validity window, binds
every response to its assignment, and cryptographically verifies all three Ed25519 signatures before writing. Failure
produces only a metadata-only error receipt and no envelope.

## Gate And Retention

The resulting envelope is still not a deployment approval by itself. Run the separate no-network deployment gate with
the same evidence and signer policy. The runtime then repeats verification against the current trust policy.

Retain the signing request, three external signing audit records, three detached responses, final envelope, gate report,
change record and signer-policy version according to the production evidence retention policy. Revoke compromised keys
in the independently deployed trust policy; there is no threshold bypass or emergency signing shortcut.
