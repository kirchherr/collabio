# GenOffice DOCX Fidelity Study

## Purpose

This control defines the reproducible Word/LibreOffice/GenOffice comparison for the future DOCX Quick Edit spike. The
current implementation creates policy, plan, structural baselines and readiness evidence only. It does not run any
Office engine, process tenant content, validate a compatibility claim or authorize a document write.

The implementation is `app/suite/operations/genoffice_docx_fidelity_study.py`; ADR-0072 defines the architecture.

## Exact study matrix

The plan contains nine ordered assignments:

| Engine | Runner | Fixtures | Current execution state |
| --- | --- | --- | --- |
| Microsoft Word | interactive Windows client | formatting/table, header/comment/footnote, unknown markup | not authorized |
| LibreOffice | isolated headless worker | same three fixtures | not authorized |
| GenOffice | authorized `runsc-kvm` worker | same three fixtures | blocked by ADR-0070 |

Microsoft Word must not be automated as an unattended server process. LibreOffice and GenOffice runners require exact
engine identity, environment and font baselines, no network and synthetic content only. GenOffice additionally requires
real two-person runtime authorization and a new executable image admission.

Every real runner result must bind the source, output, output preflight, structural fingerprint, Open XML validation,
CDR manifest, font baseline, page comparisons and execution receipt by SHA-256. One distinct Ed25519 runner key is
authorized per engine. Collabio accepts public keys and detached signatures only; private keys are prohibited.

## Current metadata-only bundle

Create a private empty generation directory after the required `dev001` project/container/port inspection. Acquire
`build.lock` before `docker.lock`, then run:

```bash
export SUITE_GENOFFICE_FIDELITY_STUDY_MODE=bundle
export SUITE_GENOFFICE_FIDELITY_STUDY_HOST_DIR=./backups/genoffice-supply-chain/solo-founder-20260812-02/fidelity-study-plan-20260813-01
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-docx-fidelity-study-control
```

The output directory must be empty and is never overwritten. The bundle contains exactly:

- `genoffice-docx-fidelity-study-policy.json`;
- `genoffice-docx-fidelity-study-plan.json`;
- `genoffice-docx-fidelity-baseline-report.json`;
- `genoffice-docx-fidelity-readiness-report.json`.

The baseline covers only the three preflight-approved synthetic fixtures. It records part, XML and relationship counts,
canonical inventory hashes and fixed semantic-feature counters. It includes no document text and performs no archive
extraction.

Generate the ten public JSON Schemas into a different clean directory with
`SUITE_GENOFFICE_FIDELITY_STUDY_MODE=schema`. Checked-in schemas are documentation and integration contracts; the
container writes only to the explicit private output mount.

## Result intake

A runner signs domain-separated canonical `genoffice_docx_fidelity_engine_result_payload.v1` bytes. The verifier rejects a result when
the signer is not authorized for that engine, any hash binding drifts, the assignment is unknown, the runner mode is
wrong, the result predates its signer policy or the signature fails. The three active engine identities must use distinct
public keys. Matrix intake additionally requires all nine assignments in canonical order with nine distinct envelope
hashes.

Matrix intake is not study acceptance. It records that signatures and evidence references are bound while keeping:

- `referenced_evidence_content_verified=false`;
- `visual_thresholds_calibrated=false`;
- `human_fidelity_review_verified=false`;
- `compatibility_claim_allowed=false`;
- `quick_edit_spike_complete=false`.

ADR-0073 implements the independent evidence verifier. It reads and hashes each receipt-inventoried artifact, reruns the
output preflight and OOXML structural fingerprint, validates strict Open XML and font reports, reconciles both CDR
bundles, and recomputes every RGB comparison. This can set `referenced_evidence_content_verified=true` for one signed
result while preserving the same fail-closed state until all nine real results, calibration and human review exist.

## Visual measurement

Page comparison consumes raw RGB bytes with fixed dimensions from `collabio-pixel-cdr:raw-rgb.v1` at 144 DPI. It
records changed pixels, changed-pixel ratio in parts per million, mean absolute channel delta in parts per million and
maximum channel delta using deterministic integer arithmetic. These are observations, not acceptance thresholds.

Exact pixel equality can be stated for a page. Cross-engine visual fidelity cannot be accepted automatically until real
results establish calibrated thresholds and a human reviewer approves the study.

## Backup and restore

Back up canonical policy and schemas, study plan, source corpus manifest binding, structural baselines, readiness report,
public signer policy, signed result envelopes, verified evidence artifacts and later review records under
`office_documents`. Private keys, credentials, Office profiles, decrypted scratch, raw transient RGB, tokens and
unverified engine outputs are prohibited backup artifacts.

After restore, recompute all hashes and signatures, require the exact 3x3 assignment matrix, and revalidate every
referenced evidence byte. A historical runtime authorization does not authorize a new run. Missing evidence, thresholds
or human review keeps compatibility and Quick Edit completion false.
