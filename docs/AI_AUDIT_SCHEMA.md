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

## CRM/ERP prompt audit contract

CRM/ERP prompt-audit contract events may store model IDs, prompt-template IDs, source object IDs, source-citation audit event IDs, contract hashes, required audit field names, citation counts, approval states, and blocking reasons. They must not store prompt bodies, retrieved source text, generated outputs, tool-call bodies, transcripts, raw audio, embeddings, or source snippets.

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
