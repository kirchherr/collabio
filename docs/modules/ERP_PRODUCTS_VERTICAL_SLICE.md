# ERP Products Vertical Slice

Status: initial
Date: 2026-06-12

This slice is a deliberately small ERP architecture proof. It proves that the CRM/ERP module pattern also works for internal master data without starting order, invoice, tax, GoBD, or accounting workflows.

## Scope

- Module: `crm_erp`
- Feature gate: `crm_erp.erp.products`
- API: `GET /v1/erp/products`
- Persistent table: `erp.products`
- Object type: `erp.product`
- Classification: `internal`
- Retention policy: `rp-standard`

## Control Flow

```text
request tenant context
  -> module gate crm_erp + crm_erp.erp.products
  -> tenant-scoped product repository
  -> object read authorization
  -> metadata-only response
  -> audit event without prompt, output, source text, or raw payload body
```

## Persistence Contract

`0020_erp_products.sql` creates `erp.products` with:

- tenant RLS and forced RLS
- tenant-scoped primary key
- required object metadata from `docs/modules/CRM_ERP_OBJECT_RULES.md`
- `internal` data classification
- Legal Hold and lifecycle fields
- KMS and audit-chain references
- update timestamp trigger
- no hard-delete policy or grant

## Runtime Contract

The API returns only products for the current tenant and current user's authorized product object IDs. Normal use is blocked unless the tenant has provisioned and enabled `crm_erp` with `crm_erp.erp.products` enabled.

This slice intentionally stops at read-only product metadata. Suppliers, orders, invoices, GoBD records, prices, tax logic, stock, fulfillment, and accounting actions are outside this proof and must enter through separate scoped slices.

## Verification

- `tests/test_erp_products.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
