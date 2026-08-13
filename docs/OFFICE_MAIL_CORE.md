# Office And Mail Core

The suite is not a document editor with compliance added later.

Office, mail, search, RAG, voice, e-discovery, and admin surfaces must all sit on the same compliance core:

- tenant context
- IAM and authoritative authorization
- object metadata, versions, manifests, and content hashes
- retention, legal hold, WORM, and cryptoshred lifecycle
- KMS references and encryption policy
- append-only audit evidence
- source resolving, parser isolation, text extraction, chunking, and indexing
- candidate-only search and vector retrieval

## Product Surfaces

Office and mail are product surfaces, not separate storage or AI worlds.

Office modules will add editors, spreadsheets, import/export, comments, collaborative drafts, saved versions, business records, and WORM evidence records.

Mail modules will add accounts, messages, threads, attachments, team inboxes, delivery/submission workflows, security evidence, and AI-assisted triage or drafting.

Both surfaces must write and read through the same compliance APIs. No editor, mail client, previewer, or assistant may bypass object metadata, retention, authz, parser isolation, audit, or source indexing.

## Source Object Types

The indexing model already treats source type as metadata:

```text
document
mail
attachment
comment
wiki
procedure_doc
```

These types are used by source resolvers, parser policies, vector metadata, audit events, and later e-discovery/export flows.

## Mail Boundary

RFC mail objects are immutable evidence inputs. Team comments, assignments, labels, workflow state, and internal notes must be separate domain objects and must never be written into the RFC message.

Attachments are separate source objects with their own classification, retention policy, content hash, legal hold state, parser result, and index lifecycle.

Mail AI can draft or classify, but sending mail is a separate explicit action with policy and human confirmation.

## Parser Boundary

Parser code is security-sensitive. Production parsers must run outside the API process in isolated workers.

Parser workers must enforce:

- MIME and source-type allowlists.
- maximum input and output sizes.
- no network access by default.
- no direct storage mutation.
- no direct vector writes.
- separate handling of attachments.
- hash-only audit metadata outside authorized source text flows.

Current implementation:

- `app/suite/storage/source_objects.py` defines the shared source object metadata model, guarded tenant/version-scoped in-memory repository, and RAG-compatible resolver for documents, mail, attachments, comments, wiki content, and procedure documentation.
- `app/suite/rag/parser_worker.py` defines the parser worker request, result, sandbox policy, and `ParserWorkerTextExtractor`.
- `PolicyEnforcedParserWorker` supports `text/plain`, `text/markdown`, and safe `message/rfc822` plain-text extraction for tests and local development.
- `app/suite/rag/rich_document_parser.py` supports DOCX, ODT, and basic text PDF extraction without network access or external processes.
- `rich-document-parser` in Docker Compose runs the parser manifest command in a read-only, no-network, no-new-privileges container.
- Complex PDFs, scanned PDFs, macro-bearing files, password-protected files, and high-fidelity Office compatibility still require dedicated hardened parser engines and malicious-file test corpora.

## Guarded Plain-Text Preview Release

The shared content boundary now includes a productive but deliberately narrow preview release for UTF-8 `text/plain`
and `text/markdown` documents, wiki objects, and procedure documents. It requires current tenant policy, authoritative
ACL revalidation, complete preview-decision and renderer evidence, a fresh operational release gate, unchanged source
manifest/content hashes and ACL version, and exact human confirmation. Output is returned as plain text only and is not
persisted in release receipts or normal audit logs.

This does not open RFC mail bodies, attachments, HTML, PDF, DOCX, ODT, spreadsheets, presentations, macros, active
content, external resources, or mail sending. Those surfaces retain their dedicated hardened worker and action gates.
See `docs/modules/SOURCE_OBJECT_PREVIEW_CONTENT_RELEASE.md`.

## Office Editing Boundaries

Office editing follows a hybrid architecture rather than one embedded vendor suite:

- **Quick Edit** is a Collabio-native surface for constrained DOCX and Markdown changes. A future save creates a
  candidate SourceObject version; it never mutates the authoritative version in place.
- **Full Collaboration** is a separate provider-neutral WOPI adapter, with Collabora Online preferred for the first
  evaluation and ONLYOFFICE retained as an alternative.
- **Preview** remains the independent canonical PDF/LibreOffice/PDF.js boundary from ADR-0060.
- **Office AI** remains draft-only behind the Local LLM Gateway and may not commit or perform external actions without
  explicit human confirmation.

ADR-0061 introduces `office_edit_adapter.v1` and a selective GenOffice evaluation. The complete GenOffice application
is not forked or embedded. The evaluation pins commit `fd33934dab1fdf8666af3f88b9794e7b4e19474a`, treats only
`packages/docx-engine/**` as a future import candidate, keeps spreadsheet and presentation engines reference-only, and
prohibits `ee/**`, shell, cloud-AI provider, and AI-search source scopes.

The current API is metadata-only. It performs authoritative tenant and ACL lookup and binds its plan to the policy,
adapter descriptor, source manifest, content hash, ACL version, and exact upstream commit. It does not read source
bytes, import upstream code, invoke an engine, start an editor or WOPI session, access a network, or write a draft or
candidate version.

ADR-0062 adds the first real source-admission evidence without opening that boundary. The exact codeload archive is
bound by SHA-256, read directly without extraction, and reduced to a deterministic manifest for root evidence plus the
selected DOCX package. The offline verifier records the complete locked runtime dependency closure and vendored source
licenses, rejects links and unsafe paths, and cannot invoke npm, Node.js, a network, or the engine. This closes source-
byte and dependency inventory first. The follow-up pre-build supply-chain gate now proves byte-identical
`emf-converter@2.0.2` provenance, a schema-valid deterministic 23-component CycloneDX 1.6 SBOM, an exact netzloser
Trivy-PURL-Abgleich und zero findings against a fresh DB. A separated npm/Sigstore gate additionally verifies the
registry signature, npm publish attestation, SLSA v1 package subject, GitHub-hosted workflow identity, Fulcio
certificate and Rekor inclusion proofs. Legal approval, reproducible worker build and image SBOM, malicious-file and
fidelity proof, content access, and production use remain blocked.

Before Quick Edit may process content, a separate admission change must prove:

- final legal, license, notice, trademark, reproducible-build, image-SBOM, and runtime-vulnerability review of the now
  hash-bound and cryptographically provenance-verified source and dependency inventory;
- malicious OOXML, macro, OLE, external relationship, ZIP expansion, and resource-exhaustion resistance;
- Word/LibreOffice/GenOffice/Collabio fidelity corpora plus explicit safe-export and high-fidelity modes;
- immutable preservation of signed originals and explicit signature-invalidated state on derived edits;
- no-egress stronger isolation, source-blind candidate revalidation, canonical PDF preview, fresh ACL checks, human
  confirmation, and an append-only edit receipt;
- restore and failover drills for durable draft journals, candidate versions, collaboration manifests, receipts, and
  policy/engine hashes. Transient plaintext worker files and session tokens are never backup artifacts.

ADR-0072 now fixes the fidelity-study control plane before those engines are run. Microsoft Word is an interactive
Windows reference runner rather than an unattended server dependency; LibreOffice is an isolated headless runner; and
GenOffice stays behind the ADR-0070 two-person `runsc-kvm` boundary. The exact three-by-three plan, structural OOXML
baselines, deterministic RGB metrics and per-engine Ed25519 result envelopes are implemented. The current readiness
bundle contains no engine output and cannot make a compatibility claim. Even a complete signed matrix still requires
referenced-evidence verification, calibrated thresholds and human fidelity review.

This division lets Collabio reuse proven format-engine work without allowing an office engine to become a second
storage, authorization, compliance, recovery, or AI control plane.

## Indexing Flow

```text
Office/Mail source object
  -> authoritative source resolver
  -> parser worker boundary
  -> extracted text artifact
  -> deterministic chunker
  -> embedding provider
  -> vector worker
  -> candidate-only vector store
```

Source text is resolved again later by the RAG pipeline after ACL validation. Vector search never returns source text, snippets, prompts, answers, or raw embeddings.
