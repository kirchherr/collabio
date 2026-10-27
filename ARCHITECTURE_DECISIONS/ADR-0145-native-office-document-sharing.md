# ADR-0145: Native Office document sharing

Status: Accepted
Date: 2026-10-08

## Context

Native Office documents already use authoritative tenant-scoped object ACLs, but authors could not inspect or change
direct user access from the Office interface. Sharing must not turn the browser, request claims or the tenant member
directory into an authorization source. It must also preserve immutable version traceability, current-ACL enforcement,
tenant isolation and the existing confirmed-write boundary.

## Decision

Add a bounded direct-user sharing workflow for native Office documents. A current direct `admin` user grant may list
active tenant members, inspect active direct user grants, grant or change `read` and `write`, and revoke a direct user
grant. The owner grant is immutable. Role and group grants continue to authorize document access, but they do not
authorize management of direct user shares. Disabled, unknown and cross-tenant principals fail closed.

Persist every successful mutation through migration 0087. The database security-definer functions revalidate the
tenant, document, direct actor grant, target principal, owner boundary, expected ACL version and unique mutation
reference. Each change revokes the complete active ACL snapshot and writes the complete next snapshot with one
monotonically increasing version. An append-only decision receipt records actor, target, action, permission, previous
and resulting versions and a content-free audit reference. The application role receives only receipt reads and
function execution, never direct mutation rights.

Require explicit human confirmation and optimistic `expected_acl_version` for grant, change and revoke. Expose only
active same-tenant users in the responsive dialog and validate every response fail closed. Apply current ACLs to reads
of both current and historical document versions. Save each immutable document version with the current ACL snapshot
version for audit and recovery traceability; that recorded number never overrides current authorization.

## Consequences

Authors with a direct administrative grant can share a document without leaving Office, and recipients receive or lose
access immediately through the existing authoritative ACL path. Concurrent changes cannot silently overwrite each
other, owner access cannot be removed, and restore verification covers both ACL snapshots and append-only decisions.
Public links, external guests, role/group administration, link passwords, expiration, approval workflows and
classification-driven sharing restrictions remain separate future decisions.
