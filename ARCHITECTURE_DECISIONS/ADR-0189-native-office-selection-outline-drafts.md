# ADR-0189: Native Office selection outline drafts

Status: Accepted
Date: 2026-10-10

## Context

The local writing assistant can summarize, rewrite and translate one exact saved selection. An outline can omit or
reorder commitments while appearing authoritative, and unrestricted formatting would create an ambiguous document
mutation surface. The first outline capability therefore needs a strict, reviewable output grammar and the existing
two-confirmation proposal boundary.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/outlines` endpoint. It accepts only the exact current
immutable version ID, one bounded same-block native text anchor and the fixed detail value `concise` or `detailed`.
The request accepts no source text, model, provider, prompt, free instruction or output format.

The server revalidates the authoritative document ACL and derives the source from the immutable version. Each detail
value maps to an approved versioned prompt. Prompts preserve source language, facts, names, numbers and commitments,
delimit the source as untrusted data and require Markdown bullet lines only. Concise output permits two through eight
nonempty lines; detailed output permits two through twenty.

Only a tenant-allowed, drafting-approved local model behind the Local LLM Gateway is eligible. Confidential and
restricted input remains closed unless tenant, model and exact prompt all admit confidential data. The server rejects
empty, unchanged, oversized, invalid-Unicode, unstructured, one-line or over-limit output.

The response remains untrusted, transient and non-indexable and binds object, version, anchor, selection hash, detail,
validated line count, model, prompt and inference audit event. Audit stores hashes and bounded metadata without source
or output bodies. The browser places the outline in the existing editable proposal composer. Explicit suggestion
creation and separate explicit acceptance remain required before an immutable version can be appended.

## Consequences

This adds no migration, whole-document outline, semantic heading insertion, arbitrary depth, free prompt, durable AI
draft, automatic suggestion/save, RAG/indexing, Business/WORM transition or production admission. Policy comparison,
risk analysis, source-backed RAG, voice and text-to-speech remain separate roadmap items.
