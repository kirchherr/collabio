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

`jwt` mode uses a local HS256 verifier for signed development and integration tests. `oidc` mode uses a static OIDC/JWKS verifier that supports:

- trusted issuer allowlists
- audience allowlists
- RS256 verification from JWKS keys
- `kid`-based signing-key selection and rotation
- `jti` replay detection
- verifier health reporting

`oidc` mode requires either:

- `SUITE_OIDC_ISSUERS_JSON`, a JSON array of issuer configs with `issuer`, `audiences`, and `jwks`
- or `SUITE_OIDC_ISSUER`, `SUITE_OIDC_AUDIENCE`, and `SUITE_OIDC_JWKS_JSON`

The current OIDC boundary is intentionally networkless and deterministic. Production still needs dynamic `.well-known/openid-configuration` discovery, JWKS refresh scheduling, key-cache expiry, IdP outage policy, and persistent replay storage.

## Server-Side Authorization

Runtime `UserContext` fields are derived as follows:

- `user_id`: server-side principal directory
- `tenant_id`: signed tenant claim plus active server-side membership
- `role_ids`: server-side tenant membership
- `readable_object_ids`: server-side object ACL records using user, role, and group grants

No LLM, RAG, module, admin, or voice endpoint may derive roles or readable object IDs from caller-controlled headers.
