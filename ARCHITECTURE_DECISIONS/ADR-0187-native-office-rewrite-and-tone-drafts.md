# ADR-0187: Native Office rewrite and tone drafts

Status: Accepted
Date: 2026-10-10

## Context

ADR-0186 admits summaries for one exact saved text selection. Rewriting has a larger integrity risk because a fluent
result can silently change facts, commitments or tone and can look ready to publish. Browser-supplied instructions
would also turn the endpoint into a general prompt surface. The feature must therefore reuse the exact-version,
authoritative-ACL and explicit proposal boundary rather than editing the document directly.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/rewrites` endpoint. It accepts only:

- the exact current immutable version ID,
- one bounded native text anchor within one text block,
- the fixed operation `rewrite` or `tone`, and
- for `tone`, exactly one server-admitted value: `neutral`, `professional`, `friendly`, `formal` or `concise`.

The request accepts no source text, model, provider, prompt, free instruction or target language. The server reads the
authoritative source after ACL validation and derives the selected text from that immutable version. A stale version,
invalid anchor or inaccessible document fails before inference.

Each operation/tone maps to one versioned prompt-registry entry. Prompts preserve language, meaning, facts, names,
numbers and commitments; delimit the source as untrusted data; and tell the model not to follow embedded
instructions. The common policy engine now rejects every prompt whose `approval_status` is not `approved`. JSON-file
registries add missing built-in system prompts on startup without replacing existing rows or tenant-pinned versions.

The service selects only a `drafting`-approved model in the tenant allowlist with a local deployment and an admitted
Local LLM Gateway provider. Public content is handled at least as internal. Confidential and restricted content stays
closed unless tenant, model and the exact prompt entry all admit `confidential`.

The result is validated for nonempty bounded Unicode text and rejected when it equals the source selection. It is
marked untrusted, transient and non-indexable and is bound to the object, exact version, anchor, selection hash,
operation, tone, model, prompt and inference audit event. Audit stores hashes and bounded metadata, never source or
output bodies.

The browser puts the result into the existing proposal composer with a visible AI/tone label. A user can inspect and
edit it. Creating the suggestion remains an explicit confirmed write, and accepting it remains a second explicit
confirmed write that appends one immutable document version atomically. Discarding the draft changes nothing.

## Consequences

This adds no migration, durable AI draft, free-form prompting, caller-selected model/provider, automatic suggestion,
automatic save, whole-document inference, translation, RAG/indexing, Business/WORM transition or production
admission. Translation, outlines, policy comparison, risk analysis, source-backed RAG, voice and text-to-speech stay
separate roadmap items.
