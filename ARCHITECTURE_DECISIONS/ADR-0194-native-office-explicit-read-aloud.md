# ADR-0194: Native Office explicit read aloud

Status: Accepted
Date: 2026-10-10

## Context

Authorized readers and authors need to hear a bounded saved passage without granting document write access or
placing document content, generated audio or provider choice outside the tenant policy boundary. Browser speech
synthesis may use an operating-system voice or an external browser service. The source must therefore be derived
from the exact authorized immutable version, and speech must start only after a visible user action.

## Decision

Add a read-gated `GET /v1/office/documents/{object_id}/voice/read-aloud-capability` endpoint and a read-gated
`POST /v1/office/documents/{object_id}/voice/read-aloud-preparations` endpoint. Both require the exact current saved
version and freshly revalidate the authoritative tenant and document read ACL. The preparation request accepts only
a bounded same-block ProseMirror UTF-16 anchor, fixed language, rate from 0.5 through 2.0, explicit activation,
false audio-storage intent and one known synthesis adapter. It accepts no source text, free prompt, model or action.

The server derives the one-through-2,000-character passage from the immutable document after authorization.
`client_local_tts` requires tenant voice policy. `browser_speech_synthesis` additionally requires explicit tenant
admission for an external provider. The Voice Privacy Guard audits the selection hash plus tenant, classification,
adapter, language, rate, character count and event identities. The Office audit binds those fields to object, exact
version and anchor. Neither audit contains selected text or document bodies.

The response is noncacheable and returns the authorized passage so the browser can compare it with its exact local
selection and UTF-8 hash before speaking. The browser starts speech only from the visible **Vorlesen** action, exposes
local-versus-browser provider state, offers bounded language and speed choices and provides an explicit stop action.
It cancels speech when selection, document, editor, version or tenant context changes.

Collabio generates no server audio, receives no audio, stores no audio and persists no selection. The operation is
read-only, transient and excluded from search and RAG indexing. It cannot edit a document, append a version, create
a record, call an LLM or trigger another action.

## Consequences

This adds no migration, speech-provider credential, server synthesis runtime, audio upload, audio storage, selection
persistence, document write, AI inference, index, RAG context, destructive action or production admission. Browser
voice availability remains visible and tenant-controlled. The next Phase 3 proof target is 50 simultaneous editors
per document; it does not become complete through this read-only adapter.
