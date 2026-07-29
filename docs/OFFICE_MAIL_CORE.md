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
