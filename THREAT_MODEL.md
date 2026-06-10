# Threat Model

Status: initial
Date: 2026-06-10

## Scope

This initial threat model covers the planned enterprise suite foundation:

- Identity and tenant context.
- Authorization and policy engine.
- Data classification.
- KMS and cryptographic boundaries.
- Storage and WORM records.
- Audit events.
- Search, vector search, and RAG.
- Local LLM gateway.
- Voice transcripts.
- Office and mail parser boundaries.
- Exports and e-discovery.

## Assets

- Tenant data.
- Business records.
- Evidence records.
- Draft and collaborative working data.
- Mail messages and attachments.
- Audit events and hash chains.
- KMS keys and key references.
- Search indexes and snippets.
- Vector embeddings and retrieval traces.
- AI prompts and outputs.
- Voice transcripts and optional raw audio.
- Export packages and chain-of-custody records.
- Admin policies and model/prompt registries.

## Trust Boundaries

```text
Browser / Client
  -> API Gateway
    -> Tenant Context / Authz
      -> Domain Services
        -> DB / Storage / Search / Vector DB / KMS / LLM Gateway
          -> Worker Sandboxes
```

Key boundaries:

- Client-to-API is untrusted.
- AI outputs are untrusted.
- RAG source content is untrusted.
- Uploaded office/mail files are untrusted.
- Search/vector indexes are untrusted for authorization.
- Admin users are powerful but not omnipotent; break-glass and WORM controls still apply.

## Threats And Required Mitigations

| Threat | Risk | Required mitigation |
| --- | --- | --- |
| Tenant data leakage | Cross-tenant disclosure | Request-scoped tenant context, app authz, DB RLS, tenant-scoped storage metadata, tenant isolation tests |
| Authz bypass | Unauthorized access or action | Deny-by-default policy engine, server-side checks, no UI-only authorization |
| Audit tampering | Loss of evidence | Append-only audit, hash chain, runtime DB permissions, verifier, WORM snapshots |
| KMS bypass | Data exposure or unrecoverable deletion | Crypto adapter only, key refs not raw keys, key-use audit, rotation tests |
| WORM bypass | Record mutation or deletion | Object lock, retention policy, legal hold enforcement, no direct storage writes |
| Search index leakage | Unauthorized snippets or hits | Candidate-only index, authoritative ACL check, source fetch, redaction |
| Vector leakage | Semantic discovery of protected data | Tenant filters, candidate-only retrieval, ACL validation, embedding classification |
| Prompt injection | Tool misuse or exfiltration | Treat retrieved content as untrusted, tool permissions, human approval, injection tests |
| Excessive AI agency | Unsafe autonomous action | Prepare-don't-execute default, tool registry, approval engine, audit |
| Sensitive logging | Data exposure | Hashes and IDs in logs, no raw prompts, outputs, documents, mails or transcripts |
| Malicious document upload | Parser exploit | Isolated parser workers, no network, resource limits, malware scanning |
| Mail attachment exploit | Malware or data leak | MIME sandbox, attachment scan, no direct preview before scan |
| Legal hold bypass | Illegal deletion | Hold in policy, storage, retention worker and export logic |
| DSGVO/GoBD conflict | Wrong deletion or over-retention | Lifecycle decision order and policy evidence |
| Supply-chain compromise | Backdoored dependency or image | SBOM, provenance, signing, pinning, scanning |

## Security Invariants

- No persistent object exists without tenant and classification metadata.
- No record write occurs without retention metadata.
- No AI call occurs without tenant policy, model ID, prompt ID, purpose, and audit.
- No RAG response uses a source before authoritative ACL validation.
- No destructive action is performed by AI directly.
- No raw key material is exposed to business services.
- No parser has network access.

## Open Threat Model Work

- Add STRIDE/DREAD-style scoring.
- Add data-flow diagrams.
- Add abuse stories for each phase.
- Add threat-to-test mapping.
- Add compliance-control mapping.
- Add parser-specific model for DOCX/XLSX/PPTX/PDF/MIME.

