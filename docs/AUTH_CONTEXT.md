# Authentication And Principal Resolution

The current runtime supports two authentication modes:

- `SUITE_AUTH_MODE=dev`: local development header context.
- `SUITE_AUTH_MODE=jwt` or `SUITE_AUTH_MODE=oidc`: signed bearer-token context.

Development headers are explicitly not a production path. They are disabled when `SUITE_ENV` is `prod` or `production`.

## Signed JWT Flow

```text
Authorization: Bearer <signed JWT>
  -> JWT signature and registered-claim validation
  -> server-side principal lookup
  -> server-side tenant membership lookup
  -> server-side role and group resolution
  -> server-side object ACL resolution
  -> request-scoped UserContext
  -> tenant policy lookup
```

Client-provided `X-Role-Ids`, `X-Readable-Object-Ids`, and `X-Tenant-Id` are ignored in `jwt` and `oidc` mode. The selected tenant currently comes from the signed `tenant_id` claim and is accepted only when the resolved principal has an active server-side membership for that tenant.

## Required JWT Claims

- `iss`
- `sub`
- `aud`
- `tenant_id`
- `exp`

Optional validated claims:

- `iat`
- `nbf`
- `jti`

`jwt` mode uses a local HS256 verifier for signed development and integration tests. `oidc` mode supports both static and discovery-backed OIDC/JWKS verification.

Static OIDC/JWKS verification supports:

- trusted issuer allowlists
- audience allowlists
- RS256 verification from JWKS keys
- `kid`-based signing-key selection and rotation
- `jti` replay detection
- verifier health reporting

Static `oidc` mode requires either:

- `SUITE_OIDC_ISSUERS_JSON`, a JSON array of issuer configs with `issuer`, `audiences`, and `jwks`
- or `SUITE_OIDC_ISSUER`, `SUITE_OIDC_AUDIENCE`, and `SUITE_OIDC_JWKS_JSON`

Discovery-backed `oidc` mode is enabled with either:

- `SUITE_OIDC_DISCOVERY_ISSUERS_JSON`, a JSON array of issuer configs with `issuer`, `audiences`, `discovery_url`, refresh settings, stale-grace settings, and outage policy
- or `SUITE_OIDC_ISSUER`, `SUITE_OIDC_AUDIENCE`, and `SUITE_OIDC_DISCOVERY_URL`

The discovery-backed verifier fetches `.well-known/openid-configuration`, validates the issuer, fetches JWKS, refreshes keys on schedule, refreshes again when an unknown `kid` appears, and can either fail closed or use stale keys during an IdP outage until the configured grace period expires.

`jti` replay detection can use a JSON file store through `SUITE_JWT_REPLAY_STORE_PATH`; by default it stores under `SUITE_DATA_DIR/auth/jwt_replay_store.json`. Production should move replay state to PostgreSQL or another durable low-latency store with tenant-aware audit events.

## Server-Side Authorization

Runtime `UserContext` fields are derived as follows:

- `user_id`: server-side principal directory
- `tenant_id`: signed tenant claim plus active server-side membership
- `role_ids`: server-side tenant membership
- `readable_object_ids`: server-side object ACL records using user, role, and group grants

No LLM, RAG, module, admin, or voice endpoint may derive roles or readable object IDs from caller-controlled headers.

## PostgreSQL Principal Directory

`SUITE_PRINCIPAL_DIRECTORY_BACKEND=postgres` enables the PostgreSQL-backed Principal Directory. It uses `SUITE_PRINCIPAL_DIRECTORY_DSN` when set, otherwise `SUITE_DATABASE_DSN`.

The store is tenant-scoped and protected by PostgreSQL RLS:

- `tenant_principals`
- `tenant_principal_memberships`
- `tenant_roles`
- `tenant_groups`
- `tenant_principal_role_assignments`
- `tenant_principal_group_memberships`
- `object_acl_entries`
- `abac_policy_bindings`

Every row carries `tenant_id`, `audit_chain_ref`, and `schema_version`. The normal `collabio_app` role receives read access only; future authz administration must write through explicit audit and approval paths.
