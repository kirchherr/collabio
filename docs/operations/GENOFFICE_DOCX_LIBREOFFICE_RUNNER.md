# GenOffice DOCX LibreOffice Synthetic Runner

## Purpose

This runbook produces unsigned LibreOffice evidence for one ADR-0072 synthetic fixture. It does not authorize tenant
content, a product write, a compatibility claim or production use. Follow `/home/extern/AGENTS.md`, use
`dev001:/home/extern/collabio`, project `collabio`, and acquire `build.lock` before `docker.lock` when both apply.

## Fixed Boundary

- Only `formatting-table-fidelity`, `headers-comments-footnotes-fidelity` and `unknown-markup-passthrough` are valid.
- The runner image reference must be `sha256:<64 hex>` or a registry name plus digest.
- Assignment and output directories must already exist, be empty and be private.
- The assignment expires after four hours.
- The runner uses `runsc-kvm`, no network, a read-only root and no Linux capabilities.
- The worker receives no signer key, tenant credential, Docker socket or tenant content.
- Output is an unsigned handoff. ADR-0073 verification requires a later external signature.

Before every Compose or container start, inspect:

```bash
docker compose -p collabio ls
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -ltnH
```

## Build

```bash
flock -w 600 /home/extern/.codex-coordination/build.lock \
  flock -w 600 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  build genoffice-docx-fidelity-libreoffice-image

flock -w 60 /home/extern/.codex-coordination/docker.lock \
  docker image inspect collabio/genoffice-docx-fidelity-libreoffice:dev --format '{{.Id}}'
```

Record the returned immutable image ID. Never substitute the mutable `:dev` tag in an assignment.

## Generate Schemas

Create a new empty mode-`0700` directory inside the approved private evidence generation, then run:

```bash
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_SCHEMA_HOST_DIR="$SCHEMA_DIR" \
  flock -w 300 /home/extern/.codex-coordination/build.lock \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-libreoffice-schema
```

The two generated schema files must byte-match the versioned files in `docs/operations/`.

## Prepare And Run One Fixture

Create new empty mode-`0700` assignment and output directories. Do not reuse a failed or completed directory.

```bash
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_FIXTURE_ID="$FIXTURE_ID" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_RUNNER_IMAGE_REF="$IMAGE_ID" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_ASSIGNMENT_HOST_DIR="$ASSIGNMENT_DIR" \
  flock -w 300 /home/extern/.codex-coordination/build.lock \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-libreoffice-prepare
```

Repeat host preflight, then execute the exact image without pulling:

```bash
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_RUNNER_IMAGE_REF="$IMAGE_ID" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_ASSIGNMENT_HOST_DIR="$ASSIGNMENT_DIR" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_OUTPUT_HOST_DIR="$OUTPUT_DIR" \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm --pull never genoffice-docx-fidelity-libreoffice-runner
```

## Expected Output

`evidence/` contains the output DOCX, preflight, structure, OpenXML, font, source/candidate CDR, visual and execution
receipt records. `handoff/` contains the result payload, canonical signature message and runner report. Files are
write-once `0600`; directories are private. Profiles, temporary PDFs and in-memory RGB buffers are not retained.

The runner report must state:

- `engine_executed=true`
- `evidence_materialized=true`
- `result_signed=false`
- `evidence_independently_verified=false`
- `compatibility_claim_allowed=false`
- `tenant_content_processed=false`
- `private_key_included=false`

OpenXML findings are valid failed observations. Do not edit, filter or relabel them. A run is not a compatibility pass.

## First Baseline

Generation `fidelity-libreoffice-20260813-04` used image
`sha256:0d0f6adac9b18f07a213f85f116690051c9b6d38d0be10e9bafea36d636715ab`:

| Fixture | Runner report | Execution receipt | OpenXML findings | Visual result |
| --- | --- | --- | ---: | --- |
| formatting-table-fidelity | `sha256:c273fb89e085aa470e71ff25df1e7c7aaaf789a0ddce62edd6c84ae20a66972b` | `sha256:ddcfed83958b6bc00418dc9ee1bdbf6b1b43ffdb6a3a3a883d0f2177e69ac74c` | 7 | exact, one page |
| headers-comments-footnotes-fidelity | `sha256:a09e7ba7f32f67b413b6d9c26dd2bb7cf306eb1fe453c8f006ef2a7b34230f17` | `sha256:8d4ad6242039f576c27b8c4a9729fa76d3bb7016b6f71d7b9433808ec11bd7ff` | 6 | exact, one page |
| unknown-markup-passthrough | `sha256:db66c0eff2577e76203aa1ce642d8c8eab069ad98d1d7ba6a6881854e8e42609` | `sha256:b97edb1405010f71b8b99cf2e9cae2fac2b7b5c99f002ba6bf06c7aa822d9a31` | 6 | exact, one page |

## Next Gate

Use an externally held LibreOffice engine key to sign each canonical message under the complete three-engine signer
policy. Then run the ADR-0073 source-blind verifier against a copied, read-only evidence bundle. Do not place private
keys in Collabio, Docker, `dev001`, backups or normal logs. Cross-engine matrix completion, threshold calibration and
human review remain separate later steps.
