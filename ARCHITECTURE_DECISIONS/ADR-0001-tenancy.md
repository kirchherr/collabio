# ADR-0001: Tenancy Model And Tenant Context Propagation

Status: accepted
Date: 2026-06-10

## Context

The suite is B2B-only and must support multiple tenants without data leakage across API, database, storage, search, vector indexes, audit, export, AI, or voice workflows.

Tenant isolation cannot be bolted onto feature modules later. It must be a mandatory request and data invariant.

## Decision

Every request that touches tenant data must run with a request-scoped tenant context and principal.

Every persistent object must include:

```text
tenant_id
object_id
object_type
owner_principal_id
created_by
created_at_utc
updated_at_utc
data_classification
retention_policy_id
legal_hold_state
kms_key_ref
audit_chain_ref
source_system
schema_version
```

Authorization is enforced in application logic first. PostgreSQL RLS will be used as defense in depth after persistent storage is introduced.

## Consequences

- APIs without tenant context are invalid.
- Tests must prove tenant leakage cannot occur through normal endpoints, search, RAG, audit, export, or error paths.
- Background workers must carry tenant context explicitly.
- Tenant context cannot be inferred from client-controlled IDs alone.

## Alternatives Considered

- Single-tenant first, multi-tenant later: rejected because it would invalidate storage, audit, search, vector, KMS, and export design.
- UI-only tenant switching: rejected because UI checks are not authorization.
- Database RLS only: rejected because RLS is defense in depth, not the whole policy model.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-001, CM-002
- DSGVO: privacy and security by design
- OWASP ASVS: access control and tenant isolation
- NIST CSF 2.0: Govern, Protect

## Verification

- Tests for missing tenant context.
- Tests for cross-tenant read/write denial.
- Tests for search/RAG candidate leakage.
- Tests for background worker tenant propagation.

