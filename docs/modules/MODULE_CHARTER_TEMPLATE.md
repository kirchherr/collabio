# Module Charter Template

Status: template
Date: YYYY-MM-DD
Module ID: `<module_id>`
Module kind: `<business_domain | platform_extension | integration | ai_extension>`
Owner: `<team-or-role>`

## 1. Product Decision

Describe why this module belongs in the suite and whether it is native, optional, required, or integration-only.

Required statement:

```text
The module is optional in normal use, but compliance obligations for existing data remain mandatory.
```

## 2. Module Lifecycle

Declare supported states:

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

Define what each state means for:

- normal user API
- admin API
- compliance API
- UI navigation
- feature workers
- compliance workers
- backup and restore
- export and e-discovery

## 3. Tenant Activation Model

Define:

- deployment installed state
- tenant entitlement rule
- tenant enablement rule
- required provisioning evidence
- required approval policy
- disable confirmation requirements
- suspend trigger
- decommission precheck

## 4. Feature Flags

List feature IDs and default states.

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `<module.feature>` | off | yes | `<notes>` |

## 5. API And Worker Gates

Every normal route and feature worker must require:

```text
Tenant Context
+ module state
+ feature permission
+ authorization policy
```

Document:

- public API prefixes
- admin API prefixes
- compliance API prefixes
- feature workers
- compliance workers
- destructive or external actions requiring explicit human confirmation

## 6. Persistent Objects

List every persistent object type.

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `<module.object>` | `<class>` | `<policy>` | `<scope>` | `<key>` | yes/no |

Every object must carry:

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
kms_key_ref
audit_chain_ref
source_system
schema_version
```

## 7. Data Classification And Retention

Map the module to canonical classes from `DATA_CLASSIFICATION.md`, such as:

- `gobd_record`
- `personal_data`
- `legal_hold`
- `working_data`
- `temporary`
- `security_data`
- `export_package`
- `rag_chunk`
- `embedding`
- `retrieval_trace`
- `ai_prompt`
- `ai_output`
- `tool_call`

Document retention policy IDs, disposal behavior, Legal Hold override behavior, and cryptoshred constraints.

## 8. Legal Hold

Define Legal Hold scopes:

- object scope
- related-object scope
- tenant scope if needed
- matter reference
- release and re-evaluation behavior

State which deletion, export, decommission, or AI actions Legal Hold blocks.

## 9. Audit Events

List audit event names for:

- module provisioning
- module enablement
- module disablement
- module suspension
- decommission request
- decommission blocked
- decommission completed
- import
- export
- destructive intent
- approval or rejection
- AI/RAG use if applicable

Normal logs must not contain prompt bodies, output bodies, personal data, document content, mail content, secrets, or raw transcripts.

## 10. Search, RAG, AI, And Voice

State whether the module supports:

- keyword search
- vector search
- RAG
- AI assist
- voice input

Rules:

- Search and vector backends return candidate IDs only.
- Authoritative ACL validation runs before source fetch.
- RAG answers cite source object IDs and versions.
- AI output is untrusted until validated or accepted.
- LLM providers must go through the Local LLM Gateway.
- External AI provider use must be enabled by tenant policy.
- Voice must be push-to-talk or explicitly activated.

## 11. Backup, Restore, And Failover

Declare continuity domain ownership.

| State | Continuity domain | Backup target | RPO | RTO | Restore evidence |
| --- | --- | --- | ---: | ---: | --- |
| `<state>` | `<domain>` | `<target>` | `<minutes>` | `<hours>` | `<evidence>` |

Required:

- restore drill expectations
- row-count or object-count checks where applicable
- checksum or manifest checks
- module state restore checks
- tenant isolation checks
- disabled-state restore checks
- Legal Hold restore checks
- degraded mode

## 12. Migrations And Imports

Document:

- module schemas
- migration catalog path
- checksum policy
- provisioning command
- import command if any
- validation report
- rollback or cutover decision points
- source-system archive strategy

Do not run schema migrations on first user request.

## 13. Decommissioning

Decommissioning must check:

- retention obligations
- Legal Hold state
- export obligations
- audit evidence
- backup/restore evidence
- approval policy
- tenant notification if applicable

Define blocked and completed outcomes.

## 14. UI Expectations

Document:

- normal navigation
- disabled module behavior
- suspended module behavior
- compliance-only entry points
- admin state display
- feature-flag display

UI hiding is never authorization.

## 15. Verification

Required tests:

- module disabled blocks normal API
- module enabled allows authorized API
- suspended state allows only configured read-only or compliance paths
- compliance workers continue when data exists
- feature workers stop when disabled
- tenant isolation and RLS
- retention and Legal Hold behavior
- backup/failover restore evidence
- search/RAG candidate-only behavior if applicable
- AI/voice policy behavior if applicable

## 16. Open Questions

List unresolved product, legal, compliance, security, migration, or operations questions.
