# GenOffice Internal OSS Admission

## Purpose

This gate replaces the unavailable external legal review for the isolated development candidate. It records an internal
Open Source compliance and risk decision. It does not claim legal advice or production clearance.

The immutable input remains the ADR-0065 dossier
`sha256:eb523d13b0cb10fea752c4e0d549a9c06f2736e4f3f38721bb7b0ba948614c5a`.

## Usage Profiles

| Profile | Internal decision effect |
| --- | --- |
| `development_evaluation` | May permit exact build-context materialization and a reproducible isolated worker build. |
| `hosted_service` | Blocked. Requires a separate product and deployment decision. |
| `on_prem_distribution` | Blocked. Requires a separate distribution review. |
| `production` | Blocked. Requires image, security, fidelity, recovery and production admission. |

Tenant content, source import into the Collabio product tree, engine execution and service activation remain blocked in
all outputs of this gate.

## Deterministic Notice

`genoffice-third-party-notice-builder` runs without a network and reads archives without filesystem extraction. It
produces:

- `GENOFFICE_THIRD_PARTY_NOTICES.txt`;
- `genoffice-third-party-notice-report.json`.

The artifact contains the pinned Apache-2.0 LICENSE and NOTICE, the vendored EMF converter license and the required legal
texts for all 21 runtime dependencies. It records MIT as the selected `jszip` distribution option and both MIT and Zlib
for `pako`. Enterprise terms are evidence of exclusion and are not copied into the distributable notice.

## Internal Decision

The generated `genoffice_internal_oss_decision_envelope.v2` schema requires:

- the exact dossier, notice-report and notice-artifact hashes;
- the exact allowed and prohibited source scopes;
- Collabio-only branding and explicit Apache-2.0, NOTICE and patent-term acknowledgements;
- all 21 dependency resolutions;
- the risk-acceptance and change-control references;
- complete reevaluation triggers;
- detached Ed25519 approvals by two different people in the roles `product_owner` and
  `security_compliance_owner`.

The separate signer policy binds signer IDs, roles, key IDs and public keys. Its hash is part of the signed decision
payload, so replacing the policy after request creation invalidates the ceremony. The verifier accesses cryptography
only through the Suite KMS adapter. The repository contains schemas, never private keys and never invented human
approvals.

## Signing Ceremony

The ceremony has four fail-closed stages:

1. Two real internal people supply their identities, key IDs and raw 32-byte Ed25519 public keys. The policy builder
   requires one `product_owner` and one `security_compliance_owner`, distinct people and distinct keys.
2. The request builder binds that policy hash, the immutable dossier and NOTICE evidence, all accepted obligations and
   blocked profiles into one canonical message. Request v2 assigns the exact signer ID, role and key ID, expires after
   at most 72 hours and explicitly records `admission_effective=false`, `private_key_ingestion_allowed=false` and
   `signature_creation_performed=false`.
3. Each signer reviews and signs the exact `genoffice-internal-oss-signature-message.json` bytes on a separate approved
   workstation or KMS. The signer returns a strict metadata-only JSON response containing the request hash, message
   hash, assigned identity, role, key ID and the base64-encoded raw 64-byte detached signature.
4. The no-network assembler reads the request, public policy and two structured responses, rejects expired, replayed,
   cross-request or reassigned responses, verifies both signatures through the Suite KMS adapter and writes the
   decision envelope. It cannot read or generate a signing key.

Policy, request, canonical message and envelope outputs use mode `0600` and are write-once. Existing outputs or stale
temporary files stop the ceremony instead of being overwritten.

The resulting envelope is still not a production approval. The separate admission verifier must validate the complete
legal-evidence chain before the development worker-build permission can become effective.

## Runbook

After the standard `dev001` preflight and with `build.lock` before `docker.lock`:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-third-party-notice-builder

docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-schema
```

After the two accountable people and their approved public keys are available, set their non-secret IDs and the two
public-key host paths, then create the policy:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-signer-policy-builder
```

Set the decision ID, UTC preparation, proposed-decision and expiration timestamps, risk-acceptance reference and
immutable Git change-control reference, then create the policy-bound request. The expiration must be after preparation
and no more than 72 hours later:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-signing-request
```

Distribute the request and canonical signature-message file to both signers. Each external signer must return this
strict response shape without content, secrets or private key material:

```json
{
  "algorithm": "ed25519",
  "content_included": false,
  "key_id": "ASSIGNED_KEY_ID",
  "private_key_included": false,
  "request_hash": "sha256:REQUEST_HASH",
  "schema_version": "genoffice_internal_oss_external_signature_response.v1",
  "secrets_included": false,
  "signature_base64": "BASE64_RAW_64_BYTE_ED25519_SIGNATURE",
  "signature_message_sha256": "sha256:SIGNATURE_MESSAGE_HASH",
  "signer_id": "ASSIGNED_SIGNER_ID",
  "signer_role": "product_owner"
}
```

The second response uses role `security_compliance_owner` and its independently assigned identity and key. After both
response files have been installed at the configured read-only host paths, assemble and verify the envelope, then run
admission:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-envelope-assembler

docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-admission
```

Every stage exits `2` for missing, malformed, expired, same-person, unauthorized, replayed, cross-request, drifted or
invalidly signed evidence.
A green admission report opens only the development worker-build gate.

The next boundary is `genoffice-development-build-context`. It revalidates this report together with source,
supply-chain, npm-provenance and NOTICE evidence before producing the normalized TAR described in ADR-0067. It still
does not install dependencies or build an image.

The evidence set to back up together is the signer policy, signing request, exact signature-message bytes, both
structured external signature responses, assembled decision envelope and admission report. Public keys and signatures
are evidence; signing keys are never copied into Collabio backup storage. Source archive and public-key/signature file
mounts use `create_host_path: false`, so a missing file cannot silently become a root-owned directory.

## Verified Evidence Snapshot

The reproducible 2026-08-11 run on `dev001` produced:

- 23-component, 27-file `GENOFFICE_THIRD_PARTY_NOTICES.txt`:
  `sha256:e6dada57493fc5161dc4c5364f36feab11298fc887f5253eb1f03b3920239162`;
- notice report: `sha256:878e93a174a9deeae9c137a0229210c45dd636c9763cda9d430d42e6ad07fdc7`;
- policy-bound v2 decision-envelope schema:
  `sha256:e81f267d3e1eb5f06da724c59346cb4cbb06a8ace5dd6a6c46e16195568904fe`;
- signer-policy schema: `sha256:c5eb255d880075ed408bfe48d73e09156c58f31ee146ebc37e47c499ff700ed3`.

A second independent builder execution produced the identical notice bytes. No decision envelope, signer policy or
admission report is committed because no human identity, public key or approval has been supplied. A meaningful signing
request is intentionally not fabricated without its real public signer policy. The development worker build therefore
remains correctly blocked.

## Alternatives

Collabora remains the preferred later WOPI candidate for full collaboration, but its official terms distinguish source
and executable forms. ONLYOFFICE Community Edition uses AGPLv3 with additional terms. Neither removes the need for a
deliberate compliance decision. ECMA-376 plus the MIT-licensed Open XML SDK remains the independent long-term format
manipulation path; the SDK is a low-level document API rather than a ready browser office suite.
