# ADR-0058: Platform Module System

Status: accepted
Date: 2026-06-11

## Context

The suite is growing beyond the first Office, Mail, Search, RAG, AI, Audit, KMS, WORM, Retention, Legal Hold, and E-Discovery surfaces. Planned modules include CRM/ERP, knowledge base, LMS, tasks and activities, incident and ticket systems, and time tracking.

These modules must be optional per tenant, but their compliance obligations must not become optional. A disabled module may hide normal product navigation and reject ordinary user workflows, but it must not stop retention, Legal Hold, audit, backup, restore, export, GoBD, DSGVO, or decommissioning controls for existing data.

Feature flags alone are not enough. UI hiding is not authorization. Tenant-specific add-ons also create migration, backup, AI, search, RAG, audit, and lifecycle risks if every module invents its own activation model.

## Decision

Introduce a core-owned Platform Module System.

The platform owns:

- a global module catalog
- tenant module state
- tenant entitlement and enablement
- feature flags within a module
- server-side module gates for APIs, workers, and admin actions
- module-aware migrations and provisioning evidence
- lifecycle transitions for enable, disable, suspend, decommission request, blocked decommission, and completed decommission
- audit events for every compliance-relevant module lifecycle change

Every module must have a Module Charter before implementation. The charter must follow `docs/modules/MODULE_CHARTER_TEMPLATE.md` and define object types, data classes, retention policies, Legal Hold scopes, KMS expectations, audit events, backup/failover domains, migration behavior, AI/RAG behavior, UI behavior, worker behavior, and verification evidence.

The canonical module lifecycle states are:

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

Normal module routes and workers require:

```text
Tenant Context
+ module enabled or allowed compliance state
+ feature permission
+ ordinary authorization policy
```

The UI may call `GET /v1/platform/modules` to decide navigation, but the backend remains authoritative.

`collabio.module_catalog` and `collabio.tenant_modules` are the persistent source for API and worker gates in containerized development. The catalog stores required migration versions. Tenant module rows store migration evidence captured at provisioning time. API paths use tenant-scoped RLS through the app role; compliance workers use a narrow worker select policy for module discovery and then re-check each tenant with `ModuleWorkerGate`.

Module-aware migrations are deployment-time and provisioning-time operations. They must be checksummed, audited, and blocked on mismatch. A tenant module cannot be enabled before required migrations and provisioning evidence pass.

Decommissioning is a compliance workflow, not a delete button. It must check retention, Legal Hold, export obligations, audit evidence, backup/restore evidence, and approval policy before any data disposition.

The first business module is `crm_erp`. It proves the model with CRM entities, ERP entities, SQL Server legacy import, GoBD-relevant records, DSGVO workflows, Legal Hold scopes, module disable behavior, and restore evidence.

## Consequences

Easier:

- Future modules enter through one repeatable intake model.
- Tenant administrators get consistent module state and feature discovery.
- API and worker gates can be tested once and reused.
- Disable, suspend, and decommission semantics are explicit.
- Backup/failover, audit, retention, Legal Hold, KMS, search, RAG, and AI controls stay attached to every module.

Harder:

- Even small modules must define compliance metadata before implementation.
- Module migrations need a catalog and evidence path, not ad-hoc startup changes.
- Some disabled modules still need compliance-only admin surfaces.
- Decommissioning takes longer because it must prove obligations are cleared.

Required guardrails:

- UI visibility never counts as authorization.
- Disabled module does not mean deleted data.
- Compliance workers continue for disabled modules when data exists.
- Module data must use the suite persistent object model.
- Search and RAG return candidate IDs only until authoritative ACL validation, source fetch, redaction, and citation construction pass.
- LLM assistance for module data is default-off unless tenant AI policy allows it.
- External or destructive actions require explicit human confirmation.

## Alternatives Considered

### Feature flags only

Rejected because feature flags can hide navigation but do not define compliance state, migrations, restore evidence, decommissioning, or worker behavior.

### Separate application per module

Rejected for the core suite because separate apps would duplicate tenancy, policy, audit, KMS, retention, Legal Hold, search, RAG, and backup boundaries. External integrations may still exist later, but native modules must use the platform module model.

### Hard-coded modules without a registry

Rejected because tenant entitlement, enablement, provisioning evidence, and module lifecycle audit would become scattered product logic.

### Tenant-triggered dynamic schema migrations

Rejected because schema changes must not happen on first user request. Migrations must be controlled, checksummed, auditable, and safe to rehearse.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-001, CM-002, CM-003, CM-004, CM-005, CM-007, CM-008, CM-009, CM-010, CM-011, CM-012, CM-016, CM-017, CM-018, CM-019, CM-020
- `DATA_CLASSIFICATION.md`: `gobd_record`, `personal_data`, `legal_hold`, `working_data`, `security_data`, `export_package`, `rag_chunk`, `embedding`, `retrieval_trace`, `ai_prompt`, `ai_output`, `tool_call`
- `docs/operations/backup_failover_policy.json`: `module_registry_state`, `crm_erp_business_records`, `knowledge_base_content`, `learning_management_records`, `task_activity_records`, `service_ticket_records`, `time_tracking_records`
- DSGVO: privacy by design, data subject rights, restriction, deletion, access control
- GoBD: retention, immutability, procedural documentation, traceability for business records
- EU AI Act and OWASP LLM/GenAI: tenant policy, logging, human oversight, tool-use boundaries
- NIST CSF: Recover and Govern functions through explicit continuity domains and evidence

## Verification

- Module charter review is required before implementing a stateful module.
- Tests must prove disabled, enabled, suspended, and decommission-blocked behavior.
- API tests must prove server-side module gates, not only UI hiding.
- Worker tests must prove feature workers stop when disabled and compliance workers continue when required.
- Migration tests must prove checksum validation and provisioning blockade.
- Backup/failover tests must prove every stateful module has a continuity domain and restore evidence.
- Search/RAG tests must prove candidate-only retrieval and authoritative ACL checks.
- AI tests must prove tenant policy enforcement, output validation, and human approval for destructive or external actions.
- Docker Compose quality gate must pass for module-system changes.

## References

- `docs/ROADMAP.md`, Phase 11
- `docs/modules/MODULE_CHARTER_TEMPLATE.md`
- `docs/modules/CRM_ERP_MODULE_CHARTER.md`
- `docs/operations/BACKUP_FAILOVER.md`
- `docs/operations/backup_failover_policy.json`
