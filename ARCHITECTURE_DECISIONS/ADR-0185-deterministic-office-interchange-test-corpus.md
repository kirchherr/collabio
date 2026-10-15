# ADR-0185: Deterministic Office interchange test corpus

Date: 2026-10-10

Status: Accepted

## Context

ADR-0184 documents feature-level DOCX, ODT and PDF compatibility, but a matrix alone does not prove that the active-
content policy and development parser behave consistently on concrete bytes. The next interchange step needs a
small reproducible corpus before any import dispatcher, export engine or round-trip claim can be considered.

## Decision

Generate nine synthetic repository-owned fixtures: one allowed text, one nonexecuting signature marker and one
blocked active-content input for each of DOCX, ODT and PDF. Use deterministic ZIP metadata for package formats and
bind every source to SHA-256 and byte length. Bind fixture identity, policy expectation and expected text hash into a
canonical manifest hash.

Evaluate every fixture with the real pre-extraction active-content detector and development rich-document parser.
Record exact policy decision, parser outcome, expected text hash and warning count. Block DOCX VBA, ODT Basic script
and PDF JavaScript; marked fixtures remain extractable with visible warnings.

Expose only the tenant-scoped metadata manifest through the Office read gate. Return no source bytes. Audit bounded
counts and closed states only. Keep import dispatch false, every export expectation `blocked_no_engine`, round-trip
fidelity false and production admission false.

## Consequences

Parser and policy drift now fail against deterministic content rather than descriptive metadata alone. The corpus is
synthetic and deliberately bounded; it is not representative external interoperability evidence.

External licensed/provenanced fixtures, expected exported derivatives, malicious-format breadth, nonempty recovery
and engine admission remain required. This ADR adds no migration, content upload, import dispatch, export engine,
round-trip claim or production release.
