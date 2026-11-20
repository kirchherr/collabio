# ADR-0196: Native Office RAG document answers

Date: 2026-10-10

Status: Accepted

## Context

ADR-0192 added a bounded, current-version-only source search with authoritative per-document ACL checks, but it
deliberately created no RAG context or answer. The final Phase-3 Office exit criterion requires document answers that
show exact source versions without allowing a browser, retrieved document or model to expand authorization, forge a
citation, persist an AI result or trigger an action.

## Decision

Add a read-gated Office RAG endpoint for an exact current saved document version. Its strict request contains a
normalized question with at most eight searchable terms and a bounded result limit. Tenant AI and RAG policy must be
enabled. Only a tenant-allowed local model approved for RAG and every admitted source classification may run.

Retrieval reuses the ADR-0192 bounded tenant-scoped current-version search. Immediately before inference, every
candidate is fetched again through the authoritative repository, its document must still point to the cited exact
version, and content hash, ACL version, title, classification and server-derived anchor excerpt must still match.
The prompt uses one approved fixed template and marks every authorized source block as untrusted data. The browser
cannot submit source bodies, citations, prompts, models, actions or persistence intent.

If no authorized source remains, return an explicit unsupported answer and do not invoke a model. Otherwise return a
bounded untrusted answer with server-derived citations containing object ID, exact current version ID, title,
classification, content hash, ACL version, anchor and excerpt. Audit records only question/output hashes, model and
prompt IDs, event IDs and exact citation references/hashes; it records no question, source or answer body.

The response is transient, noncacheable, non-indexed and read-only. It cannot change a document, create a suggestion
or record, commit a business version, certify compliance or trigger any action. Confidential and restricted sources
remain fail closed unless tenant, model and prompt registries all admit their classification.

## Consequences

Native Office closes its Phase-3 versioned-source RAG criterion with visible, exact and freshly authorized citations.
The responsive desktop/mobile panel identifies the answer as AI-generated and untrusted and lets the reader open each
exact cited version through the ordinary reauthorized document path. This adds no migration, vector index, durable RAG
result, cloud provider admission, automatic edit or production collaboration runtime.
