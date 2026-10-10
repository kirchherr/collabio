# ADR-0177: Bounded native Office advisory edit leases

Date: 2026-10-10

Status: Accepted

## Context

Native Office already uses immutable saved versions and optimistic compare-and-swap, but two browser sessions can
still edit the same saved version and discover the conflict only when one tries to save. Authors need early, visible
coordination that protects an unsaved draft without weakening tenant isolation, document ACLs or version history.

A coordination record can become a privacy and authorization hazard if it exposes another principal, stores raw
browser identifiers, outlives the version it describes or is mistaken for a security lock. It must also remain
recoverable with the rest of the Office PostgreSQL domain.

## Decision

Migration 0090 adds one `office.document_edit_leases` row per tenant and document. The row binds a holder to the
current immutable base version for 90 seconds and records a monotonically increasing revision, acquire/renew/expiry
timestamps, an optional release timestamp, takeover count and metadata-only audit reference. Forced tenant RLS,
tenant policies, a no-delete policy and column-level app update grants constrain storage access.

The repository persists the browser session only as a SHA-256 binding over tenant ID, object ID, principal ID and
session ID. API responses expose only `available`, `held_by_current_session`, `held_by_other` or `unavailable`, plus
bounded coordination metadata. They never return another holder's identity or a raw session value.

Read, acquire, renew and release remain behind the Office feature gate and authoritative document read/write checks.
PostgreSQL serializes mutations with a tenant/document advisory transaction lock. Acquire and renew require the
caller's expected current version ID; a new saved version therefore invalidates every lease on its predecessor.
The lease supplements the existing immutable-version compare-and-swap and never authorizes a read or write.

An active foreign session makes the editor read-only. Takeover requires a separate dialog and explicit confirmation.
The browser reconciles and renews every 15 seconds and releases best-effort on workspace close or page unload. If
status is foreign or unavailable, content editing and Save fail closed while the already-entered local draft stays in
memory. A confirmed takeover makes the previous session observe read-only state within the bounded poll interval.

Lease reads, requests, actual takeovers, actual releases and ineffective release requests receive distinct
metadata-only audit events. Audit records contain status, revision and base version, never document content or raw
session IDs.

## Consequences

The edit-lease table, RLS policies, constraints and column grants are part of the PostgreSQL backup/restore contract.
In-memory, API and PostgreSQL tests cover contention, explicit takeover, hashed storage, tenant isolation, stale
version rejection, save invalidation, release and audit precision. A real two-browser Playwright workflow passes on
desktop and mobile and confirms local draft retention after takeover.

The feature provides one-writer advisory coordination for one saved document version. It does not implement CRDT,
WebSocket broadcast, presence, operational transforms, merge, simultaneous coauthoring, durable browser drafts or
DOCX lock interoperability. Expiry or takeover can allow a new writer, while ACL and current-version CAS remain the
authoritative security and consistency boundaries.
