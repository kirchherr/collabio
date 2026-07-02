# LMS Module Charter

Status: proposed
Date: 2026-06-29
Module ID: `lms`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

The Learning Management System is a native optional suite module for governed training catalogs, enrollments, mandatory training evidence, completion status, and later certificates.

The module is optional in normal use. Compliance obligations for existing training records, completion evidence, Legal Hold, retention, backup, restore, export, and audit remain mandatory.

The first slice is intentionally small: course catalog metadata plus enrollment status. It does not include authoring, tests, certificates, automations, notifications, content playback, SCORM/xAPI runtime, RAG, AI assist, or external LMS integrations.

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

Disabled stops normal course and enrollment browsing. Disabled does not stop retention, Legal Hold, audit, backup, restore, export, decommission evidence, or compliance-only administration for existing training records.

## 3. Feature Flags

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `lms.courses.read` | on | no | Course catalog metadata and lifecycle state |
| `lms.enrollments.read` | on | no | Current user's enrollment and completion status metadata |
| `lms.completion_evidence.read` | off | yes | Compliance read path for completion evidence and held records |
| `lms.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `lms.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

The canonical registry lives in `app/suite/platform/lms_module.py`.

## 4. API And Worker Gates

Every future normal LMS route must require:

```text
Tenant Context
+ lms enabled
+ feature permission
+ object authorization
```

Initial planned API:

- `GET /v1/lms/courses`
- `GET /v1/lms/enrollments`

Compliance-only later:

- completion evidence read
- retention evaluation
- Legal Hold enforcement
- certificate/export evidence
- decommission precheck

No LMS API route is enabled by this charter. Module catalog registration and migration evidence must happen before any route or worker is wired.

## 5. Persistent Objects

First planned object types:

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `lms.course` | `internal` | `rp-standard` | course and related enrollments | tenant + class | optional |
| `lms.enrollment` | `personal` | `rp-standard` | learner, course, training campaign | tenant + class | yes |
| `lms.completion_evidence` | `personal` | `rp-standard` | learner, course, certificate evidence | tenant + class | yes |

Every object must carry the required metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, including tenant, object ID, object type, owner, classification, retention policy, Legal Hold state, lifecycle state, KMS key reference, audit-chain reference, source system, and schema version.

The canonical first object-rule contract lives in `app/suite/platform/lms_module.py`.

## 6. Search, RAG, AI, And Voice

Initial state:

- keyword search: off
- vector search: off
- RAG: off
- AI assist: off
- voice: off

Future search and RAG must return candidate IDs only, validate authoritative ACLs before source fetch, cite `lms.course`, `lms.enrollment`, and source versions, and audit retrieved context, model ID, tool calls, and output hashes without writing prompt or output bodies to normal logs.

AI providers must go through the Local LLM Gateway. Cloud AI provider use requires tenant policy enablement.

Voice input is not part of the first LMS slice.

## 7. Backup, Restore, And Failover

Continuity domain: `lms_training_records`

Required evidence:

- module state restore check
- course row-count check
- enrollment row-count check
- completion evidence row-count check
- source-version or evidence hashes where content is referenced
- tenant isolation check after restore
- disabled-state restore check
- Legal Hold restore check
- restore evidence hash for `lms_training_records`
- approval-record store restore check for `lms.package_install_approval_records`

New course content stores, assessments, certificate files, search indexes, RAG chunks, embeddings, approvals, exports, or integrations must update this continuity domain in the same change.

## 8. Migrations And Imports

The first LMS migrations now register the module as `not_installed`, create only the metadata needed for `lms.course` and `lms.enrollment`, and prepare an append-only package-install approval-record store. `0046_lms_metadata_schema.sql` stays metadata-only with RLS, no hard delete, required metadata, KMS references, audit-chain references, and no training content body columns. `0047_lms_package_install_approval_records.sql` stores only tenant-scoped refs, hashes, approver metadata, restore evidence and audit-chain references; it forbids package-install execution, tenant module state creation, LMS runtime activation, content payloads, destructive actions and external side effects. The package-installation execution boundary, executor skeleton, dry-run plan and dry-run execution boundary remain metadata-only and review only hashes, refs and explicit tenant-admin intent before a separate future dry-run execution or installer can be designed.

Future imports must run metadata discovery, dry-run validation, row counts, checksums, quarantine, and approval before content import.

## 9. Decommissioning

Decommissioning requires:

- disabled or suspended normal use
- retention evaluation
- Legal Hold check
- export/archive decision
- audit evidence
- backup/restore evidence
- completion-evidence disposition evidence
- explicit approval

Missing or blocked evidence leaves the module in `decommission_blocked`.

## 10. Catalog Readiness Boundary

The LMS module is registered in the global module catalog as `not_installed`. `GET /v1/platform/modules/families/lms/catalog-readiness` exposes the catalog boundary, `GET /v1/platform/modules/families/lms/restore-drill-evidence` exposes the metadata-only restore evidence hash, `GET /v1/platform/modules/families/lms/tenant-admin-package-approval-gate` exposes the metadata-only human approval boundary, `POST /v1/platform/modules/families/lms/tenant-admin-package-approval-records` records an explicit tenant-admin approval as refs and hashes only, `GET /v1/platform/modules/families/lms/package-installation-readiness` exposes the next package-installation gate, `POST /v1/platform/modules/families/lms/package-installation-execution-boundary` reviews the execution boundary without executing installation, `POST /v1/platform/modules/families/lms/package-installation-executor-skeleton` prepares the non-executing installer skeleton, `POST /v1/platform/modules/families/lms/package-installation-dry-run-plan` prepares the non-executing dry-run plan, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-boundary` reviews the dry-run execution boundary, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-skeleton` prepares the dry-run execution skeleton, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-implementation-review` reviews the future dry-run executor implementation, and `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-contract`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-gate`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-request-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-runtime-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-preflight` define the future dry-run receipt fields without executing a dry-run. These endpoints are tenant-scoped and metadata-only. They return manifest hashes, migration-version evidence, object-rule counts, continuity-domain evidence and required gate evidence only. They do not install the module package, register LMS business APIs, create content, run workers, create tenant module state, or activate tenant runtime. The first metadata schema migration `0046_lms_metadata_schema.sql` creates only `lms.courses` and `lms.enrollments` metadata with RLS, Legal Hold, retention, KMS and audit references; package installation remains blocked until a separate future dry-run execution request boundary is prepared after the dry-run execution gate.

## 11. Explicit Non-Goals For The First Slice

- course authoring
- tests and grading
- certificates
- SCORM/xAPI runtime
- notifications or reminders
- automations
- RAG answer generation
- AI tutoring
- external LMS synchronization
- payroll or HR writes

## 12. Verification

- `tests/test_lms_module_foundation.py`
- `tests/test_lms_catalog_readiness.py`
- `tests/test_lms_package_installation_readiness.py`
- `tests/test_lms_restore_drill_evidence.py`
- `tests/test_lms_tenant_admin_package_approval_gate.py`
- `tests/test_lms_tenant_admin_package_approval_record.py`
- `tests/test_pgvector_migration.py`
- `tests/test_module_family_backlog.py`
- `tests/test_module_implementation_contract.py`
