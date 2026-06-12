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
