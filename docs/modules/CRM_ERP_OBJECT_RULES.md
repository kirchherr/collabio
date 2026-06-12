# CRM/ERP Schema And Object Rules

Status: initial

This document defines the canonical planning contract for CRM/ERP schemas and business object rules. It is intentionally a contract before real business tables or import writes exist.

Implementation:

- Code: `app/suite/platform/crm_erp_object_rules.py`
- Migrations: `app/suite/persistence/migrations/0016_crm_erp_schema_scaffold.sql`, `app/suite/persistence/migrations/0017_crm_accounts.sql`, `app/suite/persistence/migrations/0018_crm_contacts.sql`, `app/suite/persistence/migrations/0019_crm_activities_notes.sql`, `app/suite/persistence/migrations/0020_erp_products.sql`
- Tests: `tests/test_crm_erp_object_rules.py`, `tests/test_crm_accounts.py`, `tests/test_crm_contacts.py`, `tests/test_crm_activities.py`, `tests/test_erp_products.py`
- Cross-checks: `tests/test_crm_erp_subfeatures.py`, `tests/test_api.py`

## Planned Schemas

| Schema | Purpose | Notes |
| --- | --- | --- |
| `crm_erp` | module control | Migration runs, manifests, mapping evidence, validation reports, and module-local control metadata. |
| `crm` | CRM domain | Accounts, contacts, activities, and notes. |
| `erp` | ERP domain | Products, suppliers, orders, invoices, delivery notes, and contracts. |
| `crm_erp_legacy` | legacy staging | Metadata-only legacy rows, quarantine decisions, and source-row references until approved import exists. |

All schemas require tenant RLS, audit evidence, backup coverage, and restore validation. The schema plan does not allow raw SQL Server payload storage yet.

The `0016` migration creates the four schemas and the first tenant-scoped scaffold tables:

- `crm_erp.schema_plans`
- `crm_erp.object_type_rules`

These tables are manifest/evidence anchors, not business-data tables. They are RLS-protected, append-only by policy, and do not store source text, raw legacy payloads, prompts, snippets, or generated answers.

The `0017`, `0018`, `0019`, and `0020` migrations create the first persistent business tables:

- `crm.accounts`
- `crm.contacts`
- `crm.activities`
- `crm.notes`
- `erp.products`

`crm.accounts` implements the `crm.account` object-rule contract for the gated `/v1/crm/accounts` read slice. Rows include tenant, object, owner, source, classification, retention, Legal Hold, lifecycle, KMS, audit, and schema-version metadata, are protected by RLS, and have no hard-delete grant.

`crm.contacts` implements the `crm.contact` object-rule contract for the gated `/v1/crm/contacts` read slice. Contact rows use the same mandatory metadata and may reference `crm.accounts` through a tenant-scoped FK; API responses redact that relation unless the linked account object is readable.

`crm.activities` and `crm.notes` implement the `crm.activity` and `crm.note` contracts for gated `/v1/crm/activities` and `/v1/crm/notes` read slices. Both tables use mandatory metadata and tenant-scoped links to accounts, contacts, and activities. Notes are metadata-only in this slice; note bodies require a later source-object/content-resolver path.

`erp.products` implements the `erp.product` contract for gated `/v1/erp/products`. This table deliberately proves internal master-data handling without starting ERP order, invoice, tax, or GoBD workflows.

## Required Object Metadata

Every CRM/ERP object rule requires:

```text
tenant_id
object_id
object_type
owner_principal_id
created_by
created_at_utc
updated_at_utc
data_classification
retention_policy_id
legal_hold_state
lifecycle_state
kms_key_ref
audit_chain_ref
source_system
schema_version
```

These fields align the CRM/ERP module with `DATA_CLASSIFICATION.md`, the roadmap persistent-object contract, KMS, retention, Legal Hold, backup/restore, search, RAG, and audit.

## Initial Object Rules

| Object type | Schema | Table | Feature | Class | Retention | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `crm.account` | `crm` | `accounts` | `crm_erp.crm.accounts` | `personal` | `rp-standard` | Customer or organization record. |
| `crm.contact` | `crm` | `contacts` | `crm_erp.crm.contacts` | `personal` | `rp-standard` | Contact person and relationship metadata. |
| `crm.activity` | `crm` | `activities` | `crm_erp.crm.activities` | `personal` | `rp-standard` | Follow-ups, calls, meetings, tasks. |
| `crm.note` | `crm` | `notes` | `crm_erp.crm.activities` | `personal` | `rp-standard` | Notes are personal by default until policy narrows them. |
| `erp.product` | `erp` | `products` | `crm_erp.erp.products` | `internal` | `rp-standard` | Product and service catalog. |
| `erp.supplier` | `erp` | `suppliers` | `crm_erp.erp.suppliers` | `personal` | `rp-standard` | Supplier contacts may contain personal data. |
| `erp.order` | `erp` | `orders` | `crm_erp.erp.orders` | `gobd` | `rp-gobd-10y` | GoBD-relevant business record and WORM candidate. |
| `erp.order_item` | `erp` | `order_items` | `crm_erp.erp.orders` | `gobd` | `rp-gobd-10y` | Child record inherits order retention posture. |
| `erp.invoice` | `erp` | `invoices` | `crm_erp.erp.invoices` | `gobd` | `rp-gobd-10y` | GoBD-relevant business record and WORM candidate. |
| `erp.invoice_item` | `erp` | `invoice_items` | `crm_erp.erp.invoices` | `gobd` | `rp-gobd-10y` | Child record inherits invoice retention posture. |
| `erp.delivery_note` | `erp` | `delivery_notes` | `crm_erp.erp.orders` | `gobd` | `rp-gobd-10y` | Delivery evidence for orders. |
| `erp.contract` | `erp` | `contracts` | `crm_erp.erp.orders` | `gobd` | `rp-gobd-10y` | Contract evidence, later expandable by contract type. |
| `legacy.row` | `crm_erp_legacy` | `legacy_rows` | `crm_erp.legacy_import.sqlserver` | `confidential` | `rp-restricted` | Quarantined metadata-only fallback for unknown source tables. |

## Non-Negotiable Rule Defaults

- Tenant RLS is required for every planned schema and object.
- KMS key references are mandatory before persistence.
- Audit chain references are mandatory before persistence.
- Legal Hold support is on for every object type from day one.
- Search is candidate-only; no object rule may expose raw source text or snippets from the index.
- RAG indexing remains default-off and may only run after source resolver, ACL validation, redaction, and audit trace exist.
- Raw import payload storage is not allowed in this planning contract.
- Destructive actions require explicit approval and cannot bypass retention or Legal Hold.
- GoBD objects require `rp-gobd-10y`, record lifecycle state, and WORM-candidate posture.

## Drift Rules

The object-rule manifest is checked against:

- CRM/ERP target profiles from legacy mapping.
- CRM/ERP subfeature registry coverage.
- Required metadata fields.
- Schema ownership of object types.

If any of these drift, tests fail before we add tables, APIs, or import writes.
