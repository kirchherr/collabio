# ADR-0004: Append-Only Audit Event Model

Status: accepted
Date: 2026-06-10

## Context

Normal application logs are not evidence. The suite needs an audit trail that can prove what happened, who acted, under which tenant/policy context, and whether later tampering occurred.

## Decision

The audit system will use append-only typed events with a hash chain.

Minimum audit event fields:

```text
event_id
tenant_id
actor_principal_id
event_type
occurred_at_utc
object_refs
policy_refs
source_ip_or_session_ref
input_hash
output_hash
previous_event_hash
event_hash
signature_ref
schema_version
```

Sensitive bodies such as document text, mail bodies, prompts, outputs, transcripts, and secrets are not written to normal logs. Audit events may store hashes, IDs, classes, versions, and controlled metadata.

## Consequences

- Audit writes become part of domain workflows.
- Tamper verification tooling is required.
- Runtime roles must not update or delete audit rows.
- Periodic WORM snapshots are needed for long-term evidence.

## Alternatives Considered

- Use normal logs: rejected because logs are not structured, append-only evidence.
- Store full sensitive bodies in audit: rejected because audit would become a high-risk data lake.
- Add hash-chain later: rejected because early events would lack evidence continuity.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-007, CM-011, CM-012
- GoBD: traceability and procedural documentation
- NIST CSF 2.0: Detect, Respond, Recover
- OWASP ASVS: logging and monitoring

## Verification

- Tamper detection tests modify/remove events and verifier must fail.
- Tests prove prompts/outputs/bodies are stored as hashes only in normal audit paths.
- DB permission tests prove runtime roles cannot update/delete audit events.
- WORM snapshot tests verify exported audit partitions.

