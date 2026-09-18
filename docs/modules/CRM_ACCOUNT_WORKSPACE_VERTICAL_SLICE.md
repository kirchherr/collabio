# CRM Account Workspace Vertical Slice

Status: operational API and Work detail integration
Date: 2026-09-18

This slice moves CRM Accounts, Contacts, Activities, and Notes from isolated in-memory lists onto the shared PostgreSQL runtime and exposes one account-centered workflow. It remains metadata-only: note bodies and attachments are not released.

## Runtime Path

```text
request tenant context
  -> crm_erp.crm.accounts feature gate
  -> crm_erp.crm.contacts feature gate
  -> crm_erp.crm.activities feature gate
  -> PostgreSQL repository with forced tenant RLS
  -> authoritative object ACL filtering
  -> linked-object redaction
  -> account workspace response
  -> one metadata-only audit event
```

The API route is `GET /v1/crm/accounts/{account_object_id}/workspace`. An unreadable account and an absent account produce the same `404` response. Contacts, activities, and notes are included only when the object itself is readable and its relation belongs to the selected account workspace. Unreadable linked IDs are redacted.

## Daily Work Detail (Roadmap 251)

`/work` opens an account from the existing CRM list in a separate detail dialog. It uses the account-workspace route
as one authorized projection, showing account information, associated contacts and activities. Contact names,
email addresses and phone numbers remain personal data; metadata-only does not mean anonymous. The API retains
its existing note-metadata contract, but this UI adds no note-body or attachment surface.

All three CRM feature gates and the existing productivity-pilot traffic-scope dependency remain mandatory.
An account-list entry does not grant access to its children. Every child must be independently readable and match
the account relation; unreadable linked IDs remain redacted. A denied account is rejected before child repositories
are queried. JWT/OIDC permissions are resolved server-side, ignoring browser-supplied grants.

The detail dialog has loading, empty, blocked/unavailable, refresh and close states. It clears previous data before
refresh or after close/context changes and rejects late responses from a prior account or principal. User-provided
fields render as literal text. Long names and identifiers wrap within desktop/mobile viewports. The existing API
returns non-cacheable successful detail responses and safe route-local errors, including a generic 503 for database
failures; error text must not expose personal data or database details. Audit events contain IDs/counts, never field
values or note bodies.

The proof runs only in the guarded Work-E2E environment with synthetic records, real PostgreSQL repositories and
fresh database ACLs. The allowed test process retains its existing synthetic traffic override; the blocked process
must still reject CRM reads under the real route policy with the normal pilot switch closed.

This read integration adds no schema migration, business mutation, module activation, RAG indexing or AI execution.
The existing `crm_erp_business_records` continuity domain and PostgreSQL restore coverage remain applicable.

## PostgreSQL Runtime

`app/suite/platform/crm_runtime.py` implements one RLS-aware repository for:

- `crm.accounts`
- `crm.contacts`
- `crm.activities`
- `crm.notes`

The Compose API selects this repository through `SUITE_CRM_REPOSITORY_BACKEND=postgres`. The explicit `crm-runtime-bootstrap` service performs an idempotent development seed before API and backup execution. Its output contains counts and a hash only; no CRM field values or note content are emitted.

The CRM bootstrap is an explicit operation. Once its transaction is committed, CRM records are included in the same PostgreSQL backup and independent restore comparison as every future module table. The backup service intentionally does not invoke the bootstrap or migrations, so it can preserve a true pre-change database state.

## Deliberate Boundary

The read workflow remains the authoritative account-centered projection. The productive mutation boundary is now implemented by POST /v1/crm/account-onboardings: Account, Contact, Activity, metadata-only Note, four owner ACL grants, and an immutable receipt commit atomically. See CRM_ACCOUNT_ONBOARDING_VERTICAL_SLICE.md.

## Verification

Roadmap 251 passed full remote quality on `e966989` (Ruff, 653 formatted files, Mypy on 516 source files and full
Pytest) and all 60 isolated browser cases in 130.014 seconds, with no skipped, unexpected or flaky results. The ten
CRM cases cover current PostgreSQL ACLs, child filtering/redaction, feature/pilot denial, database failure/retry,
literal rendering, context races and desktop/mobile containment. Screenshots passed visual review. Evidence hashes
and the controlled development rollout are recorded in `docs/operations/DEV001_OPERATIONS_LOG.md`.

- `tests/test_crm_runtime.py`
- `tests/test_crm_workspace.py`
- `tests/test_crm_workspace_api.py`
- `tests/test_crm_accounts.py`
- `tests/test_crm_contacts.py`
- `tests/test_crm_activities.py`
- `tests/test_work_e2e_harness.py`
- `e2e/work/tests/crm.spec.mjs`
- `e2e/work/tests/crm-responsive.spec.mjs`
