# ADR-0084: Native Office title search and document discovery

Date: 2026-09-21
Status: accepted; development validation and controlled dev001 rollout complete
Scope: Roadmap 260 / PLANS 121, extending ADR-0079 and ADR-0083

## Context

The native document list returned at most 200 records and filtered their titles in the browser. Older readable
documents could therefore remain undiscoverable. List membership also incorrectly represented source authorization
in several client workflows; absence from a filtered or paginated page cannot establish access revocation.

## Decision

Extend the existing GET document list with an optional literal title query, a bounded page size and an opaque cursor.
Keep the existing response fields and add page size, has-more and next-cursor metadata, without a total count or query
echo. Calls without parameters remain bounded to 200 records. The Office UI explicitly requests pages of 50.
Case-insensitive matching uses lowercase substring comparison; percent signs, underscores and backslashes are literal.
Queries are bounded to 200 Unicode codepoints and reject control characters or invalid Unicode.

Order by immutable creation time and object ID, descending. Saving or renaming does not move a document between pages.
Each page rechecks the current module, role, ABAC and typed object ACL before applying its limit and lookahead.
New documents require a refresh; concurrent title or permission changes can alter later results. This is live discovery,
not a frozen snapshot. A cursor never grants access, and no unreadable count or title is returned.

Authenticate cursors with HMAC and bind them to tenant, actor, role set, normalized query and page size. Validate their
shape, size and position before repository access. The signing key belongs to the current service instance and is not
persisted: restart invalidates cursors and requires a list refresh. This supports the current single-worker deployment;
multi-worker/shared-key operation requires a separate deployment decision. No signing secret is exposed or added to Git.

Search, next-page loading and list retry use separate request generations and cancel stale work. They never replace an
editor, discard drafts or infer source permissions from the returned page. A manual refresh separately reauthorizes the
exact opened saved version while preserving local edits; an actual authorization denial clears protected content.
Transient failures preserve drafts. Fresh content responses, rather than list membership, authorize historical takeover
and suggestion acceptance. Existing source/version/hash checks, confirmed writes and exact retries stay intact.
Keep the existing Work-to-Office link reachable in compact mobile navigation as well as the desktop sidebar.

Keep query text and cursors out of audit metadata and ordinary Uvicorn access logs. The narrow access-log filter removes
the list request's query string before handlers format its structured record, retaining path, method and response status.
No content index, RAG path, new endpoint, dependency, schema or durable record is introduced.

## Validation and boundaries

Exercise genuine PostgreSQL authorization before pagination, beyond-200 discovery, literal titles, stable order, current
role/ACL changes, malformed and cross-context cursors, logging redaction, protected drafts, errors/retries, late responses
and desktop/tablet/mobile controls. Preserve all 180 prior browser/model checks and run full Python quality on dev001.
Ordinary tenant, pilot, indexing, cloud provider and DOCX engine gates remain closed. Existing Roadmap 257 recovery
evidence remains retained; this read-only API/UI extension does not claim a new main-database migration or recovery drill.

Focused verification on `5bcb7d2` passed ten discovery browser checks in 46.602456 seconds, zero skipped/unexpected/flaky.
They use 225 real PostgreSQL/S3 documents and a dedicated reader with grants to only the three oldest entries, exercising
the authorization-before-limit boundary without successful-CRUD mocks. Independent desktop/tablet/mobile visual review
passed; 51 actual list access records contained no query/cursor values. Report:
`sha256:663d6370c40b38e432000b458ea2f7fb662121fd3a0be3b19ddfdf2b59e42c03`.
The preceding nine-of-ten run on `e304b28` exposed the hidden mobile Work link; its narrow product fix retains the same
real navigation assertion.

Full quality and all 190 checks on immutable `5bcb7d2` completed successfully at 2026-09-21 13:01:19 UTC. Ruff, formatting
across 699 files, Mypy across 547 sources and full Pytest passed with only the known Starlette/AnyIO warning. The browser
matrix passed in 651.284899 seconds: 155 browser and 35 model cases, zero skipped/unexpected/flaky, preserving all 180
previous checks. Independent review passed three Office discovery and two Work screenshots. Inspection at 13:01:29 UTC
confirmed query/cursor redaction in 306 actual list access records.
Final report: `sha256:f11d3d0e6130351760439eec1ea7e71ae85de1fe881d76d2df4c9eee0ac8b8ef`;
quality log: `sha256:627d7e5a71376e443db09d5bc78e953c86298b699d3df8a8b2e3feaba1fc446c`.
The API-only `--no-deps` rollout retained pilot 0 and reached healthy at 2026-09-21 13:03:04 UTC. Live checks at
13:04:01 UTC verified the list contract, controls, thirteen Office OpenAPI operation definitions, local assets/licenses,
Work navigation and no-store/CSP. They do not claim execution of all thirteen operations. Cleanup finished healthy at
13:04:19 UTC with only regular API/PostgreSQL/MinIO running; main stores were unchanged and test/restore services stopped.
Ordinary Office remains unprovisioned, with Office features, KB write and pilot closed. Roadmap 260 development is complete;
no main-database migration or new recovery drill ran. Roadmap 257 recovery evidence remains retained, without ordinary-tenant
or production admission.
