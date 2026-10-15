# ADR-0180: Bounded native Office CRDT service preflight

Date: 2026-10-10

Status: Accepted

## Context

Native Office already separates browser-memory drafts, short-lived advisory edit leases and immutable saved versions.
The roadmap next requires preparation for a CRDT collaboration service, but the repository has no admitted CRDT
engine, durable update log, replay recovery proof, malicious-update fuzzing, fifty-editor load proof or WebSocket
gateway. Treating a client handshake as live collaboration would hide those missing controls.

The preparation must establish one narrow compatibility and authorization boundary while keeping every content-
bearing and runtime path closed. It must not weaken tenant isolation, document ACL checks, edit-lease coordination or
immutable save compare-and-swap.

## Decision

Add a versioned metadata-only preflight command for `collabio-office-crdt-preflight.v1`. It accepts the existing
bounded browser session ID, one bounded client instance ID, the expected current immutable version and one canonical,
unique capability list. Binary update and state-vector support are mandatory; awareness support is optional. The
contract publishes a future 256 KiB update ceiling and a target of fifty concurrent editors, but accepts no update
bytes, state vectors, awareness payload or document content.

Every request passes the Office write gate, authoritative tenant/document write authorization and exact current-
version compare-and-swap. The service also requires the same browser session to hold the current version's active edit
lease. A stale version, foreign session, missing lease, disabled write feature or lost ACL fails closed.

The only successful state is `prepared_runtime_closed`; transport is `websocket_not_admitted` and runtime admission is
false. The response lists six ordered blockers: CRDT engine admission, durable update log, restore replay, malicious-
update fuzzing, fifty-editor load evidence and WebSocket gateway admission. Document and per-update ACL revalidation
plus immutable save compare-and-swap remain mandatory future properties.

Session and client instance IDs are request-transient. The operation writes no document, version, lease, update or
collaboration state. Its audit event contains only the current version, protocol, capability count, closed contract and
transport states, runtime false and blocker count. It excludes raw IDs, document content and future update bodies.

The responsive **Dokumentstatus** dialog invokes preflight only for a writable document with the current lease and
shows the closed runtime and evidence gaps directly. It does not open a socket or retry a collaboration transport.

## Consequences

Clients and server now share one strict future protocol envelope and the UI exposes its real readiness state without
claiming live coauthoring. Service and API tests cover capability canonicalization, ACL/version/lease binding,
write-disablement, metadata-only audit and unchanged persistent document state. Fifty distinct client metadata values
verify the declared target field and stateless behavior; this is deliberately not a concurrent load test. The real
desktop/mobile lifecycle workflow verifies the visible closed boundary.

WebSocket routing, CRDT engine selection, update validation, durable sequencing, presence, merge behavior, recovery
replay, fuzzing, a real fifty-editor load test and production admission remain separate roadmap work. None may infer
admission from this preflight response.
