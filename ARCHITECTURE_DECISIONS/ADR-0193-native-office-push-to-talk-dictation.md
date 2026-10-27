# ADR-0193: Native Office push-to-talk dictation

Status: Accepted
Date: 2026-10-10

## Context

Authors need an explicit voice-to-text path that respects the same tenant, document ACL and immutable-version
boundaries as typed edits. Browser speech recognition can use an external provider, transcripts are personal data,
and raw microphone audio must never enter Collabio implicitly. A transcript must therefore be admitted only after a
fresh policy and document check and must remain a local draft until the author explicitly saves a new version.

## Decision

Add a write-gated `GET /v1/office/documents/{object_id}/voice/dictation-capability` endpoint and a write-gated
`POST /v1/office/documents/{object_id}/voice/dictations` endpoint. Both require the exact current immutable document
version and revalidate the authoritative tenant and document write boundary. The preparation request accepts only a
bounded normalized transcript, exact ProseMirror UTF-16 insertion position, language, explicit push-to-talk state,
raw-audio-storage intent and a fixed recognition adapter. Unknown fields and invalid Unicode fail closed.

`client_local_stt` is available only when tenant voice policy is enabled. `browser_web_speech` additionally requires
the tenant's explicit external-AI/provider admission. The browser checks capability before activating a microphone
path. Recording begins only while the user holds the visible button or keyboard control and ends when it is released.
Always-on listening is absent.

Collabio neither accepts nor stores raw audio. The server rejects every raw-audio-storage request and receives only
the normalized transcript. The Voice Privacy Guard and Office audit record tenant, object, exact source version,
adapter, language, insertion position, character count, policy, event IDs and transcript hash without transcript or
document bodies. The response is noncacheable and labels the transcript as personal `voice_transcript` data with the
transient `transient-not-persisted` retention contract.

The browser validates the complete response and transcript hash before inserting text. The insertion changes only
the local ProseMirror draft. It creates no document version, record, search entry or RAG context and invokes no LLM.
The existing explicit version-save confirmation remains the only durable document write.

## Consequences

This adds no migration, server-side transcript persistence, raw-audio upload, raw-audio storage, background
microphone capture, automatic save, AI inference, indexing, RAG context, destructive action or production admission.
Actual browser microphone permission and the selected provider remain visible user and tenant decisions. Read aloud
through a governed text-to-speech adapter remains the next Office voice roadmap item.
