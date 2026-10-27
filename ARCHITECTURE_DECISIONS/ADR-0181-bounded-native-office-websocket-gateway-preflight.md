# ADR-0181: Bounded native Office WebSocket gateway preflight

Date: 2026-10-10

Status: Accepted

## Context

ADR-0180 establishes a metadata-only CRDT compatibility boundary while keeping the engine, update log and transport
closed. The next roadmap item prepares the WebSocket gateway. A credible gateway contract must settle browser origin,
subprotocol, credential, frame, backpressure, heartbeat, reauthorization, lifetime, delivery and resume rules before
an upgrade route can exist.

The current repository still lacks a single-use credential store, a WebSocket upgrade handler, per-update
authorization, disconnect recovery, multi-node fan-out, an admitted CRDT engine and load evidence. The preparation
must expose those gaps instead of creating a socket that looks usable.

## Decision

Add `collabio-office-websocket-preflight.v1` as a metadata-only HTTP preflight layered on the CRDT protocol. The body
contains bounded session, client and expected-version identifiers, the exact future subprotocol
`collabio-office-crdt.v1`, the complete canonical transport capability list and the existing 256 KiB frame ceiling.
It contains no caller-supplied origin, credential, URL, update or document content.

The API derives the request origin and requires an exact constant-time match with the browser `Origin`. Missing,
opaque, malformed and cross-origin values fail closed before document lookup. The ordinary Office write gate,
authoritative tenant/document write ACL, exact current immutable version and current browser edit lease are then
revalidated.

The future transport is binary-only with compression disabled. One frame is limited to 256 KiB; queued bytes are
limited to 1 MiB and overload uses close code 1013. Heartbeat cadence is 25 seconds, reauthorization cadence is 60
seconds and one connection may live at most five minutes. Resume requires state-vector reconciliation. Delivery is
at least once and therefore requires client deduplication. Document and per-update ACL revalidation remain mandatory.

A later upgrade requires a short-lived, single-use, hash-bound credential from an authenticated HTTP exchange. This
slice deliberately does not issue it. Query credentials are forbidden, responses include neither ticket nor socket
URL, server connection acceptance is false and the advertised socket path has no registered upgrade route.

The response lists eight ordered blockers: upgrade route, credential store, real origin/subprotocol rejection
integration, per-update authorization, backpressure/disconnect recovery, multi-node fan-out, CRDT engine admission
and WebSocket load evidence. Audit contains only version, protocol, bounded counts, closed states and blocker count;
raw origin, session/client IDs, credentials and content are excluded.

## Consequences

The browser and server now agree on a strict future transport envelope, and **Dokumentstatus** displays the closed
gateway state after the CRDT preflight. Desktop and mobile exercise a real same-origin HTTP request and validate that
no ticket or socket URL is returned. This remains preparation: no WebSocket object is created and no live
collaboration claim follows.

Implementing the upgrade route requires separate persistence, replay, authorization, abuse, recovery, fan-out and
load decisions plus integration tests that exercise actual handshake rejection and disconnect behavior. None of
those controls may infer admission from this preflight response.
