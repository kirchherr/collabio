# Compliance Matrix

Status: initial
Date: 2026-06-10

This matrix maps external requirements and internal controls to product capabilities. It is intentionally incomplete and must become machine-readable during Phase 0.

## Control Families

| Control ID | Area | Requirement | Product control | Evidence target | Status |
| --- | --- | --- | --- | --- | --- |
| CM-001 | Tenancy | Tenant data must be isolated | Tenant context, authz, DB RLS, tenant-scoped storage/indexes | `tests/test_principal_store.py`, `tests/test_authz_admin_store.py` | partial |
| CM-002 | Authorization | UI checks are insufficient | Server-side policy engine, PostgreSQL Principal Directory, audited authz admin APIs | `tests/test_principal_store.py`, `tests/test_authz_admin_store.py`, `tests/test_api.py` | partial |
| CM-003 | Data classification | Persistent data must be classified | Canonical DataClass registry plus runtime, KMS, retention, DB, and registry drift tests | `tests/test_data_class_registry.py` | partial |
| CM-004 | Retention | Records need retention policy | Retention policy engine | Retention simulation | planned |
| CM-005 | Legal Hold | Holds override lifecycle deletion | Legal hold service and storage lock | Hold-aware deletion tests | planned |
| CM-006 | WORM | Business/evidence records require immutability | S3-compatible object lock | Object lock integration tests | planned |
| CM-007 | Audit | Security and lifecycle actions need evidence | Append-only audit with hash chain, PostgreSQL/RLS writer role, HMAC checkpoints, and WORM export evidence | `tests/test_audit_chain.py`, `tests/test_pg_audit_store.py` | partial |
| CM-008 | KMS | Keys must be tenant- and class-aware | KMS adapter and envelope encryption | Key rotation tests | planned |
| CM-009 | Search security | Search must not leak unauthorized data | Candidate search, KeywordSearchService ACL filter, Authorized ChunkRepository, redaction | `tests/test_keyword_search.py`, `tests/test_api.py`, `tests/test_rag_security.py` | partial |
| CM-010 | Vector security | Embeddings are classified data | Vector metadata and exact authorized chunk retrieval | `tests/test_rag_security.py`, `tests/test_pgvector_integration.py` | partial |
| CM-011 | AI governance | AI must follow tenant policy | AI Control Plane | AI policy tests | partial |
| CM-012 | Human oversight | Critical actions require approval | Approval engine, Knowledge Base write/edit approval dry-run, command hashing, append-only write-approval evidence ledger, approval-transition lineage, trusted create metadata evidence, source-object write guard, metadata-only restore/source evidence refresh preview, explicit-human-confirmation write-execution skeleton, guarded edit/create execution, durable source-object write receipts, PostgreSQL source metadata/storage-manifest bridge, and PostgreSQL transactional KB metadata/evidence writes before production source-object content persistence | `tests/test_knowledge_base.py`, `tests/test_api.py`, `tests/test_source_object_write_receipts.py`, `tests/test_source_object_storage_bridge.py`, `tests/test_knowledge_base_pg_repository.py`, `tests/test_knowledge_base_write_approval_ledger.py`, `tests/test_pgvector_migration.py`, approval workflow tests | partial |
| CM-013 | Voice privacy | Voice capture must be explicit | Push-to-talk guard | Voice tests | partial |
| CM-014 | Supply chain | Artifacts need provenance | SBOM, signing, pinned deps | Release evidence | planned |
| CM-015 | Parser safety | Untrusted files need isolation | Networkless parser workers | Sandbox tests | planned |
| CM-016 | Module lifecycle | Optional modules must be tenant-wise enabled, disabled, suspended, and decommissioned without bypassing compliance | Platform module registry, tenant module state, server-side module gates, `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, CRM/ERP object rule manifest, gated CRM account/contact/activity/note/product APIs, gated Knowledge Base article API, Knowledge Base admin evidence API, Knowledge Base write/edit approval dry-run | `tests/test_platform_modules.py`, `tests/test_api.py`, `tests/test_module_implementation_contract.py`, `tests/test_knowledge_base.py`, `tests/test_knowledge_base_docs.py`, `tests/test_crm_erp_object_rules.py`, `tests/test_crm_accounts.py`, `tests/test_crm_contacts.py`, `tests/test_crm_activities.py`, `tests/test_erp_products.py` | partial |
| CM-017 | Module migration | Module and legacy imports must be repeatable, checksummed, validated, and auditable | Module-aware migration catalog, CRM/ERP schema scaffold, CRM account/contact/activity/note/product table migrations, Knowledge Base article/version metadata migration, Knowledge Base source-version/restore evidence migration, Knowledge Base write-approval ledger, transition-lineage, trusted-create-metadata migration, source-object write receipt migration, source-object metadata/storage-manifest migration, Postgres transaction adapter, metadata-only refresh-preview hashes, write-execution plan hashes, refreshed restore evidence hashes, import manifests, validation reports | `tests/test_pgvector_migration.py`, `tests/test_source_object_write_receipts.py`, `tests/test_source_object_storage_bridge.py`, `tests/test_knowledge_base_pg_repository.py`, `tests/test_knowledge_base_write_approval_ledger.py`, migration checksum tests and import reports | partial |
| CM-018 | Module retention | Business module objects need retention and disposition rules | CRM/ERP object rules, `crm.accounts`, `crm.contacts`, `crm.activities`, `crm.notes`, `erp.products`, `knowledge_base.articles`, `knowledge_base.article_versions`, Knowledge Base source-version evidence, and source-object write guard map business objects to retention policies and GoBD/WORM posture | `tests/test_crm_erp_object_rules.py`, `tests/test_knowledge_base.py`, `tests/test_crm_accounts.py`, `tests/test_crm_contacts.py`, `tests/test_crm_activities.py`, `tests/test_erp_products.py` | partial |
| CM-019 | Module Legal Hold | Legal Hold must apply to module business objects and related objects | CRM/ERP object rules require Legal Hold support for all planned object types; Knowledge Base source-version/restore evidence and source-object write guard carry and evaluate Legal Hold state before write/RAG expansion | `tests/test_crm_erp_object_rules.py`, `tests/test_knowledge_base.py` | partial |
| CM-020 | Module decommission | Module removal must respect retention, Legal Hold, export, audit, and backup obligations | Decommission precheck workflow, evidence package, module implementation contract decommission checklist, and module restore evidence such as `knowledge_base.restore_evidence` | `tests/test_module_implementation_contract.py`, `tests/test_knowledge_base.py`, decommission-blocked tests and restore evidence | planned |

## Standards Mapping

| Standard | Relevant themes | Internal controls |
| --- | --- | --- |
| DSGVO | Privacy by design, security, deletion, restriction, TOMs | CM-001, CM-003, CM-004, CM-008, CM-009, CM-010, CM-016, CM-018, CM-019, CM-020 |
| GoBD | Immutability, traceability, data access, procedural documentation | CM-004, CM-005, CM-006, CM-007, CM-017, CM-018, CM-019, CM-020 |
| EU AI Act | Risk classification, transparency, logging, human oversight, robustness | CM-011, CM-012, CM-010, CM-013 |
| NIST CSF 2.0 | Govern, Identify, Protect, Detect, Respond, Recover | all controls |
| NIST SSDF | Secure development and vulnerability reduction | CM-014 plus SDLC controls |
| NIST AI RMF | Trustworthy AI risk management | CM-011, CM-012 |
| OWASP ASVS 5.0 | Web app security requirements | CM-001, CM-002, CM-008, CM-014 |
| OWASP LLM/GenAI | Prompt injection, data leakage, tool misuse, vector weaknesses | CM-010, CM-011, CM-012 |
| SLSA | Build provenance and tamper resistance | CM-014 |
| CycloneDX | SBOM/CBOM/AI/ML-BOM evidence | CM-014 |
| WCAG 2.2 AA | Accessibility | Design-system controls, to be added |

## Release Rule

No feature that creates, modifies, deletes, searches, exports, indexes, embeds, summarizes, sends, or stores tenant data is complete until this matrix has a row or linked control covering its compliance impact.
