# ADR-0059: Atomic Business Data, ACL And Receipt

Status: Accepted
Date: 2026-07-30

## Context

A productive module write is unsafe when its business row can commit without the authoritative object ACL or when retry evidence can be written independently. A later compensating job leaves a period in which data is inaccessible, overexposed, or ambiguously accepted.

## Decision

Aggregate creation writes business metadata, initial object ACL grants, and an immutable idempotency receipt in one PostgreSQL transaction. The transaction uses a narrowly granted database role that can write the required business tables and authoritative ACL table under Forced RLS.

The receipt is metadata-only and append-only. The command hash includes the tenant-scoped actor. A tenant-scoped mutation reference is serialized with a transaction advisory lock. Matching retries return the original receipt; mismatched retries fail closed.

The global append-only audit event is emitted after commit and references the transaction receipt hash. The transaction receipt is the authoritative proof that business data and ACL state committed together; normal logs remain content-free.

## Consequences

- Partial business/ACL writes roll back automatically.
- The normal application role does not gain ACL mutation permission.
- Each future productive module write must either reuse this unit-of-work pattern or document a stronger transactional equivalent.
- Backup and restore gates must verify the new state relation, RLS, append-only policies, grants, migration, and row counts.
- Cross-database ACL and business-state writes are not permitted for this contract without a separately approved consistency design.
