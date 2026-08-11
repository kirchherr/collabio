# GenOffice Solo-Founder Development Exception

## Purpose

This workflow is the temporary compensating control for a one-person Collabio organization. It records one founder's
cryptographic risk acceptance and may open only deterministic GenOffice development build-context materialization. It
does not claim two-person control, legal approval, source import, document processing or production readiness.

The preferred `GENOFFICE_INTERNAL_OSS_ADMISSION.md` ceremony remains mandatory before runtime, pilot, Hosted Service,
On-Prem distribution or production. The exception expires after at most 30 days and cannot be extended in place.

## Exact Boundary

The signed payload contains these compensating controls:

- pinned public evidence chain;
- dedicated founder Ed25519 risk acceptance;
- private write-once exception evidence;
- maximum 30-day validity;
- development build-context only;
- no-network materialization;
- no tenant content;
- two-person reauthorization before runtime.

The report always records `two_person_control_verified=false`. Source import, engine execution, tenant content, Hosted
Service, On-Prem distribution and production use remain false. A changed public evidence hash, signer policy, assigned
identity, key, request, message, validity window or response stops verification.

## Key Boundary

Use a dedicated Ed25519 signing key held outside Collabio and outside `dev001`. Prefer a hardware-backed key or an
offline encrypted signing environment. Only these public artifacts enter Collabio:

- raw 32-byte Ed25519 public key;
- structured signature response containing a raw 64-byte detached signature;
- non-secret signer ID and key ID.

Do not mount, upload, copy or back up the private key through a Suite service. The Suite verifies signatures only
through its KMS adapter and cannot create them.

## Ceremony

After the standard `dev001` project/container/port preflight, acquire `build.lock` before `docker.lock` for every
Compose run and use explicit project `collabio`.

1. Generate the four committed JSON schemas in a new empty evidence directory:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-solo-founder-schema
```

2. Set a stable non-secret signer ID, key ID, policy ID, UTC effective time and the host path of the raw public key.
   Build the write-once public policy:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-solo-founder-policy-builder
```

3. Set a unique exception ID, UTC issue and expiration times, risk-acceptance reference and immutable Git
   change-control reference. Expiration must be no more than 30 days after issue. Create the write-once request and
   canonical message:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-solo-founder-signing-request
```

4. Review `genoffice-solo-founder-exception-request.json`, then sign the exact bytes of
   `genoffice-solo-founder-signature-message.json` in the external signing environment. Return this strict response:

```json
{
  "algorithm": "ed25519",
  "content_included": false,
  "key_id": "ASSIGNED_KEY_ID",
  "private_key_included": false,
  "request_hash": "sha256:REQUEST_HASH",
  "schema_version": "genoffice_solo_founder_signature_response.v1",
  "secrets_included": false,
  "signature_base64": "BASE64_RAW_64_BYTE_ED25519_SIGNATURE",
  "signature_message_sha256": "sha256:SIGNATURE_MESSAGE_HASH",
  "signer_id": "ASSIGNED_SIGNER_ID",
  "signer_role": "founder_risk_owner"
}
```

5. Install the response at the configured read-only bind path and verify it while the request is active:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-solo-founder-exception-verifier
```

6. Select the exception explicitly for materialization:

```text
SUITE_GENOFFICE_DEVELOPMENT_AUTHORIZATION_MODE=solo_founder_development_exception
```

Then run `genoffice-development-build-context`. It rechecks the report hash, active validity window, compensating
controls and NOTICE binding before reading source bytes.

## Renewal And Closure

Renewal creates a new policy or request, signature response and report with new IDs and timestamps. Existing evidence
is retained and never overwritten. Close this exception path when either a second accountable person is available or a
customer, certification, insurer or law requires organizational separation. The two-person ceremony then becomes the
only accepted mode.

## Backup And Restore

Back up the public policy, request, exact message, response and final report as one versioned evidence set. Verify file
mode, report hash, request/message/response binding and expiration on restore. Public keys and signatures are evidence;
private keys, package caches, tenant content and scratch data are excluded.
