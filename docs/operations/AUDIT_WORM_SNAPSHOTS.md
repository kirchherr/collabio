# Audit WORM Snapshots

## Purpose

The `audit-worm` Compose profile provides a one-shot, tenant-explicit audit snapshot worker. It is intended for an external scheduler such as a Kubernetes CronJob, systemd timer or controlled operations pipeline. Collabio does not run a privileged in-process scheduler for this control.

The worker is non-destructive but compliance-relevant. It fails closed unless `SUITE_AUDIT_WORM_SNAPSHOT_ENABLED=1` and all tenant, database, signing-key and storage-key mappings are explicit.

## Security boundary

- Use the dedicated, non-cryptoshred signing-key namespace `kms-sign://tenant-a/audit/v3` and map it to an asymmetric provider key with `SIGN_VERIFY` usage.
- Use a separate storage-encryption key mapping. Signing and storage-encryption keys must not be the same key.
- Prefer workload identity or an instance/task role. Do not place long-lived cloud credentials in the repository or Compose file.
- The database DSN must use `collabio_audit_writer`, not the normal application role.
- The target bucket must have versioning and Object Lock enabled before the first write.
- Production writes require `COMPLIANCE` mode, an explicit retain-until timestamp, exact-version readback and SSE-KMS verification.
- A Legal Hold is independent of fixed retention. Set `SUITE_AUDIT_WORM_LEGAL_HOLD=1` only from an authoritative hold decision.
- Do not route snapshot event bodies, signed bundles, credentials or signatures into normal observability logs. The worker prints only the metadata-only result receipt.
- The public key archived in a bundle is verification material, not a trust anchor. Pin the tenant trust-policy hash in a separate, change-controlled evidence record.

## Required configuration

The worker reads these required values:

- `SUITE_AUDIT_WORM_TENANT_ID`
- `SUITE_AUDIT_WORM_CREATED_BY`
- `SUITE_AUDIT_DATABASE_DSN`
- `SUITE_AUDIT_SIGNING_KMS_KEY_REF`
- `SUITE_AUDIT_SIGNING_PROVIDER_KEY_ID`
- `SUITE_AUDIT_STORAGE_KMS_KEY_REF`
- `SUITE_AUDIT_STORAGE_PROVIDER_KEY_ID`

Retention defaults to policy `audit-security-10y-v1` and 3650 days. The default bucket is `evidence-records`. Override values only through an approved tenant retention policy.

Run one explicit tenant snapshot with the `audit-worm` profile after migration `0075` is applied. Schedule the same one-shot command at the required interval; completed unchanged prefixes return their existing receipt without another KMS or S3 call.

## Offline verification

`audit-worm-verify` validates an exact v2 object without network or provider access. It requires all of these independently sourced inputs:

- the exact object-version bytes and bundle SHA-256 from the append-only storage receipt;
- the tenant-specific `audit_signing_trust_policy.v1` file;
- the expected canonical trust-policy SHA-256 from a separate change-controlled evidence record;
- the expected tenant ID and, when available, checkpoint ID.

The trust policy binds each `kms-sign://<tenant>/audit/vN` reference to the exact provider profile, provider key ID, SPKI DER public-key hash, allowed algorithm and signing-time validity window. Retired keys remain available for historical signatures by closing their validity window. A compromised key is marked `revoked=true` and is rejected for all snapshots. Never replace the pinned trust-policy hash with a value calculated from an untrusted policy delivered beside the bundle.

Run the verifier through its default-off, read-only Compose profile. Mount only a controlled input directory; the service has no network, ports, database dependency or cloud credentials:

```sh
docker compose -p collabio --profile audit-worm-verify run --rm --no-deps \
  --volume "$INPUT_DIR:/input:ro" audit-worm-verify \
  --bundle /input/bundle.json \
  --trust-policy /input/trust-policy.json \
  --expected-bundle-hash "sha256:<receipt-hash>" \
  --expected-trust-policy-hash "sha256:<pinned-policy-hash>" \
  --expected-tenant-id "<tenant-id>" \
  --expected-checkpoint-id "<checkpoint-id>"
```

Success emits `audit_worm_snapshot_verification_report.v2` with hashes, key references, timestamps and counts only. It never emits events, metadata, user IDs, source-object IDs, signatures or public-key bytes. Failure emits one fixed metadata-only response and a non-zero exit code. The verifier checks exact bundle bytes, canonical schemas, manifest/event hashes, the complete tenant chain, the pinned key identity and signing window, then verifies ECDSA/SHA-256 or RSA-PSS/SHA-256 locally against the archived SPKI public key.

## Acceptance evidence

A production provider is accepted only when one real, non-content test tenant run proves all of the following:

1. KMS `DescribeKey` reports an enabled asymmetric `SIGN_VERIFY` key.
2. KMS signs and verifies the manifest digest and returns auditable request IDs.
   The bundle contains the public DER key and its SHA-256 for later offline verification; it never contains a private key.
3. S3 returns a non-empty object version ID.
4. Exact-version readback reproduces the bundle SHA-256.
5. `HeadObject` reports `COMPLIANCE`, a retain-until value at or beyond the requested time, the requested Legal Hold state and the expected SSE-KMS key.
6. PostgreSQL stores one tenant-scoped checkpoint and one receipt, rejects owner update/delete, and an isolated restore reproduces both rows.
7. A deletion attempt against that exact protected version is denied. Perform this only in an approved disposable proof bucket because Compliance retention cannot be shortened.
8. The exact downloaded object version passes `audit-worm-verify` against the separately pinned tenant trust-policy hash without network access.

Until this evidence exists for the selected production providers, the roadmap item remains partially complete and no claim of productive WORM/KMS operation is allowed.

### Provider acceptance gate

`audit-worm-provider-acceptance` automates the live AWS acceptance ceremony but never provisions or changes a bucket, Object Lock configuration or KMS key. The profile is off by default and uses the AWS SDK workload-identity chain only; no static access-key variables are present in Compose.

Use a dedicated, empty proof bucket created with Object Lock enabled. The proof tenant must contain exactly one synthetic, non-personal and non-business event named `audit.worm_provider_acceptance.synthetic`. It must have no source objects, input/output hashes, model or prompt reference; its metadata must be exactly `{"purpose":"audit_worm_provider_acceptance","synthetic":true}`. Configure exactly one day of Compliance retention and Legal Hold `OFF`. The acceptance identity should have only the read actions needed for the exact object, `kms:DescribeKey`, and `s3:DeleteObjectVersion` for the proof prefix. It must not have bucket-management, retention-change, Legal-Hold-change, KMS-administration or Object-Lock-bypass permissions. `s3:DeleteObjectVersion` is present solely so S3 can reject the exact-version request because of active Compliance retention.

Before any provider call, the command validates a separately pinned `audit_worm_provider_acceptance_policy.v1`. Its canonical hash binds:

- hashes of the synthetic tenant and synthetic principal IDs;
- the exact region, dedicated bucket and proof object-key prefix;
- hashes of the signing and storage provider key IDs;
- the exact bundle, snapshot receipt, signing trust policy and PostgreSQL restore-report hashes;
- an at-most-seven-day policy validity window and a one-to-seven-day permitted retention range;
- explicit authorization for provider calls and the exact-version delete-denial attempt.

The acceptance policy is a reviewed authorization record, not configuration inferred by the command. Pin its canonical SHA-256 outside the mounted input directory. Do not calculate the expected policy hash from an untrusted file delivered beside the evidence at execution time.

The ceremony order is fixed:

1. Validate all policy, receipt, trust-policy and restore-report hashes locally.
2. Require an isolated, metadata-only PostgreSQL restore report whose exact source and target state manifests match and whose append-only audit controls pass.
3. Read and head only the receipt's exact S3 `VersionId`; verify its hash, active Compliance retention, Legal Hold `OFF` and expected SSE-KMS key.
4. Describe the exact asymmetric KMS signing key and require `Enabled` plus `SIGN_VERIFY`.
5. Run the complete offline bundle, tenant-chain and signature verifier.
6. Submit exactly `DeleteObject(Bucket, Key, VersionId)`. An unversioned delete-marker request is forbidden and is not evidence.
7. Require AWS `403 AccessDenied`, then read the same exact version again and reproduce its hash.

Run only after the snapshot and isolated restore evidence have been produced and the policy hash has been approved:

```sh
export SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_ENABLED=1
docker compose -p collabio --profile audit-worm-provider-acceptance run --rm --no-deps \
  --volume "$INPUT_DIR:/input:ro" audit-worm-provider-acceptance \
  --policy /input/provider-acceptance-policy.json \
  --expected-policy-hash "sha256:<separately-pinned-policy-hash>" \
  --receipt /input/audit-worm-object-receipt.json \
  --restore-report /input/postgres-restore-report.json \
  --expected-restore-report-hash "sha256:<approved-restore-report-hash>" \
  --trust-policy /input/trust-policy.json \
  --expected-trust-policy-hash "sha256:<approved-trust-policy-hash>" \
  --expected-bundle-hash "sha256:<receipt-bundle-hash>" \
  --expected-tenant-id "<synthetic-proof-tenant-id>" \
  --execution-confirmation I_APPROVE_EXACT_VERSION_DELETE_DENIAL_PROBE
```

Success emits `audit_worm_provider_acceptance_report.v1`. Bucket, object key, version ID, tenant ID, provider key IDs and provider request IDs are represented only by SHA-256 references. Event bodies, signatures, public-key bytes and secrets are never emitted. Any failure emits one fixed metadata-only record and exits non-zero. If the exact-version delete unexpectedly succeeds, the ceremony fails irrecoverably and must not be represented as accepted evidence.

The command deliberately cannot run on `dev001` yet: no approved AWS workload identity, dedicated Object-Lock proof bucket or purpose-bound KMS keys are configured there. This is an external acceptance prerequisite, not an implementation fallback to MinIO or local credentials.

## Recovery

The S3 write precedes the PostgreSQL receipt transaction. A database failure can therefore leave a valid protected object version without a receipt. Reconciliation must inspect only the configured tenant prefix, verify the bundle, signature, exact object controls and current audit prefix, then append the missing receipt. Never overwrite or delete an orphaned protected version.

## Primary references

- AWS KMS `Sign`: https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html
- AWS KMS `GetPublicKey`: https://docs.aws.amazon.com/kms/latest/APIReference/API_GetPublicKey.html
- AWS KMS key-spec and signature algorithm reference: https://docs.aws.amazon.com/kms/latest/developerguide/symm-asymm-choose-key-spec.html
- AWS KMS asymmetric keys: https://docs.aws.amazon.com/kms/latest/developerguide/symmetric-asymmetric.html
- Amazon S3 Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- Amazon S3 Object Lock operations: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-managing.html
- NIST FIPS 186-5 Digital Signature Standard: https://csrc.nist.gov/pubs/fips/186-5/final
