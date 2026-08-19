# Audit WORM Snapshots

## Purpose

The `audit-worm` Compose profile provides a one-shot, tenant-explicit audit snapshot worker. It is intended for an external scheduler such as a Kubernetes CronJob, systemd timer or controlled operations pipeline. Collabio does not run a privileged in-process scheduler for this control.

The worker is non-destructive but compliance-relevant. It fails closed unless `SUITE_AUDIT_WORM_SNAPSHOT_ENABLED=1` and all tenant, database, signing-key and storage-key mappings are explicit.

## Security boundary

- Use the dedicated, non-cryptoshred signing-key namespace `kms-sign://tenant-a/audit/v3` and map it to a versioned OpenBao Transit key such as `openbao-transit://transit/tenant-a-audit/v3`.
- Use a separate storage-encryption key mapping. Signing and storage-encryption keys must not be the same key.
- Collabio's production reference profile is self-hosted Ceph RGW plus OpenBao Transit. AWS infrastructure, an AWS account and AWS IAM are not prerequisites or roadmap goals.
- Use short-lived, least-privilege Ceph credentials and a narrowly scoped OpenBao machine token delivered through mounted secret files. Do not place credentials or tokens in the repository or Compose file.
- The database DSN must use `collabio_audit_writer`, not the normal application role.
- The target bucket must have versioning and Object Lock enabled before the first write.
- Production writes require `COMPLIANCE` mode, an explicit retain-until timestamp, exact-version readback and SSE-KMS verification.
- Ceph exposes the S3-compatible wire token `aws:kms` for SSE-KMS. This protocol literal in SDK calls and persisted v2 receipts does not select or contact AWS; the mandatory explicit endpoint selects the self-hosted Ceph RGW service.
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
- `SUITE_S3_ENDPOINT_URL` as an explicit HTTPS Ceph RGW origin
- `SUITE_OPENBAO_ADDR` as an explicit HTTPS OpenBao origin
- `SUITE_OPENBAO_TOKEN_FILE`; the token is read from the mounted file and is never accepted as a Compose value

Retention defaults to policy `audit-security-10y-v1` and 3650 days. The default bucket is `evidence-records`. Override values only through an approved tenant retention policy.

Run one explicit tenant snapshot with the `audit-worm` profile after migration `0075` is applied. Schedule the same one-shot command at the required interval; completed unchanged prefixes return their existing receipt without another OpenBao or S3-compatible call.

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

1. OpenBao exposes the exact non-deletable asymmetric key version and its public key.
2. OpenBao Transit signs and verifies the manifest digest and returns auditable request IDs.
   The bundle contains the public DER key and its SHA-256 for later offline verification; it never contains a private key.
3. S3 returns a non-empty object version ID.
4. Exact-version readback reproduces the bundle SHA-256.
5. `HeadObject` reports `COMPLIANCE`, a retain-until value at or beyond the requested time, the requested Legal Hold state and the expected SSE-KMS key.
6. PostgreSQL stores one tenant-scoped checkpoint and one receipt, rejects owner update/delete, and an isolated restore reproduces both rows.
7. A deletion attempt against that exact protected version is denied. Perform this only in an approved disposable proof bucket because Compliance retention cannot be shortened.
8. The exact downloaded object version passes `audit-worm-verify` against the separately pinned tenant trust-policy hash without network access.

Until this evidence exists for the self-hosted production providers, the roadmap item remains partially complete and no claim of productive WORM/KMS operation is allowed.

### Provider acceptance gate

`audit-worm-provider-acceptance` automates the live self-hosted provider acceptance but never provisions or changes a bucket, Object Lock configuration or signing key. The profile is off by default. It requires explicit HTTPS origins for Ceph RGW and OpenBao, and those origin hashes are pinned in the approval policy. The S3-compatible Python SDK is used only against that explicit Ceph endpoint; no AWS endpoint or AWS account is involved.

Use a dedicated, empty proof bucket created with Object Lock enabled. The proof tenant must contain exactly one synthetic, non-personal and non-business event named `audit.worm_provider_acceptance.synthetic`. It must have no source objects, input/output hashes, model or prompt reference; its metadata must be exactly `{"purpose":"audit_worm_provider_acceptance","synthetic":true}`. Configure exactly one day of Compliance retention and Legal Hold `OFF`. The Ceph acceptance identity should have only exact-object read/head plus version-delete permission for the proof prefix. The OpenBao token should have only read access to the exact Transit key metadata. Neither identity may manage buckets, retention, Legal Hold, key lifecycle or Object-Lock bypass. Version delete is present solely so Ceph RGW can reject the exact-version request because of active Compliance retention.

Before any provider call, the command validates a separately pinned `audit_worm_provider_acceptance_policy.v2`. Its canonical hash binds:

- hashes of the synthetic tenant and synthetic principal IDs;
- the exact self-hosted provider profile, S3 signing region, hashes of both HTTPS origins, dedicated bucket and proof object-key prefix;
- hashes of the signing and storage provider key IDs;
- the exact bundle, snapshot receipt, signing trust policy and PostgreSQL restore-report hashes;
- an at-most-seven-day policy validity window and a one-to-seven-day permitted retention range;
- explicit authorization for provider calls and the exact-version delete-denial attempt.

The acceptance policy is a reviewed authorization record, not configuration inferred by the command. Pin its canonical SHA-256 outside the mounted input directory. Do not calculate the expected policy hash from an untrusted file delivered beside the evidence at execution time.

The ceremony order is fixed:

1. Validate all policy, receipt, trust-policy and restore-report hashes locally.
2. Require an isolated, metadata-only PostgreSQL restore report whose exact source and target state manifests match and whose append-only audit controls pass.
3. Read and head only the receipt's exact S3 `VersionId`; verify its hash, active Compliance retention, Legal Hold `OFF` and expected SSE-KMS key.
4. Inspect the exact OpenBao Transit key version, require deletion to be disabled, bind its asymmetric type and public-key hash to the trust policy.
5. Run the complete offline bundle, tenant-chain and signature verifier.
6. Submit exactly `DeleteObject(Bucket, Key, VersionId)`. An unversioned delete-marker request is forbidden and is not evidence.
7. Require S3-compatible `403 AccessDenied`, then read the same exact version again and reproduce its hash.

Run only after the snapshot and isolated restore evidence have been produced and the policy hash has been approved:

```sh
export SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_ENABLED=1
export SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_S3_ENDPOINT_URL=https://rgw-proof.internal.example
export SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_ADDR=https://openbao.internal.example
export SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_TOKEN_FILE=/run/secrets/openbao-audit-proof-token
docker compose -p collabio --profile audit-worm-provider-acceptance run --rm --no-deps \
  --volume "$SECRET_DIR/openbao-token:/run/secrets/openbao-audit-proof-token:ro" \
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

Success emits `audit_worm_provider_acceptance_report.v2`. Bucket, object key, version ID, tenant ID, provider key IDs and provider request IDs are represented only by SHA-256 references. Event bodies, signatures, public-key bytes and secrets are never emitted. Any failure emits one fixed metadata-only record and exits non-zero. If the exact-version delete unexpectedly succeeds, the ceremony fails irrecoverably and must not be represented as accepted evidence.

The command deliberately cannot run on `dev001` yet: no approved Ceph RGW proof endpoint, dedicated Object-Lock proof bucket or OpenBao signing service is deployed there. Do not turn the shared development host into an improvised production storage or key-management cluster. MinIO remains a development compatibility target and is not accepted as productive WORM evidence.

## Recovery

The S3 write precedes the PostgreSQL receipt transaction. A database failure can therefore leave a valid protected object version without a receipt. Reconciliation must inspect only the configured tenant prefix, verify the bundle, signature, exact object controls and current audit prefix, then append the missing receipt. Never overwrite or delete an orphaned protected version.

## Primary references

- Ceph RGW S3 API: https://docs.ceph.com/en/latest/radosgw/s3/
- Ceph RGW bucket and Object Lock operations: https://docs.ceph.com/en/latest/radosgw/s3/bucketops/
- Ceph RGW object retention and Legal Hold operations: https://docs.ceph.com/en/reef/radosgw/s3/objectops/
- Ceph RGW KMIP integration: https://docs.ceph.com/en/latest/radosgw/kmip/
- OpenBao Transit: https://openbao.org/docs/secrets/transit/
- OpenBao Transit API: https://openbao.org/api-docs/secret/transit/
- OpenBao security model: https://openbao.org/docs/internals/security/
- NIST FIPS 186-5 Digital Signature Standard: https://csrc.nist.gov/pubs/fips/186-5/final
