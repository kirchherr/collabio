# Agent Rules

## AI, Voice and RAG rules

- No AI feature may bypass tenant isolation.
- No LLM may receive data the current user is not authorized to read.
- No vector search result may be returned without authoritative ACL validation.
- Vector DB metadata must include tenant_id, object_id, object_type, classification, retention_policy_id, legal_hold_state and acl_version.
- RAG answers must cite source object IDs and source versions.
- LLM output is untrusted until validated.
- LLM output must not directly trigger destructive actions.
- Destructive, external or compliance-relevant actions require explicit human confirmation.
- Prompts, retrieved context, model ID, tool calls and output hashes must be audit logged.
- Sensitive prompts and outputs must be redacted before observability logging.
- Voice input must be explicit push-to-talk or explicitly activated.
- Always-on microphone capture is forbidden by default.
- Raw audio must not be stored unless a tenant policy explicitly allows it.
- Transcripts are personal data and must follow retention policies.
- AI-generated content must be labelled where required by policy or law.
- RAG indexes must be rebuildable and deletions must propagate to vector indexes.
- Embeddings must not be treated as anonymous by default.
- No cloud AI provider may be used unless enabled by tenant policy.

## Development rules

- Run the suite through Docker Compose.
- Keep provider adapters behind the Local LLM Gateway.
- Add or update tests for every policy, registry, RAG, or voice behavior change.
- Do not write prompt or output bodies to normal application logs.

