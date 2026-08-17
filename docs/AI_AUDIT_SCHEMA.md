# AI Audit Schema

## Event fields

- event_id
- tenant_id
- user_id
- event_type
- model_id
- prompt_template_id
- source_object_ids
- input_hash
- output_hash
- metadata

## Event types

- `ai.inference`
- `rag.retrieval`
- `voice.transcript`
- `search.keyword.query`
- `vector.reindex.started`
- `vector.reindex.completed`
- `vector.reindex.failed`
- `vector.deletion_propagation.started`
- `vector.deletion_propagation.completed`
- `vector.deletion_propagation.failed`
- `embedding_model_version.registered`
- `embedding_model_version.approved`
- `embedding_model_version.retired`
- `crm_erp.source_resolver_acl_trace`
- `crm_erp.source_citation_contract`
- `crm_erp.prompt_audit_contract`
- `crm_erp.redaction_contract`
- `crm_erp.authorized_context_contract`
- `crm_erp.inference_execution_boundary`

## CRM/ERP prompt audit contract

CRM/ERP prompt-audit contract events may store model IDs, prompt-template IDs, source object IDs, source-citation audit event IDs, contract hashes, required audit field names, citation counts, approval states, and blocking reasons. CRM/ERP redaction contract events may additionally store redaction policy IDs, redaction contract hashes, covered source data classes, required redaction step names, upstream prompt-audit event IDs, and blocking reasons. CRM/ERP authorized-context contract events may additionally store authorized chunk counts, contract hashes, upstream redaction event IDs, covered source data classes, required context step names, and blocking reasons. CRM/ERP inference-execution boundary events may additionally store required inference event types, model provider/checksum metadata, prompt-template versions and approval states, tenant AI/RAG policy booleans, risk levels, derived inference data classes, policy decisions, human-confirmation presence, upstream authorized-context event IDs, boundary hashes, provider-call flags, answer-generation flags, and blocking reasons. They must not store prompt bodies, retrieved source text, redacted source text, context bodies, generated outputs, tool-call bodies, transcripts, raw audio, embeddings, or source snippets.

## Logging rule

Prompts, retrieved source text, outputs, and transcripts must not be written to normal application logs. Audit records may store hashes and controlled metadata.

Vector worker events may store source IDs, source versions, counts, lifecycle targets, model IDs, ACL hashes, ACL versions, and upstream audit event IDs. They must not store raw source text, prompts, generated answers, transcripts, raw audio, or raw embedding vectors.

Embedding model administration events may store model ID, model version, provider, deployment, dimensions, distance metric, checksum, approved data classes, approval or retirement references, and status timestamps. They must not store model weights, tokenizer files, prompts, outputs, source text, or embeddings.

RAG retrieval events may store candidate counts, authorized source counts, authorized chunk counts, authorized chunk references, retrieval policy IDs, source object IDs, source versions, and source classifications. They must not store retrieved chunk text or generated answers.

Keyword search events may store candidate counts, authorized candidate counts, authorized candidate references, search policy IDs, source object IDs, source versions, source classifications, and result-contract metadata. They must not store raw query text in metadata, source text, snippets, prompts, generated answers, transcripts, raw audio, or embeddings.

## PostgreSQL audit store

`collabio.audit_events` persists the same hash-chain fields with a tenant-local sequence number. The `collabio_audit_writer` role can only `SELECT` and `INSERT` tenant-scoped rows through RLS. The normal `collabio_app` role has no audit-table grants.

`collabio.audit_checkpoints` stores HMAC-SHA256 checkpoint evidence over a tenant chain prefix. The row stores a key reference and the checkpoint hash, never signing key material.

`collabio.audit_worm_exports` stores evidence that a checkpointed chain prefix was exported to WORM-capable storage. It records the export manifest hash, storage URI, object lock mode, and audit chain reference; the object-store write path remains responsible for actual WORM enforcement.

These two tables are the legacy v1 path. Existing rows remain readable and restoreable, but new production automation must use the v2 path below. HMAC checkpoint creation accepts process-local secret material and is therefore not a production signing boundary.

## KMS-signed WORM snapshots v2

`audit_worm_snapshot_worker` creates a complete tenant audit-chain prefix from sequence 1 through the latest committed event. It verifies the chain before any provider call, serializes events canonically, and builds `audit_worm_snapshot_manifest.v2` with the exact range, event hashes, classification, retention policy and Legal Hold state. Prompt and output bodies are absent because the authoritative audit store contains only hashes and controlled metadata.

The manifest SHA-256 digest is signed through `AuditCheckpointSigner`. Audit-signing keys use the dedicated `kms-sign://<tenant>/audit/vN` namespace and are not cryptoshreddable data-class keys. The production adapter calls an asymmetric AWS KMS `SIGN_VERIFY` key with `MessageType=DIGEST`, accepts only ECDSA/SHA-256 or RSA-PSS/SHA-256, immediately asks KMS to verify the detached signature, and records the provider key ID, key version, public-key hash and provider request IDs. The public DER key is included in the signed WORM bundle for later offline verification. No private key or signing secret enters Collabio, Docker, object storage or PostgreSQL.

The signed bundle is written through `AuditWormObjectStore`. The AWS/S3-compatible adapter requires bucket versioning and Object Lock, writes an explicit object version in `COMPLIANCE` mode with an explicit retention timestamp and SSE-KMS, reads that exact version back, verifies its SHA-256, and verifies Object Lock, Legal Hold, metadata and encryption through `HeadObject`. Only then are these rows committed atomically:

- `collabio.audit_snapshot_checkpoints_v2`: append-only KMS signature and chain-prefix evidence.
- `collabio.audit_worm_snapshot_receipts_v2`: append-only exact object-version, retention, readback and encryption evidence.

Both tables use forced tenant RLS, the isolated `collabio_audit_writer` role, denied update/delete policies and owner-level mutation-rejection triggers. The normal application role has no grants. A deterministic checkpoint ID makes a completed chain prefix idempotent. If storage succeeds but the PostgreSQL transaction fails, the protected object version is retained and must be reconciled; it must never be deleted to hide an incomplete receipt.

Operational details and the production proof boundary are in `docs/operations/AUDIT_WORM_SNAPSHOTS.md`.
