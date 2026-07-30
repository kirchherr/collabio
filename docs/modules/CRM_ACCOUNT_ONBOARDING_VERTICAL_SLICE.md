# CRM Account Onboarding Vertical Slice

Status: operational write workflow
Date: 2026-07-30

This slice is the first productive CRM write workflow. It creates one account-centered aggregate while keeping authorization state and acceptance evidence inside the same PostgreSQL transaction.

## API Contract

`POST /v1/crm/account-onboardings` requires:

- an authenticated tenant context
- enabled `crm_erp.crm.accounts`, `crm_erp.crm.contacts`, and `crm_erp.crm.activities` features
- a server-side `tenant-admin`, `crm-manager`, or `crm-operator` role
- a tenant-unique namespaced `mutation_reference`

The command creates one Account, Contact, planned Activity, and metadata-only Note. Note bodies, attachments, destructive transitions, external effects, and LLM actions are outside this endpoint.

## Atomic Boundary

```text
request tenant and operator context
  -> all three CRM feature gates
  -> server-side operator role gate
  -> actor-bound command hash
  -> PostgreSQL advisory transaction lock
  -> Account + Contact + Activity + Note
  -> four user/admin object ACL entries
  -> append-only account onboarding receipt
  -> commit
  -> metadata-only global audit event
```

The transaction runs through the isolated `collabio_authz_admin` database role. Migration `0057` grants this role only `SELECT` and `INSERT` on the five CRM relations needed by the unit of work. The normal application role does not receive ACL write permission.

Migration `0058` reconciles the stored, checksum-bound `0057` evidence into already provisioned CRM tenant states during controlled upgrades. It does not change lifecycle status, feature switches, operator attribution, or the existing lifecycle audit reference.

The immutable receipt contains object IDs, ACL reference strings, actor ID, command hash, receipt hash, and audit-chain reference. It contains no account name, contact details, activity subject, note title, note body, prompt, output, or attachment data.

## Idempotency And Failure Semantics

The primary idempotency key is `(tenant_id, mutation_reference)`. Its command hash is bound to the creating actor. Repeating the same command by the same actor returns the existing receipt; a changed command or actor returns `409 Conflict`.

Any unique-key, foreign-key, RLS, ACL, or receipt failure rolls back all business rows and ACL rows. No partially authorized CRM aggregate is accepted.

## Backup And Restore

`crm.account_onboarding_receipts` is included in the PostgreSQL backup automatically. Restore acceptance additionally verifies:

- all four CRM business tables and the receipt table exist
- Forced RLS is enabled on all five relations
- the receipt has no-update and no-hard-delete policies
- `collabio_authz_admin` has `SELECT` and `INSERT`, but no `UPDATE` or `DELETE`, on each CRM relation
- source and isolated restore target have identical relation, policy, grant, migration, and exact row-count manifests

## Verification

- `tests/test_crm_onboarding.py`
- `tests/test_crm_onboarding_api.py`
- `tests/test_crm_onboarding_migration.py`
- `tests/test_postgres_restore_drill.py`
- `ARCHITECTURE_DECISIONS/ADR-0059-atomic-business-data-acl-receipt.md`
