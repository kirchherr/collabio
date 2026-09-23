# Knowledge Base Reader Vertical Slice

Status: complete; full remote quality and 50 isolated browser cases passed on `d8d0386`
Date: 2026-09-18

Roadmap item 250 closes the normal-reader workflow after the item 249 authoring slice. It follows
`MODULE_IMPLEMENTATION_CONTRACT.md` and the existing `knowledge_base_content` continuity domain.

## Product and authorization contract

`GET /v1/kb/articles/{article_object_id}/content` supplies the current published article and its exact source version.
It requires authenticated tenant context, an enabled Knowledge Base module and `knowledge_base.articles.read`.
Readers do not require tenant-admin or `knowledge_base.articles.write`. The existing admin edit-content route and
all write/approval stages keep their stronger write authorization.

The response contains tenant_id, article metadata, plain-text body, audit_event_id, and false RAG/search indexing
flags. Authorization must cover the article, current article version and current source object before content fetch.
JWT/OIDC permissions come from the authoritative principal resolver; client-supplied readable IDs cannot grant them.
An absent or unauthorized article returns the same unavailable response. Restricted, draft, archived and
disposition-pending articles are outside this reader surface.

The source is WIKI/text/plain in saved_version state. Metadata is checked before content loading and the exact loaded
source is revalidated against article/source/version identity, canonical manifest, content hash, ACL version,
classification, retention and Legal Hold. Content is bounded to 400,000 bytes and 100,000 UTF-8 characters.
Matching Legal Hold does not prevent an otherwise authorized read. Corruption, unsupported content or storage failure
returns a generic error without raw source content or storage exception details.

## Browser behavior

`/work` offers an explicit read action beside each authorized article. A separate accessible dialog displays the
title, version, change date and plain-text body, with loading, unavailable/error, refresh and close states.
Content is inserted as text rather than executable HTML. Long content wraps within desktop and mobile viewports.
Opening or refreshing revalidates the current server state; previous body data is cleared before loading.
Closing, choosing another article or applying a different context invalidates pending requests and clears the
displayed content. Late responses cannot reopen the dialog or repopulate the wrong tenant's reader.

## Audit, storage and continuity

The read audit contains source object IDs, source-version evidence hashes and metadata-only result information.
Article bodies never enter ordinary application logs or audit events. Content responses are non-cacheable.
The read path adds no article/source mutation, ACL grant, retention change, Legal Hold change, hard delete, schema
migration or runtime activation. Existing PostgreSQL/S3 backup and exact-version restore contracts remain applicable.

The browser proof uses only the isolated ephemeral Work-E2E environment. A synthetic non-admin reader receives
explicit database ACLs; the read-only API keeps the write feature disabled. No real tenant is activated.
RAG and indexing remain closed. Future search remains candidate-only with authoritative ACL validation, and any
future AI path must use the Local LLM Gateway and source/version citations.

## Acceptance evidence

- Positive normal-reader access with read enabled and write disabled.
- Create, reader access, edit and reader access to the new version against real PostgreSQL/S3.
- Missing/revoked article or version permissions, foreign tenant and unavailable source fail closed.
- Corrupt/mismatched content, storage failure and unsupported states do not leak source bodies.
- Context/close races, literal markup and responsive browser behavior.
- Full remote quality and the existing authoring/browser regression matrix remain green.

The final browser report passed 50/50 in 120.480 seconds without skipped, unexpected or flaky cases. Both reader
viewport screenshots passed visual review. Ruff, formatting across 652 files, Mypy across 515 source files and the
full Pytest suite passed remotely. Hashes and deployment state are recorded in CURRENT_HANDOFF.md and the append-only
operations log. Existing migration 0082 recovery evidence is retained; this read slice adds no migration or durable
business-data change and did not rerun the prior backup/restore/release ceremony.
