# ADR-0195: Isolated native Office fifty-editor load proof

Date: 2026-10-10

Status: Accepted

## Context

ADR-0180 declared a target of fifty simultaneous editors but deliberately exercised fifty client identifiers
sequentially. ADR-0181 fixed the future WebSocket envelope while keeping upgrades and connections closed. The roadmap
therefore still needs an honest concurrent load proof without presenting an isolated harness as a production CRDT or
WebSocket runtime.

## Decision

Add a deterministic isolated engine harness that starts fifty worker threads behind a common barrier against one
tenant-bound document state. Each editor submits eight ordered update envelopes in synchronized rounds. The harness
contains no document body: update IDs, byte counts, tenant/editor identity and monotonically increasing sequence are
the entire workload.

Every one of the 400 unique updates rechecks the editor's tenant and authorization. Every editor is reauthorized at
connection and twice during the workload. One repeated delivery proves deduplication. A midpoint state-vector
checkpoint must replay exactly the remaining 200 updates, and all fifty editor snapshots must converge to the same
state-vector and update-set hashes.

The proof separately fills the fixed one-MiB queue with four admitted 256-KiB envelopes and requires the next byte to
fail with close code 1013. Revoked ACL and foreign-tenant probes must fail. The committed golden report contains only
counts, booleans and hashes; it contains no document content or raw browser session identifier.

The CRDT preflight may expose `verified_50_parallel_editors` and remove only its former isolated-load blocker.
`websocket_load_verified` and `production_runtime_admitted` remain false. The gateway retains its WebSocket-load
blocker, and CRDT engine admission, durable logging, restore replay, malicious-update fuzzing, upgrade routing,
credentials, fan-out and transport recovery remain closed.

## Consequences

The Phase-3 fifty-editor target now has reproducible concurrent evidence rather than a sequential metadata loop. It
does not authorize live collaboration or weaken the existing ACL, immutable-version, edit-lease or transport gates.
The next Office exit gap is RAG-backed document answers with authoritative ACL validation and exact source versions.
