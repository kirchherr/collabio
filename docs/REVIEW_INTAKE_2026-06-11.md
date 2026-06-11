# Review Intake 2026-06-11

Source: `review.md`

## Assessment

The review is accepted as a useful static architecture and code review. Its main conclusion is correct: this repository is a strong compliance-first MVP skeleton, but it is not yet a production-ready enterprise suite.

The most important lesson is also correct: the next work must harden the foundation before more product surface is added. Office, mail, CRM/ERP imports, productive RAG, external LLMs, and mass data flows must not outrun identity, authorization, audit, data-classification, KMS, storage, and supply-chain controls.

## Implemented Immediately

- Dev header tenant context is now explicitly dev-only. It fails closed when `SUITE_ENV=prod|production` or when `SUITE_AUTH_MODE` is not `dev`.
- Signed bearer-token auth modes now resolve tenant, roles, groups, and readable object IDs from a server-side PrincipalResolver and ACL directory.
- RAG inference data classes are now derived from the actual authorized source classifications and include `ai_prompt` for the user question.
- Local dev KMS and local dev envelope encryption now fail closed in production environments.
- Tests cover the above regressions.

## Remaining P0 Gates

1. Replace the local HS256 JWT verifier with production OIDC discovery, JWKS key rotation, issuer/audience allowlists, replay controls, and health checks.
2. Persist the PrincipalResolver, tenant membership, role, group, ACL and ABAC stores in PostgreSQL with RLS and audit events.
3. Create a canonical DataClass registry and validate runtime enums, retention, KMS, DB constraints, prompt/model registries, and compliance docs against it.
4. Implement a persistent PostgreSQL append-only audit store with DB-role restrictions, concurrency-safe sequencing, HMAC/signature checkpoints, and WORM export.
5. Introduce an authorized ChunkRepository so RAG sends exact chunks, not whole source documents.

## Release Gate

Until the remaining P0 gates are closed, do not attach real customer data, production mailboxes, production CRM/ERP imports, external LLM providers, destructive automation, or productive RAG over sensitive data.

Allowed work in the meantime:

- identity and authorization foundation
- data-class taxonomy consolidation
- audit persistence and WORM checkpoints
- KMS and storage adapter hardening
- supply-chain CI
- parser/security corpus
- tests, documentation, and compliance evidence
