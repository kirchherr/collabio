# CRM/ERP Module Charter

Status: proposed
Date: 2026-06-11
Module ID: `crm_erp`
Module kind: `business_domain`
Owner: platform/product

## 1. Product Decision

CRM/ERP is a native optional suite module, not a separate side application. It must use the suite's tenant context, authorization, policy engine, audit, KMS, retention, Legal Hold, source object, search/RAG, AI control, backup, restore, and failover boundaries.

The module is optional in normal use, but compliance obligations for existing CRM/ERP data remain mandatory.

## 2. Lifecycle And Activation

Supported states:

```text
not_installed
installed
available
provisioning
enabled
disabled
suspended
decommission_requested
decommission_blocked
decommissioned
```

Activation has three separate concepts:

- Installed: code, migrations, and worker packages are present in the deployment.
- Entitled: a tenant is allowed to use the module.
- Enabled: a tenant can use normal CRM/ERP APIs, UI, and feature workers.

Disabled does not mean deleted. Disabled also does not stop retention, Legal Hold, audit, backup, restore, GoBD export, DSGVO workflows, or compliance-only admin access where policy allows it.

## 3. Feature Flags

Runtime feature IDs are fully qualified with the module prefix. Short names in product discussions must be normalized to the IDs below before they reach API or worker gates.

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `crm_erp.crm.accounts` | on | no | Customer and organization records |
| `crm_erp.crm.contacts` | on | no | Contact persons and relationship metadata |
| `crm_erp.crm.activities` | on | no | Activities, notes, and follow-ups |
| `crm_erp.erp.products` | on | no | Product and service catalog |
| `crm_erp.erp.suppliers` | on | no | Supplier records |
| `crm_erp.erp.orders` | on | no | Orders and order items |
| `crm_erp.erp.invoices` | on | no | Invoices and invoice items |
| `crm_erp.legacy_import.sqlserver` | off | yes | SQL Server import and cutover tooling |
| `crm_erp.gobd_export` | off | yes | GoBD/audit export packages |
| `crm_erp.legal_hold` | on | yes | Compliance feature, not user convenience |
| `crm_erp.rag_indexing` | off | yes | Only after source resolver and ACL checks exist |
| `crm_erp.ai_assist` | off | yes | Requires tenant AI policy and Local LLM Gateway |

The canonical registry lives in `app/suite/platform/crm_erp_subfeatures.py` and is documented in `docs/modules/CRM_ERP_SUBFEATURE_REGISTRY.md`.

## 4. API And Worker Gates

Every normal CRM/ERP route must require:

```text
Tenant Context
+ crm_erp enabled
+ feature permission
+ authorization policy
```

Initial API areas:

- `/v1/crm/accounts`
- `/v1/crm/contacts`
- `/v1/crm/activities`
- `/v1/erp/products`
- `/v1/erp/suppliers`
- `/v1/erp/orders`
- `/v1/erp/invoices`
- `/v1/crm-erp/migration/runs`
- `/v1/crm-erp/compliance/*`

Feature workers stop for disabled modules:

- CRM reminder worker
- ERP report worker
- CRM/ERP search indexing worker
- AI assist worker

Compliance workers continue when data exists:

- retention evaluation
- Legal Hold enforcement
- audit verification
- backup evidence verification
- GoBD/export preservation
- decommission precheck

## 5. Schemas And Object Types

Planned schemas:

```text
crm_erp
crm
erp
crm_erp_legacy
```

Initial object types:

```text
crm.account
crm.contact
crm.activity
crm.note
erp.product
erp.supplier
erp.order
erp.order_item
erp.invoice
erp.invoice_item
erp.delivery_note
erp.contract
legacy.row
```

Every object must carry the persistent object metadata required by `docs/ROADMAP.md` and `DATA_CLASSIFICATION.md`.

## 6. Data Classification And Retention

Canonical class mapping:

| CRM/ERP object | Data class | Retention direction |
| --- | --- | --- |
| Lead | `personal_data` | marketing or tenant policy |
| Contact person | `personal_data` | DSGVO workflow |
| Customer account | `personal_data` or `working_data` before record commit | contract or tenant policy |
| Supplier | `personal_data` or `working_data` before record commit | business policy |
| Order | `gobd_record` when tax/business relevant | GoBD retention |
| Invoice | `gobd_record` | GoBD retention |
| Invoice PDF | `gobd_record` and WORM candidate | GoBD/WORM |
| Contract | `gobd_record` or `legal_hold` when applicable | contract/legal retention |
| Dispute record | `legal_hold` | until hold release and re-evaluation |
| Import manifest | `security_data` | audit/evidence retention |
| Migration report | `security_data` or `export_package` | audit/evidence retention |

Before implementation, code and docs must use canonical data-class names from `DATA_CLASSIFICATION.md`.

## 7. Legal Hold

CRM/ERP Legal Hold scopes must support:

- all objects for one customer
- all invoices for one legal matter
- all orders connected to one project
- all contacts related to one account
- all imported legacy rows matching a source key
- all attachments or documents connected to ERP records

Legal Hold blocks deletion, cryptoshred, decommission completion, and any export narrowing that would omit held evidence.

## 8. SQL Server Migration

CRM/ERP includes a repeatable SQL Server import pipeline:

```text
SQL Server
  -> metadata discovery
legacy discovery manifest
  -> mapping evidence
crm_erp_legacy.*
  -> dry-run validation
crm.* / erp.*
  -> transform
business object registry
  -> classify
retention / legal hold / audit
  -> expose through API and UI
```

Migration evidence must include:

- source snapshot timestamp
- source table row counts
- discovery manifest hash
- mapping manifest hash
- quarantine decisions and `legacy.row` fallbacks
- target table row counts
- source checksums where possible
- target checksums
- mapping version
- manifest hash
- validation report
- initiator
- approver where required
- audit chain reference

## 9. Search, RAG, AI, And Voice

Initial search is classic filtered search. RAG indexing is not default.

Allowed flow:

```text
query
  -> candidate ids
  -> authoritative authorization
  -> source/object fetch
  -> redaction
  -> response or RAG context
```

AI assist is default-off. It may only run through the Local LLM Gateway, with tenant policy, prompt/output audit hashes, output validation, and human confirmation for destructive, external, or compliance-relevant actions.

Voice input is not part of the first CRM/ERP slice.

## 10. Backup, Restore, And Failover

Continuity domains:

- `module_registry_state`
- `crm_erp_business_records`
- `object_storage_records` for attached records, invoice PDFs, exports, and evidence packages
- `audit_evidence`
- `background_jobs_queues`

Restore drill must prove:

- module catalog restored
- tenant module state restored
- disabled module remains disabled
- enabled module works after restore
- CRM/ERP row counts and checksums match evidence
- migration reports restored
- audit chain verifies
- Legal Hold still blocks deletion
- RLS blocks cross-tenant access

## 11. UI Expectations

Initial UI areas:

- CRM accounts
- CRM contacts
- CRM activities and notes
- ERP products
- ERP suppliers
- ERP orders
- ERP invoices
- migration runs and validation reports
- compliance object lifecycle
- Legal Holds
- retention decisions
- export packages
- admin module status and feature flags

UI hiding is convenience only. Backend gates remain authoritative.

## 12. First Vertical Slice

First useful slice:

```text
module registry
  -> enable crm_erp for tenant
  -> import customers and contacts from SQL Server
  -> map to crm.accounts and crm.contacts
  -> expose GET /v1/crm/accounts
  -> show CRM account list
  -> disable module
  -> prove API and UI are blocked
  -> prove compliance/admin lifecycle view still works
  -> prove backup/restore keeps module state
```

## 13. Explicit Non-Goals For The First Slice

- full accounting engine
- tax filing automation
- payroll/HR
- autonomous AI actions
- automatic invoice sending by AI
- direct UI database access
- hard deletes from UI
- dynamic schema migrations from user requests
- external AI provider use as default
- full e-discovery export before audit/export model is ready

## 14. Verification

Required tests before implementation can be called complete:

- module disabled blocks normal CRM/ERP API
- enabled module still requires tenant context and feature permission
- suspended module exposes only configured compliance or read-only paths
- RLS blocks cross-tenant reads
- migration checksum mismatch blocks provisioning
- SQL Server import reports row counts and checksums
- retention and Legal Hold block protected disposition
- disabled module still runs compliance workers
- backup restore preserves module state
- search/RAG returns candidates only
- AI assist obeys tenant policy and human confirmation rules

## 15. Open Questions

- Which existing SQL Server schema is the first migration target?
- Which ERP objects are GoBD records from day one?
- Which CRM objects remain working data until explicit record commit?
- Which export format is required for the first GoBD/audit package?
- Which tenant roles can enable, disable, suspend, or decommission the module?
