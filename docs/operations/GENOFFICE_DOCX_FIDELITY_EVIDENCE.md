# GenOffice DOCX Fidelity Evidence Verification

## Purpose

This control verifies the actual bytes behind one signed ADR-0072 runner result. It does not invoke Word, LibreOffice,
GenOffice or a document converter. It accepts only a synthetic study bundle and public verification inputs. It writes a
metadata-only verification report and cannot accept compatibility, complete Quick Edit or authorize tenant content.

The implementation is `app/suite/operations/genoffice_docx_fidelity_evidence.py`; ADR-0073 defines the boundary.

## Exact input tree

The read-only evidence root must contain exactly:

```text
candidate-cdr/
  manifest.json
  page-NNNNNN.rgb
execution-receipt.json
font-baseline-report.json
openxml-validation-report.json
output-preflight-report.json
output-structural-fingerprint-report.json
output.docx
reference-cdr/
  manifest.json
  page-NNNNNN.rgb
visual-comparison-manifest.json
```

The receipt inventories every file except itself by canonical relative path, exact byte length and SHA-256. Additional,
missing, empty, linked, special, oversized or changed entries fail verification. JSON is UTF-8, strict-schema and
duplicate-key-free.

The separate public-input directory contains exactly the selected result envelope as `result-envelope.json`, active
signer policy as `signer-policy.json` and canonical plan as `study-plan.json`. Private signing keys and credentials are
never inputs.

## Verification

The verifier checks the plan, signer policy, Ed25519 envelope and assignment first. It then hashes the DOCX, reruns the
canonical Quick Edit preflight and OOXML fingerprint, validates the Open XML and font reports, checks every reference and
candidate RGB page, recomputes all visual metrics, reconstructs the receipt inventory and binds every report back to the
signed payload.

Open XML findings contain no descriptions or document excerpts. Font evidence contains no font names or filesystem
paths. The output report contains hashes, counters and booleans only.

A successful report means the referenced evidence bytes were present and internally consistent. It deliberately keeps:

- `thresholds_calibrated=false`;
- `human_fidelity_review_verified=false`;
- `compatibility_claim_allowed=false`;
- `quick_edit_spike_complete=false`.

## Schema generation

Create a new empty private output directory on `dev001`, inspect Compose projects, containers and ports, acquire
`build.lock` before `docker.lock`, then run:

```bash
export SUITE_GENOFFICE_FIDELITY_EVIDENCE_SCHEMA_HOST_DIR=./backups/genoffice-supply-chain/<generation>/fidelity-evidence-schemas-<generation>
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-docx-fidelity-evidence-schema
```

The six schemas cover Open XML validation, font baseline, study CDR, visual comparison, execution receipt and final
evidence verification.

## Real verification

After an authorized runner has supplied a bundle, place each input in a new mode-`0700` generation and make the output
directory separately empty. Run only after the usual `dev001` inspection and locks:

```bash
export SUITE_GENOFFICE_FIDELITY_EVIDENCE_BUNDLE_HOST_DIR=./backups/genoffice-docx-fidelity-evidence/<generation>/bundle
export SUITE_GENOFFICE_FIDELITY_EVIDENCE_INPUT_HOST_DIR=./backups/genoffice-docx-fidelity-evidence/<generation>/inputs
export SUITE_GENOFFICE_FIDELITY_EVIDENCE_OUTPUT_HOST_DIR=./backups/genoffice-docx-fidelity-evidence/<generation>/output
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-docx-fidelity-evidence-verifier
```

The verifier uses no network, has a read-only root, reads `/evidence` and `/inputs`, and writes one report to `/output`.
Existing output is never overwritten. A failed verification is retained as runner evidence outside the accepted-result
set and must not be silently repaired in place.

## Backup and restore

Retain the signed envelope, public signer policy, plan, execution receipt, output DOCX, strict reports, CDR manifests,
verified report and exact hashes under `office_documents`. Raw RGB pages are transient and excluded after their verified
hashes and required review artifacts have been retained according to the study policy. Private keys, credentials,
profiles, decrypted scratch and tokens are prohibited backup artifacts.

Restore must recompute all hashes, signatures, strict models, DOCX preflight/fingerprint and retained visual evidence.
When raw RGB has expired, the signed CDR hashes remain provenance evidence but cannot independently recreate a missing
human review. A historical report never authorizes a new engine run.
