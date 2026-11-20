# ADR-0188: Native Office selection translation drafts

Status: Accepted
Date: 2026-10-10

## Context

ADR-0186 and ADR-0187 admit local AI drafts for one exact saved selection. Translation has the same integrity and
confidentiality risks plus language drift: names, figures, obligations and formality can change while a fluent result
appears authoritative. A free target-language or instruction field would also reopen a general prompt surface.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/translations` endpoint. It accepts only the exact current
immutable version ID, one bounded native text anchor and one server-admitted target-language code. The initial fixed
set is German, English, French, Spanish, Italian, Dutch, Polish, Portuguese and Ukrainian.

The request accepts no source text, source-language claim, model, provider, prompt or free instruction. The server
reads the authoritative source after ACL validation and derives the selected text from that immutable version. A
stale version, invalid anchor or inaccessible document fails before inference.

Each target language maps to its own approved versioned prompt-registry entry. The prompt preserves meaning, facts,
names, numbers, commitments and formality; asks for translation only; delimits the source as untrusted data; and
forbids following instructions contained in it. Translation uses only a tenant-allowed, drafting-approved local model
behind the Local LLM Gateway. Public input is handled at least as internal. Confidential and restricted input stays
closed unless tenant, model and exact prompt all admit the confidential class.

The result is rejected when empty, unchanged, oversized or invalid Unicode. It is marked untrusted, transient and
non-indexable and is bound to the object, exact version, anchor, selection hash, target language, model, prompt and
inference audit event. Audit stores hashes and bounded metadata, never source or output bodies.

The browser places the result in the existing editable proposal composer with a visible target-language label.
Creating the suggestion remains an explicit confirmed write, and accepting it remains a second explicit confirmed
write that appends one immutable document version atomically. Discarding the draft changes nothing.

## Consequences

This adds no migration, durable AI draft, free target language, source-language detection, caller-selected
model/provider, automatic suggestion, automatic save, whole-document translation, translation memory,
RAG/indexing, Business/WORM transition or production admission. Outlines, policy comparison, risk analysis,
source-backed RAG, voice and text-to-speech remain separate roadmap items.
