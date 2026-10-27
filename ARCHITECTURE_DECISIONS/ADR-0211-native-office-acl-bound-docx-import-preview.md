# ADR-0211: Native Office ACL-bound DOCX import preview

## Status

Accepted on 2026-10-27.

## Decision

Native Office may create a bounded, non-persisting text preview from one exact DOCX source-object version that the
current user is authorized to read. The API resolves the tenant-owned source bytes, revalidates the current object ACL,
verifies the exact content and manifest hashes and dispatches only the authorized bytes to the admitted development
parser profile. Foreign, missing, unreadable, non-DOCX or integrity-invalid sources fail before parsing.

The parser runs as UID 1000 with no network, a read-only root filesystem, all capabilities dropped, no-new-privileges,
bounded CPU, memory and PIDs and a noexec/nosuid/nodev scratch filesystem. A narrowly privileged, no-network one-shot
initializer owns only the Unix-socket directory. The API mounts that socket read-only. No database, object-storage,
provider or vector credential is available to the parser. Active content is rejected before text extraction; request
and response sizes, identity, MIME type and input/text hashes are independently bounded and validated.

The preview maps extracted lines to native paragraphs and declares that structure and formatting can be flattened.
It persists no content. The document root carries exact source object/version/content-hash/current-ACL-version and
parser profile/text-hash provenance. The browser keeps that server-validated provenance outside editable content and
re-attaches it to the confirmed native save, so the editor round trip cannot silently discard it. A saved version is
created only through the existing explicit human confirmation and immutable Office save path.

The Office lifecycle view distinguishes the active bounded DOCX text preview from general or productive parser
dispatch. Productive import, DOCX export, round-trip fidelity, automatic save, RAG/search indexing and tenant or pilot
activation remain closed. Audits contain identifiers, hashes, counts and policy results, never source or extracted
text bodies.

## Consequences

This adds no migration, external document engine, automatic action or durable business-state schema. The Unix socket
volume carries no document content and is not a backup domain. Rich OOXML structure, styles, tables, images, tracked
changes, headers/footers, a governed source picker, malicious-corpus admission, source-blind fidelity calibration,
productive candidate-version writes, export and WOPI require separate decisions and release evidence.
