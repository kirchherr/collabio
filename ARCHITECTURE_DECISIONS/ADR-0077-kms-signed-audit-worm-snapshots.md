# ADR-0077: KMS-Signed Audit WORM Snapshots

Status: Accepted

Date: 2026-08-17

## Context

The v1 audit schema proves a tenant hash chain and stores HMAC checkpoint/WORM-export metadata, but the process receives an HMAC secret and the database receipt does not prove that an immutable object version was actually written and read back. That boundary is insufficient for productive external audit evidence.

## Decision

Collabio adds a v2 path without rewriting v1 history:

- A canonical manifest binds tenant, complete sequence range, first/last event hash, canonical event-set hash, classification, retention policy and Legal Hold state.
- An asymmetric provider KMS key, addressed through the dedicated `kms-sign://<tenant>/audit/vN` namespace, signs the SHA-256 manifest digest. It is not a cryptoshreddable data-class key. Production code has no local signing implementation and receives no private key material.
- Supported initial algorithms are ECDSA/SHA-256 and RSA-PSS/SHA-256. KMS must immediately verify its generated signature.
- The signed bundle is written as an exact S3 object version with explicit Compliance retention and SSE-KMS.
- The bundle archives the public DER key and its hash so signature verification does not depend on future private-key availability.
- The archived key is verification material, not self-authenticating trust. Offline verification requires a tenant trust policy whose canonical hash is pinned in a separate change-controlled record. It binds logical key version, provider identity, public-key hash, allowed algorithm and signing-time validity.
- A default-off, networkless and read-only Compose command verifies exact bundle bytes, the complete tenant chain and ECDSA/SHA-256 or RSA-PSS/SHA-256 signatures locally. It emits metadata-only success or fixed failure output.
- A separate default-off live-provider acceptance command binds an approved short-lived policy to exact bundle, receipt, trust-policy, restore-report, bucket/prefix and provider-key hashes. It validates the full restore and offline signature evidence before attempting an exact-version delete, requires AWS `403 AccessDenied`, then proves the same version remains readable. It has no resource-provisioning or retention-changing path.
- The worker reads that exact version back and checks content hash, metadata, retention, Legal Hold and encryption before persistence.
- PostgreSQL records separate append-only checkpoint and object-version receipts under forced tenant RLS and owner-level mutation triggers.
- A deterministic checkpoint identity makes a completed chain prefix idempotent. Storage objects left by a later database failure are retained for reconciliation.
- Scheduling remains an external operations responsibility invoking an unprivileged one-shot worker.

The existing HMAC tables remain restoreable legacy evidence and are not promoted as the production signature path.

## Consequences

An approved workload identity, a disposable Object-Lock proof bucket and purpose-bound provider keys are still required for production acceptance. The implementation cannot honestly satisfy the productive WORM/KMS roadmap item until the acceptance command records a real exact-version delete denial and binds it to an isolated restore. Compliance-mode retention is deliberately irreversible for its duration, so proof runs require an approved short-lived but non-shortenable test policy.

## References

- https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- https://csrc.nist.gov/pubs/fips/186-5/final
