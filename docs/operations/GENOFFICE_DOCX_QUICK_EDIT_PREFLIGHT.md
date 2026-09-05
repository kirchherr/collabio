# GenOffice DOCX Quick-Edit Preflight

## Purpose

This control establishes the hostile-OOXML, fidelity expectation, export and source-blind revalidation contracts for
the future DOCX Quick-Edit spike. It is deliberately engine-independent. It does not execute GenOffice, import source,
process tenant content, write document versions, use the network or grant runtime authorization.

The implementation is `app/suite/operations/genoffice_docx_quick_edit_preflight.py`; the architectural boundary is
ADR-0071. The Compose service contains only Collabio Python control code and never mounts the GenOffice worker image.

## Deterministic bundle

The write-once bundle contains:

- canonical preflight policy and policy hash;
- 19 synthetic DOCX/DOCM fixtures and their exact byte manifest;
- one metadata-only preflight report per fixture;
- a corpus evaluation report with three accepted fidelity inputs and 16 expected pre-engine rejections;
- a source-blind revalidation report over a clean synthetic policy fixture;
- a hard-closed proof-harness admission report.

Reports contain hashes, byte/part/relationship counters, signature state and finding codes. They contain no document
body, prompt, tenant identifier, user identifier, credential or private key.

## Materialization

Create a new private empty host directory for every evidence generation, for example with
`install -d -m 0700 <generation-directory>`. Then, after the required `dev001` project/container/port inspection and
coordination locks, run:

```bash
export SUITE_GENOFFICE_QUICK_EDIT_PREFLIGHT_MODE=bundle
export SUITE_GENOFFICE_QUICK_EDIT_BUNDLE_HOST_DIR=./backups/genoffice-quick-edit-preflight/generation-01
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-quick-edit-preflight-control
```

The service has no network, a read-only root filesystem, all capabilities dropped, no-new-privileges, bounded PIDs,
CPU and memory, and only the Collabio control code plus output directory mounted. The output directory must be empty;
existing evidence is never overwritten.

Schemas are generated separately into a different clean 0700 output target with
`SUITE_GENOFFICE_QUICK_EDIT_PREFLIGHT_MODE=schema`. Both modes use only the explicit `/bundle` output mount; the
repository documentation tree is never writable in the container. The six checked-in schemas cover policy, corpus
manifest, single preflight, corpus evaluation, source-blind revalidation and harness admission.

## Expected result

The canonical evaluation must report:

- `allowed_fixture_count=3`;
- `rejected_fixture_count=16`;
- `expected_outcomes_matched=true`;
- `engine_executed=false` and `tenant_content_processed=false` in every report;
- no extracted archive, external network use or persistent document write;
- `harness_execution_allowed=false` with exactly the three current blockers from ADR-0071.

Any drift in fixture bytes, inventory, policy hash, expected finding, candidate hash or report binding fails closed.

## Claims deliberately not made

This evidence does not prove GenOffice execution, DOCX round-trip fidelity, Microsoft Word or LibreOffice compatibility,
safe export output, high-fidelity export output, authoritative package-signature validity, CDR of an edited candidate,
tenant isolation of an executable worker, pilot readiness or production readiness.

Those claims require a real two-person ADR-0070 authorization, a newly rebuilt and attested executable proof-harness
image, isolated no-egress runtime evidence, recorded cross-engine outputs and independent CDR-linked revalidation.

## Backup and recovery

Back up the policy, corpus bytes and manifest, all metadata-only reports and their schemas under `office_documents`.
Never back up scratch, transient extraction data, tokens, credentials or private signing keys. Recovery must reproduce
the exact policy/corpus/report hashes and must still show the harness gate closed unless a separately valid runtime
authorization and executable-harness admission are restored and revalidated.
