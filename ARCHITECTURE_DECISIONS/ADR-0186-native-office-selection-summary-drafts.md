# ADR-0186: Native Office selection summary drafts

Date: 2026-10-10

Status: Accepted

## Context

Native Office needs its first bounded writing-assistant operation without allowing AI to broaden document access,
select an external provider, persist generated text automatically or bypass the existing saved-version and suggestion
confirmation contracts. Browser selection text is not authoritative and cannot be trusted as the model source.

## Decision

Add a read-gated summary endpoint for one nonempty text selection within the current immutable document version. The
client sends only the exact version ID and native text anchor. The server revalidates the document ACL, reads the
saved version and derives the selected text itself. Stale versions and invalid anchors fail closed.

Select a summarization-approved model only from the tenant allowlist and only when its registry deployment is local
and its provider is an admitted Local LLM Gateway provider. Treat public content at least as internal. Confidential
and restricted content map to the confidential AI data class and remain blocked until tenant, model and prompt
registries all admit that class.

Return the generated summary as untrusted, transient text bound to the exact object, version, anchor and selection
hash. Persist neither prompt nor output body outside the hash-only AI audit. Record model ID, prompt-template ID,
source object ID, input/output hashes and the inference audit reference. Do not change the document or create a
suggestion.

In the browser, place the result in the existing proposal composer with a visible untrusted-AI label. The user must
still explicitly confirm creation of the suggestion and separately confirm acceptance before a new immutable
document version can exist.

## Consequences

The feature is useful with any tenant-admitted local summarization model and remains deterministic in the isolated
test environment through the registered mock provider. Cloud-provider selection, caller-selected models, automatic
save, automatic suggestion creation and Business/WORM record transitions remain impossible.

This decision adds no migration or durable AI-draft store. It does not cover whole-document summaries,
multi-paragraph selections, rewriting, tone, translation, outlines, policy comparison, risk analysis, RAG citations,
voice or text-to-speech.
