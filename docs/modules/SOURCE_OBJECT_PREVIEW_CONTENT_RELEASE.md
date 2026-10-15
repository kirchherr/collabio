# Source Object Preview Content Release

Status: guarded productive vertical slice for sanitized plain text

## Purpose

The source preview content release path is the first productive content read built on the shared compliance core. It is
not a general Office renderer, mail viewer, attachment opener, or parser bypass.

`POST /v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-content-releases` returns source text
only when all of these checks pass:

- the current principal can read the exact source object;
- the tenant's `content_preview_enabled` policy is currently enabled;
- a complete tenant-scoped preview decision exists;
- the decision resolves to intact metadata-only renderer sandbox evidence;
- a fresh tenant-scoped renderer release gate is ready;
- the authoritative source manifest hash, content hash, and ACL version still match the renderer evidence;
- the caller supplies the exact one-time human confirmation statement;
- the source is a `document`, `wiki`, or `procedure_doc` with `text/plain` or `text/markdown` UTF-8 content;
- the source is at most 256 KiB and is not restricted, deleted, or cryptoshredded.

Mail bodies, attachments, HTML, rich Office formats, PDFs, binary files, active content, external fetches, persistent
preview output, destructive actions, and background execution remain blocked.

## Output Boundary

The API returns sanitized content in a JSON string with the render contract
`plain_text_json_field_no_html_interpretation`. Clients must render the value as plain text and must not interpret it as
HTML. The sanitizer normalizes line endings and removes Unicode control and formatting characters. The endpoint does
not persist the sanitized body.

Normal audit events and release receipts contain only source identifiers, hashes, ACL version, byte length, evidence
references, requester, timestamps, and policy/boundary booleans. They do not contain source text, confirmation text,
reason text, mail bodies, attachment bytes, prompts, outputs, embeddings, transcripts, or raw payloads.

## Durable Evidence

Migration `0055_source_object_preview_content_release_receipts.sql` creates
`collabio.source_object_preview_content_release_receipts` with:

- forced tenant row-level security;
- tenant-scoped select and insert policies;
- blocked update and delete policies;
- schema checks that keep content, human confirmation statements, and reasons out of receipt JSON;
- source, preview decision, renderer evidence, release gate, audit, and sanitized-output hash bindings.

Migration `0056_source_object_preview_content_release_nonempty.sql` additionally enforces that a recorded released representation has a non-empty sanitized byte length.

The Docker Compose API uses the PostgreSQL receipt store. In-memory storage remains available for tests.

## Restore Rule

After restore, preview content release stays closed until source objects, preview decisions, renderer evidence, release
gate evidence, audit events, tenant policy, and release receipts have been restored and tenant isolation, append-only
behavior, evidence hashes, source integrity, and gate freshness have been revalidated. Receipt recovery never replaces
source-object recovery because receipts deliberately contain no source content.

## Next Boundary

Rich Office documents, PDFs, RFC mail, and attachments require dedicated hardened parser/renderer workers, malicious
file corpora, scan evidence where applicable, bounded output artifacts, and format-specific release policies. They must
not be enabled by widening this plain-text allowlist.
