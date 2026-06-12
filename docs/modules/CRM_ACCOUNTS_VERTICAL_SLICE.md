# CRM Accounts Vertical Slice

Status: initial
Date: 2026-06-12

This slice is the first native CRM/ERP business-data path. It proves the shape that later contacts, activities, ERP products, orders, and invoices must follow.

## Scope

- Module: `crm_erp`
- Feature gate: `crm_erp.crm.accounts`
- API: `GET /v1/crm/accounts`
- Persistent table: `crm.accounts`
- Object type: `crm.account`
- Classification: `personal`
- Retention policy: `rp-standard`

## Control Flow

```text
request tenant context
  -> module gate crm_erp + crm_erp.crm.accounts
  -> tenant-scoped account repository
  -> object read authorization
  -> metadata-only response
  -> audit event without prompt, output, source text, or raw payload body
```

## Persistence Contract

`0017_crm_accounts.sql` creates `crm.accounts` with:

- tenant RLS and forced RLS
- tenant-scoped primary key
- required object metadata from `docs/modules/CRM_ERP_OBJECT_RULES.md`
- Legal Hold and lifecycle fields
- KMS and audit-chain references
- update timestamp trigger
- no hard-delete policy or grant

## Runtime Contract

The API returns only accounts for the current tenant and current user's authorized object IDs. Normal use is blocked unless the tenant has provisioned and enabled `crm_erp` with `crm_erp.crm.accounts` enabled. The response is metadata-only and includes `access_checked=true` on every row.

Compliance, search, RAG, AI assist, import writes, attachments, and destructive actions are outside this slice and must be added behind their own gates and evidence.

## Verification

- `tests/test_crm_accounts.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
