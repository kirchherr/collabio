# ADR-0192: Native Office versioned source search

Status: Accepted
Date: 2026-10-10

## Context

Authors need to find supporting material without losing the exact document version behind a result. A global title or
content index can leak inaccessible metadata, and a vector or RAG result is not authoritative authorization. Search
therefore needs bounded server-side discovery followed by fresh ACL and version checks for every candidate.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/source-searches` endpoint. It accepts the exact current
saved source version, a normalized query of one through eight searchable terms and a result limit of one through ten.
It accepts no document body, model, provider, prompt, embedding, vector candidate or browser-supplied citation.

The service first revalidates the source document's authoritative read ACL and current version. It asks the existing
tenant-scoped repository for at most 101 currently readable candidates, excludes the source document, and re-reads
each candidate document and its exact current version through the authoritative repository before loading content.
It admits at most 100 documents, 32,000 native text characters per document and 256,000 characters in aggregate.
When the document or aggregate bound is reached, the response reports truncation.

Search is deterministic case-folded keyword matching over server-derived native text blocks. Each result contains
only an exact object ID, immutable current version ID, title, information classification, content hash, ACL version,
server-derived excerpt, score and ProseMirror UTF-16 anchor. The response states that current version and ACL were
validated. The browser renders dismissible read-only cards and opens a result through the existing exact-version read
path, which performs another authorization check.

The operation uses no LLM, vector store or RAG context and creates no durable result, index entry, suggestion or
document version. Audit records the query hash, bounded counts, exact result object/version references and content
hashes, but never query text, document text or excerpts. Responses are noncacheable.

## Consequences

This adds no migration, cross-tenant discovery, historical-candidate search, fuzzy or semantic ranking, persistent
search result, vector metadata, RAG answer, model invocation, automatic citation insertion or production admission.
Push-to-talk dictation, read aloud and production-grade indexed search remain separate roadmap items.
