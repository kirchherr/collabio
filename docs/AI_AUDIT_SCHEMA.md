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

## Logging rule

Prompts, retrieved source text, outputs, and transcripts must not be written to normal application logs. Audit records may store hashes and controlled metadata.

