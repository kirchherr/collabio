# RAG Security Model

## Required flow

```text
user query
  -> tenant context
    -> policy engine
      -> vector search candidates
        -> authoritative ACL check
          -> source fetch
            -> redaction
              -> prompt build
                -> local LLM
                  -> answer with source citations
                    -> audit
```

## Non-negotiable rules

- Vector search returns candidates only.
- Candidate metadata is not sufficient authorization.
- Source objects are fetched only after ACL validation.
- Vector metadata must carry the authoritative ACL hash and ACL version that were current at indexing time.
- Index jobs with stale expected ACL versions must fail before writing vector metadata.
- Reindex workers must not mix multiple ACL hashes or ACL versions in one source-version reindex.
- RAG answers must cite source object IDs and versions.
- Prompt injection content in documents is treated as untrusted data.
- Authorized source text is rendered inside explicit untrusted source blocks before prompting.
- Inference data classes must include `ai_prompt` plus the classifications of all authorized source objects used in context.
- RAG must be blocked when the tenant policy, model policy, or prompt policy does not allow any source classification in the final context.
- Deleted or cryptographically destroyed sources must disappear from retrieval context.
