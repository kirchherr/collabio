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

119. [x] Complete native Office saved-version print preview with A4/Letter and orientation, fresh exact-version authorization before browser print/PDF, safe literal content rendering, isolated print media and cleanup. Full quality on cf2244c passed Ruff, formatting across 689 files, Mypy across 541 sources and full Pytest. All 170 browser/model checks passed in 562.234 seconds (135 browser + 35 model, zero skipped, unexpected or flaky), preserving the previous 162. Real PDF output passed text, pagination, semantic-structure and visual checks. The final test-cleanup guard on d8300aa passed its affected browser case. No new persistence, schema, API, dependency, server export or DOCX admission; item 257 recovery evidence is retained. Final rollout, health and safeguards are recorded in docs/CURRENT_HANDOFF.md.

120. [x] Reuse an exact saved native Office version as an independent new document draft: fresh source read and create capability after discard consent, editable bounded title, protected dirty drafts and existing explicit create confirmation. Preserve source history and ACLs; do not copy discussion/suggestion state. Full quality and all 180 checks (145 browser + 35 model) passed on e7fec24; API-only rollout and final health/gates passed on dev001. No new persistence or recovery execution; closed tenant/pilot/engine gates remain.

121. [x] Make native Office documents discoverable beyond the initial 200 records: bounded server-side literal title search, current ACL checks before pagination, authenticated context-bound cursors, and clear next-page/retry controls. Preserve open and dirty documents independently of list membership; reauthorize exact saved sources for refresh/takeover/acceptance. Search values stay outside normal logs; mobile Work navigation exposes Office. Full quality passed on 5bcb7d2; all 190 checks (155 browser + 35 model) passed in 651.284899 seconds, and 180 focused Python and ten focused browser cases passed. API-only rollout, live checks and cleanup completed at 2026-09-21 13:04:19 UTC with closed gates. No new schema/persistence or recovery drill; item 257 evidence remains retained.

122. [x] Load older saved native Office versions beyond the 200-version window through authenticated, document-bound
pagination along the immutable predecessor chain. Revalidate current parent ACLs for every page; preserve drafts,
comparison selections and already rendered results while appending. Clearly identify newer saved heads and restart
history without silently replacing content. Discussion/suggestion drafts survive history navigation; hide, tab and
focus changes cancel pending reads. Full quality passed on 46a83b4; all 200 checks (165 browser + 35 model) passed in
688.743181 seconds, with zero skipped/unexpected/flaky and all previous 190 preserved. Also passed: 249 focused Python
checks and 23 focused browser cases, independent code/visual review and actual access-log cursor redaction. API rollout
and final health/gate evidence are recorded in docs/CURRENT_HANDOFF.md; no new schema, durable format or recovery drill.

123. [x] Implement native Office paragraph alignment and line/before/after spacing through a compact selection-aware
dialog. Strict optional attributes survive saved versions, undo, comparison, reuse, print and recovery without changing
legacy canonical bytes. Full quality on 8b61d8d passed Ruff, formatting across 712 files, Mypy across 557 sources and
complete Pytest. All 215 checks (176 browser + 39 model) passed in 759.313613 seconds, zero skipped/unexpected/flaky;
294 focused Python and 46 focused browser/model checks also passed. Independent responsive and three-page PDF review
passed. Complete paginated nonempty recovery verified 330 documents, 666 versions and 721 sources; release gates passed.
API rollout and final health/gate details are recorded in docs/CURRENT_HANDOFF.md. See ADR-0086; Office remains ahead of CRM.

124. [x] Add native Office character font sizes and named text colors with selection/caret formatting, mixed values,
explicit reset, strict validation, isolated undo and complete save/comparison/replacement/reuse/print/recovery preservation.
Full remote quality passed; all 231 distinct browser/model cases have passing evidence: 230 full-run passes plus
the corrected complete eight-case history suite. The original setup failure remains in the raw reports. Actual PDF
and responsive review passed. Fresh recovery verified 460 documents, 935 versions and 1,045 source objects; both
release gates passed. See ADR-0087 and docs/CURRENT_HANDOFF.md for rollout and the remaining rich-table input follow-up.

125. [x] Make whole-document keyboard replacement reliable across rich tables, with structural full selection,
confirmation, cancellation, isolated undo and unchanged schema/size guards. Preserve local review drafts, immutable
saved versions, reader/history gates and context invalidation. Ten new browser cases and the existing table/history
suites cover this UI-only change. Full quality and all 241 browser/model checks passed on d7270a7; desktop/mobile
confirmation review passed. Rollout and closed-gate evidence are recorded in docs/CURRENT_HANDOFF.md.

126. [x] Add in-document native Office format transfer for direct character and paragraph formatting, together or
separately. Preserve text/structure/code, exact text/cell selection, default values, pending typing marks, isolated undo,
confirmed immutable versions, size guards and read/history/context boundaries. Mobile review drawers retain usable
space independently of wrapping tools. Full quality and all 252 browser/model cases passed on ac70c29; the 43-case
responsive/transfer run and visual review passed. See ADR-0088 and docs/CURRENT_HANDOFF.md for API rollout and closed gates.

127. [x] Add selection-bound native Office list levels and ordered-list start values using the existing format.
Preserve text/marks/paragraphs/sublists, table Tab navigation, pending typing marks, isolated undo, size/depth guards,
read/history/context boundaries and confirmed immutable saves. All twelve focused cases, full quality and the single
264-case browser/model matrix passed on fb8dbd3. Responsive visual review passed; see ADR-0089 and
docs/CURRENT_HANDOFF.md for API rollout and closed gates.

128. [x] Add document-owned named paragraph styles with reusable definitions, shared updates, fixed presentation
values, contextual controls and preview. Preserve direct overrides, immutable versions, comparison/print/reuse,
selection-bound undo and authorization gates. ADR-0090; full quality and all 280 browser/model cases passed on 1e09a10.
Actual PDF/visual checks, fresh nonempty recovery, release gates and API-only rollout passed; see CURRENT_HANDOFF.md.
Image/object follow-up design is in docs/modules/OFFICE_IMAGES_AND_OBJECTS_CONCEPT.md; implementation remains separate.

129. [x] Implement document-owned native images with isolated PNG/JPEG normalization, upload/insert, resize/align,
alt/caption, move/remove/undo, confirmed save, history, independent copy and print. ADR-0091; all297 browser/model cases
passed on96a299f and full quality on5d3eb35 with identical runtime/browser sources. PDF/visual checks, fresh nonempty
document-plus-asset recovery and both release gates passed before decoder/API rollout. See CURRENT_HANDOFF.md.
Active objects and other object types remain separate work; ordinary admission stays closed.

130. [x] Add non-destructive native image cropping with interactive preview, reset and keyboard-accessible bounded
controls under ADR-0092. Immutable versions retain geometry and exact normalized renditions; undo, comparison, reuse,
actual PDF and fresh nonempty recovery passed. Full quality passed on 54fe1ff; passing browser/model evidence covers
all 303 distinct cases via the 302/303 full attempt and corrected 57-case helper suite on 3da08b8, not a single green
full run. Both release gates passed before API-only rollout. See CURRENT_HANDOFF.md.

131. [x] Add native image text wrapping with stable in-flow anchors, left/right placement and bounded text distance
under ADR-0093. Narrow-screen/nested block fallback, physical page-break behavior, crop, accessible controls, isolated
undo, exact history and owned copies are verified. Full quality and one complete 313-case browser/model run passed
on 1d8a58f. Actual PDF/visual checks, fresh nonempty wrap/reset recovery, both release gates and API-only rollout passed.
See CURRENT_HANDOFF.md. Arbitrary page-positioned objects and other object types remain separate.

132. [x] Add explicit native page breaks under ADR-0094: visible root-only markers, menu/keyboard insertion and
removal, isolated undo and preserved text/image/table placement. History, comparison, owned copies, actual PDFs and
legacy bytes retain their exact contracts. Full quality passed; all 325 distinct browser/model cases are covered by
the 324/325 complete run plus the 12/12 corrected subset (not one all-green full run). Four PDFs/14 pages, fresh
nonempty insert/remove recovery, both release gates and API-only rollout passed. Evidence: CURRENT_HANDOFF.md.
Continuous pagination, section layouts and DOCX interchange remain separate. Continue native Office before CRM.

133. [x] Add document-owned page settings under ADR-0095: A4/Letter, portrait/landscape and bounded margins,
accessible preview/reset and isolated undo. Exact optional metadata preserves legacy bytes, saved history and copies.
Full Python quality and one complete 345-case browser/model run passed on 800a3a5. Eight actual PDFs/16 pages,
fresh four-version recovery, both release gates and API-only rollout passed. Independent PDF QA caught and verified
the correction of a legacy CSS cascade override. Evidence: CURRENT_HANDOFF.md. Section layouts and pagination remain separate.

134. [x] Add document-owned headers/footers and page numbers under ADR-0096: bounded literal text,
page/page-total choices, accessible preview, independent reset and isolated undo. Exact history/copies remain.
All 2924 Python cases passed; full 367 browser/model cases plus 42 affected cases after a final reset correction
passed, not a single full run on final source. Twelve PDFs/36 pages, fresh nonempty recovery, both release
gates and API-only rollout passed. Published as implementation commit `9892e41`. Evidence: CURRENT_HANDOFF.md.

135. [x] Add first-page header/footer differences and explicit first-page number suppression under ADR-0097.
Separate previews, complete reset, isolated undo and trusted static print rules preserve legacy bytes and exact
history/copies. All 2936 Python and 372 browser/model cases passed. Four real three-page PDFs verify separate
profiles, hidden/shown first-page numbers and continued pages 2/3; fresh six-version recovery, both release gates,
API-only rollout and live checks passed. General sections, arbitrary fields, continuous editor pagination and DOCX
interchange remain separate. Published as implementation commit `48ae9c9`.

136. [x] Add native root-level section breaks under ADR-0098. Each marker starts a new printed page and owns the
complete validated page and running-text profile of the following section. Provide responsive insert/edit/remove,
preview, isolated undo, exact save/history/copy positions, global continuous numbering, trusted static print slots,
real mixed-format PDF proof and a four-version legacy/one-section/two-section/reset recovery fixture. Keep arbitrary
fields, per-section first-page variants, number restarts, continuous editor pagination, floating objects and DOCX
interchange separate. Full quality, one complete 379-case browser/model run, responsive visual review, two real
mixed-format PDFs, fresh four-version recovery, main backup/restore, both release gates and API-only rollout passed.
Published as implementation commit `04d45cd`.

137. [x] Add safe native hyperlinks under ADR-0099. Store an exact bounded inline target restricted to absolute HTTPS
or simple mailto addresses; reject credentials, active/ambiguous schemes and automatic navigation. Provide responsive
add/edit/remove and deliberate-open controls, isolated undo, exact history/comparison/reuse positions, semantic print
output and a four-version legacy/add/edit/remove recovery fixture. Keep bookmarks, cross-references, URL previews,
automatic link recognition, arbitrary fields and DOCX interchange separate. Full Python quality, one complete 384-case
browser/model run, responsive visual review, two real PDFs, fresh four-version recovery, main backup/restore, both
release gates, API-only rollout and live verification passed. Published as implementation commit `12e8fca`.

138. [x] Add native document-local bookmarks and internal cross-references under ADR-0100. Store bounded unique
bookmark atoms and explicit selected-text references to stable IDs. Provide responsive insert/rename/remove and
deliberate-jump controls, safe broken-target behavior, isolated undo, exact history/comparison/reuse positions,
semantic internal PDF anchors and a five-version legacy/add/rename/broken/reset recovery fixture. Keep automatic
captions, page fields, cross-document references, backlinks, URL previews and DOCX interchange separate. Full Python
quality, one complete 389-case browser/model run, responsive visual review, two real PDFs, fresh five-version recovery,
main backup/restore, both release gates, API-only rollout and live verification passed. Published as implementation
commits `6c4c6e0` through `7e61f72`.

139. [x] Add native figure captions and stable figure numbering. Let document-owned images carry an optional semantic
caption, derive numbering deterministically from document order, and preserve exact image/caption identity through
undo, save, history, comparison, copies and print. Reuse stable destination IDs for explicit figure references and
safe broken-target behavior. Keep table captions, arbitrary page fields, cross-document references, backlinks and
DOCX interchange separate. Full Python quality, two complete 394-case browser/model runs, responsive visual review,
two real tagged PDFs, fresh five-version recovery, main backup/restore, both release gates, API-only rollout and live
verification passed. Published as implementation commits `1559bb5` through `42a6f67`.

140. [x] Add native table captions and stable table numbering. Let tables carry an optional semantic caption and a
stable document-local destination ID, derive a separate table-number sequence from document order, and preserve exact
identity through undo, save, history, comparison, copies, print and explicit cross-references. Keep arbitrary page
fields, cross-document references, backlinks and DOCX interchange separate. Full Python quality, one complete
398-case browser/model run, responsive visual review, two real tagged A4 PDFs, fresh five-version recovery, main
backup/restore, both release gates, API-only rollout and live verification passed. Published as implementation commits
`e757b7e` through `d2fe43f`.

141. [x] Add native free document fields. Store a bounded document-owned key/value catalog and explicit field nodes
for reuse in body and running text without scripts, external resolution or silent rewrites. Preserve exact undo,
save, history, comparison, copies, print and broken-field behavior. Keep cross-document references, backlinks,
formulas and DOCX interchange separate.

142. [x] Add a native generated table of contents derived from current heading order and bounded depth without storing stale rendered entries.

143. [x] Add native footnotes with stable local identities, order-derived numbering and semantic print output.

144. [x] Add native endnotes with an independent sequence and exact version, comparison, copy and recovery behavior.

145. [x] Add native citations and a generated bibliography backed only by a bounded document-owned source catalog; never fetch a source.

146. [x] Add native inert formulas with bounded literal source and required accessible text; keep evaluation and external engines closed.

147. [x] Add a native local reference navigator derived from fields, notes, citations and formulas, including visible broken targets without cross-document lookup.

148. [x] Add bounded native outbound document references under ADR-0104. Store only exact target object/version IDs on
selected text. Re-read the exact source and revalidate target tenant, current authoritative ACL and exact version for
loading, deliberate open and every print action. Collapse missing, deleted and unauthorized targets into one inert
title-free state; print no cross-document action. Preserve exact marks through undo, confirmed CAS save, immutable
history, comparison, copies and recovery. Keep global backlinks, graph discovery, URL previews and DOCX relationships
separate.

149. [x] Add bounded native backlinks under ADR-0105. Reauthorize the exact target version, then derive matches only
from current versions of source documents readable under the current tenant and authoritative ACL. Return no content
or inaccessible-source metadata. Bind signed pagination to tenant, actor, roles, exact target and page size; cap each
scan and result page at 50. Recheck the exact source on deliberate open. Keep the view out of print and avoid a
persistent backlink index, deletion queue or authorization snapshot. Preserve exact behavior through recovery.

150. [x] Add bounded anchored image layers under ADR-0106. Keep the ordered image node as the durable anchor, admit
only front/behind plus normalized horizontal and bounded vertical coordinates, and make the anchor draggable and
keyboard operable. Keep wrapping mutually exclusive; preserve exact undo, history, owned copy, print and recovery.
Absolute DOCX page anchors, wrap contours, rotation and grouping remain separate.

151. [x] Add bounded native image transforms under ADR-0107. Store only quarter-turn rotation and explicit horizontal
or vertical mirror booleans; reject arbitrary angles, matrices, CSS and explicit identity defaults. Reserve responsive
rotated bounds while keeping source pixels and crop immutable. Preserve exact preview, undo, comparison, history,
owned copy, print and fresh recovery through a rotate/mirror/reset lineage. Arbitrary angles, wrap contours, grouping
and absolute DOCX page anchors remain separate.

152. [x] Add bounded native image groups under ADR-0108. Group two through eight existing images with exact member
order, row/stack layout and a bounded gap. Preserve responsive fallback, undo, history, copies, print and recovery;
keep nested groups, positioning and transforms outside the group contract.

153. [x] Add bounded inert native shapes under ADR-0109. Admit only top-level rectangles, rounded rectangles and
ellipses with fixed colors, integer geometry, literal text and fixed alignment. Preserve exact undo, history,
comparison, print and independent copies while rejecting arbitrary SVG, CSS, URLs, scripts and freeform paths.

154. [x] Add bounded native shape layers under ADR-0110. Store only optional front/behind plus normalized horizontal
and bounded vertical coordinates. Keep a separate pointer/touch/keyboard anchor operable above content, preserve
isolated undo and exact flow reset, and exclude arbitrary z-index, physical page anchors and wrap contours.

155. [x] Add bounded direct native shape resizing under ADR-0111. Expose a focusable control on the selected shape,
preview pointer/touch width and height within the existing limits, and commit one isolated undo step on release.
Support one- and ten-pixel keyboard changes and preserve the existing canonical dimensions through history, copies
and print without adding schema, arbitrary transforms or DrawingML.

156. [x] Add bounded native shape rotation under ADR-0112. Store only optional 90/180/270 degree values and keep zero
as canonical omission. Provide dialog and direct clockwise control with isolated undo, responsive transposed bounds
for sideways flow shapes, accessible descriptions and exact history/copy/print preservation. Reject arbitrary angles,
matrices, separate text rotation and DrawingML.

157. [x] Add bounded native shape text wrapping under ADR-0113. Store only left/right plus an integer 0–48 pixel gap,
make wrapping mutually exclusive with free positioning, cap wrapped width and visual height, and fall back to a block
at narrow container widths. Preserve exact undo, history, copies and print while rejecting CSS floats, contour paths
and simultaneous positioning.

158. [x] Add bounded native shape groups under ADR-0114. Group two through eight adjacent flow shapes with exact member
order, row/stack layout and an integer 0–48 pixel gap. Support extension, member edits/removal, isolated undo/redo and
dissolution; collapse rows on narrow screens and preserve exact comparison, history, copies and print. Reject nested or
mixed groups, member positioning/wrapping, arbitrary group transforms, connectors and DrawingML.

159. [x] Add bounded native connections inside shape groups under ADR-0115. Apply one optional line, direction-arrow
or double-arrow style uniformly between consecutive ordered members, with a fixed color token and integer 1–8 pixel
width. Orient it for rows, stacks and compact fallback; preserve exact undo, comparison, history, copies and print.
Reject arbitrary endpoints, paths, per-edge styling, SVG, URLs, CSS and DrawingML.

160. [x] Add direct accessible member ordering inside native shape groups under ADR-0116. Let an author move the
selected member one exact position earlier or later, disable unavailable boundary actions and commit each move as one
isolated undo step. Preserve the existing exact member sequence, group presentation, connections, history, copies and
print without adding schema, drag-only interaction, overlap ordering or arbitrary z-index behavior.

161. [x] Add bounded native shape typography under ADR-0117. Let each shape optionally override the canonical
16-pixel text size with an integer 10–72 pixel size, select one fixed text-color token and select bold, italic or both.
Preserve exact preview, accessibility, undo, comparison, immutable history, groups, copies and print. Reject fonts,
URLs, CSS, markup, arbitrary style strings and transparent text.

162. [x] Add direct native shape duplication under ADR-0118. Create a new opaque shape identity while preserving all
validated presentation, text and layout attributes. Insert grouped copies immediately after their source and visibly
offset positioned copies within existing bounds. Make each duplication one undo step, enforce global and group limits
before mutation and preserve exact save, history, print and independent document-copy behavior.

163. [x] Add direct native shape-group duplication under ADR-0119. Clone the complete validated group with a fresh
group identity and fresh identities for every member while preserving exact order, layout, gap, connection and member
attributes. Insert the copy after its source as one undo step and enforce both the 20-group and 100-shape limits before
mutation. Preserve exact save, history, comparison and print behavior without introducing shared identities.

164. [x] Add atomic native shape-group removal under ADR-0120. Resolve the selected group's stable validated identity
against the current editor document, remove the complete group as one isolated undo step and restore the exact group on
undo. Preserve unrelated content, immutable earlier versions, confirmed save and print while failing closed for stale,
missing or read-only targets without adding durable schema.

165. [x] Add direct native shape-group ordering under ADR-0121. Move the complete selected group exactly one top-level
document position earlier or later, disable unavailable boundary actions and commit each move as one isolated undo
step. Preserve group and member identities, member order, layout, gap, connection, attributes, immutable history and
print without adding durable schema, arbitrary drag ordering or overlap layers.

166. [x] Add direct standalone native shape ordering under ADR-0122. Move the selected ungrouped shape exactly one
top-level document position earlier or later, disable unavailable boundary actions and commit each move as one
isolated undo step. Preserve stable identity and every validated presentation attribute through save, immutable
history and print without adding durable schema, arbitrary drag ordering or overlap layers.

167. [x] Add atomic native image-group removal under ADR-0123. Resolve the selected group's stable validated identity
against the current editor document, remove the complete group as one isolated undo step and restore the exact group
on undo. Preserve source assets, member bindings and attributes, unrelated content, immutable earlier versions,
confirmed save and print without adding an asset-deletion path or durable schema.

168. [x] Add independent native image-group duplication under ADR-0124. Revalidate current tenant/write access and
all source members, create fresh document-owned asset/version identities atomically, then insert a fresh group and
fresh figure identities directly after the source as one undo step. Preserve exact ordered pixels and presentation,
enforce the existing group/image/storage limits before mutation, fail closed without a partial draft copy, and prove
the new durable assets through an isolated PostgreSQL/S3 recovery.

169. [x] Add independent standalone native image duplication under ADR-0125. Revalidate current tenant/write access
and immutable source bytes, create a fresh document-owned asset/version, then insert the copy directly after its
source as one isolated undo step. Preserve exact pixels and presentation, issue a fresh figure identity when
numbered, visibly offset bounded free-positioned copies, fail closed on stale or incomplete responses, and prove the
durable copies through an isolated PostgreSQL/S3 recovery.

170. [x] Add in-place native image-file replacement under ADR-0126. Reuse the authorized normalized upload path to
create a fresh document-owned asset/version, preserve accessibility text, caption, numbering, layout, group placement
and inert transforms, reset source-pixel crop coordinates and change the draft only on explicit apply as one undo
step. Prove cancel, undo/redo, immutable predecessor pixels, persisted reload and fresh PostgreSQL/S3 recovery.

171. [x] Add direct accessible native image-group member ordering under ADR-0127. Move the selected member exactly one
position earlier or later, disable boundary actions, keep selection on the moved image and preserve the complete
validated group and member representation in one isolated undo step. Distinguish member order from whole-group
document order and prove exact save, immutable predecessor, reload, print and desktop/mobile behavior.

172. [x] Add bounded responsive native image-group grids under ADR-0128. Extend the canonical saved layout vocabulary
with two-, three- and four-column grids, derive editor/comparison/print columns from one model and retain readable
two-column fallback for denser grids on narrow viewports. Preserve every group/member attribute and prove exact save,
reload, immutable predecessor and print geometry.

173. [x] Add independent duplication of one selected native image-group member under ADR-0128. Give every nested image
a focusable edit entry point, reuse the authorized immutable-image copy endpoint, require fresh asset/version identity
with exact source pixels and insert the copy immediately after its source as one isolated undo step. Keep all existing
group, image and retained-asset limits fail closed.

174. [x] Add atomic extraction of one selected native image-group member under ADR-0128. Place the existing member
before or after its group, rebuild larger groups exactly and dissolve two-member groups into ordered standalone images
without creating or deleting assets. Prove both placements, undo/redo, save, reload and print on desktop and mobile.

175. [x] Add an inert native Office document-object block under ADR-0129. Store only an exact authorized target object
and version plus a bounded snapshot/linked mode, share the existing 100-reference limit and authoritative ACL-safe
resolution/backlink path, and never persist a resolved title, target body, URL, HTML or executable payload.

176. [x] Separate fixed snapshots from explicitly refreshable document links under ADR-0129. Keep every saved source
version pinned; allow a linked draft to adopt the target's current saved version only through a visible author action
that creates an ordinary undoable draft change. Never refresh during load, print or historical rendering.

177. [x] Complete accessible document-object authoring under ADR-0129. Provide focusable edit, exact-target open,
one-position movement, duplicate and remove actions with disabled boundaries and isolated undo. Prove confirmed save,
reload, comparison, print, fresh ACL revocation, backlinks and desktop/mobile behavior without active embedding.

178. [x] Add bounded inert native Office charts under ADR-0130. Store only a fresh stable ID, bar/line/pie kind,
literal title and alternative text, legend flag, unique categories and small integer series. Reject formulas, URLs,
remote sources, arbitrary markup/style and executable payloads in both server and browser validation.

179. [x] Render the canonical chart model accessibly under ADR-0130. Use fixed colors and limits, generated inert DOM
for bar and pie charts, generated internal SVG for lines and an exact assistive data table. Keep editor and print on
the same model without a network, calculation or embedded-runtime path.

180. [x] Complete accessible chart draft operations under ADR-0130. Provide tab-separated data entry with preview,
insert, edit, fresh-ID duplicate, one-position movement and removal as isolated undo steps with disabled boundaries.

181. [x] Close the native chart lifecycle under ADR-0130. Prove confirmed save, immutable predecessor, reload,
comparison, print and responsive desktop/mobile containment, retaining the existing Office version and recovery
contracts without a database migration or document-engine admission.

182. [x] Add bounded native merged table cells under ADR-0131. Persist canonical row and column spans and validate a
rectangular logical grid independently in browser and server without gaps, overlaps, truncated spans or expansion
beyond twenty columns and two hundred rows.

183. [x] Add focusable merge and split operations under ADR-0131. Enable each action only for a valid selection and
commit every accepted change as one isolated undo step while leaving rejected drafts untouched.

184. [x] Add a semantic header-column toggle under ADR-0131. Derive row and column header state from the logical grid
and print native spans with exact `scope="col"` and `scope="row"` semantics.

185. [x] Close the merged-table lifecycle under ADR-0131. Prove undo/redo, confirmed save, immutable predecessor,
reload, comparison, print and responsive desktop/mobile containment without a migration or spreadsheet runtime.

186. [x] Add safe native SVG image import under ADR-0132. Admit bounded inert vectors through the authorized image
upload, reject active and external content before rendering, preserve source alpha and store only a canonical
document-owned RGBA PNG rendition.

187. [x] Add bounded EPS image import under ADR-0132. Require EPSF plus a finite numeric bounding box, render only the
first page with Ghostscript `SAFER` on a transparent canvas and reject generic PostScript while retaining the shared
pixel, byte, time and process limits.

188. [x] Keep vector rendering inside the credential-free network-none decoder under ADR-0132. Pin the renderer
packages, use a fresh resource-limited child for each request and prevent original SVG/EPS bytes or external-resource
dependencies from entering immutable Office versions.

189. [x] Close the SVG/EPS authoring lifecycle under ADR-0132. Support browser MIME and extension selection, preview,
insert, replacement, confirmed save and reload, and prove alpha plus the complete PNG/JPEG image regression on
desktop and mobile.

190. [x] Add bounded native table-cell fills under ADR-0133. Store only one optional token from a fixed print-safe
palette, reject arbitrary color and style input in browser and server validation, and preserve canonical legacy cells.

191. [x] Add bounded vertical table-cell alignment under ADR-0133. Treat top as the absent default and admit only
middle or bottom, with identical inert editor and print rendering.

192. [x] Add accessible multi-cell styling under ADR-0133. Apply the selected fill and alignment across cell, row,
column or rectangular selections in one validated undo step, preserve mixed values until explicitly changed and
retain exact styling through merge, split and header conversion.

193. [x] Close the table-cell styling lifecycle under ADR-0133. Prove undo/redo, confirmed save, immutable predecessor,
reload, comparison, print, responsive desktop/mobile containment and fail-closed reader/historical controls.

194. [x] Add fixed native table presentation styles under ADR-0134. Keep grid as the absent default and admit only
minimal, banded or accent presentation while rejecting arbitrary CSS, classes, colors and URLs.

195. [x] Add bounded table width and alignment under ADR-0134. Keep full width and left alignment canonical, with
only wide/compact and center/right alternatives and no pixel dimensions or physical page anchors.

196. [x] Add bounded column distribution under ADR-0134. Support equal columns plus fixed first-wide and first-narrow
presets without a free grid expression, preserving semantic headers and merged cells.

197. [x] Add top or bottom table-caption placement under ADR-0134. Preserve layout while captions are added, edited
or removed, and preserve stable caption identity and text while layout changes.

198. [x] Add one accessible table-layout dialog and canonical reset under ADR-0134. Apply or reset every layout
dimension in one validated undo step with fail-closed read-only and historical controls.

199. [x] Close the native table-layout lifecycle under ADR-0134. Prove undo/redo, confirmed save, immutable
predecessor, reload, comparison, print and responsive desktop/mobile containment with a reachable document canvas.

200. [x] Add bounded horizontal table-cell alignment under ADR-0135. Keep left alignment canonical and admit only
center or right as inert cell defaults without overriding explicit paragraph formatting.

201. [x] Add bounded table-cell padding under ADR-0135. Keep normal padding canonical and admit only compact or
spacious fixed mappings without pixels, percentages or arbitrary dimensions in saved content.

202. [x] Add bounded table-cell borders under ADR-0135. Keep the table style canonical and admit only no border or
one fixed strong border without per-edge models, arbitrary colors or CSS.

203. [x] Extend the accessible multi-cell formatting dialog and add a complete canonical reset under ADR-0135.
Preserve mixed values until explicitly changed and apply or reset the full selection in one validated undo step.

204. [x] Preserve the complete cell presentation through merge, split and header conversion under ADR-0135, with
identical inert editor, comparison and print attributes.

205. [x] Close the expanded table-cell presentation lifecycle under ADR-0135. Prove undo/redo, confirmed save,
immutable predecessor, reload, comparison, print, desktop/mobile containment and fail-closed reader/history controls.

206. [x] Add deterministic stable native text sorting under ADR-0136 for simple rectangular tables. Normalize with
Unicode NFKC and lowercase code-point ordering without locale-dependent collation or automatic type inference.

207. [x] Add strict bounded number sorting under ADR-0136. Accept plain integers and decimals with one dot or comma,
reject grouping and invalid or oversized values, and leave the document unchanged on failure.

208. [x] Add strict ISO-date sorting under ADR-0136. Validate real `YYYY-MM-DD` calendar dates, keep empty cells last
in both directions and retain the original order of equal values.

209. [x] Preserve a leading header row and every complete row and cell attribute while sorting. Reject merged or
non-rectangular grids fail closed.

210. [x] Add one accessible table-sort dialog for column, type and direction. Commit one successful sort as one
validated undo transaction; cancellation, invalid input and stale selection remain no-ops.

211. [x] Close the native table-sort lifecycle under ADR-0136. Prove undo/redo, confirmed save, immutable predecessor,
reload, comparison, print, responsive desktop/mobile behavior and fail-closed reader/history controls.

212. [x] Add direct contiguous row movement under ADR-0137. Move the selected rows exactly one position before or
after while disabling boundary actions and leaving rejected commands unchanged.

213. [x] Add direct contiguous column movement under ADR-0137. Move complete selected cells exactly one position left
or right while preserving their content, marks, semantic type and bounded presentation.

214. [x] Protect an all-header first row and all-header first column under ADR-0137. Reject selections that overlap a
protected area and reject merged or non-rectangular grids fail closed.

215. [x] Preserve the complete rectangular selection after movement and commit each accepted row or column move as
one validated undo transaction.

216. [x] Integrate accessible move actions into the existing row and column menus under ADR-0137. Expose unavailable
directions as disabled and keep stale selections, readers and historical versions as no-ops.

217. [x] Close the native table-reordering lifecycle under ADR-0137. Prove undo/redo, confirmed save, immutable
predecessor, reload, comparison, print and responsive desktop/mobile behavior.

218. [x] Add direct contiguous data-row duplication under ADR-0138. Insert the complete selected block directly
below its source without reconstructing individual cells.

219. [x] Add direct contiguous data-column duplication under ADR-0138. Insert every complete selected cell directly
to the right of its source across all rows.

220. [x] Protect an all-header first row and all-header first column during duplication. Reject merged or
non-rectangular grids and enforce the existing 200-row and 20-column limits before mutation.

221. [x] Preserve complete content, marks, semantic cell types and bounded presentation, select the inserted block
and commit each successful duplication as one validated undo transaction.

222. [x] Integrate accessible duplication actions into the existing row and column menus. Keep protected selections,
size-limit crossings, stale selections, readers and historical versions disabled or no-ops.

223. [x] Close the native table-duplication lifecycle under ADR-0138. Prove undo/redo, confirmed save, immutable
predecessor, reload, comparison, print and responsive desktop/mobile behavior.

224. [x] Add safe structured HTML-table clipboard import under ADR-0139. Translate exactly one Word/Excel table into
canonical native cells while stripping active, embedded and external content.

225. [x] Add a bounded quoted-TSV fallback with the existing 200-row, 20-column and document-size limits. Reject
irregular, oversized and unsupported input without changing the draft.

226. [x] Preserve semantic headers, bounded spans and fixed cell presentation. Keep displayed values from unknown
Excel formula dialects as inert text without executing or persisting the unsupported formula.

227. [x] Add bounded local formulas with A1 through T200 references, arithmetic, ranges and SUM, AVERAGE, MIN, MAX
and COUNT. Canonically normalize the supported German names and semicolon separators.

228. [x] Add deterministic results, fixed errors, cycle detection and live recalculation. Independently parse and
evaluate every submitted formula on the server and reject stale or forged stored results.

229. [x] Add an accessible formula dialog, removal flow and visible formula-cell marker. Reject external workbooks,
macros, networks, arbitrary identifiers and documents exceeding 1,000 formula cells.

230. [x] Limit recalculation to minimal formula-cell updates so source edits and derived results retain clean undo/redo.
Expose inert formula source/result details in comparison and preserve canonical results in print.

231. [x] Close the clipboard/formula lifecycle under ADR-0139. Prove undo/redo, confirmed save, immutable predecessor,
reload, comparison, print and responsive desktop/mobile behavior.

232. [x] Add safe rectangular Word/Excel range paste into an existing simple native table under ADR-0140. Use one cell
as the range origin and require matching dimensions for an explicit rectangular selection.

233. [x] Grow a target table from one origin within the existing 200-row and 20-column limits. Preserve complete header
row and header-column semantics and reject merged or irregular grids atomically.

234. [x] Shift admitted local formulas by the target row and column offset and recalculate the resulting table. Reject
coordinates outside A1:T200 and retain every ADR-0139 external-reference and grammar boundary.

235. [x] Preserve only safe bold, italic, underline, strike and code marks from clipboard cells. Flatten links to text
and continue stripping active, styled, embedded, framed, form, media and nested-table content.

236. [x] Commit a successful range paste as one validated undo step and select the resulting rectangle. Keep stale
sessions, readers, historical versions, dimension mismatches and size-limit failures unchanged.

237. [x] Close the range-paste lifecycle under ADR-0140. Prove undo/redo, confirmed save, immutable predecessor and
responsive desktop/mobile behavior without adding a spreadsheet runtime or recovery target.

238. [x] Add explicit source-identity maps for local formulas during row and column insertion or deletion under
ADR-0141. Move each surviving A1 reference to its logical source cell rather than retaining a stale coordinate.

239. [x] Persist deleted direct and range endpoints as the exact canonical `#BEZUG!` token. Independently parse and
recalculate it in browser and server while rejecting every other unsupported `#` or `!` form.

240. [x] Preserve logical formula targets through direct row/column movement and stable row sorting without weakening
protected headers, simple-grid validation or existing size limits.

241. [x] Deep-clone row and column duplicates and apply relative-copy semantics to copied formulas. Keep original,
copied and following cells structurally independent.

242. [x] Commit each formula-aware structural edit as one validated table replacement with a restored selection and
one undo step. Keep stale sessions, readers, historical versions, merged formula grids and limit failures unchanged.

243. [x] Close the structural-formula lifecycle under ADR-0141. Prove undo/redo, confirmed save, reload, comparison,
print and responsive desktop/mobile behavior without adding absolute references or a workbook runtime.

244. [x] Add canonical absolute and mixed local references under ADR-0142. Preserve `A1`, `$A1`, `A$1` and `$A$1`
inside A1:T200 while rejecting repeated or detached `$` anchors.

245. [x] Independently extend browser and server parsing, evaluation and stored-result validation for anchored row and
column coordinates without admitting sheets, workbooks or external references.

246. [x] Make Word/Excel range paste anchor-aware. Shift only relative axes, handle each range endpoint separately and
reject a copied reference outside the global coordinate limits atomically.

247. [x] Keep anchored references bound to logical cells through row/column insertion, deletion, movement and stable
sorting. Preserve marker placement and use canonical `#BEZUG!` for deleted dependencies.

248. [x] Apply axis-specific copy semantics to independent deep-cloned row and column duplicates. Keep fully fixed
references unchanged and shift only the relative part of mixed references.

249. [x] Close the anchored-formula lifecycle under ADR-0142. Prove dialog entry, undo/redo, confirmed save, reload,
comparison, print and responsive desktop/mobile behavior without adding a workbook runtime.

250. [x] Add bounded formula fill for a rectangular selection of ordinary data cells under ADR-0143. Treat the
top-left formula as the source for every selected target.

251. [x] Shift relative, absolute and mixed references independently for each target offset. Reject the complete fill
when any translated reference leaves A1:T200.

252. [x] Clear formulas across the current selection in one operation. Preserve the last visible results as ordinary
cell content and recalculate every formula outside the cleared range.

253. [x] Extend the accessible formula dialog with range coordinates, selected-cell and existing-formula counts.
Restore the rectangular selection and commit fill or removal as exactly one undo step.

254. [x] Keep header cells, merged grids, invalid bounds and formula-count overflow fail closed. Preserve current
authorization, stale-session, reader, historical-version and document-size boundaries.

255. [x] Close the formula-range lifecycle under ADR-0143. Prove anchored fill, atomic undo/redo, range removal,
confirmed save, reload, print and responsive desktop/mobile behavior without adding fill handles or a workbook runtime.

## Next Engineering Step

Close the next coherent product loop instead of extending preparation-only boundaries:

- Knowledge Base authoring and ordinary reading are complete through Roadmap 250. Preserve their authorization, approval, PostgreSQL/S3 and 50-case browser regression contracts.
- Native Office is complete through Roadmap 394 / PLANS 255. Preserve the complete browser/model evidence, safe Word/Excel table and in-table range translation, bounded server-verified local formulas with relative, absolute and mixed references, atomic selection-wide formula fill/removal, anchor-aware range-paste and structural rewriting, canonical `#BEZUG!` for deleted dependencies, bounded SVG/EPS normalization, vector active-content rejection, canonical RGBA image ownership, bounded logical table grids, semantic headers, fixed cell presentation and table layout tokens, deterministic stable text/number/ISO-date sorting, protected formula-aware row/column reordering and independent duplication, full Python quality, immutable versions/reviews/suggestions, current ACLs, confirmed CAS saves, schema/size guards, isolated undo and the fresh Roadmap-309 exact recovery. Continue with the next coherent native Office authoring loop. Full spreadsheet/workbook semantics, cross-table formulas, named ranges, sheet semantics, live chart data, rich embedded previews, non-document file objects, transitive reference graphs, content-wide reference search, persistent backlink indexing, URL previews, arbitrary fonts and shape style strings, automatic crop translation, absolute physical page anchors, arbitrary wrap contours, arbitrary-angle shape rotation, mixed/nested/free-positioned shape groups, arbitrary/per-edge connectors, arbitrary drag ordering, per-section first-page variants, number restarts, continuous tracked changes, live collaboration and DOCX interchange remain separate, and all engine/fidelity gates stay closed.
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
