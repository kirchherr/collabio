# Native Office Documents

Status: Roadmap 252–847 implemented and validated; ordinary tenant and production admission remain closed
Roadmap: 252 / PLANS 113 foundation through 847 / PLANS 708 richer chart types and presentation
Module: `office_documents` / version 0.9.14
Decisions: ADR-0079 through ADR-0203; current movement: `ARCHITECTURE_DECISIONS/ADR-0203-native-office-richer-chart-types-and-presentation.md`

## Richer chart types and presentation (Roadmap 840–847)

Native Office adds stacked-bar, area and doughnut charts to the existing bar, line and pie vocabulary. Stacked bars
derive scales from category totals and require nonnegative data plus zero-based manual bounds. Area charts retain
finite positive and negative line values. Doughnut charts require one nonnegative, nonzero series and reject axes.

One optional strict presentation object selects a fixed standard, accessible, warm or monochrome palette, clean, soft
or focus style and left, center or right title alignment. Browser and server independently validate the exact closed
schema. Linked-table recalculation, chart-kind conversion, immutable save/reload, accessible descriptions and hidden
data tables remain intact; old chart documents remain valid.

Focused Office schema/API tests pass, all six chart-model cases pass, and the responsive saved-version workflow passes
2/2 on desktop and mobile in 20.9 seconds. Desktop/mobile screenshot hashes are
`sha256:879c427d879d72bdaf0ef9a67f9feeb8c65ea5c79c31b42496702437c75c104f` and
`sha256:053a26b4c2146dd288aaf25607e976e636256e7f712064bf2280368148dd3711`; visual review passed. The review target is
`http://192.168.0.108:42880/office?review=chart-types-adr0203` with `office.css?v=15` and `editor.js?v=15`.
Complete quality passes Ruff, finds 964 format-conformant files, passes Mypy over 639 sources and reaches 100 percent
Pytest with only the known Starlette/AnyIO warning. The final quality image is
`sha256:ede6d7704db752034656dd8089d6f6769470c2eafb90ab52c2244b55ee82d43c`.

No migration, external chart engine, network source or new durable state is introduced. Scatter, combo and 3D charts,
secondary and logarithmic axes, free-form styling, external chart data and automatic actions remain closed.

## Chart axes and presentation (Roadmap 832–839)

Native Office bar and line charts support bounded category and value titles, deterministic automatic or fixed value
scales, optional major gridlines and general, integer, decimal, percent or euro labels. Fixed scales require finite
ordered bounds, a positive major unit, at most twelve exact intervals and every value inside the visible range. Pie
charts reject axes. Legends can be placed at the top, bottom, left or right and side placement collapses responsively.

The chart editor validates the prospective node before applying it. Linked-table recalculation, immutable save and
reload preserve the complete presentation contract. The server independently rejects surplus fields, invalid formats,
uneven scales, out-of-range data and forged pie axes. The accessible description and hidden data table remain present.

Focused Office schema/API tests pass 88/88, all five chart-model cases pass, and the responsive saved-version workflow
passes 2/2 on desktop and mobile in 20.1 seconds. Desktop/mobile screenshot hashes and final complete-quality evidence
are recorded in `docs/CURRENT_HANDOFF.md`. Complete quality passes Ruff, finds 963 format-conformant files, passes
Mypy over 639 sources and reaches 100 percent Pytest with only the known Starlette/AnyIO warning. The final quality
image is `sha256:ede6d7704db752034656dd8089d6f6769470c2eafb90ab52c2244b55ee82d43c`. The review target is
`http://192.168.0.108:42880/office?review=chart-axis-adr0202` with `office.css?v=14` and `editor.js?v=14`.

No migration, external chart engine, network source or new durable state is introduced. Secondary axes, logarithmic
scales, free-form formats, external chart data and automatic actions remain closed.

## Text and calendar formulas (Roadmap 824–831)

Native Office supports bounded quoted text literals, text-valued cells and named ranges, exact text
`XLOOKUP`/`XVERWEIS`, and `CONCAT`, `LEFT`, `RIGHT` and `LEN` with normalized German aliases. Literal spelling and
punctuation remain unchanged during normalization. Text results are limited to 512 safe characters, while leading
`#` remains reserved for deterministic formula errors.

`EDATE`, `EOMONTH`, `DAYS` and ISO `WEEKDAY` plus their German aliases operate on bounded integer UTC day numbers.
Month shifts clip to valid month ends and need no locale, timezone, current-time or network source. Formula reference
rewriting skips quoted literals. Browser and server calculate independently inside the document-wide dependency graph,
and the server rejects invalid syntax, unsafe text, missing references, calendar overflow and stale or forged results.

Focused Office schema/API tests pass 88/88, all 22 formula-model cases pass, and the responsive saved-version workflow
passes 2/2 in desktop and mobile in 19.1 seconds. Screenshot hashes are
`sha256:a1795f648c4f98d16d00977d64c7e11a2212ca032e994d932935f653aa225390` and
`sha256:ad209c5a0afda706178f6878db99c14605f875094c6ae0608ff9c8a4ebf6be6d`; visual review found no page overflow.
Complete quality passes Ruff, finds 962 format-conformant files, passes Mypy over 639 source files and reaches 100
percent Pytest with only the known Starlette/AnyIO warning. The quality image ID is
`sha256:ede6d7704db752034656dd8089d6f6769470c2eafb90ab52c2244b55ee82d43c`.
Work-E2E and review API image IDs are
`sha256:dcaaff420e8c040cab073f405beda7b6c787333272a325749e7b780c918a2341` and
`sha256:6df0d4668353dbdc8a5023070e33102ad3b77e05f50d8a4c7fb552520ee9b3aa`. The review target is
`http://192.168.0.108:42880/office?review=text-date-formulas-adr0201` with `office.css?v=13` and `editor.js?v=13`.

No migration, external calculation engine, network source or new durable state is introduced. Approximate or wildcard
lookup, volatile time functions, external workbook links, macros and automatic actions remain closed. Chart-axis and
presentation controls are completed by Roadmap 832–839.

## Multiple-criteria aggregation (Roadmap 816–823)

Native Office supports canonical `SUMIFS`, `COUNTIFS` and `AVERAGEIFS` plus the normalized German aliases
`SUMMEWENNS`, `ZÄHLENWENNS` and `MITTELWERTWENNS`. Sum and average take one result range; all three functions require
one through ten criteria-range/exact-numeric-criterion pairs. Every range must have the same shape-flattened size and
remains bounded to 4,000 values.

Local A1 rectangles and document-wide named ranges share the existing dependency graph, memoization, cross-table
cycle detection and structural remapping. Browser and server calculate independently. The server resolves every table
and named definition and rejects invalid arity, missing or unequal ranges, stale results and forged immutable content
before save.

Focused Office schema/API tests pass 87/87, and all 19 formula-model cases pass. The responsive saved-version workflow
passes 2/2 in desktop and mobile: German formulas calculate `50`, `2` and `25`, persist under canonical English names
and reload unchanged. Screenshot hashes are
`sha256:8a36b04a48ff042dd9257a648a3ce45e742d8c28875febeb8788cfdd2b84d226` and
`sha256:778a604820c5b4880b8f300100b9ed03b3d6ed97e312a6d5c172693cbf89fb90`. The workflow has no page overflow.

Complete quality passes Ruff, finds 982 format-conformant files, passes Mypy over 639 source files and reaches 100
percent Pytest with only the known Starlette/AnyIO warning. Quality, Work-E2E and review API image IDs are
`sha256:ede6d7704db752034656dd8089d6f6769470c2eafb90ab52c2244b55ee82d43c`,
`sha256:6b09c8ac9543c657288fe60611b1280e1be3bd46b220b124f2ff24d15215d845` and
`sha256:112dcc1d041649fa104ef9c237321dadae3b914410ac1ecc0ec77fdcb2484231`. The review target is
`http://192.168.0.108:42880/office?review=multiple-criteria-adr0200` with `office.css?v=13` and `editor.js?v=12`.

No migration, external calculation engine, network source or new durable state is introduced. Text, wildcard and
comparison-string criteria stay closed. Richer deterministic date/text functions and chart-axis presentation remain
the next separate Office loops.

## Versioned RAG document answers (Roadmap 784–791)

The read-gated answer endpoint accepts only an exact current saved document version, a normalized question with at
most eight searchable terms and a bounded result limit. Tenant AI and RAG policy must be enabled. The selected model
must be local, tenant-allowed, approved for RAG and admitted for every source classification.

Retrieval reuses the bounded current-version source search. Every returned candidate is then fetched again through
the authoritative repository immediately before inference. Current-version identity, content hash, ACL version,
title, classification and the server-derived anchor excerpt must all still match. The fixed approved prompt labels
each source block as untrusted; browser-provided source bodies, prompts, models and citations are rejected by the
request schema.

Without a remaining authorized source the response is explicitly unsupported and no model runs. A supported answer
is bounded, untrusted and accompanied by server-derived citations containing exact object and immutable current
version IDs, title, classification, content hash, ACL version, anchor and excerpt. Each **Version anzeigen** action
uses the ordinary exact-version read path and reauthorizes access again.

Audit retains question/output hashes, IDs and exact citation references/hashes without question, source, prompt or
answer bodies. Answers remain transient, noncacheable, non-indexed and unable to mutate documents, create records,
certify compliance or trigger actions. Desktop and mobile proofs keep source and working-document version counts
unchanged. No migration, vector index, durable result, cloud provider admission or production runtime is added.

Focused service/API and dashboard contracts pass. The desktop/mobile browser proof passes 2/2 with report hash
`sha256:b8d9a853b0332361e2bf3735c33e1d6c9e2bc9a366ffe04f67fbb1f703b92fc1`; screenshot hashes are
`sha256:ad0899e4dcea108aa29df808cfea171dea69ec2551cf9e6cdca832b5c63dd32b` and
`sha256:ab9bac1cfab04e2e54e3d07392596bc6d186cd86103d765956f625aa165d4e58`. Complete quality passes
Ruff, 964-file formatting, Mypy over 639 sources and Pytest at 100 percent.

## Isolated fifty-editor load proof (Roadmap 776–783)

The deterministic ADR-0195 harness starts fifty real worker threads behind a common barrier against one tenant-bound
document state. Each editor contributes eight synchronized update envelopes. All 400 unique updates revalidate
authorization, every editor is reauthorized at connection and twice in flight, one repeated delivery is deduplicated,
and all fifty snapshots converge to identical state-vector and update-set hashes.

A midpoint checkpoint resumes by replaying exactly 200 updates. Separate probes reject a revoked editor and foreign
tenant. Four maximum-size envelopes fill the fixed one-MiB queue, and the next byte fails with close code 1013. The
golden report contains only counts, booleans and hashes; the harness processes no document body and persists no raw
browser session identifier.

The Office preflight exposes `verified_50_parallel_editors`, but `websocket_load_verified` and
`production_runtime_admitted` remain false. This proof does not open a socket or admit a CRDT runtime. Engine
selection, durable update logging, restore replay, malicious-update fuzzing, upgrade credentials, fan-out and
transport recovery retain their own gates.

## Explicit read aloud (Roadmap 768–775)

The read-gated capability and preparation endpoints require the exact current immutable document version and freshly
revalidate the tenant module/read feature plus authoritative document ACL. The request contains a bounded same-block
UTF-16 selection anchor, fixed language, bounded rate, explicit activation, false audio-storage intent and one known
synthesis adapter. It contains no source text, prompt, model, provider credential or requested action.

The server derives at most 2,000 characters from the authorized saved version. A local client voice requires tenant
voice policy; browser speech synthesis additionally requires explicit external-provider admission. The Voice Privacy
Guard and Office audit retain only tenant, object, exact version, anchor, classification, adapter, language, rate,
counts, policy, event IDs and selection hash. Selected text and document bodies do not enter audit or normal logs.

The browser checks the returned text, anchor and UTF-8 hash against its local saved selection before speaking. Its
accessible language, speed and start/stop controls identify a local voice or browser speech service and cancel output
on selection, document, editor, version or tenant-context changes. Authorized read-only users do not need document
write permission.

Collabio generates, receives and stores no audio and persists no selected text. The operation is transient, read-only,
non-indexed and cannot alter a document or version, create a record, call an LLM or trigger an action. Desktop/mobile
synthetic speech tests prove unchanged version counts and explicit stop/completion state.

## Push-to-talk dictation (Roadmap 760–767)

The write-gated capability and preparation endpoints require the exact current immutable document version. Both
freshly revalidate the tenant module/write feature, authoritative document ACL and current-version identity. The
strict request contains only a bounded normalized transcript, ProseMirror UTF-16 insertion position, fixed language,
explicit push-to-talk state, false raw-audio-storage intent and one known recognition adapter.

Local client speech-to-text requires tenant voice policy. Browser speech recognition also requires explicit tenant
admission for an external provider. The accessible toolbar starts recognition only while the author holds the visible
button or keyboard control and stops on release. It shows the active provider boundary and that Collabio stores no
raw audio; there is no always-on or background capture path.

Collabio receives no audio. Every request for raw-audio storage is rejected. The Voice Privacy Guard and Office audit
record only bounded identities, adapter, language, position, character count, policy, event IDs and transcript hash,
never transcript or document bodies. The transcript is classified as personal `voice_transcript` data with transient
non-persistence. Responses are noncacheable.

After full response and hash validation, the browser inserts the transcript only into the local editor draft. No
document version, record, search entry, RAG context or AI output is created. The existing explicit confirmed save
remains the only durable write. Desktop and mobile synthetic-speech tests prove that version counts stay unchanged.

## Versioned source search (Roadmap 752–759)

The read-gated source-search endpoint accepts only the exact current source version, a normalized one-through-eight-
term query and a result limit. The browser sends no document body, model, prompt, embedding or proposed citation.
The service revalidates the source ACL and current version before searching.

Candidate discovery uses the tenant-scoped authoritative repository. Every candidate document ACL and exact current
version is revalidated again immediately before content is loaded. Search is bounded to 100 candidates, 32,000 native
text characters per document and 256,000 characters in aggregate; a reached bound is reported as corpus truncation.

Results contain only server-derived excerpts and UTF-16 anchors plus exact object and immutable version IDs, title,
information classification, content hash and ACL version. The responsive panel shows dismissible read-only cards;
**Version anzeigen** opens the exact version through the normal freshly authorized document-read path.

The deterministic keyword search uses no LLM, vector search or RAG context and creates no persistent result, index,
suggestion or document version. Audit stores the normalized query hash, bounded counts, exact result references and
content hashes without query text or document bodies. Historical-candidate search, fuzzy/semantic ranking, automatic
citation insertion and production-grade indexed search remain closed.

## Risk marking (Roadmap 744–751)

The read-gated risk endpoint accepts only the exact current immutable version ID. The browser sends no document
body, free instruction, model, provider, categories or requested action. The server revalidates authoritative access,
enumerates bounded native text runs with exact UTF-16 editor anchors and rejects empty or over-16,000-character input.

One fixed approved prompt treats every numbered block as untrusted. Only a tenant-allowed, drafting-approved local
model behind the Local LLM Gateway is eligible. The strict grammar allows `clear` or one through eight findings with
fixed severity/category values and existing block numbers. Duplicate, unknown or malformed findings fail closed.

Source excerpts and anchors always come from the server inventory, never from model output. The responsive report is
labelled **AI-Risikoprüfung · ungeprüft** and lets the user select each exact saved passage with **Stelle anzeigen**.
It is dismissible and transient; it changes no content or version, creates no annotation or compliance decision,
triggers no action and remains excluded from search and RAG indexing. Audit stores only IDs, counts and hashes.

## Policy comparison (Roadmap 736–743)

The read-gated comparison endpoint accepts one exact current source version and a different readable policy object
with its exact current version. The browser sends only those identifiers. The server revalidates both authoritative
ACLs and current-version identities, extracts bounded native text from both immutable versions and rejects empty or
over-16,000-character sources instead of truncating them.

One fixed approved prompt treats both delimited sources as untrusted data and forbids legal or regulatory approval.
Only a tenant-allowed, drafting-approved local model behind the Local LLM Gateway is eligible. The higher source
classification controls policy admission; confidential and restricted input remains closed unless tenant, model and
the exact prompt all admit confidential data.

The model must return one fixed status and bounded finding/recommendation lines with at least one finding. Invalid or
oversized output fails closed. The response binds the exact source version and hash to an ACL-validated policy object,
version, title and hash. Audit stores only IDs, status, counts and hashes without document, prompt or output bodies.

The responsive writing panel displays a dismissible read-only **AI-Vergleich · ungeprüft** report and the exact policy
citation. It persists nothing, changes neither document nor version count, triggers no follow-up action and is excluded
from search and RAG indexing. Compliance certification, free prompts, durable comparisons and automatic edits or
approvals remain closed.

## Selection outline drafts (Roadmap 728–735)

The read-gated outline endpoint accepts one exact current immutable version, one bounded same-block text anchor and
the fixed detail value concise or detailed. It accepts no source text, model, provider, free instruction, output
format or arbitrary depth. The server revalidates the document ACL and derives the source selection from the saved
version.

Each detail maps to an approved versioned prompt that preserves source language, facts, names, numbers and
commitments and treats the delimited source as untrusted data. Only tenant-allowed, drafting-approved local models
behind the Local LLM Gateway are eligible. Confidential and restricted documents remain closed unless tenant, model
and the exact prompt all admit confidential data.

The server accepts only structured Markdown bullet output: concise outlines contain two through eight nonempty lines
and detailed outlines two through twenty. Empty, unchanged, oversized, invalid-Unicode, unstructured, one-line and
over-limit results fail closed. Response and hash-only audit bind the exact source and validated line count without
storing source or output bodies.

The responsive AI writing panel exposes a fixed detail selector. The untrusted transient result enters the existing
editable proposal composer with a visible detail label. Saving a suggestion and accepting it remain two separate
explicit confirmations before an immutable version can change. Whole-document outlines, semantic heading insertion,
arbitrary depth and automatic writes remain closed.

## Selection translation drafts (Roadmap 720–727)

The read-gated translation endpoint accepts one exact current immutable version, one bounded same-block text anchor
and one fixed target-language code. German, English, French, Spanish, Italian, Dutch, Polish, Portuguese and Ukrainian
are admitted. The request accepts no source text, source-language claim, free instruction, model or provider. The
server revalidates the document ACL and derives the source selection from the saved version.

Each target maps to a separate approved versioned prompt. The prompt preserves meaning, facts, names, numbers,
commitments and formality, returns translation only and treats the delimited source as untrusted data. Only tenant-
allowed, drafting-approved local models behind the Local LLM Gateway are eligible. Confidential and restricted
documents remain closed unless tenant, model and the exact language prompt all admit confidential data.

The response binds object, version, anchor, selection hash and target language to the model, prompt and inference
event. Source and output bodies stay out of normal logs and audit. Empty, invalid, overlong or unchanged output is
rejected. A valid result remains visibly untrusted, transient and excluded from search/RAG indexing and document
history.

The responsive AI writing panel exposes a fixed target-language selector. The result enters the existing editable
proposal composer with its target-language label. Saving a suggestion still requires explicit confirmation, and
accepting it requires a separate confirmation before an immutable version is appended. Discarding changes neither
the document nor its version count. Whole-document translation, automatic language detection, translation memory
and automatic writes remain closed.

## Rewrite and tone drafts (Roadmap 712–719)

The read-gated rewrite endpoint accepts one exact current immutable version, one bounded same-block text anchor and
either plain rewrite or one fixed tone: neutral, professional, friendly, formal or concise. It accepts no source text,
model, provider, free instruction or target language. The server revalidates the document ACL and derives the source
selection from the saved version; stale versions and invalid anchors fail before inference.

Every option maps to a versioned prompt-registry entry that preserves language, meaning, facts, names, numbers and
commitments and treats the delimited source as untrusted data. The common policy engine rejects unapproved prompts.
Missing built-in prompts are added to a JSON registry without replacing existing customized rows. Only tenant-
allowed, drafting-approved local models behind the Local LLM Gateway are eligible. Confidential and restricted
documents remain closed unless tenant, model and the exact prompt all admit confidential data.

The response binds object, version, anchor, selection hash, operation and tone to the model, prompt and inference
event. Source and output bodies stay out of normal logs and audit. Empty, invalid, overlong or unchanged output is
rejected. A valid result remains visibly untrusted, transient and excluded from search/RAG indexing and document
history.

The responsive proposal panel provides summary, rewrite and fixed-tone controls. The result enters the existing
editable proposal composer with an exact AI/tone label. Saving a suggestion still needs explicit confirmation, and
accepting it requires a separate confirmation before an immutable version is appended. Discarding changes neither
the document nor its version count. Free prompts, whole-document inference and automatic writes remain closed.

## Selection summary drafts (Roadmap 704–711)

The read-gated summary endpoint accepts one exact current version and one bounded native text anchor. It ignores
browser-provided text because the server revalidates the authoritative document ACL, loads the immutable version and
derives the selected text itself. Stale versions, cross-paragraph selections and invalid native positions fail closed.

The service selects only a summarization-approved model from the tenant allowlist whose registry deployment is local
and whose provider is admitted behind the Local LLM Gateway. Public content is handled at least as internal;
confidential and restricted documents remain denied until the tenant, model and prompt registries explicitly admit
the confidential data class. The client cannot choose a model or provider.

The response is marked untrusted and binds the summary to the exact object, version, anchor and source-selection
hash. It is transient, not indexed and changes neither suggestion storage nor document history. The AI audit records
model, prompt template, source object and input/output hashes without bodies. A second Office audit links those hashes
and the inference event without content.

The browser places the result in the existing proposal composer with a visible **AI-Entwurf · ungeprüft** label. A
user must explicitly save the proposal and later explicitly accept it before a new immutable document version can be
created. Cancellation leaves the document and its version count unchanged. Whole-document inference stays closed;
rewrite, translation, outline, policy comparison, risk analysis and source search use separate bounded contracts.
Other Voice workflows remain separate later work.

## Deterministic interchange test corpus (Roadmap 696–703)

`office_interchange_corpus_manifest.v1` describes nine repository-generated fixtures: DOCX, ODT and PDF each have
one allowed text input, one nonexecuting signature marker and one blocked active-content input. Package timestamps,
ordering and permission bits are fixed. Every source has an exact SHA-256 and byte length, and the canonical manifest
hash binds fixture identity, policy outcome and expected text hash.

The test executes the real active-content detector and development parser against all nine byte streams. It checks
the exact allow, allow-marked or block decision, parser outcome, text hash and warning count. VBA, ODF Basic script
and PDF JavaScript exercise the three block paths; marked signatures remain visible and nonexecuting.

The tenant/read-gated endpoint returns metadata only and never returns fixture bytes. Import dispatch, export engine,
round-trip fidelity and production admission remain false. The responsive **Dokumentstatus** exposes the corpus and
closed engine boundary. Representative external fixtures, exported derivatives, recovery and engine admission remain
separate later work.

## Import compatibility matrix (Roadmap 688–695)

The tenant-scoped `office_import_compatibility_matrix.v1` records the exact development-parser boundary for DOCX,
ODT and PDF. Its thirteen feature rows distinguish `text_supported`, `text_flattened`, `blocked_active_content`,
`visible_review_marker` and `unsupported`. Every row keeps `fidelity_preserved=false`; the matrix does not infer whole-
format support from a successful text extraction.

DOCX main-document paragraph text is bounded support. Heading, list and table-cell text is flattened, while headers,
footers, notes, comments, drawings and revisions are unsupported. ODT paragraph and heading text is bounded support;
lists, tables, styles, fields and annotations are flattened. PDF basic literal strings are flattened, while scans,
complex fonts, layout, forms and accessibility structure require a separately admitted engine.

The active-content policy remains authoritative. DOCX VBA/ActiveX/OLE/templates, ODT scripts and PDF JavaScript,
actions or embedded files are blocked before extraction. Nonexecuting signature and external-link indicators remain
visible review markers. The matrix does not execute, sanitize, parse or accept content.

The endpoint is Office-read-gated, tenant-bound, noncacheable and metadata only. Audit stores the schema, state,
bounded counts and closed interchange flags. Import dispatch, export, round-trip fidelity and production admission
remain false. Focused contracts and the exact responsive desktop/mobile lifecycle workflow pass. The next bounded
step is a real import/export test corpus with explicit fixtures and expected derivatives.

## Bounded macro policy (Roadmap 680–687)

The tenant-scoped `office_macro_policy.v1` describes and enforces one fail-closed rule before text extraction. Native
DOCM MIME and DOCX-contained VBA, ActiveX, OLE/package or external-template indicators are blocked. ODF Basic/script
parts, event listeners and script URIs, plus PDF JavaScript, launch/open/additional actions and embedded files, are
also blocked. Unsafe, ambiguous, encrypted or unsupported archive structures cannot bypass inspection.

Blocked inputs are not extracted and active content is never executed. The parser does not silently strip content,
because that would make a modified file appear to be its original. Nonexecuting signature and external-link
indicators may be extracted only as `allow_marked`; the returned warning is generic and contains no path, target,
identifier or document content.

The policy endpoint itself accepts no content or source identifier, is tenant/read-gated and emits metadata-only
audit. Parser dispatch, execution, automatic sanitization and policy-receipt persistence remain false. The responsive
**Dokumentstatus** shows the block/mark behavior and closed execution state.

Focused detector, parser, service, API and dashboard contracts pass together with the exact desktop/mobile workflow.
A complete OOXML/ODF/PDF malicious corpus, quarantine/operator review, persisted and restorable policy receipts and
productive parser-image admission remain explicit later gates.

## Isolated parser-worker plan (Roadmap 672–679)

The tenant-scoped `office_parser_worker_plan.v1` response makes the existing bounded PDF, ODT and DOCX development
parser visible without accepting content, a SourceObject ID or a version ID. It requires authoritative ACL,
content-addressed exact-version lineage, classification/retention/legal-hold/ACL metadata and malware/active-content
decisions before any future source read. Dispatch and production admission remain false.

The planned pipeline authorizes before materialization, runs a one-shot no-network worker, validates the bounded
result and hashes, reauthorizes before use and erases scratch. The worker receives no database, object-storage or
provider credential and may write neither source storage nor a vector index. Normal logs may contain no content and
parser output remains untrusted until validation.

Compose enforces `network_mode: none`, UID/GID 1000, read-only root, all capabilities dropped,
`no-new-privileges`, a 64 MiB `noexec,nosuid,nodev` tmpfs, 256 MiB memory, 64 processes and one CPU. Inputs are capped
at 25 MB, expanded archives at 20 MB and extracted text at two million characters. A transient Docker probe verified
the effective HostConfig values on `dev001`.

Materialization, write-only result handoff, scheduling/timeout enforcement, malicious-document corpus, sandbox-
escape fuzzing, nonempty recovery and production image admission remain explicit blockers. The responsive
**Dokumentstatus** shows this boundary; focused contracts and the exact desktop/mobile workflow pass. No migration,
content intake, parsing job, output persistence, vector write or production release is added.

## Bounded WebSocket gateway preflight (Roadmap 664–671)

The metadata-only `collabio-office-websocket-preflight.v1` contract prepares a future gateway after the CRDT
preflight. Exact Same-Origin validation uses the browser `Origin` and actual request origin; the body cannot nominate
an origin. Only `collabio-office-crdt.v1` and the complete canonical transport capability list are accepted.

Every request retains the Office write gate and revalidates the exact tenant, document write ACL, immutable current
version and active current-version edit lease. Session and client identifiers remain request-transient. Audit contains
only bounded version, protocol, counts, closed states and blocker count, never origin, raw identifiers, credentials or
content.

The future envelope is binary-only and uncompressed: 256 KiB per frame, 1 MiB queued bytes, close code 1013 under
backpressure, 25-second heartbeat, 60-second reauthorization and five-minute maximum connection lifetime. State-
vector reconciliation is required for resume and at-least-once delivery requires client deduplication. Document and
per-update ACL checks remain mandatory.

The response requires a future short-lived, single-use, hash-bound upgrade credential but issues none. Query
credentials are forbidden, no ticket or socket URL is returned and `server_accepts_connections` remains false. The
upgrade route, credential store, real handshake rejection, update authorization, disconnect recovery, multi-node fan-
out, CRDT engine and load evidence remain explicit blockers.

Focused Ruff, format and Mypy pass with the affected service, API and capability tests. The real responsive desktop/
mobile lifecycle workflow passes 2/2 in 11.0 seconds and visibly confirms closed upgrade, ticket and connection
states. No migration, WebSocket connection, update ingestion, recovery or production admission is added.

## Bounded CRDT service preflight (Roadmap 656–663)

The metadata-only `collabio-office-crdt-preflight.v1` contract prepares binary-update and state-vector compatibility
without accepting either payload. Capabilities must be unique and canonically ordered. The response publishes a
future 256 KiB update ceiling and fifty-editor target while returning only `prepared_runtime_closed` and
`websocket_not_admitted`.

Every preflight retains the Office write gate and revalidates the exact tenant, document write ACL, current immutable
version and current edit lease held by the same bounded browser session. Browser session and client instance IDs remain
request-transient. No document, version, lease or collaboration state is written, and audit contains only bounded
protocol, count and closed-state metadata.

The response explicitly names missing engine admission, durable update log, restore replay, malicious-update fuzzing,
fifty-editor load evidence and WebSocket gateway admission. The responsive **Dokumentstatus** displays those closed
boundaries only when the current session can write and holds the lease. It opens no socket and preserves the local
draft.

Focused Ruff, format and Mypy pass together with the affected service, API and capability tests. The real responsive
desktop/mobile lifecycle workflow passes 2/2 in 11.0 seconds. Fifty distinct metadata handshakes verify stateless
behavior but are not a load test. CRDT engine, update ingestion, durable sequencing, presence, merge, WebSocket,
recovery and productive admission remain closed.

## Bounded comments, mentions and change attribution (Roadmap 648–655)

The existing version-bound, append-only review stream now derives canonical `@[principal-id]` mentions directly from
the immutable comment body. Syntax is fail closed, duplicate targets preserve first-occurrence order and one event can
reference at most twenty distinct principals. No second copy of comment content and no migration are required.

A new mention is accepted only for an active tenant principal with current direct user access to the exact document,
or for its owner. Role and group grants are deliberately not expanded into individual recipients. Mentioning never
grants access and this slice sends no notification. Idempotent replay remains stable before current mention
revalidation. If a target later loses access, the historical mention remains part of the immutable comment and is only
visible inside an otherwise authorized thread; a new mention of that target fails atomically.

Every returned review event carries the exact actor principal, operation, revision and `human_confirmed: true`
attribution. Audit records only the mention count alongside existing hashes and receipts; mentioned IDs and bodies are
excluded. The responsive UI explains the syntax, renders all values as text, shows attribution and states that no
access or notification is created.

Focused Ruff, format and Mypy pass. The complete focused service/API files pass 44 tests, all seven PostgreSQL review
tests pass, the exact desktop/mobile workflow passes 2/2 in 17.2 seconds and the full review browser matrix passes
10/10 in 1.3 minutes. Notification outbox, email, push, role/group recipient expansion, CRDT, WebSocket and production
admission remain closed.

## Bounded lifecycle-state model (Roadmap 641–647)

The authenticated read-only lifecycle endpoint names the platform states without promoting content: working data is
request-transient, drafts remain browser-memory only, collaborative state is advisory lease metadata for the current
immutable version, and the saved version is the only persistent document state. Business-record and WORM evidence-
record transitions remain closed.

The fixed browser session format, current tenant/document authorization and Office feature gates apply. Collaboration
state is returned only with current write access and uses the existing hashed lease binding; readers receive
`unavailable`. No response or audit event includes another holder, raw session value or document content. Saving
continues to require explicit human confirmation and exact current-version compare-and-swap. A later business-record
transition also requires human confirmation, `ai_may_commit_business_record` is false and no writable lifecycle route
exists.

The responsive **Dokumentstatus** dialog combines local unsaved-draft state with authoritative lease state, exact
immutable version ID and the two closed record transitions. Opening or refreshing it does not alter the editor. Ruff,
format and focused Mypy pass; the complete Office document service/API files pass 62/62 tests, and the real
desktop/mobile browser workflow passes 2/2 in 10.1 seconds. The slice adds no migration, durable draft, collaborative
content log, record promotion, retention change, object-lock transition, WORM object, AI action or production
admission.

## Bounded advisory edit leases (Roadmap 632–640)

Each tenant/document pair can hold one short-lived advisory edit lease for the current immutable version. Migration
0090 stores a 90-second expiry, monotonically increasing revision, base version, acquire/renew/release timestamps,
takeover count and audit reference under forced tenant RLS. The application can update only the bounded lease
columns, deletion is denied and the complete table, policies, constraints and grants belong to the Office restore
contract.

A browser session ID is accepted only in the fixed `office-session-` format and persisted solely as a SHA-256 binding
over tenant, document, principal and session. Lease endpoints still require the Office write gate and authoritative
document ACLs. Responses disclose only coordination state and never another holder's identity or raw session value.
Acquire and renew require the exact current version ID and run under a tenant/document advisory transaction lock; a
new saved version makes predecessor leases inactive without weakening the established version compare-and-swap.

The editor renews and reconciles every 15 seconds. A foreign holder or unavailable authoritative state makes editing
and Save read-only. Takeover uses an explicit confirmation dialog, and workspace close or page unload attempts a
best-effort release. If a session loses its lease, its existing unsaved local text remains visible while further saves
stay blocked. Lease read, request, actual takeover, actual release and ineffective release request are audited as
distinct metadata-only events.

The focused service, API, PostgreSQL, migration and restore contracts pass, including tenant isolation, hashed
storage, stale-version rejection and audit precision. The real two-browser desktop/mobile workflow passes 2/2 in
41.4 seconds and proves takeover reconciliation plus local draft retention. This is bounded one-writer coordination,
not ACL, CRDT, WebSocket, presence, merge, simultaneous coauthoring, durable draft storage or DOCX lock
interoperability.

## Bounded object visibility and editing protection (Roadmap 624–631)

Standalone root shapes and complete root shape groups may carry optional canonical `hidden: true` and `locked: true`
attributes. Omission means visible and editable. Grouped member shapes cannot carry either root state. Browser and
authoritative server accept only literal `true`; false, numbers, strings, unknown keys and member-level states fail
closed. Internal null values are omitted before persistence.

The responsive object navigator exposes state labels and show, hide, lock and unlock actions for one through twenty
complete roots. Hidden roots disappear from the editor and semantic print/PDF but remain in canonical document order
and are recoverable through the navigator. Hiding does not delete or protect content and is never a confidentiality
boundary. The UI says so explicitly.

Locked roots remain selectable and discoverable while ordinary dialog, handle, pointer, touch, keyboard and
multi-object mutations are disabled. Visibility controls and unlock stay available. Locking prevents accidental edits;
it is not an ACL, authorization decision or collaborative lease. Every state action revalidates the current authorized
session, exact document and strict root ID/type/order tuple, then commits all selected roots in one validated
transaction and undo unit. Stale, duplicate, unsorted or changed targets fail without mutation.

Two focused Python schema contracts, 22/22 strict model tests, targeted desktop/mobile workflows and the complete
46/46 native-shape matrix pass. Confirmed save, immutable history, comparison, navigator recovery, semantic print and
undo/redo are covered. The complete quality gate passes Ruff, formatting, Mypy over 607 source files and Pytest to 100
percent. The feature adds no migration, new endpoint, dependency, external request, provider, worker, recovery store,
security label, access-control change, collaborative lock, cross-document or cross-tenant transfer, ordinary-tenant
activation, document engine or DOCX DrawingML admission.

## Bounded accessible shape and group metadata (Roadmap 617–623)

Standalone shapes, grouped member shapes and complete root shape groups may carry one optional object name of at most
80 characters and one optional alternative text of at most 500 characters. Browser and authoritative server require
nonempty exactly trimmed plain text and reject C0/C1 controls, surrogates, Unicode line/paragraph separators,
booleans, unknown attributes and limit violations. Omission remains canonical and keeps existing documents
byte-compatible.

The responsive shape dialog edits member metadata alongside established shape attributes and group metadata alongside
established group layout. One accepted edit remains one validated document transaction and undo unit. The object
navigator uses a name as the primary label and searches alternative text together with visible text, kind, position
and anchor. All document-derived values enter the UI as DOM text.

Editor accessibility labels, semantic print/PDF, comparison, confirmed save, immutable history, duplication,
grouping operations and independent reuse preserve the canonical metadata. Two focused Python schema contracts,
21/21 strict model tests, 4/4 targeted desktop/mobile workflows and the complete 43/43 native-shape matrix pass. The
feature adds no migration, new endpoint, dependency, external request, provider, worker, recovery store, HTML, URL,
arbitrary attribute, cross-document or cross-tenant transfer, or DOCX DrawingML admission.

## Bounded object selection navigator (Roadmap 610–616)

The accessible responsive **Objektliste ...** exposes every standalone root shape and complete root shape group in
canonical document order, including roots behind text or otherwise difficult to reach on the page. Search covers
normalized shape text, kind, complete group-member text, document position and logical anchor. A separate type filter
limits results to all objects, standalone shapes or complete groups. Document-derived labels enter the UI only as DOM
text.

Authors can select all visible matches, invert the visible matches or clear the candidate selection. The complete
result must contain zero through twenty unique roots; an over-limit result fails atomically. Opening snapshots the
authorized editor session, exact document instance and the unique root-ID/type/order tuple. Applying revalidates this
snapshot, current write permission and every complete root. Changed, stale, unknown, duplicate or unsorted state
fails closed.

Apply normalizes the chosen roots to document order and replaces only the established transient multi-selection.
It creates no document transaction, immutable version or history entry. Cancel, close and Escape preserve the prior
selection. The resulting selection immediately enables the existing bounded multi-object commands. The focused
strict model plus desktop/mobile workflow passes 3/3 in 51.0 seconds, the targeted mobile rotation regression passes
1/1 and the complete native-shape matrix passes 42/42 in 5.0 minutes after a compact mobile-toolbar correction.
The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
browser/clipboard persistence, cross-document or cross-tenant transfer, nested group or DOCX DrawingML admission.

## Direct native table reordering (Roadmap 351–356)

Authors can move a contiguous row selection one position up or down and a contiguous column selection one position
left or right from the existing table menus. Boundary actions are disabled. The first all-header row and first
all-header column remain fixed, and selections that overlap either protected area cannot move.

Each action moves complete row or cell nodes with their semantic type, content, marks and bounded presentation. The
same rectangular selection follows the moved block, and one accepted movement is one validated undo transaction.
Merged and non-rectangular grids, unsupported options, stale selections, readers and historical views fail closed.
Confirmed save, immutable versions, reload, comparison and print consume the canonical result without a new stored
attribute, drag-and-drop layer or spreadsheet runtime.

## Bounded native table sorting (Roadmap 345–350)

Simple rectangular native tables with at least two data rows can be sorted by one selected column as normalized text,
strict decimal number or strict ISO date. The first all-header row remains fixed, empty values always move to the end,
and equal values retain their previous order. Complete row nodes move together, preserving cell content, marks,
semantic types and bounded presentation.

**Sortieren …** exposes column, type and ascending/descending direction in one accessible dialog. Invalid values,
unsupported options, merged grids, stale selections, cancellation, readers and historical views fail closed without a
document change. One accepted sort is one validated undo transaction. Confirmed save, immutable versions, reload,
comparison and print use the resulting canonical row order without a new stored attribute or formula runtime.

## Bounded table-cell presentation (Roadmap 339–344)

Native table cells and headers may add center/right horizontal alignment, compact/spacious padding and no/strong
border treatment to the existing bounded fills and vertical alignment. Omission preserves left alignment, normal
padding and the table style border. Browser and server reject unknown keys, arbitrary CSS, URLs, dimensions, colors,
per-edge border expressions and unsupported values.

**Zellen formatieren …** applies or resets all five dimensions across cell, row, column and rectangular selections
in one validated undo transaction. Mixed values remain unchanged until explicitly selected. Merge, split and header
conversion retain the exact attributes. Editor, comparison, immutable versions and print use the same canonical
state, while explicit paragraph alignment remains independent and reader/historical controls fail closed.

## Bounded table layouts (Roadmap 333–338)

Native tables may select grid, minimal, banded or accent presentation; full, wide or compact width; left, center or
right alignment; equal columns or a fixed wider/narrower first column; and top or bottom caption placement. Omission
is the canonical grid, full-width, left-aligned, equal-column and bottom-caption representation. Browser and server
reject unknown keys, arbitrary CSS, URLs and unsupported values.

**Tabellenlayout …** edits or resets the whole table in one validated undo transaction. Caption creation, editing
and removal preserve every independent layout value. Comparison and print describe and render the same canonical
state, confirmed saves preserve it in immutable versions, and compact views expand constrained tables to their
available width while retaining the selected style, caption placement and column emphasis.

## Bounded table-cell styling (Roadmap 329–332)

Native table cells and headers may carry one optional fixed fill token (`gray`, `blue`, `green`, `yellow` or `red`)
and one optional vertical alignment (`middle` or `bottom`). Omission preserves the legacy no-fill and top-aligned
form. Browser and server reject unknown attributes, arbitrary color/CSS strings, URLs and unsupported alignments.

**Zellen formatieren …** applies to the current cell selection, including complete rows, columns and rectangular
ranges. Mixed values are preserved until explicitly changed. The complete selection is updated in one validated undo
transaction, and merge, split and header conversion retain the exact attributes. Editor, comparison and print derive
their output from the same canonical model and fixed print-safe palette. Reader and historical mutation controls fail
closed from the initial static shell state.

## Bounded native shapes (Roadmap 292)

Roadmap 483 extends the earlier quarter-turn contract to every whole-degree angle from 1 through 359 under
[ADR-0156](../../ARCHITECTURE_DECISIONS/ADR-0156-arbitrary-angle-native-office-shape-rotation.md). Zero remains the
canonical absence. The responsive dialog accepts an exact value, while the selected shape's direct handle supports
pointer/touch movement around the form center, one-degree arrow steps, 15-degree Shift steps, Home reset and the
existing 90-degree click. A completed gesture is one isolated undo unit.

Normal-flow, wrapped and grouped shapes reserve the exact axis-aligned bounds derived from the validated dimensions
and angle; compact views remain contained. Semantic print/PDF uses the same trusted geometry, while positioned forms
retain their logical anchor. Browser and server reject fractions, booleans, out-of-range values, matrices and style
strings. Confirmed save, history, comparison and independent shape/group copies retain the exact angle in the existing
immutable JSON, without a migration, new store, endpoint, dependency or DOCX DrawingML admission.

Roadmap 490 adds one optional bounded logical position to a complete root-level shape group under
[ADR-0157](../../ARCHITECTURE_DECISIONS/ADR-0157-freely-positioned-native-office-shape-groups.md). The position uses
exactly a front/behind-text layer, an integer normalized X coordinate from 0 through 1000 and an integer Y offset from
-1200 through 1200 pixels. Omission remains canonical normal flow. Individual members still reject wrapping and their
own positions, and groups cannot be nested.

Roadmap 497 adds per-edge native shape-group connections under
[ADR-0158](../../ARCHITECTURE_DECISIONS/ADR-0158-per-edge-native-office-shape-group-connections.md). A group retains
either its byte-compatible uniform `connection` or one exact `connections` list with one bounded value or null entry
per ordered member gap. The responsive dialog can edit all gaps or one numbered gap while preserving untouched
values. Insertion and member duplication add one disconnected gap, removal drops one adjacent gap, reordering keeps
styling at the ordered gap and group duplication preserves the exact list with fresh identities. Editor and semantic
print/PDF resolve both forms into the same sequence through trusted static CSS.

Roadmap 504 adds bounded cross-axis alignment and equal main-axis distribution under
[ADR-0159](../../ARCHITECTURE_DECISIONS/ADR-0159-bounded-native-office-shape-group-alignment-and-distribution.md).
Canonical start alignment remains omitted; center and end map rows to top/middle/bottom and stacks to
left/middle/right. An optional 160 through 2400 pixel extent derives one deterministic equal gap from exact rotated
member bounds while retaining the existing gap as a minimum. Editor and semantic print/PDF use the same layout
function, including compact-row fallback and uniform or per-edge connections. Browser and server reject arbitrary
values, CSS and non-integer extents; existing documents remain byte-compatible.

Roadmap 560 through 566 adds bounded common shape appearance under
[ADR-0167](../../ARCHITECTURE_DECISIONS/ADR-0167-bounded-native-office-shape-multi-object-appearance.md).
Two through twenty selected root standalone shapes or complete shape groups can receive one common fill, stroke,
zero-through-eight stroke width, 10-through-72 font size, automatic or established text color, established text style
and left/center/right alignment. Positioned and normal-flow anchors remain unchanged. Null leaves a field untouched,
mixed values remain explicit, and canonical defaults are omitted.

The accessible seven-field dialog previews only editor-owned DOM. Invalid input restores the source and disables
application. Cancel, Escape, close, document/session changes, read-only state and stale selection restore all source
attributes without history. Apply rebuilds and validates every standalone root and every member of a complete group,
then writes exactly one transaction and undo unit while preserving IDs, group structure, order and geometry.

Direct mouse selection now runs on capture-phase `mousedown` before ProseMirror can retarget or rerender the clicked
shape. Touch and pen retain `pointerdown`; active drag, resize and rotate handlers still win. Confirmed CAS save,
immutable predecessor history, undo/redo, reload, semantic print/PDF and independent reuse preserve only established
canonical appearance. The complete native-shape model and responsive matrix passes 37/37. This adds no migration,
endpoint, dependency, external request, provider, worker, recovery store, arbitrary color/CSS/font value, physical
page anchor, nested group or DOCX DrawingML admission.

Roadmap 567 through 573 adds bounded shape appearance copy/paste under
[ADR-0168](../../ARCHITECTURE_DECISIONS/ADR-0168-bounded-native-office-shape-appearance-copy-paste.md).
One selected standalone root or complete root group can provide the seven established appearance values. Complete
groups are sources only when all members normalize to the same fill, stroke, stroke width, font size, text color,
text style and alignment. Defaults normalize to 16, automatic and normal before canonical omission; mixed groups and
unknown or arbitrary values fail closed.

The sample remains in memory for the current authorized document session. Document/session change or lost write
permission clears it. System clipboard, browser persistence, Office JSON, API, telemetry and cross-document or
cross-tenant transfer are excluded. Paste requires two through twenty valid roots and rebuilds all standalone targets
and group members before one transaction and undo unit, retaining IDs, structure, order, connections, text and every
geometry or anchoring attribute.

Accessible responsive controls expose remember, apply and memory status. Normal-flow group preview no longer assumes
a free position; it previews and restores appearance without adding position data. Model and real desktop/mobile
workflows cover normalized sources, uniform/mixed groups, target bounds, preview, one-step undo/redo, confirmed save,
immutable history, semantic print, reload clearing and independent reuse. The complete native-shape matrix passes
37/37. No migration, endpoint, dependency, external request, provider, worker, recovery store, clipboard/browser
persistence, arbitrary value, physical page anchor, nested group or DOCX DrawingML admission is added.

Roadmap 574 through 580 adds bounded collective top-level document ordering under
[ADR-0169](../../ARCHITECTURE_DECISIONS/ADR-0169-bounded-native-office-multi-object-document-order.md).
Two through twenty selected standalone root shapes or complete root groups can move to the document beginning, one
position earlier, one position later or to the document end. Positioned, wrapped and normal-flow roots remain
eligible because the operation changes canonical top-level order only; it does not change the separate
front/behind-text layer.

One-step actions move each selected run across at most one adjacent unselected node. Beginning/end actions form one
selected block. Selected roots keep their relative order and every unselected node keeps its relative order. A
complete group remains one root with unchanged identity, member order and connections. Content, IDs, text,
appearance, geometry, anchors, wrap, position and layer are retained.

The four responsive actions revalidate current write permission, selection and boundaries. One effective action is
one validated transaction and undo unit; the same stable IDs remain selected, while a boundary no-op stays disabled
and creates no history. Confirmed CAS save, immutable predecessor history, print, reload and reuse preserve the
resulting existing Office JSON order. The focused model plus desktop/mobile workflow passes 3/3 and the complete
native-shape matrix passes 38/38. No migration, endpoint, dependency, external request, provider, worker, recovery
store, arbitrary z-index, drag ordering, physical page anchor, nested group or DOCX DrawingML admission is added.

Roadmap 581 through 587 adds bounded collective group dissolution under
[ADR-0170](../../ARCHITECTURE_DECISIONS/ADR-0170-bounded-native-office-multi-group-ungroup.md).
Two through twenty selected complete root shape groups can be dissolved together when every group is in normal flow.
One group, mixed shape/group selections, partial or nested groups, positioned groups and invalid or stale selections
fail closed. Positioned groups remain separate because one group-level anchor and layer cannot be mapped losslessly
to several independent shapes.

The command removes only each selected group wrapper and inserts its ordered member shapes at the same top-level
position. Member IDs, text, appearance, dimensions, rotations and canonical shape attributes remain exact, while
group-only identity, layout, gap and connection data disappear. Every unselected node retains its relative order and
content. Replacements run from the document end toward the beginning in one validated transaction and undo unit.

The responsive **Gruppen auflösen** action follows current write permission and exact selection eligibility. Success
clears the transient multi-selection and focuses the first resulting shape. Model and desktop/mobile workflows cover
eligibility, atomic wrapper removal, undo/redo, confirmed save, immutable history, semantic print, reload, range
selection and independent reuse. The focused workflow passes 3/3 and the complete native-shape matrix passes 39/39.
No migration, endpoint, dependency, external request, provider, worker, recovery store, inferred position or layer,
member rewrite, nested group, arbitrary connector or DOCX DrawingML admission is added.

Roadmap 588 through 594 adds bounded current-session group restoration under
[ADR-0171](../../ARCHITECTURE_DECISIONS/ADR-0171-bounded-native-office-shape-regroup-memory.md).
After a successful collective ungroup, the editor remembers the exact original normal-flow group wrappers for the
current authorized document session. **Gruppen wiederherstellen** needs no renewed object selection and restores two
through twenty remembered groups, each with the established two-through-eight member bound.

Every invocation revalidates original group and member IDs, current standalone root shapes, exact member order,
contiguous document ranges, normal-flow anchors, connections, limits and ID collisions. It uses the current member
nodes so permitted edits made after ungroup remain intact, while restoring the original group ID, layout, gap,
alignment, distribution and connections. Unrelated node order and content remain unchanged. Stale, partial, moved,
positioned or otherwise invalid state fails closed.

The memory remains inside the current authorized editor session, survives a normal confirmed save and is cleared by
a document/session change, historical mode or lost write permission. It does not enter Office JSON, browser storage,
the clipboard, an API request or another document or tenant. All remembered ranges are replaced from the end toward
the beginning in one validated transaction and undo unit; undo/redo dynamically controls renewed eligibility.

The corrected pure-model and desktop/mobile workflow passes 4/4 in 46.2 seconds and the complete native-shape matrix
passes 40/40 in 4.8 minutes. Tests cover wrapper and current-member preservation, connections, order, collisions,
undo/redo, confirmed ungroup and regroup saves with immutable predecessor versions, print, reload/session clearing and
independent reuse. The initial three failures remain recorded as diagnostic evidence. No migration, endpoint,
dependency, external request, provider, worker, recovery store, browser/clipboard persistence, cross-document or
cross-tenant transfer, positioned or nested group, or DOCX DrawingML admission is added.

Roadmap 595 through 602 extends that lifecycle to complete freely positioned groups under
[ADR-0172](../../ARCHITECTURE_DECISIONS/ADR-0172-bounded-native-office-positioned-group-ungroup-regroup.md).
Two through twenty selected groups may be dissolved together when every selected group has the same anchor kind.
Mixed flow/position selections, partial or nested groups and independently positioned members fail closed.

For positioned groups, the control reads each rendered member's visible center immediately before the transaction and
maps it to the existing bounded standalone position model. The group layer is retained; X remains 0 through 1000 and
Y remains -1200 through 1200. Canonical member dimensions, rotations, text and presentation stay exact. The mapping
accounts for responsive flex shrink, multi-selection expansion and each inserted root. When the canonical standalone
size makes an exact edge center impossible, only the nearest bound within four pixels is accepted; larger or
non-finite drift rejects the complete operation without history.

Current-session regroup memory additionally binds every derived member position. Regroup requires the exact current
standalone IDs, order, contiguous ranges, positions and layer and rechecks limits, connections and collisions. It
removes only the derived standalone positions and restores the original positioned group IDs, anchors, layer,
layout, gap, alignment, distribution and connections while retaining other permitted member edits. A moved, missing
or duplicated member disables regrouping. Memory never enters Office JSON, browser storage, clipboard, an API
request, another document or another tenant.

The final pure-model plus narrow-desktop/mobile workflow passes 3/3 in 33.7 seconds and the complete native-shape
matrix passes 40/40 in 4.9 minutes. Confirmed ungroup and regroup saves, immutable predecessors, semantic print,
undo/redo, reload and independent reuse remain covered. The initial left-edge comparison, viewport-scroll diagnostic
and live-review rotated-edge rejection remain recorded as diagnostics. No migration, endpoint, dependency, external
request, provider, worker, recovery store, nested group, arbitrary physical page anchor or DOCX DrawingML admission
is added.

Roadmap 603 through 609 adds exact bounded placement for the established transient multi-object selection under
[ADR-0173](../../ARCHITECTURE_DECISIONS/ADR-0173-bounded-native-office-exact-multi-object-document-placement.md).
Two through twenty selected standalone root shapes or complete root groups can be inserted as one stable block at an
exact one-based document start position. The target range is 1 through the number of unselected roots plus one, and
at least one unselected document root must remain.

Selected roots retain their relative order and every unselected paragraph, shape, group or other root retains its
relative order. Complete groups move as unchanged root nodes, preserving identity, member order, connections, text,
appearance, geometry, anchors, wrapping, position and layer. The accessible responsive **Position ...** dialog shows
the selection and document counts, dynamic integer bounds, a stable-order explanation and explicit valid, invalid or
no-op status.

Open and submit revalidate the authorized session, exact document instance, write permission, selected IDs, root
count and target. Stale, historical, read-only, fractional, boolean, duplicate, unsorted, unsupported and out-of-bound
state fails closed. One effective placement is one validated transaction and undo unit, keeps the same IDs selected
and focuses the first moved root; a no-op creates no history. The focused model plus desktop/mobile workflow passes
3/3 in 50.4 seconds and the complete native-shape matrix passes 41/41 in 5.0 minutes. No migration, endpoint,
dependency, external request, provider, worker, recovery store, browser/clipboard persistence, arbitrary z-index,
drag ordering, physical page anchor, nested group or DOCX DrawingML admission is added.

Roadmap 525 through 531 adds bounded common layer and collective nudge under
[ADR-0162](../../ARCHITECTURE_DECISIONS/ADR-0162-bounded-native-office-shape-multi-object-layer-and-nudge.md).
At least two selected positioned root shapes or complete groups can move together to the front/behind-text layer
without changing coordinates. Arrow keys move the complete selection by one logical unit and Shift plus an arrow by
ten; four responsive, accessible direction buttons expose one-unit movement to pointer and touch users.

One shared delta is clamped against every selected X/Y anchor, so the complete selection stops when any member has
reached a requested boundary. Relative geometry, stable IDs, layers and document order remain intact. Keyboard input
is intercepted only in the active editor or multi-selection tools and never from a dialog or text-entry control.

Each accepted action validates the full candidate and forms exactly one transaction and undo unit. Confirmed CAS
save, predecessor history, reload, semantic print/PDF and independent reuse preserve the resulting established
positions while selection remains transient. No migration, endpoint, dependency, external request, provider, worker,
recovery store, arbitrary movement value, physical page anchor, nested group or DOCX admission is added.

Roadmap 546 through 552 adds bounded collective relative rotation under
[ADR-0165](../../ARCHITECTURE_DECISIONS/ADR-0165-bounded-native-office-shape-multi-object-rotation.md).
Dragging the rotation handle of any selected positioned root shape or complete group applies one common integer angle
delta to every selected shape and every member of selected groups. Existing distinct rotations remain relative and
normalize to canonical zero omission or 1 through 359.

The existing standalone handle and the positioned-group handle provide mouse, touch and keyboard access. Movement
around the active root center uses the shortest signed angle; Shift snaps to 15 degrees. Arrow keys apply one degree,
Shift-arrows apply 15 degrees, click applies 90 degrees and Home aligns the source angle to zero through a common
delta. Live changes affect editor-owned DOM only, with signed status, markers and accessible whole-selection labels.

Pointer cancellation, Escape, changed document/session and non-writable or stale state restore all original angles.
One effective completion validates all rebuilt shapes/groups and creates exactly one undo unit. Group attributes,
member order, connections, gap, layer, position, dimensions, typography and stable IDs remain unchanged. Confirmed
CAS save, predecessor history, reload, semantic print/PDF and independent reuse preserve only established rotations.
This adds no migration, endpoint, dependency, external request, provider, worker, recovery store, arbitrary transform,
physical page anchor, nested group or DOCX DrawingML admission.

Roadmap 553 through 559 adds the bounded exact multi-object transform inspector under
[ADR-0166](../../ARCHITECTURE_DECISIONS/ADR-0166-bounded-native-office-shape-multi-object-transform-inspector.md).
At least two selected positioned standalone shapes or complete groups can combine relative logical X and pixel Y
movement, independent or aspect-locked scaling, relative whole-degree rotation and an optional common text layer.

The pure command accepts exactly seven typed keys and rejects extra keys, fractions, numeric booleans and values
outside the established X/Y, 10-500 percent, -359/359-degree and front/behind bounds. Existing common translate and
resize constraints derive one effective clamped result for the complete selection. Stable IDs, group membership and
order, connections, gaps, literal text and typography remain intact.

Every valid input change previews complete root position/layer plus all affected member sizes and rotations in
editor-owned DOM. Invalid input disables apply and restores the source view. Cancel, close, Escape, document/session
change, read-only state and stale selection restore all source values without history. Apply performs one validated
transaction and undo unit. Confirmed CAS save, immutable predecessor history, undo/redo, reload, semantic print/PDF
and independent reuse preserve the established canonical attributes while selection, dialog and preview stay
transient. The responsive dialog uses three two-field rows and an inline aspect lock; CSS asset `v=2` prevents stale
long-lived tabs from retaining the previous layout. No migration, endpoint, dependency, external request, provider,
worker, recovery store, arbitrary transform/CSS value, physical page anchor, nested group or DOCX admission is added.

Roadmap 539 through 545 adds bounded collective resizing under
[ADR-0164](../../ARCHITECTURE_DECISIONS/ADR-0164-bounded-native-office-shape-multi-object-resize.md).
Dragging the resize handle of any selected positioned root shape or complete group scales the complete eligible
selection. Independent X/Y factors use a fixed 1000 base; Shift uses one aspect-locked factor. The common factor is
clamped against every member shape, keeping widths within 80 through 1200 and heights within 40 through 800.

The existing standalone handle and the positioned-group handle provide mouse, touch and keyboard access. Arrow keys
change the source dimension by one pixel and Shift plus an arrow by ten. Live changes affect only editor-owned DOM,
with common percentage status, selection markers and accessible whole-selection labels. Pointer cancellation,
Escape, a changed document/session and non-writable or stale state restore every original dimension without history.

One effective completion validates all rebuilt shapes/groups and creates exactly one undo unit. Group attributes,
member order, connections, gap, layer, position, rotation, typography and stable IDs remain unchanged. Confirmed CAS
save, predecessor history, reload, semantic print/PDF and independent reuse preserve only the resulting established
dimensions. This adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
arbitrary CSS, physical page anchor, nested group or DOCX DrawingML admission.

Roadmap 532 through 538 adds bounded collective pointer and touch dragging under
[ADR-0163](../../ARCHITECTURE_DECISIONS/ADR-0163-bounded-native-office-shape-multi-object-pointer-drag.md).
Dragging the position anchor of any selected positioned root shape or complete group moves the complete eligible
selection. Horizontal pointer movement maps through the current editor width to the existing integer X scale;
vertical movement becomes an integer pixel delta. One shared dual-axis delta is clamped against every selected
anchor, preserving relative geometry, stable IDs, layers and document order.

The editor shows a DOM-only live preview, effective X/Y status, common dragging markers and an accessible anchor label
for the whole selection. Pointer cancellation, Escape, a changed document or session and non-writable or stale state
restore the original preview without a transaction. The collective capture path suppresses individual anchor drag
and its following click.

One effective pointer release validates the complete candidate and creates exactly one undo unit; no movement creates
none. Confirmed CAS save, predecessor history, reload, semantic print/PDF and independent reuse preserve only the
resulting established positions. No migration, endpoint, dependency, external request, provider, worker, recovery
store, free coordinate field, physical page anchor, nested group or DOCX admission is added.

Roadmap 518 through 524 adds bounded multi-object arrangement under
[ADR-0161](../../ARCHITECTURE_DECISIONS/ADR-0161-bounded-native-office-shape-multi-object-arrangement.md).
Two or more selected positioned root shapes or complete groups can align to their minimum, rounded midpoint or
maximum horizontal or vertical logical anchor. Three or more can be distributed equally on either axis while the
extreme anchors remain fixed. Coordinate, root order and stable ID make every result deterministic.

The responsive toolbar remains disabled if the selection is too small or contains a normal-flow or wrapped object.
An accepted action validates the complete candidate and commits one transaction and undo unit while retaining IDs,
layers, untouched coordinates and the transient selection. The editor uses only the established bounded integer
logical anchors; it does not derive layout from DOM rectangles, CSS or physical page geometry.

Confirmed CAS save, predecessor history, reload, semantic print/PDF and independent reuse preserve the resulting
existing positions. Selection state remains transient. This adds no migration, endpoint, dependency, external
request, provider, worker, recovery store, physical page anchor, arbitrary geometry, nested group or DOCX admission.

Roadmap 511 through 517 adds bounded transient root-object multi-selection under
[ADR-0160](../../ARCHITECTURE_DECISIONS/ADR-0160-bounded-native-office-shape-multi-selection.md).
Authors can select up to 20 standalone shapes or complete shape groups with an explicit mouse/touch mode,
Ctrl/Cmd-click or Shift range selection. Stable IDs keep markers attached across editor DOM updates, while document,
version and session changes clear all transient selection state.

Two or more selected roots can be duplicated or removed as one validated undo unit. Copies receive fresh group and
member IDs and positioned roots use the existing bounded visible offset. Two through eight adjacent standalone
normal-flow shapes can become one canonical row group; wrapped or positioned shapes, existing groups, intervening
blocks and nesting remain rejected. Existing shape and group limits are checked before dispatch.

Only resulting established shape/group nodes enter the immutable Office JSON. Confirmed CAS save, predecessor
history, reload, semantic print/PDF and independent reuse retain those nodes, while selection markers and anchors are
never persisted. The change adds no schema migration, endpoint, dependency, external request, provider, worker,
recovery store or engine admission.

The responsive group dialog exposes layer and coordinates. A focusable direct anchor moves the complete group by
pointer/touch, one-pixel arrows, ten-pixel Shift steps or Home reset. Live movement changes only editor-owned DOM
presentation; releasing the pointer commits one validated isolated undo step. Row/stack layout, gap, member dimensions
and arbitrary rotations feed one exact axis-aligned group bound shared by editor, comparison and semantic print/PDF.
Static CSS maps only validated tokens and product-generated numbers.

Positioned duplication creates fresh group/member IDs and a bounded visible 25/24 offset. Ungrouping requires normal
flow first. Removing one member from a two-member positioned group promotes the survivor atomically to a standalone
shape at the group anchor. Confirmed save, immutable history, reload, independent reuse and recovery preserve the exact
position in the existing JSON without a migration, endpoint, new store, physical page anchor, arbitrary z-index or
DOCX DrawingML admission.

Roadmap 305 adds direct earlier/later controls for a selected standalone shape. Each action swaps the complete shape
with exactly one adjacent top-level document node and keeps selection on the moved shape. Boundary actions are
disabled, while grouped shapes continue to use member ordering. The isolated undo transaction preserves the stable
shape ID and every validated presentation attribute. Confirmed save, immutable history and static print retain the
exact resulting order without a new stored field.

Roadmap 304 adds direct earlier/later controls for a selected native shape group. Each action resolves the stable
validated group ID against the current document, swaps the complete group with exactly one adjacent top-level node
and keeps selection on the moved group. Boundary actions are disabled. The isolated undo transaction preserves the
group ID, member IDs and order, layout, gap, optional connection and every member attribute. Confirmed save,
immutable history and static print retain the exact resulting order without a new stored field.

Roadmap 303 adds **Gruppe entfernen** for a selected native shape group. At activation, the editor resolves the stable
validated group ID against the current document and removes that complete node in one isolated undo transaction.
Undo restores the exact group ID, member IDs and order, layout, gap, optional connection and every member attribute;
redo removes it again. Unrelated document content remains unchanged. Missing, stale and read-only targets fail closed,
and the removal becomes durable only through the existing confirmed version save. Earlier immutable versions and
static print retain their exact content without a new stored field.

Roadmap 302 adds **Gruppe duplizieren** for an existing shape group. It generates a new opaque group ID and a new
opaque shape ID for every member, then inserts the complete copy immediately after its source. Exact member order,
row/stack layout, gap, optional uniform connection and every validated member attribute remain unchanged. The control
is disabled when the document already has 20 groups or the additional members would exceed 100 shapes. The complete
insertion and selection are one isolated undo transaction; saved versions, comparison and print treat both groups as
independent structures.

Roadmap 301 adds an explicit **Form duplizieren** action for an existing shape. Every copy receives a fresh opaque ID
and preserves the exact validated kind, dimensions, colors, stroke, literal text, alignment, typography, rotation,
wrapping and layer. A grouped copy is inserted directly after its source without changing group presentation or
connections. A positioned copy stays on the same layer and receives a bounded 25-unit horizontal and 24-pixel
vertical offset, reversing the offset near the maximum edges. The action is disabled before the 100-shape or
eight-member limit and commits one isolated undo transaction.

Roadmap 300 lets each shape optionally override its canonical 16-pixel text size with an integer from 10 through 72,
choose one fixed non-transparent text-color token and choose bold, italic or bold-italic text. Automatic contrast and
normal style remain canonical omissions. The same exact attributes render in preview, the editor, grouped shapes and
print and appear in accessible descriptions and comparisons. Unknown keys, font names, URLs, CSS, markup, arbitrary
style strings, booleans and out-of-range sizes fail closed in browser and server validation.

Roadmap 299 adds direct keyboard-accessible controls that move the selected shape-group member exactly one position
earlier or later. The unavailable direction is disabled at each boundary. Every move replaces the validated group in
one isolated undo transaction and keeps selection on the moved member. It changes only the group's existing exact
member sequence, so layout, gap, connection, member attributes, immutable history, copies and print need no new
durable representation. Drag-only ordering, overlap layers and arbitrary z-index behavior remain excluded.

Roadmap 298 adds one optional uniform connection between consecutive members of a shape group. The exact bounded
value admits only a line, direction arrow or double arrow, a fixed color token and integer 1–8 pixel width. Rows render
horizontal connections; stacks and compact row fallback render vertical connections. The dialog disables color and
width without a selected connection. Comparison, undo, immutable history, historical reuse, independent copies and
print preserve the exact type, color and width without storing markup, paths, endpoints or executable styles.

Roadmap 297 adds root-level groups of two through eight flow shapes with exact member order, row/stack layout and an
integer 0–48 pixel gap. Authors can create or extend a group from adjacent shapes, change its layout, edit or remove
members and dissolve it with isolated undo/redo. Row groups collapse to one column in compact views. Group members
retain their own validated shape presentation and optional quarter-turn rotation, while wrapping and free positioning
of individual members are rejected. Comparison, immutable history, historical reuse, independent copies and print
preserve the exact group.

Roadmap 296 adds optional left/right text wrapping with an exact integer 0–48 pixel gap. Wrapping and free positioning
are mutually exclusive in the dialog and both validators. Wrapped shapes occupy at most 45 percent of the available
text width and a visual height equivalent to 480 pixels; below the narrow-container threshold they return to a safe
block. Rotation and resizing remain available. Undo, comparison, immutable history, historical reuse, independent
copies and print preserve the exact side and gap.

Roadmap 295 adds optional 90-, 180- or 270-degree rotation; zero degrees remains the canonical absence. The dialog and
the selected shape's direct **90° drehen** control use isolated undo transactions. Rotation applies to the inert form
and its literal text. Normal-flow sideways shapes reserve responsive transposed bounds, while positioned shapes retain
their exact logical anchor and dimensions. Comparison, history, copies and print preserve the exact angle. Arbitrary
angles, matrices and executable transform strings fail closed.

Roadmap 294 adds a visible direct resize control to the selected shape in normal flow or on either logical layer.
Pointer/touch movement previews both dimensions and commits the final bounded size as one isolated undo step; pointer
cancellation restores the previous display. Arrow keys change one dimension by one pixel and Shift plus an arrow by
ten pixels. The accessible name reports the current dimensions. This editor-only control is absent from saved content
and print, because width and height remain the existing canonical bounded integer attributes.

Roadmap 293 optionally anchors a shape in front of or behind nearby text with an integer normalized X coordinate and
bounded Y offset. The explicit dialog and an always-visible pointer/touch/keyboard anchor use the same validation.
Normal flow omits the anchor. Responsive rendering, comparison, history, copies and print preserve its exact logical
value without treating it as a physical page coordinate or admitting arbitrary CSS and z-index values.

**Form einfügen …** creates an inert top-level rectangle, rounded rectangle or ellipse. The stored node contains only
a unique restricted ID, bounded integer width/height/stroke width, fixed fill/stroke color tokens, literal text and a
fixed text alignment. Selection or double-click reopens the responsive editor. Insert, edit and remove are isolated
undo steps and become durable only through the existing confirmed CAS save.

Shapes shrink to the available editor or print width without horizontal overflow. Comparison, history and independent
copies preserve exact attributes and print emits an inert accessible element. Server and browser reject unknown keys,
duplicate IDs, nesting, excess shapes, control characters and values outside the fixed vocabularies. Arbitrary SVG,
paths, CSS, remote resources, scripts, OLE, freely routed connectors, nested shape grouping and DrawingML interchange
are not admitted.

## User workflow and scope

`/office` is a focused writing workspace linked from `/work`. Users can start from an empty document or a local template,
apply text styles, paragraph alignment and spacing, headings, lists and tables, navigate an outline, search within text, inspect word count, use focus mode,
save a confirmed version, compare saved versions, take a historical version into a new local draft, discuss an exact
saved version through comments and replies, and propose text replacements for explicit acceptance or rejection.
Roadmap 258 adds a saved-version print preview and browser print/PDF action, with completed development validation below.
Search within the current document remains local. Roadmap 260 extends title discovery to server-side search and
paginated results, described below; it does not enable a global content index. Desktop, tablet and mobile layouts support keyboard controls and keep reload
available. Formatting returns focus to the editor before immediate typing.

This slice stores native structured documents. Roadmap 256 adds review discussions with verified browser and recovery
evidence below. DOCX interchange, tracked changes, live collaboration, spreadsheets,
presentations and mail remain separate product work. Existing DOCX engine fidelity and admission gates are unchanged.

## Bounded ACL-safe backlinks (Roadmap 288)

**Rueckverweise** on a saved document version derives exact incoming references from current versions of documents
the reader may access now. The server first authorizes the target and exact target version. It then rechecks every
candidate source through the normal tenant and authoritative ACL path, reads the current immutable source version and
returns a row only when it contains the exact target object/version pair. Each row carries the current source title,
exact source version and reference count, but no content.

One request scans at most 50 authorized candidates and returns at most 50 matches. Its signed cursor is bound to the
tenant, actor, roles, exact target and page size. Empty intermediate pages can therefore offer a deliberate next scan
without claiming that no later match exists. The browser rejects mismatched tenant/target/version responses and stale
session results. Opening a row deliberately loads the exact source version through the ordinary freshly authorized
read path.

There is no backlink table or content index. Revoked and deleted sources disappear on the next request without
denormalized cleanup, and neither their count nor title is exposed. Audit stores target identity and aggregate counts
only. Backlinks are not included in print. Transitive graphs, content-wide reference search, persistent indexing and
DOCX relationships remain separate.

Validation completed on Roadmap 288 with full Python quality and a green 409/409 desktop/mobile browser and model
matrix. Fresh recovery verified 929 documents, 1,801 exact versions and exact backlink behavior across signed pages,
including current source ACL revocation and foreign-tenant denial. The final API-only rollout keeps pilot runtime at
zero; live checks cover the roadmap metadata, OpenAPI route, Office control and bundle, CSP, `no-store` and a
fail-closed synthetic tenant. Detailed hashes and host operations are recorded in `docs/CURRENT_HANDOFF.md` and
`docs/operations/DEV001_OPERATIONS_LOG.md`.

## Exact outbound document references (Roadmap 287)

**Dokumentverweis …** applies an exact target object and immutable target version to selected text. The saved mark
contains no title or authorization snapshot. The target chooser lists only documents readable at that moment. An
existing reference may open its pinned historical version only after a fresh server resolution; an unsaved reference
must first pass the normal confirmed CAS save.

The resolver re-reads the exact source version and uses the ordinary repository tenant, current ACL and exact-version
checks for every distinct target. Missing objects, missing versions and denied targets all become
**Dokumentziel nicht verfügbar**, without a target title. The editor refreshes this state on load. Print repeats the
same resolution for every preview and final browser print and emits only an inert semantic span, with no cross-document
link action. Copies keep exact IDs and safely become unavailable under a different reader.

Server and browser independently enforce exact ID shapes, mark compatibility and a 100-mark limit. Audit records hold
only source identity and resolution counts. No backlink table, global discovery query, remote fetch or DOCX relationship
is introduced. A two-document/four-version recovery fixture proves a source pinned to target version one while target
version two is current.

## Inert document objects (Roadmap 314–316)

**Dokumentobjekt einfügen …** adds a top-level atomic card that stores one exact document object/version pair and
either `snapshot` or `linked`. The card contains no saved title, body, URL, markup or executable object. It shares the
existing 100-occurrence limit and authoritative outbound-reference/backlink walker with inline references.

Both modes stay pinned while loading, reopening, comparing and printing a saved source version. A linked card exposes
**Auf aktuelle Version aktualisieren** only when the currently readable target has a newer saved version. Choosing it
changes the local draft visibly and undoably. Snapshot cards never offer automatic movement. The title and current/
historical state come only from a fresh server resolution; revoked, missing and foreign targets collapse to the same
title-free unavailable state.

The focusable card action opens its exact target only from a clean source, duplicates the exact inert binding, moves
the block one document position earlier/later or removes it. Confirmed CAS save remains the sole durable mutation.
Editor, immutable history, comparison and print share the same representation. No OLE, ActiveX, macro, iframe,
external content, implicit grant, relational migration or engine path is introduced. Decision:
[ADR-0129](../../ARCHITECTURE_DECISIONS/ADR-0129-native-office-document-objects.md).

## Native calculations and linked charts (Roadmap 317–320 and 792–799)

**Diagramm einfügen …** creates a top-level atomic bar, line or pie chart from a bounded tab-separated literal table.
The saved object contains a fresh stable ID, title, alternative text, legend flag, one to twelve unique categories and
one to four uniquely named finite decimal series using a fixed four-color vocabulary. Bar and pie values are
nonnegative; line values may be negative. Pie charts use exactly one series with at least one positive value. Documents
contain at most twenty charts.

Under ADR-0197, a chart may instead bind to one exact two-through-thirteen-row and two-through-five-column range of a
numbered table in the same document. The first row supplies unique series names, the first column supplies unique
categories and the remaining cells contain bounded decimal literals or verified formula results. Pie sources contain
exactly two columns. The stored source has only `tableId` and an A1 range; URLs, external workbooks and queries are not
accepted.

Native table formulas now support comparisons, transitive references and `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`,
`IF`, `AND`, `OR`, `NOT`, `ROUND`, `ABS`, `POWER`, `SQRT`, `PRODUCT` and `MEDIAN`. German aliases and semicolon
separators normalize to the canonical grammar. Relative, absolute and mixed references keep their existing
copy/fill/structural behavior. `IF` evaluates only the selected branch. Browser and server independently recalculate
results and preserve explicit `#BEZUG!`, `#DIV/0!`, `#ZYKLUS!`, `#WERT!` and `#LIMIT!` outcomes.

After an accepted table edit, formulas and linked chart snapshots update together without creating a version. Before
confirmed CAS save, the browser verifies every binding; the server independently resolves the numbered source table,
re-derives the exact snapshot and rejects missing sources, merged grids, stale or forged values, invalid ranges and
unknown fields. Immutable history therefore records a deterministic table, formula-result and chart snapshot for each
version.

Rendering creates inert DOM, or internal SVG geometry for lines, only after validation. An exact hidden data table,
title, alternative text and optional legend keep the result accessible without turning the chart into an embedded
application. The responsive dialog provides preview, insert, edit, fresh-ID duplicate, one-position movement and
removal. Manual charts remain supported. The existing Office JSON recovery contract applies; there is no migration,
object-storage write, network read, spreadsheet engine or engine admission. Decisions:
[ADR-0130](../../ARCHITECTURE_DECISIONS/ADR-0130-native-office-inert-charts.md) and
[ADR-0197](../../ARCHITECTURE_DECISIONS/ADR-0197-native-office-calculations-and-linked-charts.md).

### Named ranges and cross-table formulas (Roadmap 800–807)

**Bereich benennen …** binds the current rectangular simple-cell selection to the stable ID of its numbered table.
The document stores at most 100 unique canonical names with exact `A1:T200` rectangles. Names cannot look like cell
references or supported functions. They contain no title snapshot, URL, external workbook, query or executable source.
The dialog shows the exact table number and coordinate and supports replacement and removal before confirmed save.

Local A1 references still resolve inside their containing table. A named single cell can be used as a scalar; a named
rectangle can feed aggregate functions from any other table in the document. `XLOOKUP`/`XVERWEIS` performs bounded
exact numeric lookup across equal-length local or named ranges. `DATE`/`DATUM`, `YEAR`/`JAHR`, `MONTH`/`MONAT` and
`DAY`/`TAG` use deterministic UTC day numbers relative to 1970-01-01. Current-time functions, approximate and text
lookup, external connections and automatic actions remain unavailable.

The browser evaluates all formula cells through one document dependency graph and updates their stored snapshots in a
single local editor transaction. Insertion, deletion, movement and duplication remap a named rectangle when its cells
remain contiguous. A definition is removed if its rectangle is destroyed, or atomically with its table ID. The server
independently resolves every name and table range, recalculates cross-table dependencies, detects cycles and rejects
stale or forged results before accepting a version. This adds no migration or external spreadsheet engine. Decision:
[ADR-0198](../../ARCHITECTURE_DECISIONS/ADR-0198-native-office-named-ranges-and-cross-table-formulas.md).

### Conditional aggregation, presentation and chart editing (Roadmap 808–815)

`SUMIF`/`SUMMEWENN`, `COUNTIF`/`ZÄHLENWENN` and `AVERAGEIF`/`MITTELWERTWENN` compare a local or named numeric range
with one exact numeric criterion. Sum and average may read an equally sized result range; count accepts exactly the
tested range and criterion. The functions use the existing document graph and 4,000-value bound. An empty average
returns `#DIV/0!`; mismatched ranges or arity return `#WERT!`.

The cell-format dialog now offers fixed integer, two-decimal, percent, EUR and date presentations. Stored text and
`formulaResult` remain canonical numeric values. A ProseMirror decoration derives the localized visible text, so
formula evaluation and linked charts never parse the presentation. Server validation accepts only the fixed vocabulary,
finite numeric sources and valid UTC-derived dates between 1900 and 9999.

Linked chart bindings can treat either columns or rows as data series. The exact orientation is stored with the table
ID and range and participates in the existing browser/server snapshot validation. Authors can show bounded value labels
and edit source table, range, orientation, type, title, alternative text and legend before confirmed save. The feature
adds no free format strings, custom code, external workbook, network source or migration. Decision:
[ADR-0199](../../ARCHITECTURE_DECISIONS/ADR-0199-native-office-conditional-aggregation-presentation-and-chart-editing.md).

## Merged table cells and semantic headers (Roadmap 321–324)

Native table cells retain canonical column spans from one through twenty and row spans from one through two hundred.
Browser and server expand every row into the same bounded logical grid and reject gaps, overlaps, truncated spans and
nonrectangular results. Editor-only cell attributes are normalized away before validation and never enter immutable
version JSON.

**Zellen verbinden** and **Zelle teilen** are focusable contextual actions whose availability follows the current
selection. Each accepted operation creates one isolated undo step. **Kopfspalte** is independent of the existing
header-row action and follows the logical grid when a merged cell covers several columns or rows.

Confirmed CAS save, immutable predecessors, reload and comparison retain exact span geometry. Print emits native
`colspan` and `rowspan`; column headers use `scope="col"`, while first-column headers in the body use `scope="row"`.
The structure uses the existing Office JSON recovery contract and adds no spreadsheet runtime, formula evaluation,
database migration or engine admission. Decision:
[ADR-0131](../../ARCHITECTURE_DECISIONS/ADR-0131-native-office-merged-table-cells.md).

## Native semantic document structures (Roadmap 280–286)

**Struktur …** provides one responsive, keyboard-reachable workflow for document-owned fields, generated tables of
contents, footnotes, endnotes, citation sources and references, bibliographies, inert formulas and a local reference
navigator. Catalog data and explicit atoms are stored in the exact native version. Numbers and generated lists follow
current document order and are never saved as stale rendered text.

Fields use bounded keys and literal values. Reusing a key updates the catalog while inserting an explicit field atom;
`{{field:key}}` is the corresponding explicit token in a header or footer. Print resolves only the same version-owned
catalog and keeps the existing 64-character running-text boundary. Removing a field leaves uses visible as broken.

Footnotes and endnotes have separate order-derived sequences and stable local IDs. Citation sources are bounded
literal metadata and are never fetched. A bibliography is generated from the local catalog. Removing a source leaves
its citations visibly broken. Formula source and accessible text are stored as inert literals; no parser, macro,
script, external engine or calculated write exists. The reference navigator derives a read-only overview from the
current document.

Server and browser independently enforce exact shapes, limits, unique identities and control-character exclusions.
All operations remain ordinary undoable draft transactions and use the existing confirmed CAS save. History,
comparison, independent copies and semantic print retain the exact structures. A ten-version recovery lineage covers
legacy, each additive structure, broken catalog targets and a final legacy reset. Cross-document references, global
backlinks, mathematical evaluation and DOCX interchange remain separate authorization and fidelity work.

Full Python quality passed Ruff, formatting for 807 files, Mypy over 602 sources and complete Pytest. The complete
desktop/mobile browser and model matrix passed 403/403; its archived report is
`sha256:e07b3ad7cc88364f78b628e11bd8535dacdfcbce7a684efd2c4b34543a1a9977`. The final focused workflow passed with
report `sha256:e88435f84fe6e045f587f0d17bfde5b69d18ec00f6925cd6bdee828b5043d072`. Its actual one-page A4 PDF is tagged,
contains no JavaScript or form, and has SHA-256 `bac235bd08aab13a01d1aa7e95dfeaa27d68cf1f1e29d916ce74f6c811dfa73f`.

Fresh recovery into `collabio_work_e2e_286_restore` verified 586 documents, 1,161 exact Office versions, 204
multi-version documents, 1,299 source objects and all ten semantic fixture versions. The recovery report file is
`sha256:26392ff2d3097c71d87c7ae835a8c470a9b36bd6260d8983ad1ab788203ad478`; its embedded report hash is
`sha256:ea7b720c37a029b13814eda7ad367b371bc9d2c22a665ea37d7cd29130fafcfa`. Main backup/restore, foundation and
business gates, API-only rollout with pilot 0, live bundle/security checks and exact cleanup passed.

## Native table captions, numbering and references (Roadmap 279)

Select any table cell and choose **Beschriftung …** to add or edit a literal caption. A captioned table receives a
restricted stable `tableId`; removing the caption removes that destination identity. The visible label
`Tabelle N: …` is derived from the order of captioned tables and is not stored. Table and figure inventories number
independently, so editing either sequence never rewrites the other or an existing reference.

The existing **Querverweis …** dialog lists bookmarks, figures and tables in one collision-free inventory. References
store stable destination IDs. Deliberate jump selects the target table locally. Removing a referenced caption leaves
visible inert text and a disabled jump action. The server independently enforces both-or-neither attributes, ID
grammar, uniqueness across all destination kinds, literal caption limits and the bounded table inventory.

Caption add, edit and removal are isolated undo steps. Saved versions, comparison, independent copies, search,
reviews and suggestions retain the table node and identity. Editor and print derive labels from the same inventory;
print emits semantic `table`/`caption` markup and a document-local destination. The complete 398-case desktop/mobile
matrix, full Python quality, responsive screenshots and two tagged one-page A4 PDFs passed. The PDFs contain exact
captions and a local link, with no JavaScript, form or external action.

Fresh recovery into `collabio_work_e2e_279_restore` verified 506 documents, 1,013 exact Office versions, 160
multi-version documents and 1,118 source objects. The five legacy/add/reorder/broken/reset table-caption versions,
canonical legacy hash, all earlier fixtures, authoritative ACLs and foreign-tenant denial passed. Main backup/restore,
both release gates, API-only rollout with pilot 0, live bundle/security checks and exact cleanup passed. Free document
fields, cross-document references, backlinks and DOCX interchange remain separate.

## Native figure captions, numbering and references (Roadmap 278)

An existing document-owned image can be marked as a numbered figure in the image dialog. Numbered figures require a
non-empty literal caption and receive a restricted stable `figureId`; unnumbered legacy captions keep their exact
stored shape. The visible label `Abbildung N: …` is derived from current document order and is not stored. Moving a
figure therefore preserves its identity while all visible numbers update. Turning numbering off removes only the
destination identity and preserves the caption.

The existing **Querverweis …** workflow lists bookmarks and figures in one unambiguous target inventory. References
store the stable destination ID rather than the current number. Deliberate jump selects the target image locally.
Removing a referenced figure leaves visible inert text and a disabled jump action; it never guesses a replacement or
opens a URL. Bookmark and figure IDs may not collide.

The server independently validates ID grammar, uniqueness and the required caption. History, comparison, copies,
search, reviews and suggestions retain the image node and stable identity. Editor and print derive labels from the
same ordered inventory. Print emits semantic `figure`/`figcaption` markup and a fixed document-local destination;
resolved references become local PDF links and broken references remain inert.

Focused schema/model tests, the complete desktop workflow and the combined 18-case desktop/mobile figure, image and
bookmark regression are green. Full quality passed Ruff, formatting for 799 files, Mypy over 596 sources and complete
Pytest. Two complete browser/model runs passed 394/394 in 31.2 and 29.0 minutes. Desktop/mobile screenshots and actual
one-page A4 PDFs passed independent visual review; both PDFs are tagged, contain the exact reordered captions and one
local destination link, and contain no JavaScript, form or external action.

Fresh recovery into `collabio_work_e2e_278_restore` verified 503 documents, 1,002 exact Office versions, 157
multi-version documents, 1,107 source objects, 50 image assets/77 saved image references, 10 review threads/18 events
and 11 suggestions/seven decisions. The five legacy/add/reorder/broken/reset figure versions, canonical legacy hash,
exact ACLs, foreign-tenant denial and every earlier fixture passed. Main backup/restore, both release gates, API-only
rollout with pilot 0, live asset/security checks and exact cleanup passed. Table captions, arbitrary page fields,
cross-document references, backlinks and DOCX interchange remain separate.

## Native bookmarks and internal cross-references (Roadmap 277)

Place the caret in a paragraph or heading and choose **Lesezeichen …** to insert a named document-local destination.
Selecting its visible chip enables rename or removal. Names contain 1–64 visible characters, are unique without regard
to case, and remain separate from the stable restricted identifier used by references. A document supports at most 100
bookmarks. Renaming therefore preserves references; removing a bookmark deliberately leaves them as visible broken
references instead of guessing a replacement.

Select explicit text and choose **Querverweis …** to target one existing bookmark. **Zum Lesezeichen springen** is the
only navigation action. It changes the editor selection and scroll position without changing browser history, opening
a URL or issuing a request. A cross-reference cannot overlap inline code or an external link. Insert, rename, remove
and reference changes are isolated undo steps and persist only through the existing confirmed CAS save.

The server validates exact atom/mark shapes, identifier grammar, unique IDs/names and resource limits independently of
the browser. History, comparison, copies, search/replacement, reviews and suggestions retain the native node and mark
positions. Print output emits a fixed document-local fragment and semantic internal anchor only while the destination
exists; broken references remain inert text. The five-version recovery fixture covers legacy, add, stable-ID rename,
broken target and reset. Automatic captions, page fields, cross-document references, backlinks, URL previews and DOCX
interchange remain separate.

Full Python quality and all 389 browser/model cases passed. Desktop/mobile dialogs and actual one-page PDFs passed
visual review; each PDF contains exactly one local destination link and no external action. Fresh recovery verified
the exact legacy/add/rename/broken/reset sequence, all prior fixtures and authoritative ACLs. Main backup/restore,
both release gates, API-only rollout, live verification and exact cleanup passed. See CURRENT_HANDOFF.md for hashes.

## Safe explicit hyperlinks (Roadmap 276)

Select text and choose **Link …** to add or replace an absolute HTTPS target or a simple `mailto:` address. The same
dialog removes an existing link without deleting text. **Link bewusst öffnen** is the only navigation action; Collabio
does not autolink, follow redirects, fetch previews or open a target when content is loaded, selected or printed.

Targets are limited to 2,048 characters and validated independently by client and server. Credentials, HTTP,
JavaScript/data/file schemes, whitespace, controls, backslashes, markup delimiters, multiple mail recipients and
prebuilt mail query parameters are rejected. The editor renders fixed `noopener noreferrer` attributes. Link changes
are isolated undo steps and remain local until confirmed CAS Save. History, comparison, copies, search/replacement,
reviews and suggestions preserve exact text and target boundaries; inline code cannot also be a link.

Printing creates semantic inert anchors from the saved validated target without a network request. Bookmarks,
cross-references, automatic recognition, URL metadata, tracking rewrites, arbitrary fields and DOCX interchange remain
separate. Full Python quality and all 384 browser/model cases passed. Desktop/mobile PDFs retain a semantic HTTPS
annotation without application chrome; independent PDF inspection and responsive dialog review passed. Fresh recovery
verified the exact legacy/add/edit/remove sequence, all prior fixtures and authoritative ACLs. Main backup/restore,
both release gates, API-only rollout and live verification passed. See CURRENT_HANDOFF.md for exact hashes and counts.

## General sections and section-owned page profiles (Roadmap 275)

**Abschnitt einfuegen** starts a new printed page at the current valid root boundary. Its responsive dialog captures
the complete following-section profile: A4 or Letter, orientation, one/two/three text columns, four margins, literal
header/footer and page-number mode. Selecting the visible marker enables editing or removal. Apply, edit and removal each form one isolated undo
step; only confirmed CAS Save persists the change. A document supports at most twelve markers. Leading, trailing,
nested, adjacent and page-break-adjacent markers are rejected.

The document root owns the first section and each `sectionBreak.attrs` owns the next one until another marker.
Profiles are complete rather than inherited, which keeps history, comparison, independent copies and recovery
deterministic. Page numbering continues across the whole document. The root first-page profile remains limited to the
document's first page. A Roadmap-482 four-page Chromium probe verified that a named `@page …:first` selector still
matches only the first page of the complete document: the first page of the second named section received its general
header. Per-section first-page metadata therefore remains rejected until a separately proven segmented render-and-
merge path can guarantee the result. Number restarts retain the same architecture boundary.

Printing assigns fixed ordinal wrappers to twelve trusted static named-page rules. Each segment also receives exactly
one validated column token; manual page breaks retain the active section count and section markers switch to their
complete profile. Only validated enum/dimension values, escaped literal text and fixed page counters enter CSSOM. No arbitrary CSS, HTML, URL or field expression is
accepted. Desktop/mobile tests verify responsive controls and exact save/history behavior. Real PDFs verify an A4
portrait first page followed by a Letter landscape page with the section header/footer and `Seite 2 von 2`.
Fresh recovery binds legacy, one-section, two-section and reset versions. See ADR-0098 and CURRENT_HANDOFF.md.

## First-page headers, footers and page-number visibility (Roadmap 274)

In **Seite ...**, enable **Abweichende Kopf-/Fußzeile verwenden** to give the first page its own
literal header and footer. The adjacent checkbox shows or hides only the first page number; later
pages retain their real numbers, so hiding page one leaves page two as **Seite 2**. Separate previews
show page one and following pages before Apply. Turning the option off restores inheritance; the
existing running-content reset removes the general and first-page profile together.

Optional `attrs.running.firstPage` contains exactly `header`, `footer` and boolean `showNumber`.
Its absence preserves every ADR-0096 document byte-for-byte and inherits general running content.
Empty first-page strings intentionally suppress inherited text. History, comparison, independent
copies and exact recovery retain the nested metadata. Printing uses the trusted static
`@page office-document:first` rule and clears all four margin boxes afterward. Four independent
three-page PDFs verify distinct first-page content, hidden and shown first-page numbering, and
continued pages 2/3 on desktop and mobile. See ADR-0097 and CURRENT_HANDOFF.md.

## Headers, footers and page numbers (Roadmap 273)

Within **Seite ...**, expand **Kopf-/Fußzeilen und Seitenzahlen**. Enter up to 64 Unicode
characters per literal header/footer and choose no numbers, **Seite X** or **Seite X von Y**.
The illustrative preview shows example page 1 of 3. Active top/bottom regions require at least
16 mm of the corresponding saved margin; validation explains this before applying changes.
Apply changes geometry and running content in one guarded undo transaction. Cancel/no-op stays
clean, and the separate running-content reset preserves geometry. Explicit empty metadata is
preserved by no-op reads; reset removes optional root attrs.running. Reset in one group survives subsequent edits in the other. Only confirmed Save persists.

History, comparison and independent copies retain the exact metadata. The freshly authorized
print source supplies the repeated text and real browser page counters. Additional browser-dialog
headers/footers should be disabled to avoid duplicate output. Unsupported margin-box engines
refuse this output with an explanatory message. Temporary text-bearing CSS rules are cleared
after output, errors, close and context changes. Text is escaped as literal code points; no HTML,
URL, arbitrary CSS or document fields are interpreted. First-page exceptions are implemented above;
general section variants remain separate work. See ADR-0096 and CURRENT_HANDOFF.md for validation.

## Document-owned page settings (Roadmap 272)

**Seite ...** opens paper, orientation, one/two/three text columns and four margin fields with a proportionate preview.
Supported values are A4/Letter, portrait/landscape, the three fixed column counts and integer margins from 5 to 50 mm.
Cancel and unchanged values leave the draft clean. Apply retains the current selection and
pending character formatting, validates the complete document and creates one isolated undo
action. Reset removes optional metadata and restores A4 portrait with 18 mm margins.
Read-only/history, pending or uncertain saves and changed identity contexts stay guarded.

Optional root `attrs.page` belongs to the exact document version, alongside any named styles.
Legacy documents remain byte-for-byte unchanged; history, comparisons and owned copies retain
the settings. Only the existing confirmed CAS Save makes them durable. The continuous editor shows the geometry with
responsive padding and renders the document-wide two-/three-column flow when no section marker is present. Compact
editing collapses to one column for usability; saved print output retains the exact count. Independent section flows
remain exact in print and visible in their marker/dialog because the continuous editor does not promise exact
on-screen pagination.

Print starts from the freshly authorized saved settings. Paper/orientation overrides apply
only to that print session; **Dokumenteinstellungen** restores the saved choices. The four saved
margins feed a named page rule through the trusted local stylesheet's CSSOM, using only validated
enums and numbers. Final printing reauthorizes content and images. CSP remains unchanged.
Actual PDF geometry, exact document/section columns and a separate four-version legacy/custom/second-profile/reset recovery
fixture passed acceptance, together with full quality and one complete 345-case run on 800a3a5.
Eight PDFs/16 pages, both release gates, API-only rollout and live checks passed. See [ADR-0095](../../ARCHITECTURE_DECISIONS/ADR-0095-native-office-page-settings.md)
and CURRENT_HANDOFF.md. Headers/footers and continuous pagination remain separate. See ADR-0155 for the bounded
column contract and its current validation evidence.

## Document-owned images (Roadmap 268)

**Bild einfuegen** opens file selection and preview for a saved editable document. Explicit upload accepts PNG,
JPEG, safe SVG and bounded EPS up to 8 MiB, 4096 pixels per axis and four million decoded pixels. The isolated decoder
returns only normalized RGBA pixels; original filenames, EXIF and original files are not retained. SVG alpha and the
unpainted EPS canvas remain transparent in the canonical PNG. An upload belongs to the current document
but does not advance its saved version. A new document must be saved once before its first upload.

The dialog supports bounded width/height, aspect lock, left/center/right alignment, literal alternative text and
caption, moving the whole image, removal and cancellation. Decorative images require an explicit choice. Insertion
and property edits change the local draft in isolated undo groups; confirmed CAS Save creates the immutable version.
Keyboard selection and responsive controls remain available. The first slice uses in-flow block images. Roadmap 269
adds cropping below; Roadmap 270 adds bounded paragraph text wrapping. Arbitrary floating anchors, shared media
libraries and other object types remain separate.

Each node binds exact parent, asset and source-version IDs, content/manifest hashes and pixel dimensions. The asset
inherits its current authoritative parent document ACL; independent asset grants do not authorize access. Every
content fetch and final print rechecks access. Revocation during an image fetch clears the protected workspace.
Save validates all referenced bytes under the tenant write lock. Create/reuse freshly authorizes each source parent
and copies the normalized bytes into independently owned assets. Replays return the committed rewritten manifest.
Ordinary Save rejects cross-document references. History retains exact renditions; removal never deletes old assets.

At most 40 images can occur in a document and 200 uploads can be retained per document. Retention-aware orphan
cleanup is a separate confirmed lifecycle workflow. PostgreSQL metadata transactions cannot roll back S3 PUTs;
existing reconciliation still applies. Printing freshly loads and decodes every exact rendition and aborts on an
unavailable image. Short-lived authenticated blob URLs never enter stored native JSON and are revoked on close.

The credential-free `office-image-decoder` Compose service has no network, uses a non-root read-only filesystem,
drops all capabilities and bounds memory, CPU, child processes, output and decode time. It rejects SVG active content
and external resources before invoking pinned CairoSVG, and accepts only EPSF with a finite bounding box before
invoking pinned Ghostscript in `SAFER` mode for one page. Only a shared Unix socket connects the API. The test profile
owns a separate socket volume. Start it with the `office-images` profile before image traffic; missing decoder access
fails closed. No SQL migration is introduced.
Decision: [ADR-0091](../../ARCHITECTURE_DECISIONS/ADR-0091-native-office-images.md). Development acceptance and the
fresh document-plus-asset recovery proof are recorded in CURRENT_HANDOFF.md; ordinary admission remains closed.

Decision for vector import: [ADR-0132](../../ARCHITECTURE_DECISIONS/ADR-0132-native-office-vector-image-import.md).
Generic PostScript, SVG scripts/events/entities/stylesheets/external references, animated vectors and retained source
vectors remain outside the allowlist. EPS has no partial-alpha model; only its unpainted canvas can become transparent.

## Non-destructive image cropping (Roadmap 269)

**Bild zuschneiden** expands the image dialog with the original image, a visible selection rectangle, exact pixel
fields and **Ganzes Bild wiederherstellen**. Drag selects a rectangle; arrow keys move it one source pixel and Shift
moves ten. Numeric fields provide a keyboard-only alternative for both size and origin. Preview updates locally.
Aspect lock follows the chosen rectangle and adjusts display height within existing limits; unlocked display sizes
remain unchanged. Cancel discards all changes, and Apply creates one isolated undo action in the current draft.

The optional native `crop` contains exactly integer x/y/width/height within the normalized source dimensions. Reset
omits it, preserving legacy canonical bytes. No new rendition, endpoint, dependency, decoder behavior or SQL migration
is needed. Original normalized bytes, hashes and ownership remain unchanged. Saved versions retain their exact crop;
comparison describes its geometry, independently owned copies preserve it and browser print clips the same rectangle.
Cropping is presentation, not redaction: authorized readers can still retrieve the complete normalized source image.
The dialog states this explicitly. A pre-crop reader cannot safely read cropped versions; disabling new writes must
retain compatible historical reads. Fresh ACL checks, confirmed CAS save and all ordinary admission gates remain.

Decision: [ADR-0092](../../ARCHITECTURE_DECISIONS/ADR-0092-native-office-image-cropping.md). Full quality and actual PDF
raster/semantic/responsive review passed. Passing evidence covers all 303 distinct browser/model cases via the 302/303
full attempt plus the corrected 57-case helper suite, explicitly not a single all-green full run. Fresh PostgreSQL/S3
recovery verified 488 documents, 913 versions and 43 image assets, including reset immediately after crop of the same
owned rendition. Both release gates, API-only rollout and live/cleanup checks passed. Ordinary admission remains
closed. Evidence is in CURRENT_HANDOFF.md; Roadmap 270 / PLANS 131 adds bounded image text wrapping below.

## Image text wrapping (Roadmap 270)

The image dialog adds **Textumfluss**: own paragraph, image left/text right, or image right/text left. A bounded integer
**Abstand zum Text** sets 0-48 CSS pixels. The local preview uses sample text and the same layout rules; changing or
canceling fields performs no save. Apply is one context/selection-bound undo action. **Eigener Absatz** removes wrap
metadata, while the ordinary alignment controls the block fallback. Moving the image moves its ordered anchor.

Following top-level paragraphs flow beside the image; headings, lists, tables, quotes, code, rules and the next image
begin below it. Wrapping reserves at most 45% of the text column and scales the image's display height to at most 480px.
Captions remain inside the image width. Columns of 480px or less and nested images inside lists, quotes or table cells
use block layout, preserving stored dimensions, crop and wrap choices. Resizing a view never changes the document.

Optional native `wrap` has exactly `side` (left/right) and integer `gap` (0-48). Absent metadata preserves legacy bytes;
explicit API null, CSS strings, other coordinates and unknown keys are rejected. Versions, comparison, history and
owned copies retain these exact values. No new endpoint, asset, migration, dependency or decoder change is introduced.

Printing uses the physical page's text column, independently of the device viewport. Image and caption request staying
together; a figure fitting a page moves to the next page when insufficient room remains. Following text can start on
the preceding page and continue beside that figure. Over-page captions may still
fragment according to browser rules. Arbitrary page positioning and DOCX anchors remain separate. Fresh recovery must
verify consecutive left/right/reset versions of the same owned rendition without changing crop or source pixels.
Decision: [ADR-0093](../../ARCHITECTURE_DECISIONS/ADR-0093-native-office-image-text-wrapping.md). Full quality and one
complete 313-case browser/model run passed on 1d8a58f. Actual PDF/visual review, fresh nonempty recovery, both release
gates, API-only rollout and live/cleanup checks passed. Recovery verified 426 documents, 829 Office versions and
32 image assets, including consecutive left/right/reset versions of the same cropped rendition. Each actual PDF
has three A4 pages with intact left/right images, complete text and no text/image overlap. Detailed evidence is in
CURRENT_HANDOFF.md; ordinary tenant/pilot/indexing/engine admission remains closed. Explicit native page breaks are
completed below as Roadmap 271 / PLANS 132.

## Anchored image layers (Roadmap 289)

Images can remain in normal flow or use a bounded anchor in front of or behind text. The optional native `position`
contains exactly `layer` (`front` or `behind`), normalized horizontal `x` (0–1000) and vertical offset `y`
(-1200–1200 CSS pixels). It is mutually exclusive with text wrapping; unknown keys, active CSS, booleans, fractions
and out-of-range values fail before persistence. Omitting the property restores normal flow and preserves legacy
canonical bytes.

The anchor stays visible and accessible above either layer. Pointer/touch dragging and arrow keys change one bounded
undo transaction; Shift uses a larger keyboard step and numeric fields provide exact coordinates. Horizontal
normalization keeps the complete figure inside the current text column across paper and viewport sizes. Comparison,
immutable history, independently owned copies, printing and isolated recovery retain the exact position. This logical
document anchor does not claim absolute physical-page placement or continuous editor pagination.

Decision: [ADR-0106](../../ARCHITECTURE_DECISIONS/ADR-0106-native-office-image-layers.md). Acceptance evidence is
recorded in CURRENT_HANDOFF.md; ordinary tenant, pilot, indexing, cloud-AI and DOCX/engine admission remain closed.

## Bounded image transforms (Roadmap 290)

Images optionally store exactly one quarter-turn rotation and explicit horizontal/vertical mirror booleans. Invalid
angles, matrices, CSS, unknown keys and explicit identity defaults fail before persistence. A 90/270-degree responsive
frame exchanges the reserved width and height while the normalized rendition and non-destructive crop remain intact.
Captions and alternative text stay outside the transformed visual.

The image dialog provides rotation and both mirror axes with immediate preview. Apply is one undoable draft change;
reset omits the optional property. Comparison, immutable history, independently owned copies, print and isolated
recovery retain exact orientation. The complete 42-case image matrix covers desktop/mobile geometry and all earlier
upload, crop, wrap, layer, ACL, copy and PDF behavior.

Decision: [ADR-0107](../../ARCHITECTURE_DECISIONS/ADR-0107-native-office-image-transforms.md). Acceptance evidence is
recorded in CURRENT_HANDOFF.md; arbitrary angles, wrap contours, physical page anchors and DOCX interchange
remain separate.

## Bounded native image groups (Roadmap 291)

Roadmap 308 adds **Bild duplizieren** for a selected ungrouped native image. The server revalidates current document
write access and immutable source bytes, then creates a fresh document-owned asset/version. Only a complete response
with fresh identities and the same normalized pixel hash and dimensions inserts the copy after its source. Numbered
copies receive fresh figure IDs. Wrapped presentation remains exact; freely positioned copies retain their layer and
move by a bounded 40/24-unit offset that reverses near an edge. The insertion is one undo step, save remains
explicitly confirmed, and failed or stale requests leave the draft unchanged. Fresh recovery verifies copied bytes,
receipts, distinct asset/version/figure identities and the bounded position offset.

Roadmap 307 adds **Bildgruppe duplizieren**. A dedicated write-authorized endpoint revalidates every current
document-owned member and creates fresh asset/version identities atomically. The editor inserts a fresh group directly
after the source only after the complete response validates; numbered members also receive fresh figure identities.
Ordered normalized pixels, content hashes and presentation remain exact, while group, image and retained-asset limits
fail before draft mutation. Insertion is one undo step, save remains explicitly confirmed, and failed or stale requests
leave the draft unchanged. Fresh recovery verifies the copied assets, receipts, bytes and distinct identities.

Roadmap 306 adds **Bildgruppe entfernen** for a selected native image group. At activation, the editor resolves the
stable validated group ID against the current document and removes that complete node in one isolated undo
transaction. Undo restores exact group identity, member order, layout, gap and all immutable asset/version, crop,
transform, alternative-text, caption and figure attributes; redo removes it again. Other document nodes and retained
source assets remain unchanged. Missing, stale and read-only targets fail closed, and the removal becomes durable
only through the existing confirmed version save. Earlier immutable versions and static print retain exact content.

Two through eight existing native images can form one `imageGroup` block. A document admits at most 20 groups. Each
group has a unique opaque identifier, exact member order, `row` or `stack` layout and an integer gap from 0 through
48 pixels. Nested groups, active attributes, unknown keys, duplicate identifiers and grouped images with wrapping or
free positioning fail before persistence. Existing image asset, crop and transform contracts remain unchanged.

The image dialog groups with an adjacent image, extends an existing group, changes layout/gap and dissolves the group.
Removing a member from a two-image group unwraps the survivor; moving a member moves the complete group. The labelled
group control selects the group node itself and derives the first member for editing, which stays stable across
Undo/Redo. Every command is one undo unit and only confirmed CAS Save persists it. Comparison, immutable history,
print and independent copies preserve the exact group and member order; copies still own separate image assets.

Wide row groups use equal columns and compact row groups collapse vertically. The complete 47-case image matrix keeps
all prior upload, crop, wrap, layer, transform, ACL, copy and real-PDF behavior green. Fresh recovery proves exact
row/gap-12, stack/gap-24 and dissolved versions of the same three assets, including receipts and current ACLs.

Decision: [ADR-0108](../../ARCHITECTURE_DECISIONS/ADR-0108-native-office-image-groups.md). Freeform canvases, nested
groups, shapes, connectors, wrap contours, physical page anchors and DOCX drawing-group interchange remain separate.

## Explicit native page breaks (Roadmap 271)

**Einfügen → Seitenumbruch** and **Ctrl/Mod+Enter** insert a visible, selectable boundary. The editor renders that
boundary as a full-sheet canvas gap with both paper edges and a **Seitenwechsel · neue Seite** label, so desktop and
compact layouts visibly separate the preceding and following sheets without claiming automatic print pagination. The
post-review responsive page-break and A4/Letter PDF suite passed 10/10 on commit `dc6722dc`.
At a caret in a top-level paragraph or heading, insertion splits the text and preserves
both fragments' paragraph attributes and inline marks. A selected root image, rule or
table remains intact; insertion occurs after it. Text ranges and insertion inside lists,
quotes, code or table cells are rejected. Removing a selected marker through the menu
or Delete/Backspace, or deleting it from the adjacent text boundary, preserves surrounding
blocks. Insertion and removal each form an isolated undo step. Current read-only,
historical, pending-save and document-size guards apply on every action.

The native leaf is exactly `{"type":"pageBreak"}`, only at document root depth, with
at most 100 per document. Attributes, marks, content and unknown fields are rejected.
Legacy documents retain their canonical bytes. Search, review anchors and text suggestions
count the leaf as one native position; comparison identifies its exact ordered boundary.
History and independently owned copies preserve the leaf without rewriting neighboring blocks.

The print renderer contains preceding image floats before starting the following content
on a new physical page. Markers are visible in screen preview; their labels and borders are
absent from printed output. Repeated markers at one boundary coalesce. A trailing marker
alone adds no final blank page; leading markers separate the printed title from body content.
This does not add blank-page commands, section layouts or a continuously paginated editor.
Paper/orientation settings remain print-session choices. DOCX remains a separate lane.

Decision: [ADR-0094](../../ARCHITECTURE_DECISIONS/ADR-0094-native-office-page-breaks.md).
The designated recovery fixture has three consecutive versions: legacy, two explicit
boundaries, and exact reset. Fresh isolated PostgreSQL/S3 verification checks every source,
receipt, immutable version, current ACL and the fixture's exact canonical bytes/lineage.
Implementation acceptance and runtime evidence are recorded in CURRENT_HANDOFF.md.
Full quality passed; all 325 distinct cases are covered by a 324/325 full run and a corrected
12/12 subset, not a single all-green full run. Four actual PDFs/14 pages, fresh nonempty
451-document/896-version recovery, both release gates, API-only rollout and live checks passed.
The subsequent Roadmap 272 page settings are completed above; next is Roadmap 273 headers/footers and page numbers, ahead of CRM.

## Document-owned format styles (Roadmap 267)

The **Formatvorlagen** control opens a single dialog for choosing, naming, previewing and applying a reusable
paragraph style. Body, title and heading presets provide starting values. The separate **Texttyp** selector controls
semantic paragraph/heading structure. A document owns at most 20 named definitions; each name is literal, unique and
1–60 Unicode characters. Definitions contain only existing bounded font-size/color and paragraph presentation values.

Applying a style binds the selected supported paragraphs, including list/table paragraphs, and clears their direct
paragraph values. Inline character marks remain overrides. **Nur Vorlage aktualisieren** changes every paragraph
bound to that definition; the dialog reports the affected count. Direct paragraph overrides still win, and choosing
Standard in the paragraph dialog restores inheritance. Removing a binding preserves the catalog and text. There is
no cross-document style library or catalog-deletion workflow in this slice.

The optional root `attrs.styles` and paragraph/heading `styleId` are strict additive native v1 metadata. Invalid
definitions/references/placements and excess canonical bytes fail before mutation. Legacy canonical bytes remain
unchanged. Actions bind editor/session/context/revision/document/selection/pending marks and use one isolated undo
group. Only confirmed CAS Save persists an immutable version. History, independent document reuse, comparison
(including unused definitions) and actual browser print resolve the version-owned catalog. Direct format transfer
continues to transfer direct values only. No SQL table, endpoint, dependency, cloud or engine admission is added.

Decision: [ADR-0090](../../ARCHITECTURE_DECISIONS/ADR-0090-native-office-named-styles.md). Acceptance and fresh nonempty
recovery evidence are recorded in CURRENT_HANDOFF.md. The proposed follow-up for native images and inert versioned
objects is [OFFICE_IMAGES_AND_OBJECTS_CONCEPT.md](OFFICE_IMAGES_AND_OBJECTS_CONCEPT.md); that insertion workflow is
not implemented or activated by the format-style slice. Full quality and the single 280-case matrix passed on 1e09a10; actual PDF, responsive visual checks, fresh nonempty recovery and release gates passed before API-only rollout. See CURRENT_HANDOFF.md for exact evidence and closed admission boundaries.

## List levels and numbering (Roadmap 266)

The **Listenebenen und Nummerierung** button beside the list buttons opens options for an editable caret or text
selection within one nearest list. Indent puts selected sibling items under their preceding item. Outdent raises
them one level, or into paragraphs at the outer level, retaining contained sublists and document text/formatting.
An ordered list also exposes a start value from 1 through 1,000,000 for the entire current list at that level.
Other lists remain unchanged. Numbering continuity and named numbering styles are outside this slice.

Alt+Shift+Right/Left and, outside tables, Tab/Shift+Tab use the same validated level actions. Table Tab navigation
keeps precedence. Unsupported list selections cannot fall through to a default list keymap; unavailable Tab actions
leave via a reachable toolbar control. Mixed lists, code, whole-document and cell selections are excluded.

Actions preserve pending typing marks and form one undo group separated from typing. Cancel, invalid input and no-op
stay clean. The existing complete schema/size/depth preflight validates each candidate before dispatch. Dialogs bind
the editor, session, context, revision, document, selection and pending marks; a change invalidates the action.
Current read/history/busy/uncertain/review/suggestion guards and explicit confirmed CAS saving remain mandatory.

This uses existing native list nodes/start attributes, without a new backend, endpoint, dependency, SQL migration
or durable format. Roadmap 263 recovery/release evidence remains retained; no new recovery drill or activation is
claimed. Decision: [ADR-0089](../../ARCHITECTURE_DECISIONS/ADR-0089-native-office-list-editing.md). All twelve focused cases, full quality and all 264 browser/model cases passed on fb8dbd3; desktop/tablet/mobile visual review passed. API rollout and closed-gate evidence is in CURRENT_HANDOFF.md.

## Format transfer (Roadmap 265)

The **Format übertragen** menu captures direct character and paragraph presentation from an editable caret or a
uniform selection. It supports bold, italic, underline, strike, font size/color and alignment/line/before/after spacing.
Choose **Format aufnehmen**, select a target, then apply characters, paragraphs or both. The sample stays available
for another target until explicitly discarded or the document is remounted/closed or the context changes. It contains
only normalized presentation values and ownership references in memory; no text, system clipboard or browser storage
is copied. Mixed sources are rejected with guidance; there is no silently chosen first style.

An absent value means the standard direct format and clears that target property. Text, heading levels, lists, tables,
code and unselected content remain intact. Character-only transfer can affect exact Unicode ranges or marks for the
next typed text at a caret; paragraph-only transfer retains pending character choices. Selected table cells use their
exact ranges. Copy, discard and no-op stay clean. One document application forms one undo group, separated from typing.
The full schema/size preflight runs before dispatch, including the canonical-byte limit. Current editable-session and
review/suggestion guards remain mandatory. Only the separate confirmed CAS Save persists a result; old versions remain
immutable. Reader and historical views cannot capture or apply a format.

This is direct formatting, not a named style or computed browser CSS. Block types, code and cross-document libraries
remain outside the slice. There is no backend, dependency, schema, migration or durable-format change. Retained Roadmap
263 recovery applies to the unchanged format; a new recovery drill is not claimed. Decision:
[ADR-0088](../../ARCHITECTURE_DECISIONS/ADR-0088-native-office-format-transfer.md). Final validation and deployment evidence
is recorded in the current handoff.

On mobile, comment and suggestion drawers occupy the viewport between the app bar and footer independently of the
wrapping formatting toolbar. Their own close actions remain reachable; history/outline retain their original placement.

All 40 initial formatting/keyboard cases passed on 068152f. After correcting the mobile layout found by the first
full run, all 43 responsive/transfer cases passed on ac70c29 in 235.258831 seconds. The final single 252-case matrix
(209 browser + 43 model) passed on that same source in 908.294889 seconds, with zero skipped, unexpected or flaky
results. Full Python quality passed; root reviewed final transfer desktop/tablet/mobile and mobile comments. Initial
failed reports remain retained. API-only rollout and closed-gate verification passed; see the handoff for exact evidence.

## Whole-document keyboard replacement (Roadmap 264)

Ctrl+A or Cmd+A inside the editor selects every structural boundary, including a final table and selections started
inside a cell. Typing, plain-text paste, Backspace, Delete, Enter and cut across the whole document use an explicit
confirmation when tables are present. The candidate replaces complete top-level nodes with plain paragraphs and is
validated before confirmation and again before dispatch. Empty replacement leaves one editable paragraph. Cancel or
Escape keeps the original content and selection. Cut copies plain text immediately; removal still requires confirmation.

Chromium's native replacement can mutate table NodeViews before the normal text-input handler runs. A cancelable
beforeinput handler prevents that mutation; structural AllSelection and a single validated transaction avoid invalid
intermediate tables. The schema/character/node/depth/canonical-byte guard remains unchanged. Session, editor, revision,
document, selection and editability checks invalidate stale confirmations. One confirmed replacement is one undo step,
separate from adjacent typing; undo restores table structure, paragraph attributes and character marks. Saved versions
remain immutable, and only the separate confirmed CAS Save persists the draft. Reader and historical views stay closed.

Ten focused browser cases cover rich, table-only and multiple-table documents, Unicode/literal text, multiline paste,
cancel, undo/redo, real version writes, size/control rejection, cut, Ctrl/Meta selection, reader/history gates and context
changes. The previously isolated history case now owns a rich head ending in a table and confirms replacement before
checking document/review/suggestion draft preservation. Clipboard cases dispatch browser ClipboardEvents with synthetic
DataTransfer objects; they do not claim an operating-system clipboard roundtrip. No IME or non-Chromium proof is claimed.
This is a UI-only change without a new endpoint, dependency, schema or durable format. Roadmap 263 recovery remains
retained; no new recovery drill is required or claimed for this slice. Final acceptance is recorded in the current handoff.
All 26 focused keyboard/table/history cases passed in 94.556794 seconds on 460d632. Full quality and the complete
241-case matrix (198 browser and 43 model cases) passed on d7270a7 in 873.553288 seconds for the browser/model run,
with zero skipped, unexpected or flaky results. Root reviewed desktop/mobile confirmation screenshots; no independent
subagent or new PDF review is claimed. This single green matrix supersedes the combined acceptance method of Roadmap 263.

## Character formatting (Roadmap 263)

The selection-aware **Zeichen …** dialog chooses font sizes (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36 or
48 points) and named text colors (black, slate, red, dark orange, green, teal, blue or purple). It formats selected
text, including nested headings/list/quote/table content, or the next typed text at a supported caret. Code is excluded.
Mixed properties stay unchanged until chosen; Standard removes a property. Reset prepares both defaults for Apply.
Cancel/no-op stays clean, caret choices alone do not save or dirty content, and selection edits form one undo group.

The optional `textStyle` mark contains one or both strict attributes `fontSize` and `textColor`. Unknown properties,
CSS strings, empty attributes, nulls, invalid placements and code combinations are rejected. Existing legacy canonical
bytes and native v1 identifiers remain unchanged. No endpoint, SQL migration or dependency is added; rollback editors
must understand the mark before allowing edits. Fixed data attributes/CSS serve editor and print. Comparison names the
exact size/color, and replacement preserves full mark-attribute boundaries. Existing source versions, review offsets,
suggestion acceptance, confirmed CAS saves, current rights and memory-only drafts remain authoritative.

Decision: [ADR-0087](../../ARCHITECTURE_DECISIONS/ADR-0087-native-office-character-formatting.md).
Full Python quality passed on `a0b3001`, including Mypy on 562 sources; 362 focused Python checks also passed.
Product code remained unchanged through test-only `75f381a`. Passing coverage includes all 231 distinct cases
(188 browser and 43 model): the full run retained 230 passes and a history-fixture input failure, then the complete
eight-case history suite passed after giving that case its own starting document. Both raw reports remain retained;
this is not a single 231-pass run. No guard or assertion was weakened. Whole-document keyboard replacement across
rich tables was left as a separate usability follow-up and is addressed by Roadmap 264 above.

Root reviewed six Office/Work screenshots and both actual PDF pages. The A4 portrait PDF preserves sizes/colors,
all 24 numbered paragraphs and both sentinels, with 2,108 extracted characters and H1/H2/P structure; no empty pages.
Fresh complete recovery verified 460 documents, 935 saved versions and 1,045 source objects. All three designated
character versions passed (legacy plus two saved profiles), alongside paragraph, review and suggestion evidence.
Current ACLs, exact source/receipt bindings and read-only restored services passed. Both release gates passed;
operational details are maintained in the [current handoff](../CURRENT_HANDOFF.md).

## Paragraph formatting (Roadmap 262)

Roadmap 262 completes paragraph formatting under
[ADR-0086](../../ARCHITECTURE_DECISIONS/ADR-0086-native-office-paragraph-formatting.md). Four optional paragraph/heading attributes select alignment,
unitless line spacing and before/after spacing in points. Missing values retain the existing presentation; strict
validation preserves exact old payloads. A selection-bound dialog, format-aware comparison and safe print rendering
share the allowlist. Development validation and fresh paginated nonempty recovery passed; operational rollout evidence
is maintained in the [current handoff](../CURRENT_HANDOFF.md).

Select text or place the cursor inside a paragraph, then choose **Absatz …**. The dialog also handles headings,
list/quote paragraphs and exact selected table cells. Mixed values remain unchanged until selected; **Standard**
removes one explicit property and **Standard wiederherstellen** prepares removal of all four. Apply changes only the
local draft, creates one undo step and returns focus to the editor. Applying identical values leaves the draft clean.
Headings, keyboard shortcuts, Enter, find/replace and independent saved-version reuse preserve allowed attributes.
Historical views, readers and pending/uncertain saves keep formatting disabled; current access and explicit confirmed
CAS saves remain authoritative. Comparison labels explain format-only changes, including their nested location.

Alignment is left/center/right/justify; line spacing is 1, 1.15, 1.5 or 2; before/after spacing is 0, 6, 12, 18 or 24 pt.
The browser omits only its null defaults. Server validation never rewrites legacy payloads, hashes or receipts.
These attributes extend native JSON without a new SQL migration, dependency or endpoint. A rollback editor must
understand the attributes before allowing edits of formatted documents.

Acceptance on `8b61d8d` passed full Ruff, formatting across 712 files, Mypy across 557 sources and complete Pytest,
with only the known Starlette/AnyIO warning. All 215 browser/model checks passed in 759.313613 seconds: 176 browser
and 39 model cases, zero skipped, unexpected or flaky, preserving all previous 200 checks. Also passed: 294 focused
Python checks and 46 focused browser/model checks. Independent code review and all six final Office/Work screenshots
found no material issue. The actual A4 PDF has three nonempty pages, all 28 numbered paragraphs, 5,233 extracted
characters and H1/H2/P structure. Independent review of all three rendered pages found no clipped content or unexpected
page breaks; this does not claim PDF/UA certification.

Fresh paginated PostgreSQL/S3 recovery verified all 330 documents, 666 exact saved versions and 721 source objects,
including three designated paragraph fixture versions: one unchanged legacy version and two formatted versions.
Legacy canonical hashes, exact receipts, current ACLs, foreign-tenant denial and read-only restored services passed;
review and suggestion histories and accepted result versions remained valid. Foundation and business release gates
passed. This completes Roadmap 262 / PLANS 123 development without ordinary-tenant or production admission.
API rollout, live verification and cleanup details belong to the [current handoff](../CURRENT_HANDOFF.md).

Ignored evidence is under `e2e/work/artifacts/roadmap-262/`. Final matrix report:
`sha256:b9d422791168a5f1a8dc710eb1574a28fe373a928c44c11227bbd981380d71a6`;
quality log: `sha256:e60159bdafa33d3854347d8fdf6fc5f55bc4bb87c630f8e6ebdbefe6240d358c`;
synthetic recovery report: `sha256:bfc720ee2ec275061c5f934369a5864259071d5409f7bd4f99368b431951c7f7`.

## Older saved-version history (Roadmap 261)

The existing versions endpoint gains bounded page_size and cursor parameters. Default calls keep a 200-entry page;
the UI requests 50 saved versions and exposes older-version, refresh and retry controls in history and comparison.
Pages follow the immutable previous_version_id chain, including equal timestamps. The first page fixes a history head;
later pages also report the freshly read current head so concurrent saves can be shown without shifting that chain.
Every page requires current parent role/ABAC and typed ACL access. Cursors bind document, tenant, actor, roles, page size
and continuation; they grant no permission and expire on service restart under the current single-worker deployment.

Opening history retains a discussion or suggestion composer; returning resumes its exact version-bound draft.
Document/context changes and explicit close still require the existing discard confirmation. Appending preserves
comparison selections/results and local document, discussion and suggestion drafts. Refresh adopts
new history metadata only after validation, while previous exact comparison selections remain separately labelled when
outside the new window. Fresh content reads still authorize comparison and takeover. Errors distinguish retryable
failure, invalid cursor requiring refresh and actual access denial; late responses cannot repopulate closed contexts.
Hiding history, switching tabs or entering focus mode cancels pending history reads and restores their confirmed status.
No schema, durable format or new endpoint is introduced. See
[ADR-0085](../../ARCHITECTURE_DECISIONS/ADR-0085-native-office-history-pagination.md).

Focused backend verification on `0bdd522` passed 249 Python/API/PostgreSQL checks in 40.58 seconds. On `46a83b4`,
all 23 focused browser checks passed in 94.693441 seconds: ten new history-pagination cases and thirteen existing
version-workflow cases, with zero skipped, unexpected or flaky results. Root and independent desktop/tablet/mobile
visual review passed. Actual Uvicorn logs contained 63 list and 110 history access records with query/cursor values
redacted. Focused report: `sha256:ef46cb8c44612e6dcb6261f784d42a5dbfbeaca1e1bf9604e3f6869bf5e464b3`.
Full quality and all 200 checks passed on `46a83b4` at 2026-09-21 14:24:43 UTC: Ruff, formatting across 705 files,
Mypy across 551 sources and complete Pytest, with only the known Starlette/AnyIO warning. The matrix passed in
688.743181 seconds: 165 browser and 35 model cases, zero skipped, unexpected or flaky. Root and independent review
passed all five final screenshots. Actual Uvicorn logs at 14:25:11 UTC verified 322 list and 205 history access records
with query/cursor values redacted. Final report:
`sha256:926b3a0c808d6baed3c65d904257cabc85996da6eb956f58eb5d7d03fb747e79`;
quality log: `sha256:296215f2c5250e1199918099f88565806f30b1a49276e818f457b312e1508025`.
The API-only rollout reached healthy at 14:25:53 UTC (`1585ccedc940`). Live verification at 14:27:03 UTC confirmed
thirteen Office OpenAPI operation definitions, history page_size/cursor parameters, new and existing controls, local
assets/licenses, Work navigation and no-store/CSP; it did not execute all thirteen operations. Tenant-demo Office
remains unprovisioned with a non-cacheable 404; Office features, KB write and pilot remain closed.
Cleanup completed healthy at 14:27:43 UTC: six remaining exact E2E containers were removed, the disposable runner was
already absent, and postgres-test/postgres-restore/minio-restore were stopped. Collabio remained running(3), with
unchanged loopback ports 8000/5433/29000/29001. Main PostgreSQL `87a6b37942c8`, MinIO `98ce365f455b`, Webcut running(7)
and provider services were unchanged; Tricert was absent. Roadmap 261 development is complete. No main-database
migration, new recovery drill, ordinary-tenant write, indexing, cloud provider or engine activation occurred.
Roadmap 257 recovery evidence remains retained; these checks grant no ordinary-tenant or production admission.

## Document discovery (Roadmap 260)

The document list searches all currently readable titles on the server and loads results in pages of 50 through
the existing `GET /v1/office/documents` operation. Optional `query`, `page_size` and `cursor` parameters extend its
contract; the default page remains 200 for existing callers. Responses add `has_more`, `next_cursor` and `page_size`,
without a total count or query echo. Title queries are bounded literal lowercase substring matches; `%`, `_` and
backslashes have no wildcard meaning. Current ABAC and typed ACL checks precede the page limit and lookahead.

Results use creation time and object ID descending so saves and renames do not move entries across page boundaries.
Concurrent title/permission changes remain visible on later reads; this is not a frozen snapshot. Refresh discovers
newly created entries. Authenticated cursors bind tenant, actor, roles, query and page size and expire when the current
service instance restarts. The current deployment has one API worker; no shared multi-worker cursor-key setup is claimed.

Search and next-page loading never select a document, replace content or use page membership as authorization.
An explicit refresh rechecks the exact opened saved version and updates its write capability while preserving local
document, review and suggestion drafts. Actual access denial clears protected state; transient failure preserves drafts
and offers retry. Historical takeover and suggestion acceptance authorize their exact source through fresh content
responses, independently of a filtered page. Existing confirmations, version checks and exact save retries remain.

List query text and cursors do not enter audit metadata or ordinary Uvicorn access records. No new schema, persistence,
index, dependency or endpoint is introduced; existing Roadmap 257 recovery evidence is retained, not rerun.
The existing Work-to-Office link is also visible in compact mobile navigation; its destination and access checks are unchanged.

Focused development verification on `5bcb7d2` passed all ten discovery browser checks in 46.602456 seconds, with zero
skipped, unexpected or flaky cases. The fixture uses 225 genuine PostgreSQL/S3 documents under a separate synthetic
author and grants a dedicated reader only the three oldest entries. Checks cover complete unique pagination despite a
saved rename, literal Unicode/wildcard/markup titles, ACL filtering before limits, preserved document/review drafts,
fresh write revocation and read denial, query/context cancellation, a lost genuine list response with exact cursor retry,
invalid/cross-role cursors and desktop/tablet/mobile controls. All three viewport screenshots passed independent review.
The first focused run on `e304b28` passed nine cases and exposed the hidden mobile Work link; the product fix preserves
the original real-click assertions. Inspection of 51 actual list access records confirmed query/cursor redaction.
Focused report: `sha256:663d6370c40b38e432000b458ea2f7fb662121fd3a0be3b19ddfdf2b59e42c03`.
Full verification on the same immutable `5bcb7d2` completed successfully at 2026-09-21 13:01:19 UTC: Ruff, formatting
across 699 files, Mypy across 547 sources and full Pytest passed, with only the known Starlette/AnyIO warning.
All 190 checks passed in 651.284899 seconds: 155 browser cases and 35 model cases, zero skipped, unexpected or flaky.
All previous 180 checks remain included. Independent review passed the three Office discovery and two Work screenshots.
Inspection at 13:01:29 UTC confirmed query/cursor redaction in 306 actual list access records.
Final browser report: `sha256:f11d3d0e6130351760439eec1ea7e71ae85de1fe881d76d2df4c9eee0ac8b8ef`;
quality log: `sha256:627d7e5a71376e443db09d5bc78e953c86298b699d3df8a8b2e3feaba1fc446c`.
The API-only `--no-deps` rollout retained pilot 0 and reached healthy at 2026-09-21 13:03:04 UTC (`6751b0ddada8`).
Live verification at 13:04:01 UTC checked existing/new controls, the query/page-size/cursor contract, all thirteen Office
OpenAPI operation definitions, local assets/licenses, Work navigation and no-store/CSP. These are definition checks,
not execution of every operation. Ordinary Office remains unprovisioned with a 404; Office features, KB write and pilot
remain closed. Cleanup finished healthy at 13:04:19 UTC with only regular API/PostgreSQL/MinIO running, exact E2E services
removed and test/restore services stopped. Roadmap 260 development is complete. Main PostgreSQL and MinIO were unchanged;
no main-database migration or new recovery drill ran, and Roadmap 257 recovery evidence is retained. No ordinary-tenant
or production admission follows from this development evidence.
See [ADR-0084](../../ARCHITECTURE_DECISIONS/ADR-0084-native-office-document-discovery.md).

## Saved-version reuse (Roadmap 259)

"Als neues Dokument" starts an independent draft from the opened saved current or historical version. The dialog
shows the saved title and version/date label and offers an editable title. Unsaved editor changes are not used; existing
discard consent protects document, review and suggestion drafts before a replacement. Canceling keeps the original
workspace; no reuse reads begin before that decision, and reuse itself never writes. Closing during pending reads
aborts them and prevents late adoption. Discard approval only gives consent: source content and drafts remain
untouched until the subsequent fresh reads and staged editor validation all succeed.

After that decision, fresh exact-version content and then the authoritative creation capability are read through
the existing APIs. Source read access is sufficient when the user can create documents; source write access is not
required. The bounded document list does not decide source visibility. Busy, uncertain and conflicting saves are blocked;
close, context and session changes invalidate pending responses. Transient failures preserve the workspace.

The new draft has no source identity, history, ACL, discussions, suggestions or mutation key. Its first explicit save
uses the normal create operation, with a new object and creator ACL. Source content and history stay unchanged. The
draft's initial save and exact retries apply current create rights. For text-only reuse, the independent draft does
not reauthorize its former source at that later point. Roadmap 268 image references additionally require a fresh
source-parent read check during first Create and copy their normalized assets into the new document; exact replay
returns those committed assets. There is no persisted provenance link. The original Roadmap 259 slice added no API,
schema, storage format, dependency or engine admission. See
[ADR-0083](../../ARCHITECTURE_DECISIONS/ADR-0083-native-office-saved-version-reuse.md).

## Saved-version print preview (Roadmap 258)

"Drucken / PDF" or Ctrl/Cmd+P opens a preview only for a clean saved version, including a historical version or an
ordinary reader's document. Write permission is not required.
It reads the exact selected version afresh on opening and again before the explicit browser print/PDF action; current
parent ACLs and the read feature apply both times. The historical title comes from that version, not the current head.
Unsaved changes, new documents and unresolved saves cannot enter the workflow. No draft is implicitly saved or discarded.

A4/Letter and portrait/landscape are selectable temporary view settings. "Erneut laden" clears the preview and reads
that same version again. "Drucken / als PDF speichern" performs the final fresh read before opening the browser dialog.
The continuous preview shows typography and width;
the browser print dialog determines pagination, destination and final settings. Users may choose its PDF destination
where supported. The application does not receive proof that a print or PDF save completed. Existing metadata-only
version-read audits remain unchanged; there is no server export endpoint or export-completion receipt.

An allowlisted DOM renderer preserves supported native blocks, marks, list numbering, table headers, whitespace and
empty paragraphs and treats all text literally. Its semantic headings, paragraphs, lists and table header/data cells
remain available to browser PDF generation. During the browser call, the preview is temporarily nonmodal so the
separate print surface is not excluded as inert; modal state returns only for the still-valid print session.
PDF validation inspects actual structure dictionaries, not just a requested tagged-output flag. This does not claim
PDF/UA conformance or equivalent tagging, pagination or fidelity across browsers.
Print media isolates the prepared document from the editor, context, comments, suggestions and dialogs. Other browser
print entry points display neutral guidance; prepared content is cleared after the browser call, afterprint, close or
context invalidation. Fresh denial clears protected state; transient failures allow a fresh retry. No remote resource,
new dependency, durable record, DOCX engine or server PDF conversion is added. See
[ADR-0082](../../ARCHITECTURE_DECISIONS/ADR-0082-native-office-browser-print.md).

## Features and authoritative access

| Feature | Normal behavior | Default |
| --- | --- | --- |
| `office_documents.documents.read` | List authorized documents, open exact content, read/compare/print versions, discussions and suggestions | false |
| `office_documents.documents.write` | Create a document, save a successor or confirm review/suggestion actions under current parent rights | false |

The package is installed in the module catalog; migrations 0083–0085 neither provision nor enable an ordinary tenant.
Every route requires tenant context, an enabled module and the read feature. Writes also require the write feature and
explicit confirmation. Create requires `office-editor` or `tenant-admin`; save requires an explicit current write/admin
ACL on object type `office.document`. Role membership does not replace object authorization. Current PostgreSQL ACLs
and server-resolved ABAC scope are rechecked, including on replay and historical reads. JWT ignores browser grant headers.
Review mutations require that same current parent write/admin access; ordinary readers can read discussions but cannot
add, reply, resolve or reopen. The API supplies `can_create`, `can_comment` and `can_resolve`; the historical editor's
read-only state does not itself determine permission to discuss an existing thread.

| Route | Result |
| --- | --- |
| `GET /v1/office/documents` | Authorized heads and server-derived capabilities |
| `POST /v1/office/documents` | Create document and first immutable version |
| `GET /v1/office/documents/{object_id}/content` | Exact current or requested historical native content |
| `GET /v1/office/documents/{object_id}/versions` | Authorized metadata-only version history |
| `POST /v1/office/documents/{object_id}/versions` | Compare expected head and append a confirmed successor |
| `GET /v1/office/documents/{object_id}/review-threads` | Paginated version-bound discussion metadata and current capabilities |
| `POST /v1/office/documents/{object_id}/review-threads` | Confirm a discussion on the current saved version |
| `GET /v1/office/documents/{object_id}/review-threads/{thread_id}` | Paginated immutable events and verified anchor quotation |
| `POST /v1/office/documents/{object_id}/review-threads/{thread_id}/events` | Confirm reply, resolve or reopen against the expected thread revision |
| `GET /v1/office/documents/{object_id}/suggestions` | Paginated saved-text proposals with current capabilities |
| `POST /v1/office/documents/{object_id}/suggestions` | Confirm replacement text on an exact current saved selection |
| `GET /v1/office/documents/{object_id}/suggestions/{suggestion_id}` | Literal before/after text and immutable decision |
| `POST /v1/office/documents/{object_id}/suggestions/{suggestion_id}/decisions` | Confirm rejection or atomically accept and save a successor |
| `POST /v1/office/documents/{object_id}/images` | Explicitly upload and normalize a document-owned PNG/JPEG without changing its head |
| `GET /v1/office/documents/{object_id}/images/{asset_id}/{version_id}` | Read exact normalized PNG bytes under the current parent ACL |

Content and error responses use `no-store`. Invalid JSON/schema errors do not echo submitted content. Storage/database
failures use constant messages. The UI uses local assets under a restrictive CSP, retains drafts after transient failures
or stale-head conflicts, clears content when access is denied, preserves exact retry keys and drops late responses after
closing or changing context. Only connection context,
never content or credentials, is stored in browser localStorage.

## Saved text suggestions (Roadmap 257)

Roadmap 257 adds explicit saved-text proposals, described in
`ARCHITECTURE_DECISIONS/ADR-0081-native-office-text-suggestions.md`. The fourth inspector tab shows original and
replacement text, author, exact anchor version and disposition. Empty replacement deletes text; the server derives
the quotation and preserves unaffected formatting. Proposals and decisions are immutable COMMENT sources with
receipts under migration 0085. Acceptance requires an unchanged current head and saves its decision and new document
version in one PostgreSQL transaction; rejection saves only the decision. Old anchors remain on their original version.
Every mutation rechecks current parent rights and write features and requires explicit confirmation. Exact retries,
memory-only drafts and current read-only capabilities use the existing Office boundaries. Remote verification and
nonempty recovery of accepted/rejected proposals passed; exact evidence is recorded below.

## Version comparison and local takeover

Roadmap 253 extends the existing five APIs without another persistence model. Users explicitly select two saved
versions in the history dialog and load their comparison. Both exact source versions are read through the normal
authoritative content route; no stored browser copy substitutes for a new authorization check. The comparison is local
and uses literal text, showing added, removed, changed and unchanged document blocks plus both saved titles. It detects
format/structure differences even when visible text is unchanged. Tables and lists retain readable row/cell/item
boundaries. Large comparisons use bounded alignment work and paginated rendering without silently dropping blocks;
an approximate alignment is labelled. It is a block comparison, not tracked changes or automatic merging.
The history route keeps a default 200-entry page; Roadmap 261 adds older-page navigation as described above.
A connected partial history is accepted and labelled; relative labels do not invent absolute version numbers for older unloaded entries.

An authorized reader may compare but cannot take over content as a successor of the same document without write access.
Taking a historical version into a draft
refreshes its exact content, the current head and current document capabilities. The new draft uses historical content
and title while preserving the fresh head as its expected save base. Current write permission is required; historical
write capability alone is insufficient. No POST occurs until the existing explicit save confirmation. The original
versions remain immutable. An intervening save produces the ordinary CAS conflict and preserves the draft.

Comparison selection changes, close, context switches and superseding editor operations invalidate pending responses.
Access denial clears protected state; a temporary read failure clears partial comparison output but preserves the
existing draft. Cancelling the discard decision preserves edits. Unsaved takeover content stays only in memory, and
unchanged content/title does not manufacture a dirty version. No schema, retention, backup format or engine permission
changes. Existing migration 0083 and exact-version recovery contracts remain applicable.

## Find and replace

Roadmap 254 extends search within the already opened native document. Search terms and replacement text are literal;
no regex syntax, markup evaluation, global search index or network lookup is involved. Matching uses original UTF-16
positions, including text split by formatting marks. Case-insensitive matching uses Unicode simple case folding;
it does not expand sharp-s to `ss` or normalize accents. Whole-word matching treats Unicode letters, numbers, combining
marks, connector punctuation and join controls as word characters. Matches do not cross paragraph, hard-break, list-item
or table-cell boundaries. All matches are counted and navigable; only a labelled window of highlights is rendered.

Current or all replacements affect only the local draft and form one undo step separated from adjacent typing.
Untouched text keeps its formatting; replacement text takes the first matched character's marks. Empty replacement
deletes the selected text while preserving structural nodes. Identical replacement leaves content and undo state alone.
Size, character, node and depth limits are checked before changing the editor. Read-only or historical documents may
be searched but not replaced; loading, saving, restoration and an uncertain save also block replacement. Search inputs
are memory-only and cleared with the workspace/context. The existing confirmed CAS save alone persists a successor.

Ctrl/Cmd+F opens the search field; Ctrl/Cmd+H focuses replacement. Enter/Shift+Enter move forward/backward and Escape
closes the panel and returns focus to the editor. A 200-match highlight window follows the active match while the
count/navigation/replacement set stays complete. If a replacement removes the final match, keyboard focus remains in
the replacement field. Loaded content is excluded from undo history; undoing the first actual edit returns to the
loaded version instead of erasing it. Search/case/whole-word settings are reset when the panel or workspace closes.

## Contextual table editing

Roadmap 255 adds table controls to the native editor. The existing quick insertion creates a three-by-three table;
custom insertion accepts row and column counts and an optional header row. Context controls insert rows above/below
or columns before/after the selection, toggle the first row as a header and select cells, rows, columns or the table.
Removal requires a separate explicit confirmation and changes only the local draft. Cancellation preserves content,
selection and undo history. Existing versions are never removed by these controls.

Tables retain the existing rectangular format, at most 200 rows and 20 columns, without merged cells or column widths.
Prospective commands are checked against the native schema and complete document resource limits before dispatch.
Each structural edit forms one undo step, separated from adjacent typing. Keyboard movement between cells and row
creation at the table end use the same bounds. Focus returns to the editor for continued input.
If a new row cannot be added, Tab moves focus to an available control instead of trapping the keyboard in the last
cell. At tablet widths, the inspector closes when entering the compact layout; users can explicitly reopen it.
The table controls hide while find/replace is open, preserving space for the document.

Read-only and historical content cannot be edited. Loading, saving, historical takeover and an uncertain save also
block table changes. Pending table dialogs are invalidated when the document or context changes. Only the existing
confirmed CAS save persists changes as a new version. No schema, dependency, endpoint or storage change is introduced.

## Review discussions (Roadmap 256)

The Comments inspector shows discussions for the opened saved version. Users may comment on that entire version
or select text within one paragraph/inline run, including across formatting marks. The server derives the quotation
from the exact saved source and validates UTF-16 positions; selections across hard breaks, paragraphs or cells are
rejected. New anchors require a clean current saved version. No marker is added to document JSON or undo history.
An active text highlight is shown only while the editor still displays that exact unchanged version.
Comment and reply text is limited to 4,000 Unicode code points; selected quotations to 2,000. Bodies, quotations,
authors and other display fields render as literal text, without interpreting markup, links or remote resources.

Replies, resolving and reopening use their own explicit confirmation and thread revision, with current parent-document
write/admin rights and the existing write feature. Historic document text stays read-only, but existing discussions
can still receive authorized review actions. A resolved thread must be reopened before another reply. Discussions
never move automatically to a newer text version. Opening the newer version therefore shows its own discussions;
the history view remains the explicit route to comments on an earlier version.

The inspector has Gliederung, Versionen and Kommentare tabs. Desktop places the comments alongside the document;
compact layouts use an explicitly opened, closable overlay. Each thread identifies its source version, quotation,
status and revision. Opening a thread loads its contributions; locating a text anchor revalidates the exact saved
content before selecting it. Threads and events load in pages of 20 with explicit controls for further pages;
the API permits up to 50 entries per page. Loaded counts do not imply an unrequested complete history.

A single memory-only composer holds the pending comment or reply. Each create, reply, resolve and reopen has a
separate confirmation showing its action, version and content. Cancellation sends no mutation. Document save,
version/context changes and closing a comment draft require a discard decision when text or an uncertain attempt
would otherwise be lost. Editing the document invalidates a pending new anchor without silently deleting the comment
text; existing discussions remain bound to their saved source. Loading, saving, takeover and uncertain document
saves restrict comment actions, while current API capabilities govern discussion rights.

An uncertain write preserves the entire command and mutation reference for an explicit retry. A 409 retains the
comment draft and requires fresh thread or version state before another attempt. A successful mutation is acknowledged
before its thread is refreshed, so a later read failure does not cause a duplicate write. Refresh clears old thread
bodies before reading again. Closing, context/version changes and superseding requests invalidate late responses;
authorization denial clears protected document and review state. Comment bodies, quotations and retry payloads are
never saved in browser localStorage. Comment actions neither create a document version nor enter text undo history.

Migration 0084 creates `office.review_threads` and append-only `office.review_events`. Event bodies and quotations
live in bounded canonical COMMENT SourceObjects: object ID is the thread, version ID the event, parent the document.
Each event binds source content/manifest/receipt hashes, author, time, ACL snapshot, actor-scoped mutation reference,
command hash and resulting state. Quotes and bodies do not enter normal logs or audit metadata. The same tenant
write lock as document saves serializes fresh ACL checks, document/thread CAS and source/receipt writes.

New threads require the expected current document head; later events use the expected thread revision. An exact retry
is authorized afresh before replay, even if its revision has since advanced. A reused reference with different content
conflicts. Reads validate source metadata, canonical bytes and event/anchor bindings before returning content. There
is no independent comment ACL, deletion/editing, automatic reanchoring, notification sending or new search index.
See `ARCHITECTURE_DECISIONS/ADR-0080-native-office-version-bound-reviews.md`.

## Records, retention and recovery

Migration `0083_office_native_documents.sql` creates `office.documents` and `office.document_versions`. Heads carry
tenant/object identity, owner/creator, timestamps, internal classification, `rp-standard`, Legal Hold state, lifecycle,
KMS reference, source system and schema version. Version rows bind source identity, content/manifest hashes, exact
write-receipt hash, creator and mutation reference; they are append-only. The head changes only to a validated successor.
Immutable shared SourceObjects carry the exact canonical JSON bytes and full security metadata in versioned S3 storage.

The initial slice accepts ordinary internal saved versions under the shared retention/KMS contracts. It does not implement
classification changes, Legal Hold administration, record declaration or deletion; unsupported source state fails closed.
Existing hold/retention and compliance workers remain independent of normal module availability. No new deletion bypass,
index, AI provider or server export path is created. Drafts are transient and have no claim of crash recovery.

A creator ACL is inserted atomically with the head. Versions, source metadata, receipts and head updates share one database
transaction. A tenant advisory lock precedes S3 PUT and stale-head validation. An unexpected database failure after PUT
can leave a detectable orphan object; PostgreSQL rollback is not a cross-system rollback claim.

Backup covers all six Office document/review/suggestion tables, current ACLs, module/features, migration state, trigger functions, narrow column grants,
source metadata/receipts and exact S3 versions. Restore must validate forced RLS, append-only versions, creator ACL trigger,
source binding, document/review head guards, proposal/decision/result bindings and the deferred decision requirement
against the complete function bodies in migrations 0083/0084/0085, even when source and target have the same unexpected
drift. Disabled normal features do not stop backups or compliance recovery. The isolated nonempty recovery proof must
preserve native content, review events for all four operations, proposals and accepted/rejected decisions, exact saved-version
anchors, accepted result content/title/lineage, source/receipt hashes, historical reads and current ACL behavior.
Roadmap 252's completed recovery below does not cover the new review tables. Roadmap 256 has separate verified
backup, nonempty document/review restore and foundation evidence, recorded in its acceptance section below. Roadmap 257
adds its separately verified proposal/decision recovery and migration 0085 foundation evidence.

## Foundation acceptance evidence (Roadmap 252)

Domain, PostgreSQL and API tests cover strict content limits, authoritative access, CAS races, exact idempotency,
failure rollback, orphan detection, safe errors and module gates. Full backend quality on `7bba74f` passed Ruff checks
and formatting across 665 files, Mypy across 526 source files and the full Pytest suite.

The final browser run on `5917bdf` passed all 73 cases in 160.237 seconds, with zero skipped, unexpected or flaky tests.
The previous 60 Work/KB/CRM cases remain green. Thirteen Office cases cover actual rich-text/table authoring, confirmed
saves, reopen and historical reads, concurrent conflict, read-only access, forged/foreign grants, ACL revocation, feature
removal, pre-PUT and read failures, idempotent retry after a lost successful response, literal markup and delayed
close/context responses. Desktop, tablet and mobile screenshots were visually reviewed. The earlier complete run's
toolbar-focus failure was fixed in `5917bdf` and the existing rich-authoring test now checks immediate focus restoration.

The nonempty recovery proof on `5917bdf` verified 13 Office documents, 18 versions, five documents with multiple versions
and an inventory of 37 source objects, including exact content, historical reads and current ACL behavior. Its report is
`sha256:e61e7a26da539fa5a974a4faff62c31eb68502bd5c30f8f941df3effc2ae4cda`.
Migration 0083 has been applied to the main development database. The foundation gate passed with 83 migrations,
91 tables and `office_document_controls_verified=true`. The existing three-slice business release gate also passed
without business writes or tenant activation. The API-only development rollout returned healthy; final live checks
and cleanup are recorded in the operations log and current handoff.

All browser and nonempty Office recovery data use the isolated synthetic tenant `tenant-work-e2e`, real PostgreSQL/S3
and fresh ACL resolution. No ordinary tenant was enabled; the normal pilot switch, indexing and DOCX engine gates remain
closed. These results complete Roadmap 252 / PLANS 113 as a product foundation, not a production or real-user admission.

## Version workflow acceptance (Roadmap 253)

Implementation `3aa0069` passed full remote Ruff checks/formatting (665 files), Mypy (526 source files) and Pytest.
The focused 27 checks passed, followed by the complete 100-check matrix in 249.923 seconds: 88 browser cases and
12 pure comparison-model cases, with zero skipped, unexpected or flaky results. All previous 73 browser cases remain.
The model suite checks bounded alignment, semantic mark/key ordering and complete ordered projections for long text,
large unique/repeated blocks and duplicate edit patterns. Browser proof covers exact version/title/format/table changes,
read-only access, fresh-head takeover, confirmed successor lineage, later CAS conflict, current ACL/feature removal,
cancelled discard, transient storage failure and late close/selection/context/takeover responses. A partial history
window uses three real saved versions and one reduced metadata response. Identical takeover creates no dirty version.
Desktop, tablet and mobile screenshots passed visual review.

Final report: `sha256:42448945e2d326b56552c886d3603d69d1dcaf4d416ca4c727bf2e66e3ce8859`.
Evidence lives under ignored `e2e/work/artifacts/roadmap-253/`; hashes and controlled API rollout are recorded in the
operations log and current handoff. No new schema, durable record, storage format or write API was added. Roadmap 252's
verified migration/backup/nonempty recovery/foundation/business proofs remain retained; they were not rerun for 253.

## Find/replace acceptance (Roadmap 254)

Implementation `f4c37e5` passed full remote Ruff/format (665 files), Mypy (526 source files) and Pytest; only the known
Starlette/AnyIO warning remains. All 32 focused checks passed after correcting an initial undo-history defect and one
case-sensitive test expectation. Loaded content is now explicitly excluded from history, so the first typed edit cannot
merge with document loading. The full matrix passed 132/132 in 291.588 seconds: 97 browser cases and 35 pure model cases,
zero skipped, unexpected or flaky. All prior 100 checks remain green. Twenty-three new model tests cover Unicode,
exact positions, format/run boundaries, literal/no-op replacement and limits, including 100,000 matches and preflight
rejection of explosive expansion. Nine browser runs prove actual save/reopen/immutable versions, undo/redo separated
from adjacent typing, full counts above 1,000, read-only/history, literal hostile markup, size/no-op/deletion behavior,
cancelled discard/context/late reads and responsive controls. Final desktop/tablet/mobile screenshots passed visual review.

Results: `sha256:e12cf71865e5a013852d6482b6a96a33d5a37c4c031157721d0d980324d32b71`, under ignored
`e2e/work/artifacts/roadmap-254/`. API rollout, cleanup and exact screenshot hashes are in the operations log/handoff.
No new schema, storage format, write endpoint or tenant capability; item 252 recovery proofs remain retained, not rerun.

## Table editing acceptance (Roadmap 255)

Implementation `e3cf88c` passed full remote Ruff/format across 665 files, Mypy across 526 source files and Pytest;
only the known Starlette/AnyIO warning remains. The focused run on `93cbd71` passed nine cases and failed one assertion
that used a control-enabled matcher on a disabled option. `a27c433` checks the native disabled property; all ten focused
cases then passed in 38.975 seconds. Visual review found the inspector obscuring the table on a desktop-to-tablet
resize; `e3cf88c` closes it on entry to compact layout and adds a visibility regression.

The complete matrix passed 142/142 in 359.156 seconds: 107 browser cases and 35 pure model cases, zero skipped,
unexpected or flaky. All prior 132 cases remain green. Eight new table workflows and two responsive runs cover real
save/reopen/immutable history, preserved marks and content, header/row/column/selection operations, isolated undo/redo,
immediate focus, removal confirmation and cancellation, keyboard navigation and bounded new rows, read-only/history,
pending and uncertain saves with retry, context invalidation, invalid insertion and canonical-byte overflow.
Final desktop/tablet/mobile screenshots passed visual review, including the corrected tablet transition.

Results: `sha256:89c132f192d7a3302ab3a48dc201dfdc0f60c007e8334c993e79be9f7df9d2d8`, under ignored
`e2e/work/artifacts/roadmap-255/`. No new schema, storage format, dependency or endpoint; item 252 migration/backup/
nonempty recovery/foundation/business evidence remains retained, not rerun. Live rollout is recorded in the operations log.

## Review acceptance and recovery (Roadmap 256)

Final Python quality on `2305a96` passed Ruff, formatting across 674 files, Mypy across 532 source files and full
Pytest; only the known Starlette/AnyIO warning remains. All 269 focused restore/recovery/backup checks passed in
23.40 seconds. The implementation had already passed ten focused review browser cases in 44.978 seconds.

The full matrix on `7400b35` passed 152/152 checks in 432.486 seconds: 117 browser cases and 35 model cases, with zero
skipped, unexpected or flaky results. All previous 142 checks remain green. The new review cases cover Unicode text
anchors, real confirmed create/reply/resolve/reopen, immutable document versions, historical discussions, ordinary
readers, forged/foreign/current-ACL denial, stale-revision draft preservation, identical storage-failure retries,
late close/context responses, clean-source requirements and fresh feature checks. Final desktop, tablet and mobile
screenshots were independently reviewed. The compact overlay deliberately scrolls; controls and literal text remain
contained. The initial full run's two browser response-observation failures and the unchanged upstream-response
buffering correction are retained in the operations log and ignored failed-run artifacts.

Browser results: `sha256:96f4a596d21e395073967745c1811448fdbc2e04bc7f2f7e20ae4e4075fe156f`, under ignored
`e2e/work/artifacts/roadmap-256/`. Final image hashes are recorded in the operations log.

Independent restore review led to `1cf9ee9` and `552b6b6`: the verifier binds all direct Office grantees and effective column grants,
legitimate owner rights, permitted runtime privileges and all nine canonical review CHECK definitions. Its grant
inventory includes unrelated grantees and MAINTAIN privileges. Thirty-seven added cases include three live PostgreSQL
grant-tamper cases with cleanup. `2305a96` corrects an older hash fixture to target the runtime role explicitly.
These changes strengthen proof verification; product/UI/schema behavior did not change after browser acceptance.

A fresh nonempty PostgreSQL/S3 recovery on `2305a96` restored 57 documents, 93 exact versions, 30 documents with
multiple versions and 129 total source objects. It verified nine review threads and 17 events, including three
selected-text anchors, one historical thread and one complete create/reply/resolve/reopen lifecycle. Exact source,
receipt and quotation bindings, current parent ACLs, foreign-tenant denial and read-only restored services passed;
`recovery_ready=true`. The proof is synthetic and contains no bodies, tenant activation or engine admission.

- Recovery report: `sha256:330a544deb64fbcb374d1c23732660cb7c2f80b8a2f2cc14289b8e2fa59fae92`, from
  `e2e/work/artifacts/roadmap-256/office-native-review-recovery-proof.json`.
- Verified synthetic backup: `sha256:3d9fe80e786c501967d30a5b1e75614cd55e60bfb46e815d926fcb2093e64af6`.
- PostgreSQL restore: `sha256:b7b56185c4a93b64a8dd6742cf4ff2148b05f6940984731796fe0f6313b78de4`.
- Exact-version storage restore: `sha256:796ea1bdda2a57739759d6092732750573eb2e2b0c315adc9d8e9c1765a2347f`.

Migration 0084 has been applied to the main development database. The foundation check passed with 84 migrations
and 93 tables, including the document/review controls. This evidence is separate from the retained migration 0083
proof and does not grant production or real-user admission.

Primary implementation is `office_reviews.py`, `office_review_repository.py`, the Office routes and UI, and migration
0084. API/domain/PostgreSQL tests and `office-review.spec.mjs`, `office-review-responsive.spec.mjs` cover the new
contract; `tests/office_recovery_proof.py` and the shared restore gate include review records. Ignored focused browser
artifacts are under `e2e/work/artifacts/roadmap-256/focused/`.

## Continuing Office work

Roadmap 258 / PLANS 119 has completed development validation with the print evidence below. Roadmap 257's verified
recovery remains retained; printing introduces no new persistence and does not claim a new recovery execution.
Roadmap 259 completed full quality, the 180-check matrix, independent final visual review and controlled API-only rollout.
Roadmap 260 adds paginated title discovery and completes full quality, the 190-check matrix and controlled rollout.
Roadmap 261 completes loading older saved versions for reading, comparison and takeover, preserving fresh parent
ACLs, connected history validation, selection and drafts. Focused checks, full quality, the 200-check matrix, API-only
rollout, live verification and cleanup passed. Roadmap 262 completes strictly bounded paragraph alignment and spacing,
preserving legacy canonical bytes and exact saved versions. Full quality, all 215 checks (176 browser and 39 model),
responsive/PDF review, complete paginated nonempty recovery and release gates passed. Operational details remain in
the [current handoff](../CURRENT_HANDOFF.md).
Roadmap 263 completes character sizes/colors with full quality, passing coverage of all 231 cases, actual PDF review,
fresh nonempty recovery and controlled rollout. The next usability investigation is whole-document keyboard replacement
across rich tables. The history fixture now owns its starting head; this does not claim to fix that input path.
Preserve confirmed document/review/suggestion writes, atomic accepted versions, exact version anchors, current access checks and
memory-only drafts. Continuous tracked changes and live collaboration remain future product work. Native Office continues before
further CRM expansion; DOCX fidelity, engine admission and interchange keep their separate gates. Ordinary tenant,
pilot, indexing and provider activation remain outside this implementation.

Previous Roadmap 256 rollout: the verified pre-/post-0084 backups, foundation and business release gates preceded the API-only rollout. Foundation
hash `sha256:4ee5691940bec2e1b2b48623bf8a671e67efaaa8232057a01e913c3ab820b4ce` and business release hash
`sha256:e8109c8e126d80fd4bd55f16a5c432e8841e5c44a374de654b8e1eaaa354faa4` passed without tenant activation.
Live checks verified all nine Office operations, comment controls, existing editor workflows, local assets and
no-store/CSP. The ordinary tenant remains unprovisioned with 404; Office features, KB write and pilot remain closed.
At 2026-09-18 13:14:20 UTC, API `da71b8ef4e53` was healthy, Collabio was running only API/PostgreSQL/MinIO and exact
test services were removed or stopped. Main storage and other projects were untouched. Backups, full hashes and
the retained synthetic restore database are recorded in the operations log and current handoff.

## Suggestion acceptance and recovery (Roadmap 257)

Full quality on `9c17a31` passed Ruff, formatting across 684 files, Mypy across 541 sources and full Pytest; only the
known Starlette/AnyIO warning remains. All 688 focused backend/API/PostgreSQL/recovery tests passed on `0d5350d` in
52.37 seconds. Ten focused browser runs passed in 50.1 seconds. The complete matrix on `9c17a31` passed 162/162 in
535.956 seconds: 127 browser cases and 35 model cases, zero skipped, unexpected or flaky. All prior 152 remain green;
final desktop/tablet/mobile screenshots passed independent visual review.

Independent review tightened the success-response anchor aliases, reserved acceptance-reference rejection before
public writes and recovery's preserved-title check. PostgreSQL tests prove one terminal racing decision, atomically
committed document/decision metadata, no loser PUT, rollback after either source write fails and detectable S3 orphans
after a post-PUT database failure. No distributed rollback is claimed. The restore verifier pins the new append-only
constraints, grants, source functions and deferred acceptance-decision requirement, including matching-drift rejection.

The new nonempty recovery restored 67 documents, 109 exact versions, 36 multi-version documents and 162 total sources.
It also verified nine review threads/17 events and ten text proposals/seven decisions: five accepted, two rejected and
three still open. Original/replacement bytes, source receipts, accepted result content/title/predecessor/actor, current
ACLs, foreign-tenant denial and read-only recovered services passed. This is synthetic development evidence.

- Recovery: `sha256:e1ab971a88c43ff06c12544ba24619731b2b8304908da53ab5b73ad8bb017c53`.
- Synthetic backup: `sha256:06bbf77f9e41db9a7ecbc525bf17fd3e69c08b8dac7840ade2e7f10ecb9f4160`.
- Synthetic PostgreSQL restore: `sha256:90799804fabe0ca577fd9f29b9cc2ed8ae409d44e7f802a0f216d7eed02f5839`.
- Exact-version storage restore: `sha256:3a74c8fe68490779ab65ec52099cac6b0262e7b01618df6c4d5a36db95e92e7b`.
- Browser report: `sha256:42317e268bb6cd56cff3d85615bc012aed06d28ccd88f99b62228cdc03168e47`.
- Quality log: `sha256:6b49b2f2fa706fd0d42baee0a72a19111e404f66309eca3a554830804cd19a21`.

Migration 0085 is applied to the main development database. Verified pre-/post-migration backups are
`collabio-20260921T071612Z.dump` (`sha256:ed83da613feb5792a209bf428630df302804dcfe377af9b89e1e58182de63a83`) and
`collabio-20260921T071618Z.dump` (`sha256:c937926687291d847cd07daaf36034a5318bead0c13926322ac3ba2035934aeb`).
The foundation passed with 85 migrations/95 tables, expanded Office controls and three existing main sources, with
seeding disabled: `sha256:f257c62d06ba81432a909f60161faba69c1d9e3db82f998c4cfdbd02c1294ffd`.
The existing CRM/Tasks/Time business gate passed without tenant activation or business writes:
`sha256:b14e152ee2355a82a1a22cb06457daac58fe2fa0149d32b8df31678e618dca63`.
Office's product recovery is the separate nonempty proof above.

API-only rollout reached health at 2026-09-21 07:17:41 UTC. Live checks verified thirteen Office operations, suggestion
and previous editor controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo remains unprovisioned with
404; Office features, KB write and pilot remain closed. Scoped cleanup finished healthy at 07:18:57 UTC with only
API/PostgreSQL/MinIO running. API is `b4e2756191a1`; main storage and other projects were unchanged. The synthetic
restore database and verified dump remain retained. Final ignored artifacts are under `e2e/work/artifacts/roadmap-257/`.

## Browser printing acceptance (Roadmap 258)

The complete matrix on `cf2244c` passed 170/170 checks in 562.233916 seconds: 135 browser cases and 35 comparison/search
model cases, with zero skipped, unexpected or flaky results. All prior 162 checks remain included. Full Python quality
passed Ruff, formatting across 689 files, Mypy across 541 sources and full Pytest; only the known Starlette/AnyIO
deprecation warning remains. The eight focused print runs had passed on `a9477d5` in 26.199 seconds.

Six new workflows and two responsive runs verify fresh exact-version reads before preview and browser printing,
historical titles and ordinary readers, literal native formatting, paper/orientation, dirty/busy/uncertain restrictions,
current ACL revocation, storage failures/retry, delayed close/context responses and isolated output. Final desktop,
tablet and mobile screenshots passed independent visual review. No browser test substitutes cached source content
or local permission claims for the real PostgreSQL/S3-backed API reads.

The browser callback generated actual PDFs from the same page while its freshly prepared print surface was active.
Independent Poppler/QPDF inspection verified a nine-page Letter-landscape rich document, a one-page A4-portrait
historical document and a one-page unprepared-print guidance document. The rich PDF contains all 80 numbered text
paragraphs and the final sentinel, literal markup, preserved whitespace and complete table content; no application
shell, context, comments or suggestions enter the prepared output. All PDF pages passed visual review, including
wrapped long code and repeated table headers. The guidance PDF contains no draft or document content.

Actual PDF structure dictionaries include heading/paragraph tags in both prepared documents, plus two lists/two list
items, one table, 20 header cells and 40 data cells in the rich fixture. The modal preview initially suppressed these
tags; the corrected implementation becomes nonmodal only during the browser call and restores the modal only for a
still-valid session. This proves the tested Chromium output, not PDF/UA certification, cross-browser fidelity, a
guaranteed page count for other documents, or completion of a user's print/save action.

- Browser report: `sha256:8198c66138af5af63d6d767ab9e8c4c06acaf18e60013809ed31879f39faa86f`.
- Quality log: `sha256:541ce600a21a8651c99c4cb0182b24c80f5f0b3132b161c7099ea4c164d4de1a`.
- PDF QA report: `sha256:598c1e210e3cb3f4920d78120b479d36f42bb8f8d8bfb6cf3677b61a3bedb63b`.
- Rich PDF: `sha256:15c5bb6c81b7fd75a9b53ad22e1c80496f3b34584ee6bc654a8133b0b7a13785`.
- Historical PDF: `sha256:3e6094137a2b1e78191b7ba08c01d970d0250c78f179f22904e5ac562f428a67`.
- Unprepared guidance PDF: `sha256:233a9b4e3b27324c3ed86362813b0fe5f8fa6cb8bbc37dcd9bd0f84eeb1cb495`.

Ignored artifacts are under `e2e/work/artifacts/roadmap-258/`, including `pdf-qa/report.json` and rendered pages.
The complete matrix's source is `cf2244c`; later `d8300aa` changes only test cleanup and is not the source of that
report. Its affected parallel-revocation case passed in 9.001 seconds. API-only rollout reached healthy at
2026-09-21 11:31:16 UTC; live controls, all thirteen operations and closed tenant gates passed. Cleanup finished
healthy at 11:32:51 UTC with only API/PostgreSQL/MinIO running; API is fc8312db43b7. Full host evidence is in
`docs/operations/DEV001_OPERATIONS_LOG.md` and `docs/CURRENT_HANDOFF.md`. No schema, durable record, dependency,
server export or ordinary tenant/pilot/index/engine admission changed.

## Saved-version reuse validation (Roadmap 259)

The focused run on `e7fec24` passed all ten reuse checks in 41.7 seconds: eight workflows and two responsive runs.
It uses real PostgreSQL/S3 reads and confirmed creates, including historical native formatting/title, a distinct new
object and first version, unchanged source history, independent creator ACLs and no copied reader grants, comments or
suggestions. A create-capable source reader succeeds without source write permission. Fresh source revocation denies
reuse; changing the create feature while discard consent waits preserves the dirty source after the fresh capability
check. Eventual create still applies current rights. Cancellation, transient reads, delayed close/context responses,
busy or unknown saves, literal titles and an identical retry after a lost successful create response are covered.

The initial `b4add9d` run passed 9/10. Its only failure was a synthetic table fixture without the explicit unit-span
attributes emitted by the existing editor serializer. `e7fec24` adds `colspan: 1` and `rowspan: 1` to those fixture cells;
the full deep-equality assertion remains unchanged and no product behavior was changed by that correction.
Initial desktop, tablet and mobile screenshots passed visual review.

Full verification on the same immutable source `e7fec24` passed all 180 checks in 664.306054 seconds: 145 browser cases
and 35 comparison/search-model cases, with zero skipped, unexpected or flaky results. All prior 170 checks remain.
Full Python quality passed Ruff, formatting across 691 files, Mypy across 541 sources and full Pytest; only the known
Starlette/AnyIO deprecation warning remains.

- Focused report: `sha256:95646616c21d7d1d140dfc05ddda7998e035551440cc5a74ef5a203711240385`.
- Full browser report: `sha256:9792822a6de9a37b6b92acd67805e3f52ae535ad63836a70be176d72ea8f3237`.
- Quality log: `sha256:f66e1d0bacac61ebd7625e182d4293791b5b1c4856bd466d6b0a6db0f65a5cfe`.
- Final desktop screenshot: `sha256:30606618ab192d770dc04d6a1e1ec3e24c5e58250703d33aa735c712cf841ca2`.
- Final tablet screenshot: `sha256:0f2adf14eca0cf9445f9c4051183e72f7855043fef27a9ebcbe8505d29d40b1a`.
- Final mobile screenshot: `sha256:1190b026f1d0f7ee0cbfab9d26573a137e56251528bd3f3b89299a82a14819f5`.

Final artifacts are under ignored `e2e/work/artifacts/roadmap-259/final/`. Independent review passed the final desktop,
tablet and mobile screenshots, with no clipping, horizontal overflow or unreachable controls.

The API-only `--no-deps` rollout retained pilot 0 and reached healthy at 2026-09-21 12:21:23 UTC; API is `a001838868f7`.
Live verification confirmed all thirteen Office OpenAPI operation definitions and checked new and previous controls,
local assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned with 404;
Office features, KB write and pilot stay closed.
Scoped cleanup finished healthy at 12:22:11 UTC with Collabio running only API/PostgreSQL/MinIO. Exact E2E services were
removed; test and restore services are stopped. Main PostgreSQL/MinIO and other projects were unchanged.

This completes Roadmap 259 / PLANS 120 development. The existing thirteen API operations, schema, storage and recovery
contracts remain unchanged; no migration was added. Roadmap 257 recovery is retained, not rerun. Full host evidence is
in the operations log and current handoff. No ordinary-tenant, pilot, indexing or engine admission is granted.
