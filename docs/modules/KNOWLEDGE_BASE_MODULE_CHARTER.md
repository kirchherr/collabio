# Knowledge Base Module Charter

Status: proposed
Date: 2026-06-12
Module ID: `knowledge_base`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

Knowledge Base is a native optional suite module for governed internal articles, procedure snippets, runbooks, versioned sources, and later RAG citations.

The module is optional in normal use, but compliance obligations for existing knowledge base data remain mandatory.

This charter intentionally starts smaller than a full wiki. The first slices prove tenant-safe article metadata, source-version evidence, and restore evidence before article bodies, editing workflows, approvals, search indexing, or RAG are added.

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

Disabled stops normal article browsing and editing. Disabled does not stop retention, Legal Hold, audit, backup, restore, export, decommission evidence, or compliance-only administration for existing data.

## 3. Feature Flags

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `knowledge_base.articles.read` | on | no | Metadata-only article list and current version references |
| `knowledge_base.articles.write` | off | yes | Future authoring and approval workflow |
| `knowledge_base.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `knowledge_base.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

## 4. API And Worker Gates

Every normal Knowledge Base route must require:

```text
Tenant Context
+ knowledge_base enabled
+ feature permission
+ object authorization
```

Initial API:

- `GET /v1/kb/articles`
- `GET /v1/admin/kb/evidence`
- `POST /v1/admin/kb/articles/write-dry-run`
- `POST /v1/admin/kb/articles/write-approvals/approve`
- `POST /v1/admin/kb/articles/write-approvals/refresh-preview`

`GET /v1/admin/kb/evidence` is a tenant-admin compliance API. It remains available through the compliance module gate while the module is disabled, suspended, or in an active decommission workflow. It returns source-version evidence and restore evidence only, not article bodies or source text.

`POST /v1/admin/kb/articles/write-dry-run` validates a write/edit approval command, writes an audit event, and appends metadata-only approval evidence to the write-approval ledger. It does not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state. It returns command hashes and required evidence for the source-object write guard.

`POST /v1/admin/kb/articles/write-approvals/approve` transitions an existing dry-run ledger row to a new append-only `approved_for_write` ledger row. It requires a new human approval reference, verifies that the current restore evidence and expected version still match the dry-run evidence, and still does not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` accepts approved write-approval evidence and returns a metadata-only source/restore evidence projection. It verifies the approved ledger row, current restore evidence, and expected version, then returns current and projected source-version evidence hashes plus a `projected_restore_evidence_preview_hash`. It does not append ledger rows, persist source-version evidence, persist restore evidence, write article metadata, write source objects, index, embed, or update RAG state.

`KnowledgeBaseSourceObjectWriteGuard` is the mandatory precondition for future article/source mutations. It validates tenant-scoped ledger evidence, approval state, expected current version, source-object metadata guard results, proposed source-version evidence hash, current restore evidence hash, retention policy, and Legal Hold state before a write can be considered.

Future workers:

- article source extraction worker
- version approval worker
- candidate-only search indexing worker
- RAG citation rebuild worker

Destructive, external, or compliance-relevant actions require explicit human confirmation.

## 5. Persistent Objects

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `kb.article` | `internal` | `rp-standard` | article and related versions | tenant + class | yes |
| `kb.article_version` | `internal` | `rp-standard` | version and article family | tenant + class | yes |

Every object must carry the required metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, including tenant, object ID, object type, owner, classification, retention policy, Legal Hold state, lifecycle state, KMS key reference, audit-chain reference, source system, and schema version.

Article bodies are not stored in the first slice. Current article versions are references for future source-object retrieval and RAG citation, not permission to bypass ACL validation.

Current article versions must resolve to authoritative source-object records before the module can move toward authoring or RAG. The source-version evidence captures source object ID, source version ID, manifest hash, content hash, ACL version, classification, retention policy, Legal Hold state, and an evidence hash without storing article body text.

## 6. Search, RAG, AI, And Voice

Initial state:

- keyword search: off
- vector search: off
- RAG: off
- AI assist: off
- voice: off

Future search and RAG must return candidate IDs only, validate authoritative ACLs before source fetch, cite `kb.article` and `kb.article_version` object IDs and versions, and audit retrieved context, model ID, tool calls, and output hashes without writing prompt or output bodies to normal logs.

AI providers must go through the Local LLM Gateway. Cloud AI provider use requires tenant policy enablement.

## 7. Backup, Restore, And Failover

Continuity domain: `knowledge_base_content`

Required evidence:

- module state restore check
- article row-count check
- article-version row-count check
- source-version evidence row-count check
- source-version evidence hashes
- manifest or checksum check
- tenant isolation check after restore
- disabled-state restore check
- Legal Hold restore check
- restore evidence hash for `knowledge_base_content`

New article body storage, source indexes, RAG chunks, embeddings, approvals, or exports must update this continuity domain in the same change.

## 8. Migrations And Imports

Initial migrations:

- `0021_knowledge_base_articles.sql`
- `0022_knowledge_base_source_restore_evidence.sql`
- `0023_knowledge_base_write_approval_evidence.sql`
- `0024_knowledge_base_write_approval_transition_lineage.sql`

The first migration creates `knowledge_base.articles` and `knowledge_base.article_versions` with RLS, no hard delete, required metadata, KMS references, audit-chain references, source-version references, and no body text columns.

The second migration creates append-only tenant-scoped `knowledge_base.source_version_evidence` and `knowledge_base.restore_evidence` tables. These tables are RLS-protected, grant no hard delete, and are the required precondition for later write/edit or RAG expansion.

The third migration creates append-only tenant-scoped `knowledge_base.write_approval_evidence`. Future article/source writes must first persist approval evidence in this ledger, pass the source-object write guard, and refresh source-version plus restore evidence.

The fourth migration adds `transition_source_evidence_hash` so non-dry-run approval states must point back to the dry-run ledger evidence that was approved. This keeps state transitions append-only and auditable.

The refresh-preview endpoint is runtime-only and does not need a migration. Future write execution must consume its projected hash contract before refreshing append-only source-version and restore evidence.

Legacy import is out of scope for the first slice. Future import must run metadata discovery, dry-run validation, row counts, checksums, quarantine, and approval before content import.

## 9. Decommissioning

Decommissioning requires:

- disabled or suspended normal use
- retention evaluation
- Legal Hold check
- export/archive decision
- audit evidence
- backup/restore evidence
- source-version disposition evidence
- explicit approval

Missing or blocked evidence leaves the module in `decommission_blocked`.

## 10. Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
