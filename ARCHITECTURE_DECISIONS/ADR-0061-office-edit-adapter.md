# ADR-0061: Office Edit Adapter And Selective GenOffice Evaluation

Status: accepted
Date: 2026-08-10

## Context

Collabio needs a complete Office surface, but preview, lightweight document editing, full co-authoring, storage, and AI
are different trust boundaries. ADR-0060 already separates canonical PDF preview from later WOPI collaboration. The
remaining gap is a controlled path for simple DOCX editing without placing an entire desktop office application or its
cloud services inside the trusted platform core.

GenOffice is a useful upstream reference because it exposes TypeScript document, spreadsheet, presentation, PDF, and
agent components. Its DOCX engine preserves untouched package parts while applying targeted paragraph patches. The
repository root is Apache-2.0, while `ee/` has a separate license and trademarks are excluded from the Apache grant. Its
desktop application, provider integrations, local-file assumptions, update path, and AI services do not provide
Collabio tenant isolation, authoritative ACL checks, retention, Legal Hold, recovery, or append-only audit evidence.

Adopting or forking the complete application would therefore widen the attack surface and make security ownership less
clear. Rejecting every useful engine pattern would duplicate difficult format work without benefit.

## Options Reviewed

| Option | Strength | Limitation | Decision |
| --- | --- | --- | --- |
| Fork the complete GenOffice application | Broad feature surface and fast visual progress | Desktop/local-file architecture, cloud AI defaults, large supply-chain and parser surface, no Collabio tenancy or compliance lifecycle | Rejected |
| Import selected GenOffice packages immediately | Reuses focused format engines | Legal, dependency, malicious-file, fidelity, signature, provenance, and recovery gates are not yet complete | Blocked pending evidence |
| Evaluate exact source scopes behind a provider-neutral adapter | Preserves replaceability and lets evidence precede content access | Delivers no editor until the gates and worker exist | Selected |
| Build every Office parser and editor from scratch | Maximum control | High fidelity risk, slow delivery, unnecessary duplication | Rejected as a blanket strategy |
| Use only WOPI for all editing | Mature full co-authoring candidates | Stateful service and content transfer are excessive for simple edits | Retained for full collaboration only |

## Decision

Introduce provider-neutral contract `office_edit_adapter.v1` with three deliberately separate product paths:

1. **Quick Edit** is a Collabio-native editing surface for constrained DOCX and later Markdown operations. It never
   edits the authoritative source version in place. A successful future save creates a candidate SourceObject version,
   runs revalidation and canonical PDF preview, then requires explicit human confirmation before commit.
2. **Full Collaboration** remains a separate WOPI adapter. Collabora Online is the preferred first candidate and
   ONLYOFFICE remains an alternative. WOPI locks, proof keys, callback validation, save semantics, tokens, and write
   receipts do not enter the Quick Edit contract.
3. **Preview** remains `canonical-pdf-libreoffice-pdfjs.v1`. Editing cannot bypass its independent output validation and
   viewer boundary.

GenOffice is not forked. The first evaluation adapter is
`genoffice-docx-quick-edit-evaluation.v1`. It pins upstream repository
`https://github.com/genspark-ai/genoffice` to commit
`fd33934dab1fdf8666af3f88b9794e7b4e19474a` and permits only `packages/docx-engine/**` as a future import candidate.
Presentation and spreadsheet engine paths are reference-only. `ee/**`, the shell, AI provider, and AI search paths are
prohibited. No upstream source is imported by this decision.

The machine-readable policy is `docs/operations/genoffice_evaluation_policy.json`. The application loads and validates
it at startup. Mutable refs, commit drift, widened source scopes, enterprise-tree inclusion, trademark use, content
access, execution, persistence, networking, cloud AI, or production use fail validation.

The metadata-only endpoint
`POST /v1/source-objects/{source_object_id}/versions/{source_version_id}/office-edit-adapter-evaluations` resolves the
authoritative tenant-scoped SourceObject metadata and ACL, requires the caller's expected policy hash, and records only
hash-bound audit metadata. It may classify an allowlisted DOCX as eligible for a future isolated spike. It cannot read
bytes, import source, start an editor, invoke an engine, create a WOPI session, persist state, or write a candidate
version.

Office AI remains behind the Local LLM Gateway. It may produce labelled drafts through typed tools after authoritative
authorization. It cannot call GenOffice cloud services or commit, send, delete, export, or otherwise perform a
compliance-relevant action without explicit human confirmation.

## Source Import Gate

No GenOffice source may enter a runtime image or trusted browser bundle until a new versioned admission policy proves:

- legal review of Apache notices, dependencies, the separate `ee/` tree, and trademark exclusions;
- an exact source-scope manifest, universal dependency lock, SBOM, vulnerability/license review, reproducible build,
  and provenance;
- malicious OOXML, ZIP expansion, macro, OLE, external relationship, remote template, malformed XML, and resource
  exhaustion tests;
- a Word, LibreOffice, GenOffice, and Collabio golden fidelity corpus with explicit safe-export and high-fidelity modes;
- immutable preservation of signed originals and explicit signature-invalidated state on every derived edit;
- an isolated no-egress, non-root worker with CPU, memory, wall-clock, part-count, input, and output limits;
- source-blind candidate revalidation, canonical PDF preview, fresh ACL and tenant checks, human confirmation, and an
  append-only edit receipt bound to source version, engine digest, policy, and output hash;
- backup and restore proof for draft journals, candidate versions, receipts, engine manifests, and interrupted-session
  recovery while keeping transient worker workspaces non-durable.

## Recovery Contract

The current evaluation creates no durable editor state outside the existing append-only audit domain. A future source
import or editor session must update `backup_failover_policy` in the same change. Durable draft journals, saved
candidate versions, collaboration manifests, append-only edit receipts, policy/engine hashes, and recovery reports must
be restored and reconciled before editing traffic resumes. Worker scratch, decrypted copies, and browser session tokens
must never be backed up.

Failover starts with editing disabled. Recovery restores SourceObject metadata and exact object versions, verifies ACL,
retention, Legal Hold, KMS references, draft-to-candidate lineage, and receipt hashes, abandons stale locks or sessions,
and resumes only through a fresh admission gate. No recovered draft silently becomes a business record or WORM record.

## Self-Review

The selected DOCX engine may still prove unsuitable. Byte-preserving package updates can also preserve opaque active or
malicious OOXML, and any edit to a signed document can invalidate its signature. The CDR preview path cannot preserve
all edit fidelity. These are reasons for dual export modes, immutable originals, candidate revalidation, and explicit
user-visible warnings, not reasons to weaken the gate.

GenOffice spreadsheet and presentation components are interesting but substantially broader than the first need.
Formula semantics, embedded objects, animations, and co-authoring require separate decisions and corpora. They remain
reference-only so that this step does not turn into an unbounded Office rewrite.

The metadata-only endpoint creates useful, tenant-safe architecture evidence, but no user productivity by itself. The
next valuable implementation step is the legal/supply-chain/fidelity corpus and an isolated DOCX import spike, not more
layers of non-executing endpoints.

## Consequences

Easier:

- Office preview, Quick Edit, WOPI collaboration, and AI remain independently replaceable.
- GenOffice can be used where it reduces real format work without inheriting its entire application architecture.
- Upstream commit, source scope, policy, tenant, ACL, and SourceObject version are hash-bound before content access.
- Recovery obligations are explicit before the first durable draft or editing session exists.

Harder:

- The project must maintain legal, malicious-file, fidelity, and recovery corpora for every imported engine version.
- Quick Edit and full co-authoring need separate UI and backend adapters.
- Byte-preserving and safe-export behavior must be explained clearly to users.
- Upstream updates are intentional reviews, not automatic package bumps.

## Verification

- Policy tests reject mutable refs, widened/imported source scope, enterprise-tree inclusion, content access, and cloud
  AI enablement.
- Unit tests prove that only DOCX metadata is eligible and that all content, execution, session, write, network, AI, and
  WOPI flags remain false.
- API tests prove authoritative ACL and tenant lookup, policy-hash drift rejection, metadata-only output, and hash-only
  audit logging.
- Architecture tests reject content-store, process, network, and provider-client imports in the adapter module.
- Backup policy tests reserve the complete future Office edit state and recovery contract.

## References

- GenOffice repository and architecture overview: https://github.com/genspark-ai/genoffice
- GenOffice Apache-2.0 root license: https://github.com/genspark-ai/genoffice/blob/main/LICENSE
- GenOffice enterprise-tree license: https://github.com/genspark-ai/genoffice/blob/main/ee/LICENSE
- GenOffice security policy: https://github.com/genspark-ai/genoffice/blob/main/SECURITY.md
- GenOffice sheets architecture and known gaps: https://github.com/genspark-ai/genoffice/blob/main/apps/sheets/docs/architecture.md
- Microsoft WOPI overview: https://learn.microsoft.com/en-us/microsoft-365/cloud-storage-partner-program/online/
- Collabora Online SDK: https://sdk.collaboraonline.com/CO-SDK-manual.pdf
