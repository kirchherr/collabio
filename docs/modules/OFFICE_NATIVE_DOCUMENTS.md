# Native Office Documents

Status: Roadmap 252–271 development complete on dev001; ordinary tenant and production admission remain closed
Roadmap: 252 / PLANS 113 foundation; 253 / PLANS 114 version workflow; 254 / PLANS 115 find and replace; 255 / PLANS 116 table editing; 256 / PLANS 117 review discussions; 257 / PLANS 118 saved text suggestions; 258 / PLANS 119 browser printing; 259 / PLANS 120 saved-version reuse; 260 / PLANS 121 title discovery; 261 / PLANS 122 older-version history; 262 / PLANS 123 paragraph formatting; 263 / PLANS 124 character formatting; 264 / PLANS 125 whole-document keyboard replacement; 265 / PLANS 126 format transfer; 266 / PLANS 127 list levels and numbering; 267 / PLANS 128 document-owned format styles; 268 / PLANS 129 document-owned images; 269 / PLANS 130 non-destructive image cropping; 270 / PLANS 131 image text wrapping; 271 / PLANS 132 explicit page breaks
Module: `office_documents` / version 0.1.0
Decisions: `ARCHITECTURE_DECISIONS/ADR-0079-native-office-document-workspace.md`; `ARCHITECTURE_DECISIONS/ADR-0080-native-office-version-bound-reviews.md`; `ARCHITECTURE_DECISIONS/ADR-0081-native-office-text-suggestions.md`; `ARCHITECTURE_DECISIONS/ADR-0082-native-office-browser-print.md`; `ARCHITECTURE_DECISIONS/ADR-0083-native-office-saved-version-reuse.md`; `ARCHITECTURE_DECISIONS/ADR-0084-native-office-document-discovery.md`; `ARCHITECTURE_DECISIONS/ADR-0085-native-office-history-pagination.md`; `ARCHITECTURE_DECISIONS/ADR-0086-native-office-paragraph-formatting.md`; `ARCHITECTURE_DECISIONS/ADR-0087-native-office-character-formatting.md`; `ARCHITECTURE_DECISIONS/ADR-0088-native-office-format-transfer.md`; `ARCHITECTURE_DECISIONS/ADR-0089-native-office-list-editing.md`; `ARCHITECTURE_DECISIONS/ADR-0090-native-office-named-styles.md`; `ARCHITECTURE_DECISIONS/ADR-0091-native-office-images.md`; `ARCHITECTURE_DECISIONS/ADR-0092-native-office-image-cropping.md`; `ARCHITECTURE_DECISIONS/ADR-0093-native-office-image-text-wrapping.md`; `ARCHITECTURE_DECISIONS/ADR-0094-native-office-page-breaks.md`

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

## Document-owned page settings (Roadmap 272)

**Seite ...** opens paper, orientation and four margin fields with a proportionate preview.
Supported values are A4/Letter, portrait/landscape and integer margins from 5 to 50 mm.
Cancel and unchanged values leave the draft clean. Apply retains the current selection and
pending character formatting, validates the complete document and creates one isolated undo
action. Reset removes optional metadata and restores A4 portrait with 18 mm margins.
Read-only/history, pending or uncertain saves and changed identity contexts stay guarded.

Optional root `attrs.page` belongs to the exact document version, alongside any named styles.
Legacy documents remain byte-for-byte unchanged; history, comparisons and owned copies retain
the settings. Only the existing confirmed CAS Save makes them durable. The continuous editor
shows the geometry with responsive padding; it does not promise exact on-screen pagination.

Print starts from the freshly authorized saved settings. Paper/orientation overrides apply
only to that print session; **Dokumenteinstellungen** restores the saved choices. The four saved
margins feed a named page rule through the trusted local stylesheet's CSSOM, using only validated
enums and numbers. Final printing reauthorizes content and images. CSP remains unchanged.
Actual PDF geometry and a separate four-version legacy/custom/second-profile/reset recovery
fixture are required for acceptance. See [ADR-0095](../../ARCHITECTURE_DECISIONS/ADR-0095-native-office-page-settings.md)
and CURRENT_HANDOFF.md. Section layouts, headers/footers and continuous pagination remain separate.

## Document-owned images (Roadmap 268)

**Bild einfuegen** opens file selection and preview for a saved editable document. Explicit upload accepts PNG/JPEG
up to 8 MiB, 4096 pixels per axis and four million decoded pixels. The isolated decoder returns only normalized
pixels; original filenames, EXIF and original files are not retained. An upload belongs to the current document
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
drops all capabilities and bounds memory, CPU, child processes and decode time. Only a shared Unix socket connects
the API. The test profile owns a separate socket volume. Start it with the `office-images` profile before image
traffic; missing decoder access fails closed. No SQL migration or additional dependency version is introduced.
Decision: [ADR-0091](../../ARCHITECTURE_DECISIONS/ADR-0091-native-office-images.md). Development acceptance and the
fresh document-plus-asset recovery proof are recorded in CURRENT_HANDOFF.md; ordinary admission remains closed.

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

## Explicit native page breaks (Roadmap 271)

**Einfügen → Seitenumbruch** and **Ctrl/Mod+Enter** insert a visible, selectable boundary.
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
Next is Roadmap 272 / PLANS 133 document-owned page settings, ahead of CRM.

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
