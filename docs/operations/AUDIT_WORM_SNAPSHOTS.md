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

Until this evidence exists for the selected production providers, the roadmap item remains partially complete and no claim of productive WORM/KMS operation is allowed.

## Recovery

The S3 write precedes the PostgreSQL receipt transaction. A database failure can therefore leave a valid protected object version without a receipt. Reconciliation must inspect only the configured tenant prefix, verify the bundle, signature, exact object controls and current audit prefix, then append the missing receipt. Never overwrite or delete an orphaned protected version.

## Primary references

- AWS KMS `Sign`: https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html
- AWS KMS asymmetric keys: https://docs.aws.amazon.com/kms/latest/developerguide/symmetric-asymmetric.html
- Amazon S3 Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- Amazon S3 Object Lock operations: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-managing.html
- NIST FIPS 186-5 Digital Signature Standard: https://csrc.nist.gov/pubs/fips/186-5/final
