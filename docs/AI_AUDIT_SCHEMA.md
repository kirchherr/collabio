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
- `vector.reindex.started`
- `vector.reindex.completed`
- `vector.reindex.failed`
- `vector.deletion_propagation.started`
- `vector.deletion_propagation.completed`
- `vector.deletion_propagation.failed`

## Logging rule

Prompts, retrieved source text, outputs, and transcripts must not be written to normal application logs. Audit records may store hashes and controlled metadata.

Vector worker events may store source IDs, source versions, counts, lifecycle targets, model IDs, ACL hashes, ACL versions, and upstream audit event IDs. They must not store raw source text, prompts, generated answers, transcripts, raw audio, or raw embedding vectors.
