# ADR-0010: RAG Security Model And Candidate-Only Search

Status: accepted
Date: 2026-06-10

## Context

RAG can leak data if search or vector stores return unauthorized text, snippets, or embeddings directly. Search indexes and vector databases are not authorization sources.

## Decision

RAG and search must follow:

```text
query
  -> candidate ids
    -> authoritative ACL check
      -> authorized chunk repository
        -> exact chunk fetch
        -> redaction
          -> RAG context
            -> Local LLM Gateway
              -> answer with citations
                -> audit
```

Vector search and keyword search may return candidate identifiers and metadata for filtering, but not final user-visible content before authorization and redaction. Keyword search candidate API responses are visible only after authoritative ACL validation and still must not include raw index text or snippets. RAG context construction must fetch exact chunks by candidate identity and must validate tenant, ACL, source version, chunk ID, classification, ACL hash/version, embedding model version, and content hash before text enters the prompt.

RAG answers must cite source object IDs and source versions. Answers without sources must be labeled unsupported.

## Consequences

- Retrieval quality and authorization are separate concerns.
- Source resolver and redaction layer become mandatory.
- Embedding deletion/reindex flows must track source lifecycle.
- Keyword search events must be auditable without storing plaintext query bodies in metadata or index snippets in outputs.

## Alternatives Considered

- Let vector DB metadata filters decide authorization: rejected because stale ACLs and metadata bugs can leak data.
- Return search snippets directly from index: rejected because snippets can expose unauthorized content.
- Use generic RAG framework as core orchestrator: rejected for the security-critical path; adapters may be used behind our orchestration.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-009, CM-010, CM-011
- DSGVO: data minimization and access control
- OWASP LLM/GenAI: vector and embedding weaknesses

## Verification

- Unauthorized candidate tests.
- Keyword candidate-only response tests.
- Deleted source tests.
- Legal-hold visibility tests for authorized roles.
- Citation tests.
- Prompt-injection tests with hostile source text.
