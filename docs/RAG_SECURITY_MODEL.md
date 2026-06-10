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
- RAG answers must cite source object IDs and versions.
- Prompt injection content in documents is treated as untrusted data.
- Authorized source text is rendered inside explicit untrusted source blocks before prompting.
- Deleted or cryptographically destroyed sources must disappear from retrieval context.
