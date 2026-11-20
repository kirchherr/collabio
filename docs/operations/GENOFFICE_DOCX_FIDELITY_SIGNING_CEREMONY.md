# GenOffice DOCX Fidelity Signing Ceremony

This runbook authenticates one completed synthetic fidelity result without importing a private key into Collabio,
Docker or `dev001`. It does not prove compatibility, calibrate visual thresholds, complete human review, authorize
tenant content or enable a product write. ADR-0073 must independently verify every signed evidence bundle.

## Trust Boundary

The public policy contains one purpose-specific Ed25519 public key for Microsoft Word, LibreOffice and GenOffice.
These are engine provenance identities. They are not evidence of separate human approvers. In the solo-development
phase one accountable operator may hold all three keys only when they are separately generated, purpose labelled and
protected outside the repository and remote host.

Never mount private keys, DPAPI ciphertext, HSM sockets, KMS credentials or provider tokens into any service below.
The ceremony has no `sign` mode and no network. The existing founder-admission key must not be reused.

## Host Preflight

Before every Compose job on `dev001`:

```bash
cd /home/extern/collabio
docker compose -p collabio ls
docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Ports}}'
ss -ltnH
```

Use existing mode-`0700` generation directories and mode-`0600` files. Build and test jobs acquire `build.lock` before
`docker.lock`; one-shot ceremony jobs acquire `docker.lock`. Always pass `-p collabio`.

## Generate Schemas

```bash
SUITE_GENOFFICE_FIDELITY_CEREMONY_SCHEMA_HOST_DIR="$SCHEMA_DIR" \
  flock -w 300 /home/extern/.codex-coordination/build.lock \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-ceremony-schema
```

Byte-compare both generated schemas with `docs/operations/` before using the ceremony.

## Build Public Policy

Place only three raw 32-byte public keys in the external key directory. Set identities, key IDs and an effective time
that is no later than the engine results it will authenticate.

```bash
SUITE_GENOFFICE_FIDELITY_WORD_PUBLIC_KEY_HOST_PATH="$KEYS_DIR/word.ed25519.pub" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_PUBLIC_KEY_HOST_PATH="$KEYS_DIR/libreoffice.ed25519.pub" \
SUITE_GENOFFICE_FIDELITY_GENOFFICE_PUBLIC_KEY_HOST_PATH="$KEYS_DIR/genoffice.ed25519.pub" \
SUITE_GENOFFICE_FIDELITY_CEREMONY_OUTPUT_HOST_DIR="$POLICY_DIR" \
SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_ID="$POLICY_ID" \
SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_EFFECTIVE_AT_UTC="$EFFECTIVE_AT" \
SUITE_GENOFFICE_FIDELITY_WORD_SIGNER_ID="$WORD_SIGNER_ID" \
SUITE_GENOFFICE_FIDELITY_WORD_KEY_ID="$WORD_KEY_ID" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_SIGNER_ID="$LIBREOFFICE_SIGNER_ID" \
SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_KEY_ID="$LIBREOFFICE_KEY_ID" \
SUITE_GENOFFICE_FIDELITY_GENOFFICE_SIGNER_ID="$GENOFFICE_SIGNER_ID" \
SUITE_GENOFFICE_FIDELITY_GENOFFICE_KEY_ID="$GENOFFICE_KEY_ID" \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-ceremony-policy
```

## Prepare One Request

Build a fresh input directory containing exactly the public signer policy, canonical study plan and the selected
runner `handoff/result-payload.json`. Use a fresh empty output directory per fixture.

```bash
SUITE_GENOFFICE_FIDELITY_CEREMONY_INPUT_HOST_DIR="$INPUT_DIR" \
SUITE_GENOFFICE_FIDELITY_CEREMONY_OUTPUT_HOST_DIR="$REQUEST_DIR" \
SUITE_GENOFFICE_FIDELITY_PREPARED_AT_UTC="$PREPARED_AT" \
SUITE_GENOFFICE_FIDELITY_VALID_UNTIL_UTC="$VALID_UNTIL" \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-ceremony-request
```

Transfer `result-signing-request.json` and `result-signature-message.bin` to the accountable external signer. The
signer validates the request and signs the exact message bytes. Only a response conforming to
`genoffice-docx-fidelity-external-signature-response.schema.json` returns to `dev001`.

## Assemble And Verify

Place the unchanged public policy, study plan and request in a fresh read-only input directory. Mount the detached
response separately and write the envelope to a fresh output directory.

```bash
SUITE_GENOFFICE_FIDELITY_CEREMONY_INPUT_HOST_DIR="$ASSEMBLY_INPUT_DIR" \
SUITE_GENOFFICE_FIDELITY_SIGNATURE_RESPONSE_HOST_PATH="$RESPONSE_PATH" \
SUITE_GENOFFICE_FIDELITY_CEREMONY_OUTPUT_HOST_DIR="$ENVELOPE_DIR" \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-ceremony-assemble
```

Then copy the signed envelope, public signer policy and study plan into a fresh ADR-0073 input directory and run the
independent verifier against the original read-only fixture evidence:

```bash
SUITE_GENOFFICE_FIDELITY_EVIDENCE_BUNDLE_HOST_DIR="$EVIDENCE_DIR" \
SUITE_GENOFFICE_FIDELITY_EVIDENCE_INPUT_HOST_DIR="$VERIFIER_INPUT_DIR" \
SUITE_GENOFFICE_FIDELITY_EVIDENCE_OUTPUT_HOST_DIR="$VERIFIER_OUTPUT_DIR" \
  flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile office-worker-runtime-proof \
  run --rm genoffice-docx-fidelity-evidence-verifier
```

Retain the policy, request, canonical message, detached response, signed envelope and ADR-0073 report. Retain the
original evidence directory unchanged. Record hashes, key IDs, policy effective time and honest failed checks in the
operations log. Microsoft Word and GenOffice results remain absent until their own authorized runners execute.

