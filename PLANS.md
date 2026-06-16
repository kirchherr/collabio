# Plans

This file tracks the active implementation sequence. The canonical roadmap is `docs/ROADMAP.md`.

## Current Journey

Theme: Build proof capability before product surface.

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

## Next Engineering Step

After proving the reusable module contract outside CRM/ERP, the Knowledge Base now has a readable evidence trail, audit-only authoring dry-run, a persistent approval ledger schema, ledger persistence wiring, a source-object write guard, an append-only approval transition path, a metadata-only restore/source evidence refresh preview, an execution skeleton, atomic in-memory edit/create execution paths, a PostgreSQL transaction adapter for article/version/evidence metadata, durable source-object write receipts, a PostgreSQL source metadata/storage-manifest bridge, a coordinated write unit-of-work, a shared PostgreSQL metadata transaction for that unit of work, content-store recovery evidence, and an S3/MinIO-compatible content-store adapter port. The next narrow step is production API wiring under a deployment gate:

- Require clean `source_object_content_recovery_evidence.v1`, provider-profile evidence, and restore-drill evidence before enabling `PostgresKnowledgeBaseWriteUnitOfWork` for API writes.
- Keep the concrete SDK binding behind the S3-compatible client protocol and outside feature code.
- Keep hybrid search behind the same candidate-only, authoritative-ACL search contract.

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
