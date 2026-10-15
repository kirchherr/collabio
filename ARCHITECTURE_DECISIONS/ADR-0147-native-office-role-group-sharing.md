# ADR-0147: Native Office role and group sharing

Status: Accepted
Date: 2026-10-08

## Context

ADR-0145 and ADR-0146 provide confirmed direct-user document grants with optional expiration. The authoritative ACL
model already recognizes users, roles and groups, but Office administrators could not manage role or group grants in
the native sharing dialog. Administrators therefore had to maintain repeated individual grants or use a separate
authorization path. Adding these subjects must preserve tenant isolation, active-directory validation, immutable owner
access, optimistic ACL revisions and the rule that only a direct user administrator may change document sharing.

## Decision

Allow a current directly granted Office document administrator to grant, change or revoke `read` and `write` access for
an active user, active tenant role or active tenant group. Every API command carries an explicit `principal_type`; IDs
are interpreted only within that type and the current tenant. The server lists active users with active membership,
active roles and active groups. Disabled, unknown and cross-tenant targets fail closed.

Migration 0089 replaces user-specific security-definer functions with subject-aware functions. PostgreSQL validates
the direct actor administration grant, immutable user owner boundary, target type and active target, expected ACL
version, unique mutation reference, permission and optional expiration before replacing the complete active ACL
snapshot. Append-only decisions now record `subject_type`. The application role retains no direct ACL write grant.

Role and group grants authorize normal document reads and writes through the existing authoritative resolution rules.
A role or group grant, including an administrative grant created outside this Office flow, never authorizes share
management: that boundary continues to require a current direct user `admin` entry. Expiration is evaluated at request
time for all three supported subject types.

The responsive dialog labels each target as person, role or group and keys selections by both type and ID. Grant and
revoke requests keep explicit human confirmation, optimistic conflict handling and content-free audit events.

## Consequences

One document decision can safely cover an organizational role or group while preserving immediate membership-based
authorization. ACL snapshots and decision receipts distinguish equal IDs in different subject namespaces. Removing a
membership or disabling a directory subject removes effective access without rewriting document ACLs. Nested groups,
dynamic group rules, delegated share administrators, public links, external guests, notifications and custom recurring
access windows remain separate decisions.
