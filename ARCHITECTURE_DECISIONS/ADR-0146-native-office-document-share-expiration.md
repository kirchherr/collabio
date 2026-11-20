# ADR-0146: Native Office document share expiration

Status: Accepted
Date: 2026-10-08

## Context

ADR-0145 introduced direct-user sharing with authoritative current ACLs, but every `read` or `write` grant remained
valid until an administrator revoked it. Temporary collaboration therefore depended on a later manual action. An
expiration must remain effective even when no scheduler runs, and it must not create a second authorization source or
weaken tenant, owner, history, optimistic-concurrency and audit boundaries.

## Decision

Allow a direct Office document `read` or `write` grant to carry an optional UTC expiration. `NULL` means permanent.
The server accepts only timezone-aware future instants no more than 366 days away. The Office dialog offers the bounded
choices permanent, one day, seven days and 30 days. Owner and administrative grants cannot expire through this flow.

Migration 0088 adds `expires_at_utc` to authoritative object ACL entries and append-only Office share decisions. Every
grant change continues to replace the complete active ACL snapshot at one new monotonic version, including the exact
expiration of every copied grant. The security-definer function independently validates the expiration window and
records it in the decision receipt. Revocation preserves the expiration terms of every unaffected grant.

Evaluate expiration at authorization time in both the central PostgreSQL principal directory and the native Office
repository. An expired entry may remain as immutable ACL evidence with status `active`, but it grants no readable
object ID, never appears as a current share and cannot authorize current or historical content. This makes expiry
independent of background jobs and closes the interval immediately according to database time.

## Consequences

Authors can create permanent or predictably temporary direct-user access, and recipients lose access without a later
operator action. ACL snapshots and append-only receipts retain the exact term for audit and restore. Clock authority is
the PostgreSQL server for persisted authorization and UTC in API validation. Custom dates, recurring access windows,
notifications, extension approval, public links and external guests remain separate future decisions.
