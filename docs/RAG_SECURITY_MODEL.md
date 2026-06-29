# RAG Security Model

## Required flow

```text
user query
  -> tenant context
    -> policy engine
      -> keyword/vector search candidates
        -> authoritative ACL check
          -> authorized chunk repository
            -> exact chunk fetch
            -> redaction
              -> authorized context contract
                -> prompt build
                -> local LLM
                  -> answer with source citations
                    -> audit
```

## Non-negotiable rules

- Keyword and vector search return candidates only.
- Candidate metadata is not sufficient authorization.
- Search responses must not return raw source text, snippets, prompts, answers, or embeddings from the index.
- Keyword search candidate responses are user-visible only after authoritative ACL validation.
- Keyword search audit events store candidate counts, authorized candidate refs, policy IDs, and hashes, never raw query text in metadata or source snippets.
- Source chunks are fetched only through the Authorized ChunkRepository after tenant, ACL, and candidate/chunk metadata validation.
- RAG context must contain exact authorized chunks, not whole source documents.
- Vector metadata must carry the authoritative ACL hash and ACL version that were current at indexing time.
- Index jobs with stale expected ACL versions must fail before writing vector metadata.
- Reindex workers must not mix multiple ACL hashes or ACL versions in one source-version reindex.
- RAG answers must cite source object IDs and versions.
- Prompt injection content in documents is treated as untrusted data.
- Authorized source text is rendered inside explicit untrusted source blocks before prompting.
- Inference data classes must include `ai_prompt` plus the classifications of all authorized source objects used in context.
- RAG must be blocked when the tenant policy, model policy, or prompt policy does not allow any source classification in the final context.
- Deleted or cryptographically destroyed sources must disappear from retrieval context.

## CRM/ERP source resolver ACL trace

`POST /v1/platform/search/crm-erp/source-resolver-acl-trace` is the metadata-only bridge between ACL-first CRM/ERP search candidates and any future RAG context builder.

- The request accepts object IDs only, not query text, snippets, prompts, or source bodies.
- The server resolves candidate metadata from canonical CRM/ERP repositories, not from client-supplied metadata.
- Each resolved source ref is revalidated against the current tenant context and readable object IDs.
- Blocked or unresolved refs are reported by object ID only and do not include classification, hashes, titles, snippets, or source text.
- The response is not RAG context and must keep `content_included=false`, `ai_used=false`, and `rag_context_created=false`.
- CRM/ERP RAG readiness may satisfy the source-resolver ACL-trace gate only after this endpoint and its audit coverage are present.

## CRM/ERP source citation contract

`POST /v1/platform/search/crm-erp/source-citation-contract` is the metadata-only proof that authorized CRM/ERP refs can be cited before any prompt or retrieval context exists.

- The request accepts object IDs only and reuses the server-side source resolver ACL trace.
- Client-supplied source metadata is not trusted; citation refs are created only from authoritative resolved source refs.
- Each citation carries tenant ID, source object ID, source object type, source version ID, source chunk ID, classification, retention policy ID, legal hold state, ACL version, ACL hash, and content hash.
- Blocked or unresolved refs are reported by object ID only and do not include citation metadata.
- The response is not RAG context and must keep `content_included=false`, `ai_used=false`, and `rag_context_created=false`.
- CRM/ERP RAG readiness may satisfy the source-citation gate only after this endpoint and its audit coverage are present.

## CRM/ERP prompt audit contract

`POST /v1/platform/search/crm-erp/prompt-audit-contract` is the metadata-only proof that future CRM/ERP RAG inference can be bound to audit hash requirements before any prompt or retrieval context exists.

- The request accepts object IDs plus model and prompt-template IDs only.
- The server reuses the source-citation contract and does not trust client-supplied source metadata.
- The contract requires `model_id`, `prompt_template_id`, source object IDs, `input_hash`, `output_hash`, context hash, retrieval audit event ID, source-citation audit event ID, authorized chunk refs, source classifications, tool-call hashes, and redaction policy metadata for future inference events.
- Prompt bodies, retrieved source text, generated outputs, and tool-call bodies are not included in the response and remain forbidden in normal application logs.
- The response is not RAG context and must keep `content_included=false`, `prompt_body_included=false`, `output_body_included=false`, `ai_used=false`, and `rag_context_created=false`.
- CRM/ERP RAG readiness may satisfy the prompt-audit gate only after this endpoint and its audit coverage are present; redaction remains a separate required gate before RAG context creation.

## CRM/ERP redaction contract

`POST /v1/platform/search/crm-erp/redaction-contract` is the metadata-only proof that authorized CRM/ERP source refs have a redaction policy boundary before any prompt or retrieval context exists.

- The request accepts object IDs, model and prompt-template IDs, and a redaction policy ID only.
- The server reuses the prompt-audit contract and does not trust client-supplied source metadata.
- The contract requires classification-aware redaction, personal-data minimization, secret and credential masking, legal-hold marker preservation, untrusted source block wrapping, redacted context hash evidence, and a redaction audit event.
- Raw source text, redacted text, prompts, outputs, snippets, and embeddings are not included in the response.
- The response is not RAG context and must keep `content_included=false`, `redacted_content_included=false`, `prompt_body_included=false`, `output_body_included=false`, `ai_used=false`, and `rag_context_created=false`.
- CRM/ERP RAG readiness may satisfy the redaction gate only after this endpoint and its audit coverage are present; authorized context assembly remains a separate required gate before RAG context creation.

## CRM/ERP authorized context contract

`POST /v1/platform/search/crm-erp/authorized-context-contract` is the metadata-only proof that future CRM/ERP RAG can bind exact authorized chunk refs to a redaction contract before any prompt, answer, or context body exists.

- The request accepts object IDs, model and prompt-template IDs, and a redaction policy ID only.
- The server reuses the redaction contract and does not trust client-supplied source metadata.
- The contract returns authorized chunk refs, source object IDs, source versions, source chunk IDs, source classifications, the redaction contract hash, and upstream audit event IDs only.
- Raw source text, redacted text, prompts, outputs, snippets, embeddings, and context bodies are not included in the response.
- The response is not RAG context and must keep `content_included=false`, `redacted_content_included=false`, `prompt_body_included=false`, `output_body_included=false`, `ai_used=false`, `rag_context_created=false`, and `context_body_created=false`.
- CRM/ERP RAG readiness may satisfy the authorized-context gate only after this endpoint and its audit coverage are present; actual inference and answer generation remain separate gated work.
