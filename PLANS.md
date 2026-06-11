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

## Next Engineering Step

After review intake, close the remaining P0 foundation gates before attaching real data or expanding product surface:

- Implement persistent append-only audit storage with DB-role restrictions, concurrency-safe sequencing, HMAC/signature checkpoints, and WORM export.
- Introduce authorized ChunkRepository retrieval so RAG passes exact chunks instead of whole source documents.
- Add audited authz administration APIs for PostgreSQL principal, role, group, ACL, ABAC, and replay-retention mutations.
- Then resume keyword indexer, hybrid search, and CRM/ERP schemas and object rules for `crm_erp`, `crm`, `erp`, and `crm_erp_legacy`.

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
