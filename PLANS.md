# Plans

This file tracks the active implementation sequence. The canonical roadmap is `docs/ROADMAP.md`.

## Current Journey

Theme: Turn the proven foundation into coherent product workflows without weakening its gates.

User priority (2026-09-18): Office development comes before further CRM expansion. Continue native document and version
workflows; keep DOCX Quick Edit/fidelity on its separate gated path. Defer CRM account onboarding in `/work` and
subsequent CRM mutations until after the Office work.

Current sprint:

1. [x] Research baseline, stack candidates, and ADR backlog.
2. [x] Product charter, security policy, threat model, compliance matrix.
3. [x] Data classification, retention policies, legal hold model.
4. [x] ADR template and initial ADRs.
5. [x] Phase 0 engineering tooling.
6. [x] Request-scoped tenant context.
7. [x] Append-only audit model.
8. [x] File-backed policy, registry, and audit stores.
9. [x] Admin API for tenant AI settings and allowed models.
10. [x] Prompt-injection and unauthorized-RAG-output tests.
11. [x] Direct LLM provider bypass architecture guards.
12. [x] ADR for pgvector vs. Qdrant.
13. [x] First pgvector embedding metadata migration and tests.
14. [x] PostgreSQL/pgvector dev service, migration runner, and live RLS tests.
15. [x] pgvector adapter for upsert, lifecycle transitions, and candidate-only search.
16. [x] Vector reindex and deletion-propagation worker entry points.
17. [x] Source resolver and text extraction pipeline feeding the pgvector worker.
18. [x] Vector worker audit events and exact-search benchmark fixtures.
19. [x] Office/mail core architecture and parser worker boundary behind text extraction.
20. [x] Suite-wide backup/failover continuity culture, policy, and dev backup verification commands.
21. [x] Isolated rich-document parser service for DOCX, ODT, and basic text PDF extraction.
22. [x] Source object metadata model and RAG resolver for documents, mails, attachments, comments, wiki content, and procedure documentation.
23. [x] Storage write guard for tenant, classification, retention policy, KMS key reference, manifest hash, and content hash.
24. [x] S3/MinIO-compatible storage adapter ADR, bucket profiles, Object Lock posture, and manifest restore checks.
25. [x] Retention defaults and RetentionManifest model for storage, legal hold, WORM, backup, and e-discovery.
26. [x] Legal Hold API boundary for source object versioning and retention-manifest re-evaluation.
27. [x] Reusable content hash verification for source object writes, reads, restore drills, parser inputs, and exports.
28. [x] Storage object manifest model and restore verification for object records.
29. [x] KMS adapter boundary, canonical key references, rotation evidence, and destruction guards.
30. [x] Envelope encryption API with local dev implementation, manifests, AAD binding, and destroyed-key rejection.
31. [x] Key rotation interface connected to envelope rewrap manifests and restore evidence.
32. [x] Cryptographic shredding simulation with GoBD, legal-hold, retention, and KMS destruction gates.
33. [x] Restore-test framework for storage, envelope, retention, KMS, and cryptoshred evidence.
34. [x] Vector metadata schema validation and ACL-version propagation hardening.
35. [x] Vector benchmark thresholds, report hashes, and ANN candidate decision gates.
36. [x] Durable deployment audit storage for vector worker events.
37. [x] Embedding model versioning registry checks before production indexing.
38. [x] Production-grade embedding model registry administration and approval audit events.
39. [x] Platform Module System ADR, module charter template, and initial CRM/ERP module charter.
40. [x] Compliance matrix controls for optional module lifecycle, migration, retention, Legal Hold, and decommissioning.
41. [x] Platform module catalog and tenant module state core model with SQL migration and gatekeeping tests.
42. [x] Tenant-secure `GET /v1/platform/modules` discovery endpoint.
43. [x] Tenant-admin module lifecycle APIs for provision, enable, disable, suspend, and decommission precheck.
44. [x] Decommission Request API with retention, Legal Hold, export, audit, and backup evidence references.
45. [x] Decommission Blocked/Completed workflow with final disposition evidence.
46. [x] Decommission Cancel/Reopen workflow with explicit approval and audit evidence.
47. [x] Server-side module gates for API routers and workers.
48. [x] Module-aware migration catalog with checksums, evidence, and startup mismatch blockade.
49. [x] Module provisioning connected to migration manifest evidence with missing-startup-migration blockade.
50. [x] Legacy SQL Discovery and Import Evidence Framework for metadata-only legacy source assessment.
51. [x] Isolated SQL Server metadata adapter worker with connector policy, secret-reference boundary, and metadata-only query plan.
52. [x] CRM/ERP legacy mapping evidence for discovered tables, target object candidates, `legacy.row` fallbacks, and quarantine decisions.
53. [x] CRM/ERP subfeature registry for accounts, contacts, activities, products, suppliers, orders, invoices, import, export, Legal Hold, RAG, and AI assist gates.
54. [x] Review intake P0 hardening: dev header auth production block, RAG source data-class propagation, and local dev KMS/envelope production block.
55. [x] Signed JWT PrincipalResolver with server-side tenant membership, roles, groups, and object ACL resolution.
56. [x] Static OIDC/JWKS verifier with RS256 key selection, issuer/audience allowlists, replay guard, and health reporting.
57. [x] Dynamic OIDC discovery, JWKS refresh scheduling, key-cache expiry, outage policy, and persistent replay store.
58. [x] PostgreSQL/RLS-backed PrincipalResolver, tenant membership, role, group, object ACL, and ABAC stores with audit-chain references.
59. [x] PostgreSQL/RLS-backed JWT replay store with tenant-aware accepted/replayed events and no token-body storage.
60. [x] Canonical DataClass registry with runtime, retention, KMS, DB constraint, prompt/model registry, and docs drift tests.
61. [x] PostgreSQL/RLS-backed append-only audit store with isolated writer role, tenant-local sequencing, HMAC checkpoints, and WORM export evidence.
62. [x] Authorized ChunkRepository retrieval for RAG so prompts receive exact authorized chunks instead of whole source documents.
63. [x] Audited authz administration APIs with a dedicated PostgreSQL admin role for principal, role, group, ACL, ABAC, and replay-retention mutations.
64. [x] Keyword Indexer Boundary with candidate-only API results and Search Audit Events.
65. [x] CRM/ERP schema and object-rule registry for `crm_erp`, `crm`, `erp`, and `crm_erp_legacy`.
66. [x] Persistent CRM/ERP schema scaffold migration with RLS-protected schema and object-rule manifest tables.
67. [x] First gated CRM accounts read vertical slice with `crm.accounts`, audit, and `GET /v1/crm/accounts`.
68. [x] Gated CRM contacts read vertical slice with `crm.contacts`, account-link redaction, audit, and `GET /v1/crm/contacts`.
69. [x] Gated CRM activities/notes read vertical slice with `crm.activities`, `crm.notes`, link redaction, audit, and metadata-only notes.
70. [x] Minimal ERP products read vertical slice with `erp.products`, internal classification, audit, and `GET /v1/erp/products`.
71. [x] Reusable module implementation contract for knowledge base, LMS, tasks, tickets, time tracking, and later suite modules.
72. [x] First Knowledge Base metadata/read slice with `knowledge_base`, `kb.article`, `kb.article_version`, RLS, audit, and `GET /v1/kb/articles`.
73. [x] Knowledge Base source-version and restore evidence hardening for manifest hash, content hash, ACL version, disabled-state restore, and Legal Hold restore checks.
74. [x] Admin compliance read path for Knowledge Base source-version and restore evidence with disabled-state access and metadata-only audit.
75. [x] Knowledge Base write/edit approval command model and audit-only dry-run endpoint without persistence or RAG indexing.
76. [x] Persistent Knowledge Base write-approval evidence ledger migration and ledger-ready dry-run evidence hash.
77. [x] Knowledge Base write-dry-run approval evidence persistence through append-only ledger port with Postgres adapter.
78. [x] Knowledge Base source-object write guard that validates ledger evidence, expected version, retention, Legal Hold, restore evidence, and source metadata before future writes.
79. [x] Knowledge Base approval-state transition from dry-run to append-only `approved_for_write` evidence with lineage and no article/source writes.
80. [x] Metadata-only Knowledge Base restore/source evidence refresh preview for approved writes, still without article/source writes or RAG indexing.
81. [x] Guarded Knowledge Base write-execution skeleton with approved evidence, source-guard decision, refresh-preview hash, explicit human confirmation, and no article/source writes.
82. [x] Atomic Knowledge Base edit-write execution path that persists the source object, updates article/version metadata, refreshes source/restore evidence, and keeps RAG/indexing disabled.
83. [x] Trusted Knowledge Base create metadata in approval evidence plus guarded in-memory create execution, with RAG/indexing still disabled.
84. [x] PostgreSQL-backed Knowledge Base article/version/source-evidence/restore-evidence transaction adapter for guarded create/edit writes.
85. [x] Durable metadata-only source-object write receipts with PostgreSQL/RLS store, API execution evidence, and backup/failover coverage.
86. [x] PostgreSQL/RLS source-object metadata and storage-manifest bridge with explicit content-store interface.
87. [x] Coordinated Knowledge Base write unit-of-work that binds source-object receipts, source metadata, storage manifests, article/version metadata, source-version evidence, and restore evidence.
88. [x] Shared PostgreSQL metadata transaction for Knowledge Base write unit-of-work across receipts, source metadata/storage manifests, and article/version/source/restore evidence.
89. [x] Content-store recovery evidence for Knowledge Base writes with inventory comparison, orphan detection, restore-drill hash, and API-wiring gate signal.
90. [x] S3/MinIO-compatible content-store adapter port with Object-Lock/WORM capability checks, metadata-only orphan-reconciliation worker output, and clean recovery-evidence gate for `PostgresKnowledgeBaseWriteUnitOfWork`.
91. [x] Knowledge Base production write deployment gate that requires clean source-content recovery evidence, S3/MinIO provider-profile evidence, and bound restore-drill evidence before Postgres UoW API wiring can be enabled.
92. [x] Concrete boto3/MinIO-compatible SDK client behind `S3CompatibleObjectStoreClient`, Compose `object-storage` profile, bucket bootstrap, and provider-profile evidence check service.
93. [x] Default API runtime on PostgreSQL source manifests plus S3-compatible exact-version content, with isolated test database and metadata-only runtime report.
94. [x] Exact-version restore drill to an independently addressed MinIO target with source/target version reads, manifest/content verification, Object Lock, Legal Hold, and metadata-only report.
95. [x] Backend storage foundation gate that binds the current restore report to a freshly recomputed persistent runtime report.
96. [x] Isolated PostgreSQL restore drill with checksum-bound loader receipt, exact schema/row-count comparison, migration catalog validation, RLS, roles, and grants.
97. [x] Metadata-only backend foundation completion gate combining Tenant/IAM, append-only Audit, Module Registry, PostgreSQL recovery, persistent SourceObjects, and exact-version object restore.
98. [x] Separate hash-only real-user pilot closure with append-only PostgreSQL/RLS evidence, complete observation and receipt manifests, safe zero-activity closure, API audit metadata, and restore coverage.
99. [x] Fail-closed production continuity deployment gate for PostgreSQL PITR/WAL, encrypted immutable offsite recovery, fenced HA promotion, cross-site PostgreSQL/Object Storage/KMS recovery, fresh three-party approvals, and runtime-switch binding without deployment or failover execution.
100. [x] Tenant-bound Security-Admin evidence-requirements and gate-status read models for accountable production continuity collection, with normalized fail-closed states, metadata-only audit, and no upload, mutation, deployment or failover surface.
101. [x] Tenant-safe real-user pilot readiness read model that revalidates the current nomination-to-closure hash chain, separates stale prior-cycle evidence, identifies the next admissible step, and performs no activation or write.
102. [x] Consolidated Tickets & Incidents controlled-pilot status with authoritative approval-boundary hashing, persisted receipt-chain validation, exact next human confirmation, and no activation or content surface.
103. [x] PostgreSQL/RLS-backed append-only persistence and restore coverage for the first Tickets & Incidents tenant activation-readiness approval.
104. [x] First end-user Work surface over the existing guarded Tasks, Time, Tickets, Knowledge Base, and CRM APIs, with partial-failure isolation and explicit business mutations.
105. [x] Append-only task lifecycle workflow with atomic status activities, optimistic state checks, database-enforced hash-chain continuity, exact destructive confirmation, restore coverage, API, and Work UI actions.
106. [x] Append-only time-entry submission and maker-checker approval workflow with database-enforced chain integrity, hash-only exact confirmation, restore coverage, API, and Work UI actions.
107. [x] Append-only task reassignment and due-date amendments with optimistic checks, active-principal validation, precise ACL rebinding, activity evidence, shared serialization with lifecycle transitions, restore coverage, API, and Work UI actions.
108. [x] Versioned time-entry correction and resubmission bound to the exact correction-request and correction hashes, with database enforcement, restore coverage, API, and Work UI actions.
109. [x] Isolated browser-level `/work` proof with 32 deterministic desktop/mobile cases across ready, empty, blocked, and unavailable domain states, the real task-reassignment and time-correction workflow, production route-policy checks, and a fully closed pilot runtime.
110. [x] Guarded Knowledge Base create/edit in `/work` with server-prepared source metadata, authoritative ACLs, explicit approval/confirmation, tenant-serialized PostgreSQL/S3 writes, conflict/failure recovery, migration 0082 ACL restore verification, and 41 passing isolated browser cases; full remote quality and backup/restore/release gates passed with pilot and indexing closed.
111. [x] Complete Knowledge Base reading in `/work`: authorized non-admin readers open exact current article content with the read feature alone, safe plain-text rendering, integrity checks and context-safe refresh; full remote quality and 50 isolated browser cases pass, with pilot/indexing closed and existing write controls preserved.
112. [x] Bring the existing CRM account workspace into `/work`: authorized account details, associated contacts and activities, explicit empty/blocked/unavailable states, safe refresh and context handling; full remote quality and 60 isolated browser cases pass with current PostgreSQL ACLs and the existing pilot boundary closed.

113. [x] Complete the native Office product foundation at `/office`: rich-text editing, tables, outline, search, focus mode, confirmed version saves, current ACLs, PostgreSQL/S3, CAS and exact retries. Backend quality passed on `7bba74f`; all 73 browser cases and nonempty recovery passed on `5917bdf`, with desktop/tablet/mobile visual review. Migration 0083 and the 83-migration/91-table foundation gate passed; ordinary tenant activation, pilot, indexing and DOCX engine gates remain closed. Business/API rollout verification is recorded separately.
114. [x] Compare authorized saved Office versions, including text, titles, formatting, lists and tables, and take an earlier version into a new local draft. Refresh the current head and capabilities; require a confirmed CAS save to append without rewriting history. Full remote quality and all 100 checks (88 browser cases plus 12 comparison-model cases) pass on `3aa0069`, including desktop/tablet/mobile review, current access removal, late responses, partial history and no-op takeover. Existing migration/recovery contracts and closed tenant/pilot/engine gates remain unchanged.
115. [x] Complete native Office find and replace: literal Unicode-safe positions, case/whole-word options, full counts and current/all replacement as one reversible local edit. Preserve structure, outside formatting, limits and read-only/history boundaries. Loaded content stays outside undo history. Full remote quality and all 132 checks (97 browser cases plus 35 model cases) pass on `f4c37e5`; desktop/tablet/mobile visually reviewed. Existing confirmed CAS saves and closed tenant/pilot/engine gates remain unchanged.

116. [x] Complete contextual native Office table editing: configurable insertion, row/column operations, first-row headers, cell/row/column/table selection and bounded keyboard navigation. Validate prospective changes before dispatch, separate each edit in undo history, confirm removals and preserve current read-only/history/save-state boundaries. Full remote quality and all 142 checks (107 browser cases and 35 model cases) passed on `e3cf88c`, preserving the previous 132. Desktop/tablet/mobile reviewed; entering tablet width closes the inspector to keep the table visible. Existing schema, recovery and closed tenant/pilot/engine gates remain unchanged.

117. [x] Complete version-bound native Office review discussions: confirmed create/reply/resolve/reopen, server-validated text anchors, fresh parent ACLs, thread revision conflicts and exact retries, backed by immutable PostgreSQL/S3 event evidence. Full quality passed on `2305a96` (Ruff/format across 674 files, Mypy across 532 files and full Pytest); all 152 checks (117 browser cases and 35 model cases) passed on `7400b35` in 432.486 seconds, with zero skipped, unexpected or flaky cases. Migration 0084, the 84-migration/93-table foundation and nonempty isolated recovery of 57 documents, 93 versions, nine review threads and 17 events passed. API rollout, health and cleanup were verified green at 2026-09-18 13:14:20 UTC. Ordinary tenant activation, pilot, indexing and DOCX/engine gates remain closed.

118. [x] Complete saved-version native Office text suggestions: confirmed creation, literal before/after review, atomic acceptance/new document version, immutable rejection, current ACLs, exact retries and version conflicts. Full quality passed on `9c17a31` (684 formatted files, Mypy 541 sources and full Pytest); 688 focused tests passed and all 162 browser/model checks passed in 535.956 seconds, preserving the prior 152 with zero skipped, unexpected or flaky results. Migration 0085, 85-migration/95-table foundation and nonempty PostgreSQL/S3 recovery verified 67 documents, 109 versions, ten suggestions and seven decisions (five accepted, two rejected). API rollout, thirteen Office operations, health and cleanup passed at 2026-09-21 07:18:57 UTC. Ordinary tenant, pilot, indexing and engine gates remain closed.

## Next Engineering Step

Close the next coherent product loop instead of extending preparation-only boundaries:

- Knowledge Base authoring and ordinary reading are complete through Roadmap 250. Preserve their authorization, approval, PostgreSQL/S3 and 50-case browser regression contracts.
- Native document authoring, version history, comparison, historical takeover, find/replace, contextual table editing, version-bound discussions and explicit saved-text suggestions are complete through Roadmap 257. Preserve all 162 checks (127 browser cases and 35 model cases), immutable review/suggestion history, atomic accepted versions and nonempty recovery. Continue user-visible native Office development before CRM expansion; continuous tracked changes and live collaboration remain future work. DOCX interchange remains a separate Quick Edit/fidelity path; real Word/GenOffice results, calibrated thresholds and human review remain prerequisites, and DOCX saves/WOPI retain their gates. Do not resume Word/account/firewall interventions on the original workstation.
- Roadmap 251 completes CRM account details with associated contacts and activities in `/work`, reusing all three CRM feature gates and the existing account-workspace API. Preserve the 60-case browser matrix. CRM account onboarding and further CRM expansion are deferred behind Office development by the user's priority decision.
- Keep RAG/indexing disabled for these writes until deletion propagation, source-version citation, and authoritative ACL revalidation pass together.
- Keep every new durable workflow in the PostgreSQL restore catalog, continuity policy, backend release gate, and isolated recovery drill.
- Treat real-user pilot and production-continuity evidence as a separate accountable-human lane; read current readiness, but never fabricate principals, approvals, topology, PITR, offsite, promotion, or cross-site evidence.
- Keep `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0` until a new evidence chain, four-eyes approvals, and the hash-only closure path pass together.
- Keep productive Legacy SQL writes, DOCX engine/WOPI and Mail runtime execution, AI provider execution, and destructive automation closed until their current release gates are independently satisfied.

## Module Expansion Stance

ERP/CRM and later modules such as knowledge base, LMS, tasks and activities, incident/ticket systems, and time tracking must enter through the Platform Module System.

Each module charter must define:

- module ID, tenant entitlement, tenant enablement, and server-side module gates
- object types, classifications, retention policies, legal-hold scopes, and KMS expectations
- audit events for lifecycle, imports, exports, approvals, and destructive intents
- backup/failover continuity domain, restore evidence, and degraded mode
- search/RAG source contract with candidate-only results and authoritative ACL checks
- migration, provisioning, disable, suspend, and decommission behavior
- legacy-source discovery, import dry-runs, quarantine handling, and mapping evidence before data import
