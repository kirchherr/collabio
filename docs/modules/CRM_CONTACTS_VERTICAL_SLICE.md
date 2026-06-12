# CRM Contacts Vertical Slice

Status: initial
Date: 2026-06-12

This slice extends the native CRM/ERP business-data path after accounts. It keeps the same runtime contract and adds safe handling for contact-to-account relations.

## Scope

- Module: `crm_erp`
- Feature gate: `crm_erp.crm.contacts`
- API: `GET /v1/crm/contacts`
- Persistent table: `crm.contacts`
- Object type: `crm.contact`
- Classification: `personal`
- Retention policy: `rp-standard`

## Control Flow

```text
request tenant context
  -> module gate crm_erp + crm_erp.crm.contacts
  -> tenant-scoped contact repository
  -> contact object read authorization
  -> linked account read authorization
  -> metadata-only response
  -> audit event without prompt, output, source text, or raw payload body
```

## Persistence Contract

`0018_crm_contacts.sql` creates `crm.contacts` with:

- tenant RLS and forced RLS
- tenant-scoped primary key
- optional tenant-scoped FK to `crm.accounts`
- required object metadata from `docs/modules/CRM_ERP_OBJECT_RULES.md`
- Legal Hold and lifecycle fields
- KMS and audit-chain references
- update timestamp trigger
- no hard-delete policy or grant

## Runtime Contract

The API returns only contacts for the current tenant and current user's authorized contact object IDs. If a contact references an account the user cannot read, the account relation is redacted from the response. Normal use is blocked unless the tenant has provisioned and enabled `crm_erp` with `crm_erp.crm.contacts` enabled.

Compliance, search, RAG, AI assist, import writes, attachments, and destructive actions are outside this slice and must be added behind their own gates and evidence.

## Verification

- `tests/test_crm_contacts.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
