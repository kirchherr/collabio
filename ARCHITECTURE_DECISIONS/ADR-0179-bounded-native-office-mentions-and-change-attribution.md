# ADR-0179: Bounded native Office mentions and change attribution

Date: 2026-10-10

Status: Accepted

## Context

Native Office already stores version-bound discussion threads and append-only, human-confirmed review events outside
the document version stream. Events retain their actor, operation and revision, but the API did not express that
attribution as one explicit contract and comment text had no authoritative mention semantics.

A mention must not become an access-control side channel. It must never grant document access, expose content to an
unauthorized target or silently trigger an external notification. The immutable review payload should remain the sole
content record, and existing events must stay readable without a storage rewrite.

## Decision

Comment and reply bodies may contain canonical `@[principal-id]` tokens. Parsing is fail closed: every `@[` opening
must form one complete token, IDs use the existing bounded principal alphabet, duplicates are returned once in first
occurrence order and one event may mention at most twenty principals.

Before a new event is persisted, the repository verifies each target in the current tenant and exact document
transaction. A target must be an active tenant principal and either the document owner or hold a current, unexpired,
direct user ACL with read, write or admin permission. Role and group grants are not expanded to individual recipients
in this slice. The check occurs after actor write authorization and before the source object, receipt, event or thread
is written.

Idempotent replay is resolved before revalidating current target access. A previously committed command therefore
replays the same event even after a later target revocation. Historical mentions remain part of the immutable comment
and are only returned to callers who still pass the current thread and parent-document authorization. A new event that
mentions the revoked principal fails atomically.

The API derives `mentioned_principal_ids` from the stored body and returns an attribution object containing the exact
actor principal, operation, revision and `human_confirmed: true`. The browser validates that both derived structures
match the event and renders them only with text nodes. Audit receives the bounded mention count, not target IDs or
comment bodies.

The composer explains the syntax and states that a mention grants no access and sends no notification. No notification
outbox, email, push or other external action is part of this decision.

## Consequences

The design reuses the existing immutable event source, content hash, source manifest, write receipt, thread CAS and
tenant RLS. It adds no migration and preserves existing review payload bytes. Service, API and PostgreSQL tests cover
canonical parsing, the target cap, direct ACL validation, atomic rejection, revocation, replay, attribution and
metadata-only audit. Responsive and complete browser matrices cover safe UI rendering on desktop and mobile.

Role/group recipient expansion, notification delivery and notification preferences require separate privacy,
authorization, outbox, retry, audit, retention and user-experience decisions. CRDT, WebSocket, simultaneous editing
and productive admission remain separate Office roadmap work.
