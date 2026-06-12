# CRM Activities And Notes Vertical Slice

Status: initial
Date: 2026-06-12

This slice extends the native CRM path after accounts and contacts. Activities and notes share the `crm_erp.crm.activities` feature gate because notes are part of the activity/follow-up surface in the module charter.

## Scope

- Module: `crm_erp`
- Feature gate: `crm_erp.crm.activities`
- APIs: `GET /v1/crm/activities`, `GET /v1/crm/notes`
- Persistent tables: `crm.activities`, `crm.notes`
- Object types: `crm.activity`, `crm.note`
- Classification: `personal`
- Retention policy: `rp-standard`

## Control Flow

```text
request tenant context
  -> module gate crm_erp + crm_erp.crm.activities
  -> tenant-scoped activity/note repository
  -> object read authorization
  -> linked object read authorization
  -> metadata-only response
  -> audit event without prompt, output, source text, note body, or raw payload body
```

## Persistence Contract

`0019_crm_activities_notes.sql` creates `crm.activities` and `crm.notes` with:

- tenant RLS and forced RLS
- tenant-scoped primary keys
- optional tenant-scoped FKs to accounts, contacts, and activities
- required object metadata from `docs/modules/CRM_ERP_OBJECT_RULES.md`
- Legal Hold and lifecycle fields
- KMS and audit-chain references
- update timestamp triggers
- no hard-delete policy or grant

## Runtime Contract

The APIs return only records for the current tenant and current user's authorized object IDs. If an activity or note references an account, contact, or activity the user cannot read, that relation is redacted from the response. Note bodies are intentionally not part of this slice; full note content must enter later through the source-object/content-resolver path with retention, redaction, search, and RAG controls.

Compliance, search, RAG, AI assist, import writes, attachments, body text, and destructive actions are outside this slice and must be added behind their own gates and evidence.

## Verification

- `tests/test_crm_activities.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
