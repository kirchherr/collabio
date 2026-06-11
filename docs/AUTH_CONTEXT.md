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

The current verifier supports HS256 for the local signed-token boundary and tests. Production OIDC must replace or extend this verifier with issuer metadata discovery, JWKS key rotation, asymmetric algorithms, issuer allowlists, audience allowlists, token replay controls, and operational health checks.

## Server-Side Authorization

Runtime `UserContext` fields are derived as follows:

- `user_id`: server-side principal directory
- `tenant_id`: signed tenant claim plus active server-side membership
- `role_ids`: server-side tenant membership
- `readable_object_ids`: server-side object ACL records using user, role, and group grants

No LLM, RAG, module, admin, or voice endpoint may derive roles or readable object IDs from caller-controlled headers.
