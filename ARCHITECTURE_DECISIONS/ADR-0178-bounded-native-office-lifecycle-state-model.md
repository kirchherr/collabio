# ADR-0178: Bounded native Office lifecycle-state model

Date: 2026-10-10

Status: Accepted

## Context

ADR-0005 defines the platform order from working data through draft, collaborative state, saved version, business
record and WORM evidence. Native Office already has browser-memory drafts, immutable saved versions and advisory edit
leases, but the product did not present their boundaries together. That ambiguity can make a temporary edit appear
record-like or suggest that an AI action, a lease or an ordinary save creates a regulated business record.

The current product has no approved record-promotion workflow, retention-policy transition or WORM storage ceremony.
The lifecycle surface must therefore explain current evidence without inventing a transition or persisting extra
content.

## Decision

Native Office exposes a read-only lifecycle response for one authorized document. It declares:

- working data as request-transient;
- a draft as browser-memory only;
- collaborative state as metadata-only advisory lease state for the current immutable version;
- the current saved version as the sole persistent document state;
- business-record promotion as closed; and
- WORM evidence-record promotion as closed.

The request uses the fixed browser edit-session format. The service first performs the normal tenant and document read
authorization. It exposes collaborative state only when the same request also has current Office write access;
otherwise that state is `unavailable`. If exposed, the repository applies the existing tenant/document ACL and hashes
the session binding before comparison. The response never includes another holder, a raw session identifier or
document content.

The lifecycle response states that saving requires explicit human confirmation and exact current-version
compare-and-swap. A future business-record transition also requires human confirmation. `ai_may_commit_business_record`
is always false, and no writable lifecycle route exists.

The responsive **Dokumentstatus** dialog renders these boundaries as text, including whether the current browser has
unsaved changes, the current advisory coordination state and exact immutable version ID. It loads authoritative state
without changing or discarding the local draft.

Lifecycle reads are audit logged with tenant-bound object ID, current version and bounded state names only. Raw
session values and content remain excluded.

## Consequences

Service and API tests cover the exact state vocabulary, read-only behavior, malformed session rejection, lease
binding, human-confirmation flags, the AI prohibition and absence of session values in audit. The complete Office
document service/API files pass 62/62 tests. A real Playwright workflow passes on desktop and mobile and confirms that
opening the dialog preserves an unsaved draft.

This decision adds no migration, durable draft, collaborative content log, record promotion, retention change,
object-lock transition, WORM object, AI action, external provider or production admission. Those require separate
policy, storage, human-confirmation, restore and release evidence before they can open.
