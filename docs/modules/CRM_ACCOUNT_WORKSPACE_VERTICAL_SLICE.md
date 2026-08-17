# CRM Account Workspace Vertical Slice

Status: operational read workflow
Date: 2026-07-30

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

- `tests/test_crm_runtime.py`
- `tests/test_crm_workspace.py`
- `tests/test_crm_workspace_api.py`
- `tests/test_crm_accounts.py`
- `tests/test_crm_contacts.py`
- `tests/test_crm_activities.py`
