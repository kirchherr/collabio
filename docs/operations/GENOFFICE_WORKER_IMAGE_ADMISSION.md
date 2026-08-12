# GenOffice Worker Image Admission

This runbook turns an authorized GenOffice DOCX development context into a reproducible, signed development image.
It does not authorize engine execution, source import, tenant content, Hosted Service, On-Prem distribution or
production use.

## Security Boundary

- Run all Compose work on `dev001` in `/home/extern/collabio` with project name `collabio`.
- Inspect Compose projects, containers and listening ports before every container start.
- Acquire `build.lock` before `docker.lock` whenever both are required.
- Keep the build network and every evidence service at `network_mode: none`.
- Never place a private signing key in the repository, a Compose bind, `dev001` or Collabio backup state.
- Treat the saved image, SBOM, scan report, signing request and admission report as one immutable generation.
- Create a new generation after any changed input; never overwrite a prior signed generation.

The worker image itself remains fail closed. Its status entry point reports `worker_execution_allowed=false`, and the
admission schema cannot express runtime approval.

## Required Inputs

The generation directory receives only already verified inputs:

- active solo-founder exception report and signer policy, or a later two-person development authorization;
- deterministic development build-context TAR and report;
- exact reviewed npm package archives and license-material report;
- pinned Dockerfile, build-base digest and runtime-base digest;
- a current Trivy database prepared by the separate update boundary;
- an external raw 32-byte Ed25519 public key and no private key.

Use dedicated absolute host directories through these variables:

```text
SUITE_GENOFFICE_SUPPLY_CHAIN_EVIDENCE_HOST_DIR
SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_HOST_DIR
SUITE_GENOFFICE_WORKER_BUILD_HOST_DIR
SUITE_GENOFFICE_TRIVY_CACHE_HOST_DIR
```

Directories are mode `0700`; evidence files are mode `0600` and write-once.

## Build And Reproducibility

Build two independent tags with `--no-cache --pull=false`, identical context/report/authorization hashes,
`SOURCE_DATE_EPOCH=0` and `BUILDX_NO_DEFAULT_ATTESTATIONS=1`:

```bash
docker compose -p collabio --profile office-worker-build build \
  --no-cache --pull=false genoffice-docx-worker-candidate
```

Set a distinct `SUITE_GENOFFICE_WORKER_IMAGE` for each build. Persist `docker image inspect` for both tags and save
exactly build A as `genoffice-worker-image.tar`. Then run:

```bash
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-build-evidence
```

The evidence gate compares config, rootfs layers, labels, platform, runtime inventory and inputs. It also opens the
saved archive structurally and verifies that its config blob is the expected image config. A tag comparison alone is
not accepted.

## SBOM And Vulnerability Gate

Run the three no-network stages in order:

```bash
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-raw-sbom
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-sbom
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-sbom-validator
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-vulnerability-scan
```

The normalized CycloneDX 1.6 document is authoritative. It binds the exact image config, build evidence, source
admission and pre-build inventory. The signing-request gate rejects a stale Trivy database, schema failure, inventory
drift, incomplete review, any High/Critical finding or any unrepresented finding.

## External Signature Ceremony

Create the canonical request and signature-message files only after the scan succeeds:

```bash
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-build-signing-request
```

Transfer only those two public files to the external signing workstation. Verify the assigned signer, role, key ID,
request hash and message hash before signing the exact message bytes with Ed25519. Return one strict response matching
`genoffice-worker-build-signature-response.schema.json`. The response includes no content, secret or private key.

Run the verifier with the response mounted read-only:

```bash
docker compose -p collabio --profile office-worker-build run --rm --no-deps \
  genoffice-worker-image-admission-verifier
```

A valid result has `development_spike_image_available=true` and
`detached_build_attestation_verified=true`. All runtime, import, content, distribution and production flags must still
be false.

## Generation 05 Verified Record

On 2026-08-12, generation `genoffice-worker-build-20260812-05` passed with:

- build-context TAR `sha256:0581152de3ca2598ed53b4c2e4d0e9d4153f693870059c2b62b1f0e0ab5f5fdb`;
- identical image config `sha256:668c433ca889fa391794d2be9480f2f1b31a7adcc2babf0f1871cce583976a9d`;
- image archive `sha256:9254c03dc56e0bd1384c2e93793a14d02d5c198fca33e351181faf1a513807fd`;
- 41-component SBOM `sha256:38de7639a994b25c2f78a5fda885b837ff3b544ea9140ff715daa2f859133516`;
- vulnerability report `sha256:8bc8ebece40ed9622b28921c2e98b8763a677f0f1f21eea84c6f3760564333b8`
  with zero findings;
- v2 signer key ID `genoffice-founder-ed25519-sha256-a26ad15b83a3bef1`;
- final admission report `sha256:6dd5bf1fd59d62e85a245fe10313a701003fec064b5b0f7e753f18441dd58ebd`.

The report expires at `2026-08-19T09:20:00Z`. Expiry closes the admission; it does not permit reuse or silent renewal.

## Backup And Restore

Preserve the entire public generation and all referenced immutable evidence. After restore, regenerate hashes, validate
the CycloneDX schema, verify Trivy metadata and the external Ed25519 signature, and confirm every runtime boundary is
still false. The DPAPI/HSM/KMS private signing key follows its separate key-recovery policy and is never copied into
Collabio evidence backups.

## Next Boundary

The next admissible step is a separate, no-egress sandbox proof using only synthetic documents. It needs real
two-person runtime authorization plus fidelity, resource-limit, malicious-document, cleanup and recovery evidence
before the status-only worker entry point can change.
