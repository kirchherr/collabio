# Security Policy

## Security Philosophy

This project treats security as a product feature and an architectural constraint. The baseline assumption is that every layer can fail, so the platform must use defense in depth:

- Application-level authorization.
- Database-level tenant defense.
- Storage-level immutability where required.
- KMS abstraction and envelope encryption.
- Append-only audit with tamper detection.
- Search and RAG post-filtering before data exposure.
- CI/CD and supply-chain checks.

## Supported Security Baseline

The current repository is a development skeleton. Production security support begins only after the Phase 0 and Phase 1 gates in `docs/ROADMAP.md` are complete.

Current skeleton guarantees:

- AI is disabled by default unless tenant policy enables it.
- LLM calls route through the Local LLM Gateway.
- RAG candidates are resolved through an Authorized ChunkRepository before context construction, with tenant, ACL, and candidate/chunk metadata checks.
- RAG inference policy receives `ai_prompt` plus the classifications of authorized sources.
- Dev header tenant context is disabled outside `SUITE_AUTH_MODE=dev` and in production environments.
- `jwt` and `oidc` auth modes resolve the request context from signed bearer tokens and server-side membership/ACL state.
- Principal, tenant membership, role, group, object ACL, and ABAC stores have a PostgreSQL/RLS-backed runtime option with read-only app-role access and audit-chain references.
- Authz administration has security-admin-only APIs, approval-reference validation, audit events, and a dedicated PostgreSQL admin role for principal, role, group, ACL, ABAC, and replay-retention mutations.
- OIDC verification supports RS256 JWKS, key refresh, IdP outage policy, and replay detection.
- JWT/OIDC replay state has a PostgreSQL/RLS-backed runtime option with tenant-aware append-only replay events and no token-body storage.
- Audit events have a PostgreSQL/RLS-backed append-only runtime store with an isolated audit-writer role, tenant-local sequencing, HMAC checkpoints, and WORM export evidence.
- Local dev KMS and envelope encryption adapters are disabled in production environments.
- Voice transcripts require explicit push-to-talk activation.
- Tests run in Docker Compose.
- CI scans the repository and built runtime image for vulnerabilities, secrets, misconfiguration, and forbidden licenses, then emits a CycloneDX SBOM.
- Tagged runtime archives receive OIDC/Sigstore-backed build-provenance and SBOM attestations without repository signing keys.

Not yet production-ready:

- Four-eyes approval workflow integration for authz administration.
- Production KMS-backed audit checkpoint signing and automated WORM object writes.
- KMS integration.
- WORM storage enforcement.
- OIDC/SAML integration.
- Production registry promotion policy and long-term release-evidence archiving.

## Reporting Security Issues

Until a private vulnerability intake channel exists, do not publish sensitive findings in public issues. Track private findings in the project security register and mark them as:

- `critical`
- `high`
- `medium`
- `low`

Each finding must include:

- Affected component.
- Tenant impact.
- Data classes impacted.
- Exploit preconditions.
- Evidence.
- Proposed mitigation.
- Test that proves the fix.

## Required Security Controls

- No secrets in source control.
- No sensitive business, document, mail, prompt, output, transcript, token, or key material in logs.
- No API endpoint without authentication and authorization once Phase 1 starts.
- No direct storage, KMS, search, vector DB, or LLM provider access outside approved adapters.
- No parser or converter workload with external network access.
- No runtime role with unnecessary UPDATE/DELETE rights on audit records.
- No WORM bypass path in application or admin code.

## Security Verification Targets

Phase 0 introduces:

- Linting and typing.
- Unit and integration tests.
- Secret scanning.
- Dependency and license scanning.
- Container scanning.
- SBOM generation.
- Prompt-injection tests.
- RAG leakage tests.

Phase 1 introduces:

- Tenant isolation tests.
- Authz bypass tests.
- Audit hash-chain tamper tests.
- AI Control Plane bypass tests.
