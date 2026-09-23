# Current Project Handoff

Updated: 2026-09-23

Roadmap 272 / PLANS 133 is complete on dev001: document-owned A4/Letter, portrait/landscape and
bounded margins with preview/reset/isolated undo, immutable history/copies and saved print geometry.
Full quality and one complete 345-case browser/model run passed. Eight actual PDFs/16 pages,
fresh nonempty recovery and both release gates passed before API-only rollout. Final health at
16:29:54 UTC is ok, Collabio running(4). Next: Roadmap 273 / PLANS 134 headers/footers and page numbers.
Continue Office before CRM. Ordinary tenant/pilot/indexing/cloud/engine admission remains closed.

## Roadmap 272 validation evidence

Final implementation/test source: 800a3a5a7403993de236a3207f9900ce0fe3094d, under ADR-0095.
Optional root attrs.page contains complete paper/orientation/four integer margins (5-50 mm).
Absence retains unchanged canonical legacy bytes and A4 portrait/18 mm defaults. Reset removes the
optional metadata. Styles, breaks, image flow, tables, exact saved versions and independent copies
retain their contracts. Only confirmed CAS Save persists changes. Print reauthorizes saved content
and images; temporary paper/orientation overrides never alter the document. The editor stays continuous;
exact on-screen pagination, sections, headers/footers and DOCX interchange remain separate.

Full quality: all 2875 Python cases, Ruff, 776-file formatting and Mypy/581 sources passed;
only the known Starlette/AnyIO deprecation warning. Quality log sha256:
0ef48f6744a69a5cdf7f2e0c75cc7882545a405fc16d566d0892cc7df92645c3.
One complete run passed all 345 distinct cases (285 browser + 60 model) in 1414.565233s,
2026-09-23 15:58:18.688-16:21:53 UTC, with zero skipped/unexpected/flaky/retries.
Every prior 325 case identity is retained. Full report sha256:
2137fea9b12a0c18f4ad0a028c2610650d0443d51b26bdbca9faa5f2d994b9bd.
Acceptance metadata sha256:0ba7b99487f54bb171f9b68f697f28a8ed985b5c8d00704559e7961d32fd9f14.

Earlier runs are retained honestly:
- First full run on 4424707 passed 343/345. An existing routed image-read PDF test stalled;
  test-only 5071632 observes actual authorized content/image responses. A real mobile toolbar
  regression reduced the search canvas; b3985b4 moves Page beside Image. Both corrected workflows
  passed 4/4 without weakening assertions. First report sha256:
  365c90210acee9f0812734076c191991473c28c107491765d6a11484ed3934f9.
- Second full run on b3985b4 passed 345/345, but independent PDF QA exposed legacy CSS selectors
  overriding the correct new CSSOM margins with 18 mm. Its green browser result was insufficient
  for acceptance. 800a3a5 removes obsolete rules/selectors and every actual PDF probe now asserts
  the computed office-document page name. Second report sha256:
  d3334d73bfeac1f99e8568669b0059bb837e5fc7f5e2847cd80634bd3b85b8b5.
- All 20 focused page-settings cases then passed in 93.173697s before the final full run.
  Focused report sha256:2742e6a79ad7b909ceed9a69fc185765de61a369a216633a307e28d336d3aeea.

Final PDF QA at 16:22:22 UTC verifies all eight A4/Letter portrait/landscape desktop/mobile
PDFs, two pages each: exact dimensions, four CSSOM margins, asymmetric text containment,
40 mm left offset, explicit page boundaries, blue image pixels and Figure/Alt/Table/TH/TD tags.
Sparse fixtures prove bottom-margin containment, not a measured last-line offset. Caption text
extraction accepts ordinary line wrapping while enforcing unique markers and exact page placement.
Root reviewed all 16 rendered pages and desktop/mobile dialogs. Every final raster page hash
matches the reviewed pixels exactly. No independent-agent or non-Chromium proof is claimed.
Final QA JSON sha256:e3f5d79968e55e023ecb8712087c6bb81bd1de829403b10b3b0b7ca634d8931d.
Reviewed pixel manifest sha256:58c70559c2010ca67cbb28e78e651785e5654e8f9c8e062bd89ea1090f588ec4.

Fresh nonempty recovery completed at 16:26:31 UTC into collabio_work_e2e_272_restore:
458 documents, 902 Office versions, 124 multiversion documents, 1001 sources, 44 image assets
and 62 saved image references (36 cropped, 36 wrapped). The designated four-version
legacy/custom Letter landscape/second A4 profile/reset fixture matches exact JSON, canonical
hashes and lineage. Previous breaks/wrap-reset/crop-reset/paragraph/character/style proofs,
10 review threads/18 events, 11 suggestions/7 decisions, bytes/receipts, read-only access and
foreign-tenant denial passed. All nine synthetic targets and their dumps/receipts remain retained.
- Recovery JSON: sha256:80512cfc53ddcf92fc221df22366c2f60d3276e2c9a82694ba6484de36876a4e.
- Embedded report: sha256:7fe3e73ee453489cacc364893ea49e69ceda35d4685aa6e99f705375fd6a19ca.
- Checked dump: sha256:5df20a490e8202262caa8cf9bff16fb46a04dfa44c75601ae02f0437bc18ccbd.
- Page-settings fixture: sha256:869b33da3e1f300ca2ae6eec7e0c2d2c700cf1df295766e3f5d1145319bf76e0.

Main backup collabio-20260923T162702Z.dump was checked before refreshing only the ordinary
isolated restore target. Foundation seed was explicitly 0; 85 migrations/95 tables and three
source objects/two tenants passed. Both release gates passed without blockers or business writes.
- Main backup: sha256:e0ecc608a0f37716fd993c0e3a29ae94ea033613b04aa3b9bd32151a9e5a1b12.
- Ordinary restore: sha256:749394338c77026b61725e09919e6b9edcb337d95c6990cc42fbebdbcc5dbf1a.
- Foundation, 16:27:14 UTC: sha256:683e256a3f1b3098daa850654032c602d197f4890f913af745a8856d55d9994a.
- Business, 16:28:03 UTC: sha256:07c7b4ed8be1ff039b11c4bae4abc1f614e8466ee1ad75a1f993cd9930c33c6e.
Synthetic page-settings content was absent from normal and both E2E API logs at 16:27:45 UTC.

API-only --no-deps rollout with pilot explicitly 0 reached health ok at 16:28:44 UTC.
API 315d76369cae runs image sha256:51136c5be6bb2ee8d86e4905d1b0aa4980636b68120844059218841bacf193a5.
Regular decoder 30766f16f16a/image unchanged: network none, user10001:10001, readonly root,
ALL capabilities dropped, no-new-privileges, 384 MiB, 16 PIDs, one CPU and only its socket volume.
Live checks verified 15 Office OpenAPI operation definitions, prior/new page controls, served
assets/licenses, Work link, no-store and CSP. Ordinary Office remains unprovisioned/non-cacheable404,
features closed, KB write false and pilot0. Definition checks do not execute business operations.
Live JSON sha256:7c0ebf0ce6233831dc47f73d943e9053762070e397887020c9a4fd10809edac1.
Exact eight E2E services including their decoder were removed; test and both restore services stopped.
Final 16:29:54 UTC health ok, Collabio running(4), loopback8000/5433/29000/29001 unchanged.
Main PostgreSQL87a6b37942c8, MinIO98ce365f455b, Webcut running(7), provider nodes/26443 unchanged;
Tricert absent. Cleanup log sha256:8ad210900cddf9597fee27dc849d6b0d0f6a5f79fd590d75f4f9646de932c80b.
All operations used dev001/collabio, fresh inventories and build.lock before docker.lock; source sync
used git.lock and never ran during acceptance/recovery. No main migration, normal content write or
ordinary tenant/pilot/indexing/cloud/DOCX activation occurred. Root matched all downloaded hashes.
Raw reports, eight PDF hashes/files, rendered pages and logs remain under ignored
 e2e/work/artifacts/roadmap-272 and the operation logs. Production continuity admission stays separate.

## Previous Roadmap 271 closeout

Roadmap 271 / PLANS 132 is complete: explicit native page breaks with safe insertion/removal, undo, immutable
history/copies and actual PDF boundaries. Full quality passed; all 325 distinct browser/model cases are covered by
a 324/325 full run plus the corrected 12/12 subset, not one all-green full run. Four PDFs/14 pages, fresh nonempty
recovery and both release gates passed before API-only rollout. Final health at 11:20:24 UTC is ok, Collabio running(4).
Office remains ahead of CRM; next is Roadmap 272 / PLANS 133 document-owned page settings. Ordinary tenant/pilot/
indexing/engine admission remains closed.

Roadmap 271 closeout 1e19eda was published and synchronized. All eleven documentation/module/roadmap checks passed
in 60.08s, with only the known Starlette/AnyIO warning; health remained ok at 2026-09-23 11:23:37 UTC. Log sha256:
b3c40ea2e86e4df2bc297df18c90d596fad89149a78b9df068e59186c10bf114. Root matched final acceptance, full/targeted
reports, quality, all four PDFs, recovery, release and live/cleanup evidence locally. The --no-deps disposable check
started no auxiliary service; Collabio remains running(4), API fd3fae191cf9 and decoder30766f16f16a. Main stores,
Webcut and provider resources remain unchanged. This final evidence-only record changes no runtime or admission.

## Roadmap 271 validation evidence

ADR-0094 implements explicit native page breaks: visible root-only markers, menu/Mod+Enter insertion,
keyboard/menu removal and isolated undo. Splitting preserves paragraph/heading attributes and inline marks;
selected images/tables/rules remain intact. Nested contexts, text ranges and more than 100 markers are rejected.
Legacy canonical bytes remain unchanged. History, comparison, owned copies, reviews and suggestions retain
exact positions. Print clears preceding image floats; repeated and trailing markers add no empty pages,
while leading markers separate the printed title from body content. Continuous pagination remains separate.

Final implementation/test source: 31aa72a2682f9d115143cae92eb41bed78e1839e. Product sources have not changed
since 87de370. Full Python quality passed on b6809f3: Ruff, 769-file formatting, Mypy 578 sources and full Pytest,
with only the known Starlette/AnyIO warning. Quality log sha256:
47ad5bf3f5519e1206c15025bb1c32c5ff1d51302d79b205517228dad6f37967.

Passing evidence covers all 325 distinct cases (269 browser + 56 model), not one all-green full run:

- First full attempt on 87de370 passed 324/325; a crop-dialog helper did not wait for authenticated image
  readiness and unconditionally toggled its details. All four affected crop cases passed after the test-only fix.
  Retained report sha256:068c36d24ed152de7dc8f60f22c2176ce6d4d1c4c3d0649af875d059a550eef6.
- Second full attempt on b6809f3 passed 324/325 in 1340.967017s, including all prior 313 cases. The desktop
  Letter PDF case timed out before printing; its final image request was pending in the trace and absent from
  server logs. The test now observes actual document/image responses without request routing, retaining the
  geometry/content assertions. Report sha256:039f78ee0bb3a8add557a0a7b329aa3f752a85dd04fe51ce13af8b951c027d18.
- Final complete page-break subset on 31aa72a passed 12/12 in 79.960380s, zero skipped/unexpected/flaky.
  Report sha256:f30d36912d6ed2abe729282da6b6bcfad169d1baadffcf34ce68385b62ee45d3.
  Exact case identities and unchanged runtime sources were cross-checked; combined metadata sha256:
  2ecff5d4fc23088bebe8cc02ecd7e9ca36c92bb57458913596d3bdaea45458fc. Both original failed traces are retained.

Root reviewed final desktop/mobile editor screenshots and all 14 pages from four fresh actual PDFs:
each A4 file has three pages; each Letter file has a title page plus three content pages. Exact text boundaries,
wrapped image/caption containment, table/heading placement, margins and Figure/Alt tags passed. The one-cell
table fixture has no PDF Table tag; it proves placement, not table tagging. The initial ad-hoc QA assumption
was corrected and this limitation is explicit in the report; existing rich-table structure tests remain intact.
No independent-agent or non-Chromium proof is claimed. PDF-QA JSON sha256:
5eb7e2d04686a02a7dd95f371c69df9d01747fee2a983acf4505d020cf0d04a9.

| Actual PDF | SHA-256 |
| --- | --- |
| A4 desktop | 142d9c8ba826d000d5900ba039267b0aa4350628ea73fee8eae3793af21146ec |
| A4 mobile | 7051b6b705e2697953b25034ade64f207d7cc6875cf7c857e71f75adac76a507 |
| Letter desktop | bc64866f54c6ad5ddb8ee7ba3f7cdf29946a8731679bc30176e916de9d1b59f6 |
| Letter mobile | c9e11cd41c553209e1b1311a87d9eb21ef35f916b3ebcc94cf85d1431cf25055 |

Fresh nonempty recovery completed at 2026-09-23 11:15:27 UTC into the separate
`collabio_work_e2e_271_restore`: 451 documents, 896 Office versions, 119 multiversion documents, 991 sources,
40 image assets and 58 saved image references (36 cropped, 32 wrapped). Exact legacy/insert/remove page-break
versions, canonical legacy hash, wrap/reset and crop/reset, paragraph/character/style, 10 review threads/18 events,
11 suggestions/7 decisions, source bytes/receipts, read-only access and foreign-tenant denial passed.
All eight synthetic restore targets and their dumps/receipts remain retained.

- Recovery JSON: sha256:46851e4c76352ef7a135f72e084f66307bd1994bcaa1eab54d70c71b37fcebf8.
- Embedded recovery hash: sha256:b0eccfa29f7cc10d0229c298cf39a3b710f1267902a9fc1d3a44018a7fde8e0c.
- Checked dump: sha256:7a723f89fcab251cbe03cadac60cbc69561b321f59f13505f1fb7b4298c62c31.
- Exact three-version page-break evidence: sha256:1e66193f9ea6b91b77e7f75442386a35ea33055b7335b5c357d404ac0097e69e.

All builds/tests/restore operations used dev001, explicit `collabio`, fresh project/container/port inventories and
build.lock before docker.lock. No source sync ran during acceptance/recovery. Synthetic page-break content was
absent from normal and both E2E API logs at 11:12:14 UTC.

Fresh main backup `collabio-20260923T111656Z.dump` was verified before refreshing only the ordinary isolated restore
target. Main schema remains 85 migrations/95 tables; foundation verified three restored sources/two tenants with
seed explicitly 0. Both release gates passed without blockers or business writes:

- Main backup: sha256:22eb9d8b213ab00dc987dd9d3351b20e14027761c5264b6aea56bef0cdb777ee.
- Ordinary isolated restore: sha256:bbe05c1b1508d7cd11c09bea1861dfe2cd115f5fff53075a2c416ec493e24ddd.
- Foundation gate, 11:17:09 UTC: sha256:797de1c213712823ae4a2b76db0604d503c40dd71efe6536ba46f870f42b8916.
- Business gate, 11:17:58 UTC: sha256:f4dceefe67d9d6692dd079633003daf8e7b9f15641dab8b12683495b8382a3e0.

API-only `--no-deps` rollout with pilot explicitly 0 reached health ok at 11:19:14 UTC. API `fd3fae191cf9` runs
image `sha256:ee33ffeb954adb775b76f5eb71f5a43794648250b094c8de3dedebabc345d52f`. Regular decoder
`30766f16f16a` and its image remain unchanged: network none, user 10001:10001, read-only root, ALL capabilities
dropped, no-new-privileges, 384 MiB, 16 PIDs, one CPU and only the shared socket volume. Live checks at 11:20:12
verified 15 OpenAPI operation definitions, served prior/new controls, assets/licenses, Work link, no-store and CSP.
Office remains unprovisioned with non-cacheable 404/features closed; KB write is false and pilot is 0. Definition
checks do not execute the 15 business operations. Live JSON sha256:
ad969af5bb3c03a9c0356f32a8920e76d68faeb12dd4c90ab16add3109ecd957.

Exact eight E2E services including their decoder were removed; test and both restore services were stopped.
Final health at 11:20:24 UTC is ok, Collabio running(4), loopback 8000/5433/29000/29001 unchanged. Main PostgreSQL
`87a6b37942c8`, MinIO `98ce365f455b`, Webcut running(7), provider nodes/26443 remain unchanged; Tricert is absent.
Cleanup log sha256:4b3000810261e343b8f7a6945e69ffa63487ef56ea4c6432519622f97d522fd4. No main migration,
ordinary content write or tenant/pilot/indexing/cloud/DOCX activation occurred. All raw evidence is retained under
ignored `e2e/work/artifacts/roadmap-271` and the dev001 operation logs; production continuity admission is separate.

## Prior completed development slices

Roadmap 270 / PLANS 131 completes native image text wrapping under ADR-0093: left/right placement, bounded text gap,
stable ordered anchors, narrow-column/nested block fallback and guarded preview/reset/undo. Full quality and one
complete 313-case browser/model run passed on 1d8a58f. Actual PDF/visual checks, fresh nonempty left/right/reset
recovery and both release gates passed before API-only rollout. Final health at 09:30:13 UTC is ok; Collabio runs
four regular services. Its then-next Roadmap 271 / PLANS 132 explicit native page breaks is recorded above.
Ordinary tenant/pilot/indexing/engine admission stays closed. Detailed evidence is recorded below.

Roadmap 270 closeout 97b777e was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.10s with only the known Starlette/AnyIO warning; health remained ok at 2026-09-23 09:33:57 UTC. Log sha256:
dc69e15ec3051377f05ebc452388fc0504b986f74169b29be3610622e2a533ea. Root matched it locally alongside the full report,
quality, PDF, recovery, release, live and cleanup evidence. The --no-deps disposable check started no auxiliary service;
Collabio remains running(4), API e031e3e9b941 and decoder 30766f16f16a. Main stores, Webcut and provider resources remain
unchanged. This final evidence-only record changes no implementation, runtime or admission boundary.

Roadmap 269 / PLANS 130 completes non-destructive native image cropping under ADR-0092: pointer/numeric/keyboard
preview, reset and isolated undo, preserving source pixels, immutable history, comparison, owned copies and print.
Full quality passed on 54fe1ff. Passing evidence covers all 303 distinct browser/model cases: the full attempt passed
302/303, then all 57 cases affected by the test-only reuse-helper correction passed on 3da08b8. This is not a single
all-green full run. Actual PDF/visual checks, fresh nonempty crop/reset recovery and both release gates passed before
API-only rollout. Its final health at 08:29:39 UTC was ok, Collabio running(4). Its then-proposed
Roadmap 270 / PLANS 131 image text wrapping is completed above. Ordinary tenant/pilot/indexing/engine admission stays closed.

Roadmap 269 closeout 85a93a6 was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.17s with only the known Starlette/AnyIO warning; health remained ok at 2026-09-23 08:33:20 UTC. Log sha256:
cef31c0199805c9d65ca29ce881885618cd1269b393528fb67d04bc6d7045d44. The --no-deps disposable check started no
auxiliary service; Collabio remains running(4), API a67cdfa88bdb and decoder30766f16f16a. Root matched acceptance,
full/affected reports, quality, PDF, recovery, live/cleanup and release evidence locally. Normal stores, Webcut and
provider nodes remain unchanged. This final evidence-only record changes no implementation, runtime or admission.

Roadmap 268 / PLANS 129 completes document-owned PNG/JPEG images under ADR-0091: upload, insert, resize/align,
alt/caption, move/remove/undo, confirmed save, history, independent copy and print. All 297 browser/model cases passed
on 96a299f. Full quality passed on 5d3eb35, whose only difference is Python test formatting and added ACL/replay
assertions; runtime and browser sources are identical. Actual PDF/visual checks, fresh nonempty document-plus-image
recovery and both release gates passed before decoder/API rollout. Its then-proposed Roadmap 269 / PLANS 130
non-destructive crop is completed above. Ordinary tenant/pilot/indexing/engine admission stays closed.

Roadmap 268 closeout94f56c3 was published and synchronized. All eleven documentation/module/roadmap checks passed
in59.72s with only the known Starlette/AnyIO warning; health remained ok at2026-09-23 07:32:20 UTC. Logsha256:
10995f0a81d453f2b86dfe21d7e552f25a44260912d6edc254a909512a1bb1c1. The --no-deps disposable check started no
auxiliary service; Collabio remains running(4), API d83a791253d4 and decoder30766f16f16a. Root matched final report,
PDF, recovery, live/cleanup and release evidence locally. Main PostgreSQL87a6b37942c8, MinIO98ce365f455b, Webcut and
provider nodes remain unchanged. This final evidence-only record changes no implementation, runtime or admission.

Roadmap 267 / PLANS 128 completes document-owned named format styles under ADR-0090. Full quality and a single
complete 280-case browser/model run passed on 1e09a10 after correcting a comparison-reference regression. Actual PDF,
responsive visual review, fresh nonempty PostgreSQL/S3 recovery, release gates, API-only rollout and live checks passed.
Its then-proposed native image follow-up is completed by Roadmap 268 above; further object types remain proposed.
Office remains ahead of CRM; ordinary tenant/pilot/indexing/engine admission remains closed.

Roadmap 266 / PLANS 127 completes native list levels and numbering under ADR-0089. All twelve focused cases,
full quality and a single complete 264-case browser/model run passed on fb8dbd3. Root reviewed desktop/tablet/mobile
list controls and mobile comments. API-only rollout and closed-gate evidence are recorded below. Office remains ahead of CRM.

Roadmap 265 / PLANS 126 completes in-document character/paragraph format transfer under ADR-0088.
All 40 initial focused formatting/keyboard cases passed on 068152f. The first full run exposed a mobile review-layout
regression, now corrected without weakening assertions. All 43 responsive/transfer cases and a single complete
252-case browser/model run passed on ac70c29, together with full quality. Root reviewed the final three transfer
viewports and mobile comments. API-only rollout, live checks and exact cleanup passed. Office remains ahead of CRM.

Roadmap 264 / PLANS 125 completes confirmed whole-document keyboard replacement across rich tables.
The original Chromium failure was reproduced; cancelable beforeinput now prevents native table DOM mutation,
and a structural full selection is replaced through one validated transaction. All 26 focused keyboard/table/history
checks passed on 460d632. Full quality and all 241 browser/model cases passed in a single run on d7270a7.
Root reviewed the desktop/mobile confirmation. API-only rollout and closed-gate checks are recorded below.
Office remains ahead of CRM; subsequent completed slices are recorded above.

Roadmap 263 / PLANS 124 completes native character font sizes and named colors under ADR-0087.
Selection/caret, mixed/reset/undo, strict marks, comparison/replacement/reuse/print and fresh nonempty recovery passed.
Full Python quality passed; passing evidence covers all 231 distinct browser/model cases, combining 230 full-run
successes with the corrected complete eight-case history suite. Both raw setup-failure reports remain retained;
this is not a single 231-pass run. Recovery verified 460 documents, 935 versions and 1,045 sources. Release gates,
API-only rollout, live verification and cleanup passed. Office remains ahead of CRM. Its then-open whole-document
keyboard replacement follow-up is completed by Roadmap 264 above; the old fixture isolation alone did not fix it.

Roadmap 262 / PLANS 123 completes native paragraph alignment and line/before/after spacing, with strict optional
attributes and unchanged legacy canonical bytes. Save, undo, comparison, reuse and print preserve formatting.
Full quality and all 215 browser/model checks passed on `8b61d8d`; nonempty recovery verified 330 documents,
666 Office versions and 721 sources. Actual PDF output and responsive layouts passed independent visual review.
Both release gates, API-only rollout, live verification and exact cleanup passed. Office development continues before CRM.
Decision: `ARCHITECTURE_DECISIONS/ADR-0086-native-office-paragraph-formatting.md`.

Roadmap 261 / PLANS 122 completes saved-version history beyond 200 entries with bounded pages along the immutable
predecessor chain. Current parent ACLs remain mandatory for every page; selection, comparisons and local drafts survive
loading and refresh. Full quality and all 200 browser/model checks passed on `46a83b4`. Independent code and visual
review, API-only rollout, live checks and exact cleanup passed. Office development continues before CRM expansion.

Roadmap 260 / PLANS 121 completes native Office discovery with server-side literal title search and cursor-based
loading beyond the initial 200 entries. Fresh ACL checks precede page limits; filtered list membership never clears
an open document or draft. Full quality and all 190 browser/model checks passed on `5bcb7d2`. Desktop/tablet/mobile
review, API-only rollout and final health/gate checks passed. Office development continues before CRM expansion.

Roadmap 259 / PLANS 120 completes saved-version reuse as an independent new document draft. Source read and create
permission are freshly checked after discard consent; the existing confirmed Create supplies the new identity and
creator ACL. Full quality and all 180 browser/model checks passed on `e7fec24`. Desktop/tablet/mobile visual review,
API-only rollout and final health/gate checks passed. No backend/schema/persistence/dependency change was introduced;
Roadmap 257 recovery evidence is retained, not rerun. Office development continues before CRM expansion.

Roadmap 258 / PLANS 119 completes saved-version print preview and browser print/PDF output. Office development
continues before CRM expansion. Full quality and all 170 browser/model checks passed on `cf2244c`; the final
cleanup-only test guard on `d8300aa` passed its affected browser case. Actual PDF text, dimensions, pagination,
semantic structure and visual output passed independent checks. There is no schema, persistence, dependency or API
change. Roadmap 257 recovery evidence is retained, not rerun. Final host verification is recorded below.

Publication state: on 2026-09-21 the operator explicitly approved publishing the prepared Roadmap 256 documentation,
including its operational metadata, to the public `kirchherr/collabio` repository and instructed work to continue.
Documentation commit `1545bb2` was pushed and synchronized. All 11 module/KB/roadmap contract checks passed in
58.85 seconds; health remained ok at 2026-09-21 06:34:16 UTC. The --no-deps test started no auxiliary service.
That Roadmap 256 publication is complete. Roadmap 257 then continued the authorized Office development below;
implementation `9c17a31` passed full validation, nonempty recovery and API rollout on dev001.
Roadmap 257 closeout `c4176de` was published and synchronized. All 11 documentation/module/roadmap contract tests
passed in 59.02 seconds; health remained ok at 2026-09-21 07:24:18 UTC. The --no-deps check started no auxiliary
service. Final independent evidence review confirmed all counts/hashes and clarified two historical module-document
references; those wording corrections change no implementation or tested contract behavior.
Roadmap 258 closeout `61d7fce` was published and synchronized. All eleven module/KB/roadmap contract checks passed
in 59.62 seconds, with only the known Starlette/AnyIO warning. Health remained ok at 2026-09-21 11:36:53 UTC;
Collabio still running(3), with no auxiliary service started by the --no-deps disposable test. Independent final review
matched all report/PDF/screenshot hashes and runtime evidence. This final evidence-only record changes no runtime or gate.
Roadmap 259 closeout `dd65d5a` was published and synchronized. All eleven documentation/module/roadmap contract checks
passed in 58.98 seconds, with only the known Starlette/AnyIO warning. Health remained ok at 2026-09-21 12:25:37 UTC;
the --no-deps disposable test started no auxiliary service. Independent review matched all report/log/screenshot hashes.
Final wording clarifies cancellation during reads, OpenAPI-definition verification and the absence of a main-database
migration or new recovery drill; isolated test databases did run their required migrations. These evidence-only changes
alter no runtime, tested behavior or gate.
Roadmap 260 closeout `b7b2cba` was published and synchronized. All eleven documentation/module/roadmap contract checks
passed in 59.43 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-21 13:07:23 UTC.
The --no-deps disposable check started no auxiliary service, and Collabio remained running(3). Independent review matched
all twelve checked report/log/screenshot hashes, counts and log-redaction evidence. Final wording updates the module's
continuation pointer, distinguishes matrix duration from full quality, and clarifies the additive existing-API contract.
These evidence-only corrections change no implementation, tested behavior or gate.
Roadmap 261 closeout `2f0c011` was published and synchronized. All eleven documentation/module/roadmap contract checks
passed in 59.42 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-21 14:30:32 UTC.
The --no-deps disposable check started no auxiliary service, and Collabio remained running(3). This final evidence-only
record changes no runtime, tested behavior or authorization boundary. Independent final evidence review matched counts,
durations, nine local report/log/screenshot hashes and both access-log redaction checks without finding a documentation
blocker. The initially failed report was also retrieved from its retained dev001 copy and its hash reconfirmed by root.
Roadmap 262 closeout `e567d76` and wording correction `3f38ffc` were published and synchronized. All eleven
documentation/module/roadmap contract checks passed in 59.12 seconds with only the known Starlette/AnyIO warning;
health remained ok at 2026-09-21 15:22:40 UTC. The --no-deps disposable check started no auxiliary service and Collabio
remained running(3). Log hash: `sha256:d8d92e59d6331672bb55664e0cc854d4a16b0fdb205284738dacc7e3e9c5ec2c`.
Independent review matched report/log/PDF/screenshot hashes and release evidence. Final wording distinguishes the normal
creator ACL from manual fixture grants and saved formatting versions from historical-only versions. This evidence-only
record changes no implementation, tested behavior or authorization boundary.

Roadmap 263 closeout `978f879` was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.17 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-22 07:22:30 UTC.
The --no-deps disposable check started no auxiliary service; only api, postgres and minio remain running in Collabio.
Log hash: `sha256:0ae2a9878594eb015da4a60e5cb4b6d1841e7c3b81b90ddd05165aafd15e16bf`.
Root verified report identity, recovery canonical hash and retained artifact hashes. The separate acceptance summary
(`sha256:9d5800e0313752f3c2c19a17c03140d8c78f2b43a609778f1d299f695111ec50`) explicitly records 230 full-run passes
plus the corrected eight-case history suite; no single all-green full run or independent subagent review is claimed.
This final evidence-only record changes no implementation, tested behavior, runtime or gate.

Roadmap 264 closeout `378c1c4` was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.43 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-22 08:07:05 UTC.
The --no-deps disposable check started no auxiliary service; Collabio remains running(3), API 12c85d748e73.
Log hash: sha256:e6b24d89116c274af68b4d3bc95f83756498628a76a028f99547b2d2388d633c.
Root matched all five final report/log/screenshot hashes locally. This evidence-only record changes no implementation,
tested behavior, runtime or gate.

Roadmap 265 closeout `fe093ff` was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.33 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-22 10:10:01 UTC.
The --no-deps disposable check started no auxiliary service; Collabio remains running(3), API fa32456a32a1.
Log hash: sha256:5ba93a632d35eb978321f040ab13544b2d6dc8a1da6333cea22501c80f946342, also matched locally.
This final evidence-only record changes no implementation, tested behavior, runtime or authorization boundary.

Roadmap 266 closeout `878feb0` was published and synchronized. All eleven documentation/module/roadmap checks passed
in 60.60 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-22 10:52:20 UTC.
Log sha256:0e86cb7f15a7fdbd0c66202c602dbf35d0119cda410ad4f868ca3747a4497bff matched locally. The --no-deps
disposable check started no auxiliary service; Collabio remained running(3). This final evidence-only update changes
no implementation, tested behavior, runtime or authorization boundary.

Roadmap 267 closeout `fd2c092` was published and synchronized. All eleven documentation/module/roadmap checks passed
in 59.86 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-22 13:54:59 UTC.
Log sha256:ff9d69bdcca395d2cd1bb398af2e9e22dbc4cb2b369756011981b891ca9f8db4 matched locally. The --no-deps disposable
check started no auxiliary service; Collabio remained running(3), API bdcb65aa540c. Final spacing and evidence-only
documentation changes alter no implementation, tested behavior, runtime or admission boundary.

This is the canonical continuation document. Read `AGENTS.md` fully first, then this document, `PLANS.md`,
`docs/ROADMAP.md`, the append-only `docs/operations/DEV001_OPERATIONS_LOG.md`, and the relevant runbooks.
AGENTS.md and current code are authoritative. Green development evidence is not production or real-user approval.

## Current slice: Roadmap 270 image text wrapping

Decision: ADR-0093. Optional `wrap` contains exactly left/right `side` and integer `gap` from 0 through 48 CSS pixels.
Reset omits it and preserves legacy canonical bytes. Ordered image nodes anchor following top-level paragraphs;
headings, lists, tables, quotes, code, rules and later images clear the float. Wrapping uses at most 45% of the column
and a displayed-image-height limit of 480px. Columns at most 480px wide and nested images use block fallback without
rewriting content. The dialog previews the same rules; Apply is one context-bound undo action. Exact crop/source,
history, comparison, owned copies and confirmed CAS saves remain intact. No endpoint, migration, dependency, asset
or decoder change is introduced. Rollback requires compatible historical readers while closing further writes.

Print uses the physical column width. A fitting image/caption moves intact to the next page when necessary;
following text can begin on the preceding page and continue beside it. Over-page captions remain browser-fragmented.
No arbitrary page-positioned object, DOCX anchor, universal pagination or non-Chromium fidelity is claimed.

Implementation and acceptance are frozen at 1d8a58ffe71ff6aff3d6a39fa314f8102c2ab6d6. The initial 31-case focused browser
run passed while Mypy rejected an untyped new test fixture. a1c8769 corrects that fixture, widens the desktop preview
and adds anchor-move/structural-clearance tests; 129 focused Python and all 33 image browser/model cases then passed.
The final test-only 1d8a58f strengthens the physical page-boundary fixture. Earlier raw reports remain retained.

Full quality passed Ruff, 764-file formatting, Mypy across 575 sources and complete Pytest, with only known Starlette/AnyIO
warning. One complete browser/model run passed 313/313 (259 browser + 54 model), zero skipped/unexpected/flaky, starting
2026-09-23T09:00:52.828Z and lasting 1255.726974s. Both processes exited 0 at 09:21:49 UTC. Root matched local report
counts and hashes and reviewed final desktop/mobile dialog/document and tablet screenshots plus all six PDF pages.
Each PDF has three A4 pages with full expected text, Figure/Alt semantics and intact left/right crops on page 2.
At 2000px raster resolution, left/right crops contain 103041/103040 orange pixels and 22/61 adjacent words, with no
text overlap or cropped-away blue pixels. The original 1000px QA quantization and same-page component-order issues
were corrected without changing product code or the 2pt tolerance. Checked synthetic text markers are absent from
the normal and both isolated API logs. No independent-agent review is claimed.

Fresh collabio_work_e2e_270_restore completed 09:26:14 UTC from its own checked dump/catalog/receipt. It verified 426
documents, 829 exact Office versions, 98 multiversion documents and 916 sources; 32 retained image assets, 50 saved image
references, 36 cropped and 24 wrapped references. Consecutive left/right/reset versions bind the same parent, asset,
rendition and crop. Previous crop/reset and all paragraph/character/style evidence passed, alongside 10 review threads/
18 events and 11 suggestions/7 decisions. Exact bytes/receipts, authoritative read-only access and foreign-tenant
denial passed. All seven synthetic targets remain retained. No source synchronization occurred during acceptance
or recovery; main stores and ordinary admission remain unchanged.

Key evidence retained locally and on dev001 under ignored e2e/work/artifacts/roadmap-270/:

- Full report: sha256:354dc941b20bef9bdcd44d8d4af1558849dba6a0dd3e19661eec62537841efff.
- Browser log: sha256:225a0ba770ceceee26a72eb8a01dc7b625c1d60df7eaadff0e49b5aec57d8e4a.
- Full quality log: sha256:c17b7b375c5dc39c8a9e3825eff687669211bfb0af5b9e86bc433562d1082a7a.
- Desktop PDF: sha256:187760afffda4e178fe8b24f0acd92117fc24db799153bc2e3e7eb4b7e189272.
- Mobile PDF: sha256:b556bc17ec2430ee8f0328ad2c8a34c9e4a6d634d3e7f9ac311db25832329494.
- Hash-bound PDF-QA: sha256:81eec6eb1cf69a55ba420575ae212fef984b8a28a3ccef8662d8f393c8fb417a.
- Recovery embedded hash: sha256:09b91cc7a6f32168fe136956fdf46ba124cb04804f65ad63d0efb49d165360ce.
- Recovery JSON: sha256:ac66d46e64e367e1e16eb9033535355e7c86c8a795fc93a234ad44a819087683.
- Synthetic dump: sha256:d66e9f89df74658e793c05787fd6f1a4b43b88a6a521d9282fbf865d8214e959.

Main backup collabio-20260923T092650Z.dump verified with hash
sha256:dbd64d7971cc228e3c75c9f59ca4887e491ff32bf544bbf52da656faf245c4a5. The ordinary isolated PostgreSQL restore
report hash is sha256:ab95f401fc8b812ab4595a1b7076c65437b3606cae750e2abd0e36d4d833ad1c. Foundation at 09:27:02 UTC
verified 85 migrations, 95 tables and three restored sources/two tenants; gate hash
sha256:850e93a743ae437f16eccb0ed99bfedbb151b8620619b9e5692610ce7a04c36f. Business at 09:27:52 is release_ready,
with no blockers or business writes; hash sha256:67f1a85817ff9f4775af545a46a1fbaab4b2dd760dfe0f068b2f3552ffddd878.
All operations held build.lock before docker.lock, used fresh inventories and explicit collabio. Loader/gates use
--no-deps; foundation seed is explicitly 0. No main migration, tenant activation or ordinary business write occurred.

API-only rollout with --no-deps and pilot explicitly 0 reached health ok at 09:28:49 UTC after bounded startup retries.
API e031e3e9b941 uses image sha256:93407a200513b63ffb0b28967504e0e8f313554c592187489e941768d036ff12.
Regular decoder 30766f16f16a retains image sha256:d3f95af20d18819e15a49e8ef499821b74a89743c8ed6b2fe1b3e4d0fa8b1276;
network none, user10001:10001, read-only root, ALL capabilities dropped, no-new-privileges, 384MiB, PIDs16, CPU1 and
its sole named socket volume were rechecked. No decoder recreation occurred. Live checks verify 15 Office OpenAPI
operation definitions, wrap/crop and all previous controls, served bundle/assets/licenses, Work link and no-store/CSP.
These checks do not execute 15 business operations. Office is unprovisioned/non-cacheable404, features closed,
KB write false and pilot0. Exact E2E services including the test decoder were removed; disposable runners are absent;
postgres-test and both restore services stopped. Final 09:30:13 UTC health is ok, Collabio running(4), unchanged loopback
8000/5433/29000/29001. Main PostgreSQL87a6b37942c8, MinIO98ce365f455b, Webcut running(7), provider nodes
1f644ba2506c/a9ab929053fa/23961c0d8cdb and26443 remain unchanged; Tricert is absent. Seven synthetic restore targets
and their dumps/receipts remain retained. Live JSON sha256:cb5211212fb3a3800f275c9b4ef507828da15611706ce18b90012ae1fb23766e;
cleanup log sha256:03fab92e8265e18b3f91a8856b1a2b0cc02e1c89b3c802389b5d3095cc58b0f4. Root matched both locally.

## Previous slice: Roadmap 269 non-destructive image cropping

Decision: ADR-0092. Optional integer source-pixel `crop` geometry is strictly bounded to the normalized image.
Absence means the full image; reset removes the optional property and legacy canonical bytes remain unchanged.
Pointer selection, pixel fields and arrow/Shift-arrow movement share one validator. Preview/cancel remain local;
Apply is one selection/context-bound undo action. Aspect lock follows the crop ratio; unlocked dimensions remain.
Editor, comparison, history, owned copies and actual print preserve the exact rectangle and caption/Alt semantics.
Crop is presentation, not redaction: authorized readers can still obtain the complete normalized source image.
No new endpoint, SQL migration, dependency, image asset or decoder behavior was introduced. Older readers reject
crop metadata; rollback must close further writes while retaining a compatible reader and exact historical data.

Implementation is frozen at 54fe1ffe5ba460dbfa4f00aab7ec42e6f0d141a4. Test-only
3da08b89989fe440abe734f90bdfdf9778b4d6a8 observes successful reuse responses passively instead of intercepting them;
all identity/content/no-store/authorization assertions and explicit fault interception remain. Product/Python sources
are identical. Initial focused failures (20/23) were fixture mutation-reference collisions and a stopped test database;
bb37cba corrected setup and passed 113 focused Python cases and all 23 focused browser/model cases.

Full quality passed Ruff, formatting across 762 files, Mypy across 575 sources and full Pytest, with only the known
Starlette/AnyIO warning. The complete 303-case run on 54fe1ff passed 302 in 1185.579592s; an existing image-copy case
stalled while fetching an image after reuse interception. Trace showed a pending fetch and no corresponding API
request, with saved content and the draft image node intact. All 57 cases in the seven helper-importing suites then
passed on 3da08b8 in 417.950193s, zero skipped/unexpected/flaky. The explicit acceptance aggregation matches file,
title and project to cover all 303 distinct cases (251 browser, 52 model); no single all-green full run is claimed.
Raw failed/focused/full/affected reports, logs and traces remain separately retained under ignored roadmap-269/.

- Full report sha256:e2786696db0b960c4c36219d053e8d6c2436840b863163efa87b5978592c1d54.
- Affected report sha256:cd1ab0ebcf2740feb7479fc3ec556282bd80644f0c5c9813a6b0d0c9b3721f2a.
- Acceptance JSON sha256:987e2f67ac36b86212f53b7c0507d88b9a9a159bb46d4cb6f7074623393c7905.
- Quality log sha256:c24384dff141d298e2c76b7471846dcaf77249b625fc04fbcbc5dbeff6ab9b3e.
- Focused report sha256:a0898f001f578f9e64db2091df1d0d49bde290509489be667de8a5ddc55cd3a4.
- Initial failed report sha256:165366ffcecadd1d54e634f9c97b54913809e6fe78a9cbaabf954dc808d57fd0.

Root reviewed desktop/tablet/mobile crop controls, mobile comments and both actual rendered PDFs. Each PDF is one
A4 page (594.96x841.92pt), retaining original 320x160 image pixels, Figure/Alt, literal caption and expected text,
with no application chrome. Each 1000px raster check finds 31,683 orange pixels and zero cropped-away blue pixels.
PDF QA ran in the pinned network-none, read-only disposable tool container. No non-Chromium or independent-agent
acceptance is claimed. Checked synthetic content markers are absent from normal and both isolated API logs.

- Desktop PDF sha256:7b5647b3b8799071e373ecb9ddb1807c9f60c6bd5780ab27f150aa34a3cc4dd8.
- Mobile PDF sha256:74f7e857470ca3f09e694cbcf84003d2131d2e5169a7d9c74b4192294b2285b0.
- PDF QA sha256:1052c52735d273e95389a6e10208e7e77e2a906819813ef110c790e152826b94.

Fresh recovery completed 08:26:06 UTC on 3da08b8 using separate checked dump/catalog/receipt and
collabio_work_e2e_269_restore: 488 documents, 913 exact Office versions, 122 multiversion documents, 1,013 sources,
43 image assets, 35 saved image references including eight cropped references. A reset immediately following a
cropped version binds the same parent, asset and rendition. All exact bytes/receipts, prior formatting, 11 review
threads/19 events, 12 suggestions/7 decisions, authoritative read-only access and foreign-tenant denial passed.
All six synthetic recovery databases and their dumps/receipts remain retained; no source sync occurred during proof.

- Recovery report hash sha256:70928c5c10e9e6e5a337e61f14ae8d8d0614a185cf95c0ad919a5bc4d9046937.
- Recovery JSON sha256:0747b846b2bd02ab6929919bc03d88c985e41778aa841b94a3169c82b671d606.
- Dump sha256:d40221acfda9093809148eeec4ded2b819fd99729d91cc84793e738265c412cc.

Main backup collabio-20260923T082635Z.dump verified; sha256:6e75168bce3e737375caad3d0bb2d552a36ece548f821a9b99e7580e063990ac.
Only the ordinary isolated restore target was refreshed, hash sha256:ca4696f2651c61e30cb3d1a05da887902a99cede3bb1885f8292cd6e6cc00797.
Foundation 08:26:48 verified 85 migrations, 95 tables, three restored sources/two tenants;
gate sha256:cad9b4210da57702a0aa5762f718ef80943fcb0214f450f65690a3ade3eb80d9.
Business 08:27:37 was release_ready without blockers;
gate sha256:fb753f69820091758fc44d53d8330a12ea9ce9725287e23f5e5dd6d79990f80a.
Both gates used --no-deps with foundation seed explicitly 0; no main migration, business write or tenant activation.

API-only rollout with --no-deps and pilot explicitly 0 reached health ok at 08:28:23 UTC. API a67cdfa88bdb,
image sha256:ba8bea9aeb2bb4118d3e34237d7bea6463b16edf910041540fd06fb7b5805308. Regular decoder 30766f16f16a and
its image remain unchanged; network none, user10001:10001, read-only, ALL capabilities dropped, no-new-privileges,
384MiB, pids16, CPU1 and sole collabio_office_image_socket volume were inspected. Live checks verify 15 Office OpenAPI
operation definitions, old controls, new crop controls and served bundle, assets/licenses, Work link and no-store/CSP.
Definition checks do not execute 15 business operations. Office remains unprovisioned/non-cacheable404, features closed,
KB write false and pilot0. Exact E2E services including test decoder were removed; disposable runners absent;
postgres-test and both restore services stopped. Final 08:29:39 health ok, Collabio running(4), unchanged loopback
8000/5433/29000/29001. Main PG87a6b37942c8, MinIO98ce365f455b, Webcut and provider nodes/26443 unchanged; Tricert absent.
Rollout held build.lock before docker.lock; live/cleanup held docker.lock, all with fresh inventories.
Live JSON sha256:dddb510cd5b8de466a2ed828a5049abecdd4a2ec8c340a4fa3a483a4310131af;
cleanup log sha256:b5326b7d91f54a66213a86e31489afb864d96f1f51cb72a58554571757baab48.

## Previous slice: Roadmap 268 native images

Decision: ADR-0091. Native PNG/JPEG upload, insertion, dimensions/aspect lock/alignment, literal alt/caption,
decorative choice, move/remove/undo, confirmed CAS save, historical reads, independent document reuse and actual
print/PDF are implemented. Upload requires an already saved writable document; it does not change the saved head.
Up to 40 image nodes/document and 200 retained uploads/document are admitted. Originals, filenames and EXIF are not
stored. Crop is completed by Roadmap 269 above; wrapping/floating anchors, shared media libraries, active objects and
DOCX interchange remain separate.

Immutable ATTACHMENT sources use the existing PostgreSQL/S3 storage and receipts. Each image node binds exact asset,
version, parent, manifest/content hashes and pixel dimensions. The current authoritative parent ACL is the asset ACL;
independent asset grants cannot authorize reads. Save verifies source bytes under the tenant write lock. Create/reuse
reauthorizes source parents and clones normalized bytes into new document-owned assets; exact replay returns the
committed rewritten references. No cross-document reference is accepted by ordinary Save. Removal/cancel never
deletes historical or unattached assets; retention-aware cleanup remains separate. PostgreSQL cannot roll back S3 PUTs.

The isolated decoder admits PNG/JPEG up to 8 MiB, 4096 pixels/axis and 4 million pixels. It has no network, credentials,
host port or host socket; only a named Unix socket volume connects it to the API. It uses the existing hash-locked
Pillow version in bounded child processes and returns raw pixels for minimal PNG reconstruction in the API. The
regular service uses the office-images profile; the test service has its own socket volume. Missing decoder access
blocks uploads, while stored-image reads remain available. A downgrade to a pre-image native reader is incompatible
with saved image versions; retain compatible reads and immutable assets when disabling further writes.

Acceptance:

- Single complete browser/model run on 96a299f: 297/297 in 1157.649996s (247 browser+50 model), zero skipped/unexpected/flaky.
  Full quality on 5d3eb35: Ruff, 758-file formatting, Mypy on 575 sources and complete Pytest passed. Only the known
  Starlette/AnyIO warning remains. The sole post-browser difference is test_office_images_pg.py formatting and added
  revoked-source Create/replay assertions; runtime/browser sources are identical. Initial fixture/infrastructure
  failures remain retained under ignored roadmap-268/first-focus,second-focus,third-focus and final logs.
- Root reviewed final desktop/tablet/mobile dialogs and both rendered PDF pages. Each is one A4 page with the exact
 320x160 image, expected text/literal caption, Figure/Alt structure and no application chrome. Checked image text
  markers are absent from regular and E2E application logs. No independent-agent or non-Chromium proof is claimed.
- Fresh collabio_work_e2e_268_restore verified 410 documents, 787 Office versions, 86 multiversion documents, 858 sources,
  16 retained image assets and 8 saved image references. Exact metadata/bytes/receipts/parent ownership and all saved
  image bindings passed, alongside paragraph/character/style fixtures, 10 review threads/18 events and 11 suggestions/
  7 decisions. Current authoritative read-only access and foreign-tenant denial passed. All five synthetic targets remain.
- Main backup collabio-20260923T072600Z.dump, isolated restore and both release gates passed. Foundation verifies 85
  migrations, 95 tables and three restored main sources/two tenants. No main migration or ordinary business write occurred.

Key evidence, retained locally under ignored e2e/work/artifacts/roadmap-268/ and on dev001:

- Browser report: sha256:70439ccf0416762c42befb4c037ff413ee64a72cf1ec2fb74519907b213280bb.
- Browser log: sha256:1f4098935ddf06260f852c19fb11347e8fcc9a1dc632881d9869fe84eec3adca.
- Full quality log: sha256:e29aa39fa497c81fde6da6d03d5c66a60772a039c5fe46727819dbd97c826dfb.
- Desktop PDF: sha256:a2d6a65ec258736db043b99333f61f1f32c4d47437d44a0e161aaf74607b9042.
- Mobile PDF: sha256:61c56f16b53455956e1b08ee821c8eeb000069692703291a36234e997d650e30.
- PDF-QA report: sha256:b1689ff842db2c40b4d261df0d5c4441208042e35e7b5307e96c53b6378bff97.
- Recovery embedded hash: sha256:c40f85de4b5e11725eec576286ab16546f5eb57aba30d11271f3ebd457713eb3;
  file hash: sha256:95af9c94d4e3677cb845b93fe756293df62222bad4a3fcc0f2977deb3bc898dc.
- Synthetic dump: sha256:3b2ae22cd33a4138ee5651b9bd84fac8d8b54df573ae33310281ace2c4cd9147.
- Main dump: sha256:4691780d168f77d2e04e9464d1aceb8ad1d49579c8f72c0c2ad0ec2b109fc8f3.
- Main restore report: sha256:afce1dc3691f488aad86b61cdde819beba750a21c60d52ed30881ff6ce44c56a.
- Foundation gate: sha256:9c46c1d9748b2f700a08ab1b080efc0c1ea7d16cf364b89c3e1b72a2228bdd2b.
- Business gate: sha256:901fdd1051cf03c89ba4fe8c8eb76a4defb13c40895500eefa942a3a091ae1e8.

Controlled rollout reached health ok at 2026-09-23 07:27:57 UTC. API d83a791253d4 and new decoder 30766f16f16a run;
decoder image sha256:d3f95af20d18819e15a49e8ef499821b74a89743c8ed6b2fe1b3e4d0fa8b1276 was inspected for
networknone,user10001:10001,readonly,ALLcapdrop,no-new-privileges,384MiB,pids16,CPU1 and its sole socket volume.
Live checks verify 15 Office OpenAPI operation definitions, discovery/history parameters, image/style/list and prior
controls, served bundle/local assets/licenses, Work link and no-store/CSP. These checks do not execute 15 business writes.
Office remains unprovisioned/non-cacheable404, features closed, KB write false and pilot 0. Exact E2E services including
the test decoder were removed; postgres-test and both restore services stopped. Final cleanup 07:29:06 health ok,
Collabio running (4), unchanged loopback 8000/5433/29000/29001. Main stores and other projects remain unchanged.
Live JSONsha256:9658792f48b72118525b4195c1545936273957674e7a1ad14eb5f51c9a012661;
cleanup logsha256:3d358a7277f83212b982356d77111f42c1ba0d1600dbf16d09a80efc2a4134a7.

## Repository and host

- Repository: `git@github.com:kirchherr/collabio.git`.
- Workstation: `C:\Users\tkirchherr\Documents\suite`; branch `kirchherr/kb-write-unit-of-work` tracks origin.
- Validated implementation: `1d8a58f` (full quality and a single complete 313-case browser/model run).
  Optional native v1 wrap metadata introduces no new endpoint, migration, dependency or decoder change. Fresh
  Roadmap 270 actual PDF, nonempty image/crop/wrap recovery, release gates and API-only rollout passed.
  The commit containing this handoff is the continuation
  baseline. Verify local and remote HEAD before continuing.
- The user's untracked `erp_modul.md` and `review.md` must never be staged, rewritten or removed without instruction.
- Generated `e2e/work/artifacts/` output is ignored and must not be committed.
- PR/merge state has not been verified; do not assume a PR exists.
- All builds, tests, migrations and service lifecycle work run on `extern@dev001` in `/home/extern/collabio`.
- Use only `C:\Users\tkirchherr\.ssh\id_ed25519_collabio_dev001` for SSH and explicit Compose project `-p collabio`.
- Read `/home/extern/AGENTS.md` before operating. Source sync holds `/home/extern/.codex-coordination/git.lock`.
- Heavy work holds `build.lock`; lifecycle holds `docker.lock`; always acquire build before docker when both apply.
- Before every start, stop, recreate or restore inspect `docker compose ls --format json`, `docker ps`, and `ss -ltnH`.
- Never use daemon-wide prune, broad container matching, plain Compose down or down -v. Never change Webcut,
  Tricert or provider resources. If SSH or locks are unavailable, report the blocker; do not use local Docker.

Previous item 267 host verification at 2026-09-22 13:50:27 UTC: Collabio running(3), healthok, unchanged loopback
8000/5433/29000/29001. Only API was rebuilt/recreated (bdcb65aa540c) with --no-deps and pilot explicitly0;
bounded startup retries reached healthy at13:49:21 UTC. Live13:50:24 verified thirteen Office OpenAPI operation
definitions, discovery/history contracts, old controls, new style dialog and served bundle, local assets/licenses,
Work link and no-store/CSP. Definition checks do not execute thirteen business operations. Tenant-demo Office remains
unprovisioned/non-cacheable404, features closed, KBwritefalse, pilot0. Exact E2E services were removed; disposable
runners absent; postgres-test and both restore services stopped. Main PostgreSQL87a6b37942c8 and MinIO98ce365f455b
remain unchanged. Four synthetic restore databases/dumps/receipts remain retained. Webcut running(7), provider nodes
and26443 unchanged, Tricert absent. No main migration, ordinary business-content write, tenant/pilot/indexing/cloud/
DOCX activation. Rollout used build.lock before docker.lock; live/cleanup used docker.lock, all with fresh inventories.
LiveJSONsha256:ce095592b0d4da4fe05664f2bdaddd1dbd17583be7ca2c208c685109016f7e06;
cleanuplogsha256:e6c6517513faa146e3f039f54562ea50e17305785faf2339cf81604cb83334c3.

Previous item 266 host verification at 2026-09-22 10:49:44 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`641024fc56b5`) with --no-deps and
pilot explicitly 0; bounded startup retries reached healthy at 10:48:16 UTC. Live verification at 10:49:40 UTC passed
thirteen Office OpenAPI operation definitions, discovery/history contracts, prior controls, local assets/licenses,
Work link and no-store/CSP, plus new list dialog controls and served bundle. Definition checks do not execute thirteen
business operations. Office in tenant-demo remains unprovisioned/non-cacheable 404, features closed, KB write false,
pilot 0. Exact E2E services were removed; disposable runners absent; postgres-test and both restore services stopped.
Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) are unchanged. All three synthetic restore databases,
dumps and receipts remain retained. Webcut running(7), provider nodes/listener 26443 unchanged, Tricert absent.
No main migration, ordinary business-content write or tenant/pilot/indexing/cloud/DOCX activation occurred.
UI-only: Roadmap 263 recovery/release evidence remains retained, not rerun. Host locks and fresh inventories protected
every lifecycle action; main rollout used build.lock before docker.lock, live verification/cleanup used docker.lock.

Previous item 265 host verification at 2026-09-22 10:05:54 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`fa32456a32a1`) with --no-deps and
pilot explicitly 0; bounded startup retries reached healthy at 10:05:00 UTC. Live verification at 10:05:51 UTC passed
thirteen Office OpenAPI operation definitions, discovery/history contracts, existing controls, assets/licenses,
Work link and no-store/CSP; new format-transfer controls and served bundle were also checked. These definition checks
do not execute thirteen business operations. Tenant-demo Office remains unprovisioned/non-cacheable 404, features
closed, KB write false, pilot 0. Six exact remaining Work-E2E containers were removed; disposable runners already
absent. postgres-test and both restore services are stopped. Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`)
are unchanged; all three synthetic restore databases/dumps/receipts remain retained. Webcut running(7), provider
nodes/listener 26443 unchanged, Tricert absent. No main migration, ordinary business-content write, tenant/pilot/indexing/
cloud/DOCX activation occurred. Roadmap 263 recovery and release-gate evidence is retained, not rerun, for this UI-only
slice. All lifecycle operations used fresh inventories and host coordination locks.

Previous item 264 host verification at 2026-09-22 08:04:14 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`12c85d748e73`) with --no-deps and
pilot explicitly 0; bounded startup retries reached healthy at 08:01:58 UTC. Live verification at 08:02:52 UTC passed
all thirteen Office OpenAPI operation definitions, discovery/history contracts, prior controls, assets/licenses,
Work link and no-store/CSP; the served bundle also contains the new whole-document confirmation/input path.
Definition checks do not execute thirteen business operations. Tenant-demo Office remains unprovisioned with a
non-cacheable 404, Office features closed, KB write false and pilot 0. Six exact remaining Work-E2E containers were
removed, disposable runners already absent; postgres-test and both restore services are stopped. Main PostgreSQL
(`87a6b37942c8`) and MinIO (`98ce365f455b`) are unchanged. All three synthetic restore databases/dumps/receipts remain
retained. Webcut running(7), provider nodes/listener26443 unchanged, Tricert absent. No main migration, new recovery
drill, ordinary business-content write, tenant/pilot/indexing/cloud/DOCX activation occurred. Roadmap 263 recovery
and release-gate evidence is retained for this UI-only change. Host locks and fresh lifecycle inventories were used.

Previous item 263 host verification at 2026-09-22 07:17:20 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`2dd08092b687`) with pilot explicitly 0;
bounded startup retries reached healthy at 07:16:02 UTC. Live verification at 07:16:54 UTC confirmed all thirteen
Office OpenAPI operation definitions, discovery/history parameters, character and previous controls, local assets/licenses,
Work link and no-store/CSP. These are definition checks, not execution of thirteen business operations. Tenant-demo
Office remains unprovisioned with non-cacheable 404; Office features closed, KB write false, pilot 0. Six exact remaining
Work-E2E containers were removed; disposable runners were already absent. Test PostgreSQL and both restore services
are stopped. Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) are unchanged; all three synthetic recovery
databases, dumps and receipts remain retained. The isolated main restore target was refreshed only from its verified
current main backup. Webcut running(7), all three provider nodes/listener 26443 unchanged, Tricert absent. No main
migration, ordinary business-content write, tenant/pilot/indexing/cloud/DOCX activation occurred. Recovery and both
release gates preceded rollout. All operations used host locks and fresh lifecycle inventories.

Previous item 262 host verification at 2026-09-21 15:18:55 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`132526da7a34`) with pilot explicitly 0;
bounded startup retries reached healthy at 15:17:23 UTC. Live verification at 15:18:18 UTC confirmed all thirteen Office
OpenAPI operation definitions, discovery/history parameters, paragraph and existing controls, local assets/licenses,
Work link and no-store/CSP. These are definition checks, not execution of thirteen business operations. Tenant-demo
Office remains unprovisioned with non-cacheable 404; Office features closed, KB write false, pilot 0. Six remaining
exact Work-E2E containers were removed, with the disposable runner already absent; postgres-test, postgres-restore
and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) remain unchanged; both old
and new synthetic recovery databases/dumps/receipts are retained. The isolated main restore target was refreshed only
from the verified current main backup. Webcut running(7), all three provider nodes and listener 26443 unchanged,
Tricert absent. No main-database migration, ordinary tenant/business-content write, indexing, cloud provider or DOCX
engine activation occurred; isolated test databases ran their required migrations. Recovery and both release gates
passed before API rollout. Locks and fresh lifecycle inventories are recorded in the operations log.

Previous item 261 host verification at 2026-09-21 14:27:43 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`1585ccedc940`) with pilot explicitly 0;
bounded startup retries reached healthy at 14:25:53 UTC. Live verification at 14:27:03 UTC confirmed all thirteen Office
OpenAPI operation definitions, additive history page_size/cursor parameters, new history and existing controls, local
assets/licenses, Work link and no-store/CSP. These are definition checks, not execution of thirteen business operations.
Tenant-demo Office remains unprovisioned with non-cacheable 404; Office features closed, KB write false, pilot 0.
Six remaining exact Work-E2E containers were removed, with the disposable runner already absent; postgres-test,
postgres-restore and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`), MinIO (`98ce365f455b`) and retained
synthetic recovery data are unchanged. Webcut running(7), all three provider nodes and listener 26443 unchanged, Tricert
absent. No main-database migration, new recovery drill, ordinary tenant/business-content write, indexing, cloud provider
or DOCX engine activation occurred; isolated test databases ran their required migrations.

Previous item 260 host verification at 2026-09-21 13:04:19 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`6751b0ddada8`) with pilot explicitly 0;
bounded startup retries reached healthy at 13:03:04 UTC. Live verification at 13:04:01 UTC confirmed all thirteen Office
OpenAPI operation definitions, additive query/page_size/cursor parameters, new discovery and existing controls, local
assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned with non-cacheable 404; Office
features closed, KB write false, pilot 0. Six remaining exact Work-E2E containers were removed, with the disposable
runner already absent; postgres-test, postgres-restore and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`),
MinIO (`98ce365f455b`) and retained synthetic recovery data are unchanged. Webcut running(7), all three provider nodes
and listener 26443 unchanged, Tricert absent. No main-database migration, new recovery drill, ordinary tenant/business
content write, indexing, cloud provider or DOCX engine activation occurred; isolated test databases ran their migrations.

Previous item 259 host verification at 2026-09-21 12:22:11 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`a001838868f7`) with pilot explicitly 0;
bounded startup retries reached healthy at 12:21:23 UTC. Live checks confirmed thirteen Office OpenAPI operation definitions,
new reuse and existing controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned with
non-cacheable 404; Office features closed, KB write false, pilot 0. The six remaining exact Work-E2E containers were
removed, with the disposable runner already absent; postgres-test, postgres-restore and minio-restore are stopped.
Main PostgreSQL (`87a6b37942c8`), MinIO (`98ce365f455b`) and retained synthetic recovery data were unchanged.
Webcut running(7), all three provider nodes/listener 26443 unchanged, Tricert absent. No migration, business-content
write, ordinary tenant, indexing, cloud provider or DOCX engine activation occurred.

Previous item 258 host verification at 2026-09-21 11:32:51 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`fc8312db43b7`) with pilot explicitly 0;
bounded startup retries reached healthy at 11:31:16 UTC. Live verification passed thirteen Office operations, new print
and existing editor controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned
with non-cacheable 404; Office features closed, KB write false, pilot 0. Exact Work-E2E services were removed;
postgres-test, postgres-restore and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`), MinIO (`98ce365f455b`)
and retained synthetic recovery data were unchanged. Webcut running(7), all three provider nodes/listener 26443 unchanged,
Tricert absent. No migration, business-content write, ordinary tenant, indexing, cloud provider or DOCX engine activation.

Previous item 257 host verification at 2026-09-21 07:18:57 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`b4e2756191a1`); bounded startup retries
reached healthy at 07:17:41 UTC. Live checks verified thirteen Office operations, suggestion controls, previous editor
workflows, local assets/licenses, Work link and no-store/CSP. Tenant-demo remains unprovisioned for Office with
non-cacheable 404; Office features closed, KB write false and pilot 0. Migration 0085 is applied: 85 migrations, 95 tables.
Fresh verified backups, nonempty document/review/suggestion recovery and foundation/business gates passed before rollout.
Exact Work-E2E services were removed; postgres-test, postgres-restore and minio-restore are stopped. The synthetic
`collabio_work_e2e_restore` database and verified ignored dump remain retained; normal `collabio_restore` stays separate.
Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) were not recreated. Webcut running(7), all three provider
nodes/listener26443 unchanged, Tricert absent. No ordinary tenant activation or business-content write occurred.

Previous item 256 host verification at 2026-09-18 13:14:20 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`da71b8ef4e53`); bounded startup retries
reached healthy at 13:12:07 UTC. Live verification at 13:13:43 UTC confirmed nine Office operations, comments and existing
version/find/table controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo remains unprovisioned for
Office with non-cacheable 404; Office features closed, KB write false and pilot 0. Migration 0084 is applied: 84 migrations,
93 tables. Fresh verified backups, nonempty document/review recovery and foundation/business gates passed before rollout.
Exact Work-E2E services were removed; postgres-test, postgres-restore and minio-restore are stopped. The new synthetic
`collabio_work_e2e_restore` database and verified ignored dump remain retained; normal `collabio_restore` stays separate.
Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) were not recreated. Webcut running(7), all three provider
nodes/listener26443 unchanged, Tricert absent. No ordinary tenant activation or business-content write occurred.

Previous item 255 host verification at 2026-09-18 12:10:34 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`5414963ff755`); bounded startup retries
reached healthy at 12:08:02 UTC. Live checks verified table, find/replace and version controls in the shell/bundle,
local assets/licenses, Work link, no-store/CSP and five Office operations. Tenant-demo remains unprovisioned for Office
with non-cacheable 404; Office features are closed, KB write false and pilot 0. Exact Work-E2E containers were removed
and postgres-test stopped. Main PostgreSQL/MinIO, stopped restore targets and retained synthetic recovery database were
untouched. Webcut running(7), all three provider nodes/listener26443 unchanged, Tricert absent. No migration was added.

Previous item 254 host verification at 2026-09-18 11:30:20 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`1f30ae972f77`); bounded startup retries
reached healthy at 11:28:21 UTC. Live verification confirmed find/replace and previous version controls in the shell and
compiled bundle, local assets/licenses, Work link, no-store/CSP and five Office API operations. Tenant-demo Office remains
unprovisioned with non-cacheable 404; Office features are closed, KB write is false and pilot is 0. Exact Work-E2E
containers were removed and postgres-test stopped. Restore targets and retained synthetic recovery database stayed
untouched. Webcut running(7), all three provider nodes/listener26443 unchanged, Tricert absent. No migration was added.

Previous item 253 host verification at 2026-09-18 10:50:07 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated (`765b23c23888`); bounded startup retries
reached healthy at 10:47:56 UTC. Live verification confirmed the new comparison/takeover controls in the shell and
bundle, local styles/notices, Work link, all five Office operations and no-store/CSP. Ordinary tenant Office remains
unprovisioned with a non-cacheable 404; Office features are closed, KB write is false and pilot is 0. Exact Work-E2E
containers were removed and postgres-test stopped after evidence preservation. Restore targets stayed stopped;
the retained item 252 synthetic restore database was untouched. Webcut remains running(7), all three provider nodes
and listener 26443 unchanged, Tricert absent. No migration or new backup/restore was required for this UI-only workflow.

Previous item 252 host verification at 2026-09-18 10:17:19 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated (`e2e37654dd3d`). Live checks verified
`/office`, its local bundle/styles/license notices, the `/work` link and all five Office API operations. The ordinary
tenant is not provisioned for Office; its read returns non-cacheable 404, both Office features stay closed, KB write is
false and the normal pilot is 0. All 73 browser cases and final nonempty recovery passed before this rollout.
Exact Work-E2E containers were removed; postgres-test, postgres-restore and minio-restore are stopped. The synthetic
`collabio_work_e2e_restore` database and its ignored verified dump remain in the stopped restore target as evidence;
the normal restore database is separate `collabio_restore`. A future synthetic restore must account for the existing
target explicitly. Webcut remains running(7); all three provider nodes and listener 26443 are unchanged; Tricert is absent.

Previous item 251 host verification at 2026-09-18 08:43:14 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated. Webcut remains `running(7)` and all three
provider nodes remain unchanged (127.0.0.1:26443). Tricert was absent. Work-E2E containers were removed; postgres-test,
postgres-restore and minio-restore are stopped. Live checks confirmed the CRM workspace and KB content/authoring
routes, CRM detail and KB reader in `/work`, the disabled KB write feature in tenant-demo and pilot runtime 0.
Bounded health retries covered startup connection resets; health and the cold OpenAPI check then passed. The live
CRM read returns 503 with the exact existing dependency error `Productivity pilot authorization evidence is invalid`,
before reaching the CRM repository. The first smoke check expected 403/423 and failed; the repeated check explicitly
verified this fail-closed evidence error. No pilot evidence was repaired or activated. The isolated blocked process
with synthetic valid scope evidence separately proves its expected CRM 403; these are distinct checks.

## Non-negotiable boundaries

- Tenant isolation, authoritative ACL, ABAC, role and module/feature gates stay server-side.
- The normal switch stays `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. Synthetic tests never authorize real users.
- `knowledge_base.articles.write` defaults false. Only the isolated synthetic E2E tenant enabled it for this slice.
- Native Office uses `office_documents.documents.read` and `.write`, both closed by default. Migrations 0083–0085 do not
  provision or activate an ordinary tenant. Native documents do not authorize a DOCX engine or WOPI session.
- No real tenant module activation, KB runtime activation, business article write, pilot admission or traffic
  authorization was performed. Tickets & Incidents remains readiness-only pending separate explicit authorization.
- RAG and keyword indexing remain false. No LLM receives unauthorized data; retrieval requires authoritative ACL
  revalidation. Cloud AI requires tenant policy and all providers remain behind the Local LLM Gateway.
- Article/prompt/output bodies must not enter ordinary logs or audit metadata. LLM output is untrusted.
- Destructive, external and compliance-relevant actions require explicit human confirmation.
- Do not invent accountable principals, legal basis, privacy/workforce approval, independent review, signatures,
  production topology, PITR, offsite recovery, HA promotion or cross-site evidence.
- The project does not use AWS. Preserve provider-neutral/self-hosted architecture. No external legal review exists;
  do not claim certification or production readiness.
- No further Word-runner/account/firewall interventions on the original workstation. The separate disposable
  Windows test path only supplied a manual DOCX check.
- Fidelity private keys stay solely as Windows CurrentUser-DPAPI ciphertext under
  `C:\Users\tkirchherr\.collabio\signing`; never send them to Git, Docker or dev001.

## Development stance

Close coherent, user-visible product loops. Reuse the Platform Module System and the existing tenant, rights,
audit, classification, retention, Legal Hold, KMS, backup, restore, failover and decommission contracts.
Do not start preparation-only infrastructure chains without an immediate product or operating need.
Prefer mature maintained open-source components behind provider-neutral interfaces, reviewing credible alternatives
before adoption. The user's priority is Office development before further CRM expansion. Extend the native Office
workspace next; DOCX Quick Edit, full collaboration and Mail retain their separate extension points and release gates.
Commit and push verified slices; synchronize dev001 only with git pull --ff-only under git.lock.

## Last completed slice: Roadmap 267

Roadmap 267 / PLANS 128 adds document-owned named paragraph styles under ADR-0090. The Formatvorlagen dialog
provides body/title/heading presets, custom names, six bounded presentation fields, inert preview, selected/affected
paragraph counts, shared updates, application and removal of bindings. Texttyp remains the separate semantic control.
Optional root attrs.styles contains up to 20 strict definitions; paragraph/heading styleId binds one definition.
Application clears direct paragraph values; inline marks remain overrides. Shared updates affect every bound block,
including nested list/table paragraphs, while direct overrides retain priority. Removing a binding preserves text
and the reusable catalog. There is no global library or definition-deletion workflow in this slice.

Current editor/session/context/revision/document/selection/pending-mark checks, read/history/busy/uncertain/review/
suggestion guards, full schema/size validation and isolated undo apply. Confirmed CAS Save creates an immutable
version with its catalog. Comparison shows effective style descriptions and unused catalog changes. Printing,
historical mounting, search/replacement and independent reuse preserve the version-owned metadata. Existing native
v1 identifiers and legacy canonical bytes remain unchanged. This is an additive durable-format extension without
a new SQL table, endpoint, dependency or engine admission; it requires fresh nonempty recovery before rollout.

The first static run found an imprecise heterogeneous enum-map annotation; the corrected focused Python run on
f7dcd55 passed all 414 cases in 21.90 seconds, Ruff and Mypy on 567 source files (one known Starlette/AnyIO warning).
The first 16-case browser run passed 13. Product creation incorrectly used secure-context-only crypto.randomUUID;
94af79a reuses the existing getRandomValues-based UUID helper. Two new test sequences were corrected to convert a
heading back to a paragraph before list wrapping and close the still-open print preview before document reuse.
Existing product assertions were not weakened. An intermediate rerun failed before tests because seed principals
already existed; only the exact isolated tmpfs E2E services were recreated for the fresh passing run.

All 16 focused cases passed on 94af79a037386dd2b900fcb31bb0b13f916a3684 in 39.855151 seconds, starting at
2026-09-22 13:03:56.940 UTC, with zero skipped/unexpected/flaky. Ten workflows, two responsive runs and four model
cases cover creation, shared updates, direct overrides, typing marks, structural transforms, catalog/byte limits,
cancel/no-op/undo, reader/history/context guards, uncertain saves, immutable versions, comparison, real PDF and reuse.
Root reviewed desktop/tablet/mobile screenshots: no horizontal overflow; mobile controls are reachable by scrolling.
Focused evidence is retained under ignored e2e/work/artifacts/roadmap-267/focused:

- Report: sha256:78b7f38e324ead4ff963068552bdf799538231cb60610a50eb1e150c33a6e0dd.
- Browser log: sha256:6f0e071951a9bba120f8d67e7662bd9824c3371c83691aeb0ee9b1b48ce2151a.
- Python log: sha256:d6c8797047e4493c1b9dfd5053aa57228d0961aa631e013460717e8151ffe450.
- Failed browser report: sha256:7dae005bf82fe3643f2d32bfa77b9a29cd955663981d5851835292576a74cc32.
- Seed rerun log: sha256:38bea8611e3e62fc70351747b899295dbc110e2db0c8c109953daf3425f316e1.

Original static/browser failures and traces are retained separately under roadmap-267/failed-focused. Final full-quality, matrix, PDF and operational evidence follows below.
The separate docs/modules/OFFICE_IMAGES_AND_OBJECTS_CONCEPT.md proposes native PNG/JPEG insertion followed by inert,
version-bound file/table/chart references. It is not implemented image/object support. Office remains before CRM.


The first complete run on 94af79a passed full quality and 270 of 280 cases in 1019.894177s, starting at
2026-09-22 13:05:57.286 UTC. All 233 browser cases passed; ten existing comparison-model cases rejected unnecessary
copies of unchanged source blocks. The initial progress summaries inspected only recent log lines and missed those
earlier failures; the final report is authoritative. Failed reportsha256:bb63aa048babb8003f74516e643d805141bab9fa97c735467ea8643f24d23401
and logs/traces/screens/PDF remain under ignored roadmap-267/failed-full. No rollout occurred.
Commit 1e09a106be3505457d5eca9060797a132dc80f1e preserves references for every unchanged subtree, copying only bound
styles or changed descendants. Existing assertions remain intact; the style model additionally checks unbound blocks
and unchanged inline contents by reference. All 20 affected comparison/style model cases passed. The corrected full acceptance on that immutable source is recorded below.


Final acceptance on immutable 1e09a106be3505457d5eca9060797a132dc80f1e passed full quality (Ruff, formatting across 748
files, Mypy on 567 sources and complete Pytest, only the known Starlette/AnyIO warning). The single complete matrix
passed 280/280 (233 browser+47 model) in 1029.824630s, starting 2026-09-22 13:26:04.752 UTC and finishing 13:43:14 UTC;
zero skipped/unexpected/flaky and both process exits 0. Root reviewed final style desktop/tablet/mobile, mobile comments
and the actual PDF page, and matched all 11 final artifact hashes locally. Mobile style actions are scroll-reachable.
No independent-agent, non-Chromium or operating-system print-dialog proof is claimed.

The actual tagged PDF is one A4 page (594.96x841.92pt), with 279 extracted characters, expected headings/paragraphs/list/
table/code, literal Unicode, preserved blue24pt style and explicit bold. No empty page, missing expected text, UI chrome,
clipping or overlap was found. Normal API access logs contain none of the checked synthetic style/content markers.
Ignored final evidence under e2e/work/artifacts/roadmap-267/final:

- Report: sha256:0306d0e3226d31275a52d11d667e4c2d9f011804905dba73c1e08053d5fded88.
- Browser log: sha256:0405c83720892bfd679eecc865f58a9536e933fb680bf280fdc247b41dd07595.
- Quality log: sha256:42ffb311f52a97483e15c8fb5cd6956f19bf15ce87a1fec20c66c3e4ba497617.
- Access log: sha256:df4db7ab47d76d49fc0f32a28dddc7d34c78a39acb29aab31398c1ab319ccf31.
- Actual PDF: sha256:d85daa38834ea64bb9fc78a3f762cc11d32c39233e38ecd2099acf3221e64389.
- Style desktop/tablet/mobile: sha256:e66d3f291aa64f657f16b91353d142dffbb9a331193302aa65a15b10dd866f55,
  sha256:7b5b30f2244732e37b83fb061357ab03be30f967c6392ee702d14fd47863491d,
  sha256:6c3b746b37c5da0db9878cd12a56d572239465b921dc9d15fa5f8b878135f56b.
- Review desktop/tablet/mobile: sha256:575cd99b830fe019011e4be6edf992c5e439745d39054d662d609d3f89e1333b,
  sha256:2bafd01e01efac6698d0c9ea15f7d449ca704f6d259509dd7340ba7d068383b4,
  sha256:64eda176f3618bf7a7421f580b2bee6abef0b4ad1ce473931bab2bbbfe22162d.


Fresh nonempty recovery completed at 2026-09-22 13:46:58 UTC on 1e09a10. A separate checked dump/catalog/receipt
restored collabio_work_e2e_267_restore; the three older synthetic databases/dumps/receipts remain retained. The proof
verified 392 documents,763 immutable Office versions,80 multiversion documents and 818 exact-version source objects.
It includes10 review threads/18 events and11 suggestions/7 decisions (5 accepted,2 rejected), existing paragraph and
character fixtures, and3 designated style fixture versions (legacy plus2 styled states, including an unused definition).
Legacy canonical hashes, exact catalogs/bindings/overrides, receipt bindings, current authoritative read-only access and
foreign-tenant denial all passed. No source content is included in the report; runtime and engine remain closed.

- Synthetic dump: sha256:e3671a84e535c2a40e9112643f41308876a2cabb130da0eab6f24d6798ab45fc.
- Canonical recovery report: sha256:79d0a9f472f8cdefb7e854c882703126ae8c3f19c1240a1c2913985a72396a59.
- Recovery JSON file: sha256:582f21ce775af7011a62f5c4736f8808b28afaf4c49cbbfe0a682acbf72b4984 (matched locally).
- PostgreSQL restore report: sha256:d2b8647b211fe27375117ab2e630eb76b4e33b7df78ff94b49358e4fb6947858.
- Exact-version object restore report: sha256:aba1e68fef537d3fef8de286599197ebacf20e62054a79c9cdee54349195aa5e.
- Style evidence: sha256:729d7792e70aaad3a8d16e8530142ce17f2d2033560d6753b86b78d270fa6a7d.
- PDF QA report: sha256:99a4c997452a0b6bd05688ed6108ef7016ec6d82462c16d3b2c248c0461ed813.
- Rendered PDF page: sha256:70c930a15ad8469de08c8a83050423af607d4321d33c4bafdcfccd48e06593fb.


Main backup collabio-20260922T134724Z.dump verified successfully and refreshed only the ordinary isolated restore
target. Backupsha256:527ded83d30ea5db6be367c4f7e8bb52477f716544c7a3574d245571abbcc8c2; bound PostgreSQL restore
reportsha256:31bb91eb9492ea699440da7df07be784446d86744bda83a5142e3a7a108a3565. No main migration was required.
Foundation at13:47:36 UTC verified 85 migrations,95 tables, three restored source objects across two tenants and all
existing controls; gatehashsha256:6144b3ac095cb4583cdeaa0ce11283ccac0b9c6a61b5ad911b88df4597d8e11f.
Business release at13:48:24 UTC is ready with no blockers and no business write/tenant activation;
gatehashsha256:50696dd57740f8934cc80e8dcbe6e4b54606a07da7b376dc63d1cf018a611041. Both preceded API rollout.
Foundation used SUITE_SOURCE_OBJECT_RUNTIME_SEED_DEMO=0; loader and checks used --no-deps with checked prerequisites.

## Previous completed slice: Roadmap 266

Roadmap 266 / PLANS 127 adds a selection-bound list dialog for indent/outdent and ordered-list starts from
1 through 1,000,000. Selected siblings move together; contained sublists, text, marks and paragraph attributes
survive. Outdent at the outer level produces paragraphs. Start changes apply to the nearest entire list, leaving
other lists alone; automatic continuation and named numbering styles remain outside scope.

Alt+Shift+Right/Left and outside-table Tab/Shift+Tab use the same prevalidated transactions; table Tab still moves
between cells. Unsupported selections cannot fall through to default list commands, and unavailable Tab actions
leave via a reachable toolbar control. Actions preserve pending typing marks and one isolated undo group. Invalid,
cancelled or no-op changes stay clean. Schema, character, node, depth and canonical-byte guards run before dispatch.
Editor/session/context/revision/document/selection/stored-mark snapshots invalidate stale dialogs. Existing
reader/history/busy/uncertain/review/suggestion boundaries and confirmed CAS saves remain mandatory.

All twelve focused cases passed on fb8dbd3 in 31.591574 seconds, zero skipped/unexpected/flaky, starting at
2026-09-22 10:26:00.778 UTC. Ten workflow cases include genuine saved versions, unchanged historical content,
comparison/print preview, keyboard priority, denied scopes, pending/uncertain saves and exact rejected depth/byte
fixtures. Two responsive projects and root's three-viewport review confirmed reachable controls and no horizontal
overflow. Report under ignored e2e/work/artifacts/roadmap-266/focused:
sha256:a46840d97f7170b1bee7718e02bbb147f87b4840fc226eca2ac4b52e9cb80893.

No backend, endpoint, schema, dependency, native format or durable contract changed. Roadmap 263 recovery and
release-gate evidence is retained; no new recovery, PDF-generation, independent-agent or non-Chromium proof is
claimed.

Full quality passed Ruff, formatting across 728 files, Mypy on 562 sources and complete Pytest, with only the known
Starlette/AnyIO warning. The complete matrix passed all 264 cases (221 browser + 43 model) in 967.211454 seconds,
zero skipped/unexpected/flaky, starting at 2026-09-22 10:30:40.689 UTC and finishing at 10:46:48 UTC. Both process
exits were 0 on immutable fb8dbd3. Root reviewed final list desktop/tablet/mobile and mobile comments, and matched
all nine final artifact hashes locally. Ignored final evidence under e2e/work/artifacts/roadmap-266/final:

- Report: sha256:7ae92a1f0dcdf8a9ede01bde58ab50ac460b534058a359963fd0d11220e86df8.
- Browser log: sha256:78c9ecfddb0d714a9e7422dc433775b6c67c56382e65f5a21d5054008ee4b9ad.
- Quality log: sha256:f86a759834d1f1adc1de1d063482db07b499767521a5e889bbaa0af28eabba4b.
- List desktop/tablet/mobile: sha256:d099d8eb920c87ad1162e51649199da4bb8c9ce85328ccca6339d5d0f55e08bf,
  sha256:16e167b29bc69ef07ca65930d1d5a680005ae0da8981160bf1c008565213b599,
  sha256:12be4be53d18dc1f95bd26abe63d7b53755e92f0d3d4038a04d52be86850c841.
- Review desktop/tablet/mobile: sha256:80b3f6a55f11b1dbf849b0e4f539afd8d06fe84ad10ca24b021df1c894764609,
  sha256:54d20f45d54cb147486805307c8f6e0546f851995bca9b3ff6caba3cfeef61d0,
  sha256:53ef3cb5f20f9d3ede79d9cf22e2e178802edc03654c7d0359fb0cf41d387225.

## Previous slice: Roadmap 265

The **Format übertragen** menu captures uniform direct character and paragraph formatting and applies characters,
paragraphs or both to the target selection. Empty values are defaults, so a plain sample clears selected formatting.
Character transfer respects exact Unicode/cell ranges or pending caret marks; paragraph-only application preserves
pending character choices. Text, heading levels, lists, tables, code and unselected content remain intact. Mixed
sources are rejected with guidance. Capture/discard/no-op stays clean; a document application forms one undo group
separate from typing. The full schema/size preflight runs before dispatch. Only the normal confirmed CAS Save creates
a durable version, and old versions remain immutable.

Samples contain only normalized presentation plus editor/session/context references in memory. They are cleared on
remount, close and context change, including the accessible status description. Reader/history and existing busy,
uncertain-state/review/suggestion guards remain mandatory. There is no clipboard, browser storage, source-text copy,
cross-document sample, computed CSS, named style or block-type transfer. ADR-0088 records the boundaries. No backend,
dependency, migration, schema or durable-format change is introduced.

The first focused run on 655a00c passed nine of ten cases and exposed the stale accessible sample description after a
context change. Its report and diagnostics remain in ignored roadmap-265/failed-focused. Correction 068152f clears the
description and preserves pending caret marks during paragraph-only changes. All 40 focused transfer/character/
paragraph/keyboard cases passed on that commit in 147.939598 seconds, with zero skipped, unexpected or flaky results.
Focused report: sha256:0fcb8da497f6c863a0ecb7f1857373109389321af40bc627c132ed1ef89ad336.
Commit 2d42293 adds the ADR and an explicit historical-view assertion; product code is unchanged from the focused run.

Nine workflow cases and two responsive project runs add eleven checks. Root reviewed desktop, tablet and mobile for
readable content, reachable wrapping controls and no horizontal overflow. No independent subagent, non-Chromium or
new PDF review is claimed. The first full run on 2d42293 passed quality and 251 of 252 browser/model cases. The
additional toolbar row reduced the mobile review area enough to put the open thread quote below the viewport.
Correction ac70c29 positions mobile comments/suggestions between the app bar and footer independently of toolbar
height, retaining history/outline placement. The first layout correction fa00102 passed 41/43 but covered history
controls; it was narrowed to review drawers with their own close actions. Existing assertions remain unchanged.
That failed layout report/trace is retained under roadmap-265/failed-layout-focused, report
sha256:acd6dd9bca3c25882359248c4ff835e5a7574fadca281395e4901c0ad8ed2e72.
The failed full report/logs/trace are retained under
roadmap-265/failed-full, report sha256:b2ce2c257f2575a0285f581886f3e752f80be890946728a1c005fa761505ccf9.
Roadmap 263 nonempty recovery and release-gate evidence remain retained, not rerun, for this unchanged durable format.
All 43 responsive/format-transfer cases passed on ac70c29 in 235.258831 seconds, zero skipped/unexpected/flaky.
Report: sha256:60cdcd6a89e42b3afe5b04adec05ec035c48334b65e9c00a14ef493f73eeebba. Root inspected the corrected mobile
review drawer and the desktop/tablet/mobile transfer screenshots.

The final ac70c29 matrix passed all 252 cases (209 browser + 43 model) in 908.294889 seconds, with zero skipped,
unexpected or flaky results, finishing at 10:04:02 UTC. Full quality on that source passed Ruff, formatting across
727 files, Mypy on 562 sources and all Pytest tests, with only the known Starlette/AnyIO warning. Both process exit
codes were 0. Root reviewed the final desktop/tablet/mobile transfer screenshots and mobile comments and matched all
nine final report/log/screenshot hashes locally. API-only rollout and the final closed-gate host state are recorded above.

Ignored final evidence under e2e/work/artifacts/roadmap-265/final:

- Report: sha256:41e8cc172dbdba55b580f75e76ca09245b933f279b07fb806fce52e5d293a899.
- Browser log: sha256:65cf557db8954241b6ac18ef6b5e9d065e87aff990908f1106ce93c87da43a4c.
- Quality log: sha256:c79ea12ebf98aad1a48fcc5275cf8bd2e9c5f83cd2b5b50e2a2cbadf87bb2586.
- Transfer desktop: sha256:099ebc2c36efc61c17b3b25150c631985f151ba30cce0fd994589bd34d908cec.
- Transfer tablet: sha256:410ad13975e17cae399d9ab3099f5a11d50f9080ccf65796882f0256e57d2a41.
- Transfer mobile: sha256:9c4743191e4357c33494899363226112a4adbca8b4cf34a3f158cf611f5ca136.
- Review desktop: sha256:f90bfaaf675178988772e5e7382dd59ae10bf63466be6d8fd2370db7387b77bf.
- Review tablet: sha256:7ae0506bfa275e0d2bc71c76335c875895ce98d008c56f7fdf4959723937f9aa.
- Review mobile: sha256:6d10fc148dd04166d73ec7c983cf94758f31ab55b5b3e503852230f1d7dd23ab.

## Previous completed slice: Roadmap 264

Ctrl+A/Cmd+A uses structural AllSelection, including tables at either document boundary and a selection started
inside a cell. Cancelable beforeinput prevents Chromium from mutating table NodeViews before validation. Whole-document
typing, plain-text paste, Backspace/Delete/Enter and cut prepare plain paragraphs and require the existing table-removal
confirmation when tables are present. Empty replacement leaves one paragraph. Cancel/Escape preserves content and
selection; confirmation checks the session/editor/revision/document/selection/editability snapshot again. One replacement
is one undo step separated from adjacent typing. Undo restores exact tables, paragraph properties and character marks.
Saved versions remain immutable; only the separate confirmed CAS Save persists the new draft. Cut copies plain text
before confirmation, but removes content only after it. No schema, backend, dependency or durable-format change exists.

The original failure was reproduced in a dedicated rich fixture. AllSelection alone still failed, establishing the need
to intercept native input before DOM mutation. The first early --no-deps rerun also exposed an API-readiness race in the
exploratory script; subsequent focused starts use --wait. The final test contains no diagnostic content logging.
All 26 focused keyboard/table/history cases passed on 460d632 in 94.556794 seconds. The history draft case now owns a rich
head ending in a table and confirms replacement before exercising concurrent history and local review draft preservation.
The complete d7270a7 matrix passed all 241 cases (198 browser + 43 model) in 873.553288 seconds, with zero skipped,
unexpected or flaky cases, finishing at 08:00:32 UTC. Full quality on the same source passed Ruff, 722-file formatting,
Mypy on 562 source files and all Pytest tests, with only the known Starlette/AnyIO warning. Both process exit codes were 0.
Root reviewed desktop/mobile confirmation screenshots. Clipboard tests use synthetic DataTransfer/ClipboardEvents;
no OS clipboard roundtrip, IME, non-Chromium, independent subagent review or new PDF proof is claimed.

Ignored evidence under e2e/work/artifacts/roadmap-264:

- Focused report: sha256:4c1ff3f7ec42e62a2a816ac32009f64034190137806eb5e39c8cc90cf0bdc310.
- Focused browser log: sha256:4df089e6a79c005872706960be6c30186719bc6d702bb0afb5b412aae2092fee.
- Complete report: sha256:a40528f367d8a032d2d2d2a0ae53304d5172b58e7c7c621a8bccdcaa0bf63efc.
- Complete browser log: sha256:2c78d8b26e6ceddf22b4e3a80a1b771e21a3c3d44d2ca2ca24c3268f0695df61.
- Full quality log: sha256:fa15e300bf3abc15289f6b91106e0085a63428d696806007097e570105e681c8.
- Desktop screenshot: sha256:503846f9e257ec45d99b92807609639fa9887cd7208852116c296bda54ca0543.
- Mobile screenshot: sha256:f3ce324e6d6f8b0b3b4c9fff089c235ac1602718e93b32cfb4154dc094a3662f.

The original failing reproduction remains retained. This is a single all-green matrix, replacing the combined
acceptance method of Roadmap 263 without erasing its historical reports. Its complete nonempty recovery and release
gates remain retained; no new recovery drill or main migration was needed or claimed for this UI-only slice.

## Previous completed slice: Roadmap 263

The selection-aware **Zeichen …** dialog supports fourteen font sizes from 8 to 48 points and eight named colors.
It changes selected text, including headings/lists/quotes/exact selected table cells, or the next typed text at a
supported caret. Mixed values remain unchanged unless chosen. Standard removes one property; reset prepares both
properties for explicit Apply. Cancel/no-op stays clean; caret choices do not dirty saved content. One selection
application is one undo step separated from adjacent typing. Code remains excluded.

The optional strict textStyle mark preserves native v1 identifiers and unchanged legacy canonical bytes, hashes and
receipts. Invalid values, CSS strings, unknown attributes, empty marks, nulls, code combinations and block placements
are rejected. There is no SQL migration, dependency or new endpoint. Rollback editors must understand the mark.
Only fixed data attributes/CSS reach editor and print. Comparison names sizes/colors; replacement distinguishes full
mark attributes so differently formatted adjacent text cannot merge. Fresh rights, exact version references, explicit
confirmed CAS saves, uncertain retry and memory-only drafts retain their existing boundaries.

Validation lineage: product implementation d235b6b; a0b3001 adds only explicit test-fixture types; 0fcf212 changes only
one history-test input to keyboard replacement and asserts the draft before navigating history. The final test-only
75f381a gives that history case its own starting head instead of inheriting a prior rich-table takeover. Full quality on
a0b3001 passed Ruff, formatting, Mypy on 562 sources and complete Pytest at 2026-09-22 06:48:44 UTC, with only the known
Starlette/AnyIO warning. The first full browser matrix passed 230/231 in 876.201937 seconds. The failing history test
had already failed to enter its draft before navigation: Chromium's contenteditable fill produced an invalid empty
table, and the existing document guard correctly rejected it. The keyboard-only correction still failed at the new
immediate assertion. A second complete run on 0fcf212 retained
230 passes and one setup failure in 1020.268560 seconds. The final isolated setup on 75f381a passed all eight history
cases in 31.423815 seconds. All 231 distinct cases have passing evidence (188 browser and 43 model), combining the
230 full-run successes with the corrected complete history suite. This is not a single 231-pass run; both raw failure
reports remain retained. No product guard or assertion was weakened. Whole-document keyboard replacement across rich
tables remains an explicit follow-up usability investigation; fixture isolation does not claim to fix that input path.

Earlier focused checks passed 362 Python/API/PG/recovery tests in 19.18 seconds and all 21 browser cases; a comparison
model assertion was corrected to inspect the description text and all four new model checks then passed. Root code
review and six Office/Work screenshot reviews found no remaining character-formatting issue. This turn did not use
independent subagents.

Evidence under ignored e2e/work/artifacts/roadmap-263:

- Initial full report: sha256:580e4e50f20e9694506ca105a1d4914942a9edeff65b2538e64647c763dad304.
- Initial full browser log: sha256:04128a67d2bd6ee1e2132b7373d3e2e097bf3b72d9220113e983fcfac2322bc8.
- Final quality log: sha256:50dc41d7ef0d6193a0a6552292e4efad0de6d4cedf9ff14934bbe55bce99e754.
- Corrected character-model report: sha256:2e1e6e61c9e800d71bf11585564ebfd521df61dfebb89a76c3e05313ea3161e3.
- Focused Python log: sha256:b2977274bc79683e51e22919dd6ac7854d455af6cd5e01540d167c2016267fbd.

- Second full report (230 passes, one retained setup failure): `sha256:2c902182d91ffe224d63d70c503ae28e1ad509ae15acbd4bca76afbd17abbec0`.
- Second full browser log: `sha256:ce700e10077611aca860a748648745863830102e503a6a71e775808c6da0250a`.
- Corrected eight-case history report: `sha256:35d3111f2630f7b699ef822942f29484237d1604707db12e2f2cac3e49d165d0`.
- Actual PDF: `sha256:caf2da90f8834ad3f10ea054929f318c5dca4db3dfefbcc65c8d9effafed761a`.
- PDF QA report: `sha256:0330e6e9c8247b984db31452675a564d642630323034f8ffdbbfd73cba4845d3`.
- Office desktop/tablet/mobile/print-preview hashes respectively:
  `5713c2b51517a7a5f7c5fd8fbeaa9a5f286dc90457dddb0357c1063a90fb8ea3`,
  `3a41543ec464917cfaa042096b0add557f547441a34c50bcbc42f52f1ace1a69`,
  `f308f8d1333fdde9520b528ef799e06882f777fb3a6c9245150a14171f328b37`,
  `501cc442fe57614cb113e7b849af6991118f4537905326038727f8f9468a76ac`.
- Work desktop/mobile hashes: `d233fd33100538aa6382bd0b60d4f0797a44a38600c0b36517de8c945e6942f3`,
  `3c315fd4e7fede1e8b526f5a3ff33b34ea2aed35b3c58a560714106b87b73965`.

The actual PDF contains two nonempty A4 portrait pages, 2,108 extracted characters, all 24 ordered paragraphs and both
sentinels with H1/H2/P structure. Root visually reviewed both rendered pages. Access-log inspection at 07:05:49 UTC
verified 752 list and 445 history records without query/cursor values. No independent-review claim is made for this turn.

Fresh recovery into `collabio_work_e2e_263_restore` completed at 2026-09-22 07:13:41 UTC. It verified 460 documents,
935 saved versions, 116 multi-version documents and 1,045 source objects using complete authorized pagination.
One unchanged legacy character version and two distinct saved size/color profiles passed, alongside all paragraph
profiles, 20 review threads/36 events and 22 suggestions/14 decisions (ten accepted, four rejected). Exact source
versions/receipts, current parent ACLs, read-only restored services and foreign-tenant denial passed. All earlier
synthetic targets and their dumps/receipts remain retained. The complete test matrix ran twice against this synthetic
store before the final targeted correction, explaining the larger inventory; this is not ordinary tenant content.

- Synthetic dump: `sha256:9866eb2c501e7713efcb8661a20b3ae86917a71c4e8f773ddaf1f578ceaf5519`.
- PostgreSQL restore: `sha256:891768bd28818c110c89beb665ff0b87db4cc0c3b482eeaadcf977eae464ce29`.
- Exact S3 version restore: `sha256:f16f23b1d99a28bc9b8ecc063426cff4e4e2b0ca8d53e86ea05f31141f6d47de`.
- Embedded recovery report hash: `sha256:9321026e05318ef59d6bd52216fa46c5a20bd9dc3532fd8a8c39ebf296deb0fd`.
- Recovery JSON file hash: `sha256:f8b3f4fdd2545ce3ea5fc240d8d9701ce0569b3b0d24314dad7bae4d7e19ca64`.

Root recomputed the canonical recovery report hash from its metadata. Main backup
`collabio-20260922T071403Z.dump` (`sha256:7d65a6204400f7e044a102e073d96e219e5f07ffa83f008f0e1289746c053775`)
was verified and restored only into the existing isolated main target. Foundation at 07:14:17 UTC verified 85 migrations,
95 tables and three existing source objects with seeding explicitly disabled; no migration was applied.
Foundation: `sha256:83a11bbd91525f416261d9a171ffc7c114b4eb11bd5eaa86a998d6d21a640428`;
bound main PostgreSQL restore: `sha256:52d52f2b1270cee6a897af98a85f201171651cc90e899304ce3a1ee7eaef1d2a`.
Business release at 07:15:03 UTC: `sha256:be604e0d9496af80d56d27f21683b2c9c68472fefe72f1bf6744e3495f166bef`;
all three existing business slices passed, with business writes and tenant activation false. Native Office has the separate
nonempty proof above. API rollout, live gates and final host state are recorded near the top of this handoff.

## Previous completed slice: Roadmap 262

The compact selection-aware paragraph dialog formats paragraphs and headings, including those inside lists, quotes
and table cells. Alignment supports left, center, right and justify; line spacing supports the exact strings 1,
1.15, 1.5 and 2; before/after spacing supports integer 0, 6, 12, 18 and 24 points. Mixed values remain unchanged
unless selected; Standard removes an attribute. Reset prepares defaults for explicit Apply. A no-op stays clean,
and one application is one undo step separated from adjacent typing. Historical/read-only views retain their gates.

Strict server validation rejects unknown or malformed values without mutating input. Optional attributes preserve
legacy canonical bytes, hashes and receipts. Selection, context, revision and document checks prevent stale edits;
resource limits are checked before applying. Heading shortcuts/input rules, split paragraphs, replacement, reuse,
version comparison and print preserve formatting. Only fixed allowlisted DOM attributes and styles are rendered.
No new endpoint, dependency or SQL migration is introduced. The native MIME and collabio_document.v1 remain unchanged.

Acceptance on immutable `8b61d8d`:

- All 294 focused Python/API/PostgreSQL/harness checks passed in 18.05 seconds. All 46 focused browser/model checks
  passed in 150.538659 seconds, with zero skipped/unexpected/flaky.
- Full quality passed: Ruff, formatting across 712 files, Mypy across 557 sources and complete Pytest; only the known
  Starlette/AnyIO warning remains. All 215 checks (176 browser + 39 model) passed in 759.313613 seconds at
  2026-09-21 15:10:02 UTC, zero skipped/unexpected/flaky, preserving all previous 200 cases.
- Independent backend/UI/test reviews found no remaining material defect. Root and independent visual review passed
  four Office views, two Work screenshots and all three actual PDF pages. The A4 portrait PDF contains 5233 extracted
  characters, all 28 ordered paragraph markers and both boundary markers, H1/H2/P structure, and no empty page.
- Actual Uvicorn logs verified 349 document-list and 219 history records without query/cursor values at
  2026-09-21 15:10:45 UTC.
- Focused report: `sha256:312bf9c8d93747ad8ce7e5cb8a99400ee075bc4998b141f1039e711fc61dbe7f`.
- Focused Python log: `sha256:0c73376a480c923e0e77292ca7ec307c79c76cd2f72c67ca020dd7c29b1145b9`.
- Final report: `sha256:b9d422791168a5f1a8dc710eb1574a28fe373a928c44c11227bbd981380d71a6`.
- Quality log: `sha256:e60159bdafa33d3854347d8fdf6fc5f55bc4bb87c630f8e6ebdbefe6240d358c`.
- Browser log: `sha256:cdd7dcf868769ec4f793971b0f438294f42d455351224abedc0b3059dbfbf35b`.
- Actual PDF: `sha256:ab04640d1bb33ad12712de3303fa98037ebad2ae1ff7689baac1419de608222f`.
- PDF QA report: `sha256:b271848bc5b5c2e3f13f6a2c99621d64f69600cb203946d8ee5eb56ae17023b1`.
- Office desktop/tablet/mobile/print-preview hashes respectively:
  `61443567cee46b6406a77388c9eacfd11d5de4ba92c49071262b875a2bad2872`,
  `e0e39c57ce1ca7c317c6fccd4f0afdc5befb2e85f55fb91f87e05196fc090754`,
  `6d3cee2186d104ffe1a15f7ac01aafdf54221f08a9fc1bbfe0aa4aee9bfef827`,
  `39aeddbcc3b2d93d77488117b6394fce8e3f027c009e5c66af566edfda50e7ac`.
- Work desktop/mobile hashes respectively:
  `7d40106046bf015678a36f48f3f11d81bbf4949debe3056dba65a4b65f617192`,
  `c1152844fab0cdf1819eb04e899507b04e9908c3a7adc1e0459952afadb8b851`.

Nonempty recovery completed at 2026-09-21 15:13:34 UTC against the new isolated database
`collabio_work_e2e_262_restore`; the previous `collabio_work_e2e_restore` remains retained. Complete document/history
pagination verified 330 documents, 666 versions, 50 multi-version documents and 721 source objects. Active database
principals, roles and groups supply authoritative read access; no extra grant or synthetic super-role is introduced.
Immutable predecessor/head inventories, exact source versions, receipts, ACL denial and read-only behavior pass.
The designated three-version fixture proves unchanged legacy bytes plus two distinct formatting profiles inside
paragraphs, headings, lists, quotes and table cells. All ten review threads/eighteen events and eleven suggestions/
seven decisions (five accepted, two rejected) pass the shared checks. No content is included in metadata evidence.

- Recovery report internal canonical hash: `sha256:bfc720ee2ec275061c5f934369a5864259071d5409f7bd4f99368b431951c7f7`.
- Recovery report file hash: `sha256:bb02922322b46b09627d9c3f842534fda0cabec5d7ab541c58f0500e60fdd94c`.
- Backup: `sha256:a4481417a96ebff0af7070bf817fcf5ad01e975e9f4fa909717c906e947379f7`.
- PostgreSQL restore: `sha256:f5b5ebfe499f6164efc6381758ed8bed548d8d1e0dfec150f07f17f462234935`.
- Exact S3 restore: `sha256:54086c3bbe49cc6576ee1c0ee60ee1f9a239dffa9c9685572587023c11b32b76`.
- Paragraph evidence: `sha256:1b58df7dd469f375e85291e229b5b1daf635229fe44b743dc3bc6f227fe5dff5`.

A separate current main-database backup was created and verified, then restored into the existing isolated main
restore target. Foundation gate `sha256:1a36fb9cd2724bd085af7dd0eb68002f53c70869c33871e15dc057e7f1fd00a9` passed
at 15:14:23 UTC; business release gate `sha256:bbfaaf80a09b1bccb477f8e6632af9fb4656381aa943d63895e4c2844344e341`
passed at 15:15:09 UTC. Both report no blocking reasons, and business writes/tenant activation remain false.
Ignored local evidence is under `e2e/work/artifacts/roadmap-262/`; the remote backup, receipt and metadata report remain
under `e2e/work/artifacts/office-262-recovery-backup/` and `office-native-paragraph-recovery-proof.json`.
Independent evidence review recomputed the canonical recovery hash and matched final report/quality/counts.

## Previous completed slice: Roadmap 261

The existing versions endpoint now supports bounded pages along the immutable predecessor chain, including identical
timestamps. Its default remains 200 entries; the UI requests 50. Authenticated cursors bind tenant, actor, roles,
document and page size, and use a distinct signing domain. Each page rechecks current parent role/ABAC and typed ACL
before reading metadata. A fixed history head keeps continuation stable; the current head is reported separately so
concurrent saves are visible without replacing selected content. No source bytes are loaded by history pagination.

History and comparison provide older-version, refresh and retry controls. Appending preserves exact selections,
rendered comparisons and document/review/suggestion drafts. Refresh can pin the two exact comparison selections outside
the new window. Opening history retains a version-bound composer; returning resumes its draft. Document/context changes
and close keep existing discard consent. Transient failure preserves state, rejected cursors offer refresh, and actual
access denial clears protected data. Inspector hide/tab/focus changes and comparison/context close cancel pending reads.
Exact source authorization and explicit confirmed CAS saves remain mandatory for historical takeover.

The first integrated browser run on `7f95caf` passed 22 of 23 cases and exposed the inspector discard path. Independent
review also found uncanceled sidebar reads and stale loading status. Product correction `46a83b4` fixes those cases;
expanded tests prove both composer drafts and the additional cancellation paths without weakening earlier assertions.
Independent backend, UI and test reviews found no remaining concrete defects after correction.

- All 249 focused Python/API/PostgreSQL/harness checks passed on `0bdd522` in 40.58 seconds.
- All 23 focused browser cases passed on `46a83b4` in 94.693441 seconds, zero skipped/unexpected/flaky.
- The fixture creates a genuine PostgreSQL/S3 document with 225 confirmed versions under dedicated author/reader
  principals. Complete unique history, exact earliest rich content, current ACL denial, cross-role cursors, concurrent
  heads, comparison, takeover, real CAS conflict and same-cursor retry are covered.
- Root and independent visual inspection passed desktop/tablet/mobile controls. Actual Uvicorn logs verified 63
  document-list and 110 history access records without query or cursor values at 2026-09-21 14:12:06 UTC.
- Focused report: `sha256:ef46cb8c44612e6dcb6261f784d42a5dbfbeaca1e1bf9604e3f6869bf5e464b3`.
- Focused Python log: `sha256:57c57ffa90404f8f0fb763e86f655a2726fa16264d2f0fc3c0bf60e809053122`.
- Initial failed browser report: `sha256:c668c76b5ccf00227eebeb03735633a80a02388b95a8b5e4a2cbb6601c7a1348`.

Full acceptance completed on unchanged `46a83b4` at 2026-09-21 14:24:43 UTC:

- Ruff and formatting across 705 files, Mypy across 551 sources and complete Pytest passed; only the known
  Starlette/AnyIO warning remains.
- All 200 checks passed in 688.743181 seconds: 165 browser and 35 model cases, zero skipped/unexpected/flaky.
  All previous 190 cases remain included.
- Final report: `sha256:926b3a0c808d6baed3c65d904257cabc85996da6eb956f58eb5d7d03fb747e79`.
- Quality log: `sha256:296215f2c5250e1199918099f88565806f30b1a49276e818f457b312e1508025`.
- Root and independent final visual review passed three Office history and two Work screenshots.
- Office desktop: `sha256:0892e8209a114f6e330161ea44668f5338da58afbfae2a428b54600b299c431a`;
  tablet: `sha256:916637c44793934818ed7068f5aae091141fd50d851709c861250e8c83c6cc05`;
  mobile: `sha256:cd21aac209668a7719e59a06ee0b4314b570a8fe9b23fb749dad862fc2e84c64`.
- Work desktop: `sha256:c45d47f7839bc45fb3d6ba79ec4364e86f35afbc94db86d2ce65bf1a5432dd08`;
  mobile: `sha256:ad1fc69cbc16d518a1c13a786a95ac214b88acfdbf5f50a6a0ac26065622afc7`.
- Actual Uvicorn logs verified 322 document-list and 205 history access records without query/cursor values at
  2026-09-21 14:25:11 UTC.

API rollout, live verification and exact cleanup passed as recorded above. Ignored evidence is under
`e2e/work/artifacts/roadmap-261/`. There is no new endpoint, schema, durable format or dependency; no main-database
migration or new recovery drill ran. Roadmap 257 recovery evidence remains retained. Ordinary tenant, pilot, indexing,
cloud provider and DOCX engine admission remain closed.

## Previous completed slice: Roadmap 260

The existing document-list operation now supports bounded literal title search and context-bound cursor pagination.
The UI requests 50 entries per page, shows loaded counts, and exposes clear next-page, reset and retry controls.
Current role/ABAC and typed ACL checks precede the page limit and lookahead. Creation time and object ID provide a
stable order across saves and renames; concurrent title/ACL changes remain live and this is not a frozen snapshot.
Cursors bind tenant, actor, roles, normalized query and page size. The per-service HMAC key supports the current
single-worker deployment; restart invalidates cursors and requires a list refresh. No shared multi-worker key is claimed.

Search and pagination preserve open documents and all local drafts independently of list membership. Manual refresh
reauthorizes the exact saved source and updates its write capability without replacing edited content or review drafts.
Actual read denial clears protected state; transient list/read failures preserve drafts. Historical takeover and
suggestion acceptance use fresh exact content permissions instead of filtered-list membership. Existing confirmation,
version/hash validation, CAS and exact save retry remain intact. Query text and cursors are excluded from audit metadata
and ordinary Uvicorn access records. The compact Work navigation now exposes the existing Office link on mobile.

Backend implementation `ac250d7` received formatting-only correction `35fdb1e`. Its real PostgreSQL revocation fixture
then required the existing mandatory revoked_at_utc value; `e304b28` corrects that fixture and integrates the UI/tests.
All 180 focused Python checks passed in 23.04 seconds, including genuine PostgreSQL authorization-before-limit tests.
The first browser run passed nine of ten and found the hidden mobile Work link. Product correction `5bcb7d2` preserves
the unchanged real-click test. All ten focused browser checks then passed in 46.602456 seconds, zero skipped/unexpected/flaky.
The separate synthetic author owns 225 real PostgreSQL/S3 documents; a separate reader can see only three oldest entries.
Independent desktop/tablet/mobile visual review passed. Actual Uvicorn logs verified 51 redacted list access records.

- Focused report: `sha256:663d6370c40b38e432000b458ea2f7fb662121fd3a0be3b19ddfdf2b59e42c03`.
- Focused Python log: `sha256:424ede12b4e521f026d5e8535595879e23de559bc4e7cd9cf7d1026d9cd622c5`.
- Failed initial browser report: `sha256:74199fc7e94aaa0580778fcef451c7d7a4f81cf4faf77369672fc404879b37c4`.
- Failed PostgreSQL fixture log: `sha256:0d6509f0c156b72c42c8502a12ac8872fe6ff9c8ad974a1f137bbfc8d328c29c`.

Full acceptance completed on immutable `5bcb7d2` at 2026-09-21 13:01:19 UTC:

- Ruff and formatting across 699 files, Mypy across 547 sources and complete Pytest passed; only the known
  Starlette/AnyIO deprecation warning remains.
- All 190 checks passed in 651.284899 seconds: 155 browser and 35 model cases, zero skipped/unexpected/flaky.
- Final report: `sha256:f11d3d0e6130351760439eec1ea7e71ae85de1fe881d76d2df4c9eee0ac8b8ef`.
- Quality log: `sha256:627d7e5a71376e443db09d5bc78e953c86298b699d3df8a8b2e3feaba1fc446c`.
- Independent final visual review passed all three Office and both Work screenshots, including mobile navigation.
- Office desktop: `sha256:2dc5a26e4a3e5002f221e9d01fc4852de6ac984ea41c7ff240a6310f871ce23e`;
  tablet: `sha256:b05b0ef9fed915953a45a12858b1e12eb70bc2b09f80b7c9091e39facae323b8`;
  mobile: `sha256:7623c55a537cba751d8626bc4a6a4edb03f87e6265ae836e0083390d529909df`.
- Work desktop: `sha256:8280b8ca8309031eefea8d13080c9d0f97d0840a5621d5490869fdeecd5f9796`;
  mobile: `sha256:693614c26b4f68e2ac4558a01d36368ed3c6221f0a702a7bc411e5f6621bc482`.
- Actual Uvicorn logs verified 306 list access records without query/cursor values at 13:01:29 UTC.

Ignored reports and diagnostics remain under `e2e/work/artifacts/roadmap-260/`. API rollout, live verification and
exact cleanup passed as recorded above and in the append-only operations log. No schema, durable storage or dependency
change is introduced and no endpoint is added; the existing read endpoint receives additive parameters/response fields.
No main-database migration or new recovery drill is claimed. Roadmap 257 recovery evidence remains retained.

## Previous completed slice: Roadmap 259

Saved current or historical native Office versions can now become independent memory-only drafts through
"Als neues Dokument". The dialog identifies the saved title/version/date and accepts a bounded new title.
Unsaved source edits are excluded. Canceling or a transient read failure preserves the current document and
discussion/suggestion drafts. Existing discard consent precedes fresh exact-version content and create-capability
reads; validation and detached editor preparation finish before the workspace is replaced.

Source read access plus create capability suffices; source write access is unnecessary. The bounded listing is not
used to authorize the source. Busy, uncertain or conflicting saves cannot be reused; close/context/session changes
reject late responses. The fresh editor has no source object/version, mutation attempt, history, ACL or discussions.
No write occurs until the existing explicit Create confirmation. That operation checks current create rights and
retains exact retry after an unknown outcome. This is a local drafting workflow, not an atomic server-side copy or
a persisted provenance link; later Create does not reauthorize the former source.

Implementation `b4add9d` initially passed nine of ten focused checks. The rich-content fixture omitted standard
unit-span table attributes that the established editor serializes explicitly. Test-only correction `e7fec24` supplies
those attributes without weakening exact content equality. All ten focused checks then passed in 41.694688 seconds.
Full quality and all 180 browser/model checks passed on the same immutable source at 2026-09-21 12:20:09 UTC:

- Ruff and formatting across 691 files, Mypy across 541 sources and the complete Pytest suite passed;
  only the known Starlette/AnyIO deprecation warning remains.
- 180/180 in 664.306054 seconds: 145 browser and 35 model cases; zero skipped, unexpected or flaky results.
- Final desktop/tablet/mobile screenshots passed independent visual review with no clipping, overflow or hidden actions.
- Final report `sha256:9792822a6de9a37b6b92acd67805e3f52ae535ad63836a70be176d72ea8f3237`;
  quality log `sha256:f66e1d0bacac61ebd7625e182d4293791b5b1c4856bd466d6b0a6db0f65a5cfe`.
- Focused report `sha256:95646616c21d7d1d140dfc05ddda7998e035551440cc5a74ef5a203711240385`;
  failed first report `sha256:54fb33988aaa253b66b662fcd19828c499890c43fbfb34554ae9c01f4cf8691b`.
- Final screenshots: desktop `sha256:30606618ab192d770dc04d6a1e1ec3e24c5e58250703d33aa735c712cf841ca2`,
  tablet `sha256:0f2adf14eca0cf9445f9c4051183e72f7855043fef27a9ebcbe8505d29d40b1a`,
  mobile `sha256:1190b026f1d0f7ee0cbfab9d26573a137e56251528bd3f3b89299a82a14819f5`.

Reports, logs, screenshots and failed-run diagnostics remain ignored under `e2e/work/artifacts/roadmap-259/`.
All execution used dev001 Compose project collabio, required locks and fresh lifecycle inventories. Quality and browser
tests used separate test databases. API rollout, live verification and cleanup are recorded above and in the append-only
operations log. Thirteen API operations, schema, storage and gates remain unchanged. No new recovery execution is claimed.

## Previous completed slice: Roadmap 258

Roadmap 258 / PLANS 119 completes native saved-version printing. A clean current or historical version opens a
literal, semantic print preview with A4/Letter and portrait/landscape settings. Readers may print without write rights.
The existing exact-version endpoint freshly rechecks current access both on preview and immediately before the
explicit browser call. Historical output uses its own saved title. Dirty, new and unresolved-save states remain blocked;
no content is implicitly saved or discarded. Prepared output is cleared after printing, close or context invalidation.

The browser controls final pagination, destination and settings; opening its dialog does not prove output completed.
The isolated print surface excludes editor controls, context, comments and suggestions. Other print entry points show
neutral guidance. Native headings, lists and table cells survive PDF structure export; the preview becomes temporarily
nonmodal during the browser call, then returns only for the still-valid session. No PDF/UA or cross-browser fidelity
claim, server export, new receipt, storage derivative, dependency, migration or engine admission is added.

- Full quality on `cf2244c` passed Ruff, formatting across 689 files, Mypy across 541 sources and full Pytest;
  only the known Starlette/AnyIO warning remains.
- All 170 checks passed in 562.234 seconds: 135 browser cases plus 35 comparison/search-model cases, zero skipped,
  unexpected or flaky. The previous 162 checks remain. Twelve targeted error cases passed first. The final
  cleanup-only guard on `d8300aa` passed its affected parallel-revocation case in 9.0 seconds.
- All eight print cases cover exact saved/historical content, ordinary readers, literal markup, all supported native
  structures, paper/orientation, current ACL revocation, transient failures, late responses, dirty/unresolved states,
  output isolation and responsive layout. Same-page Chromium PDF generation exercises the freshly prepared product surface.
- Independent Poppler/QPDF inspection verified all 80 numbered paragraphs and final sentinel across nine Letter
  landscape pages, preserved text and table content, A4 historical output on one page and one guidance-only page.
  Real H1/P/list/table/header/data-cell dictionaries are present; no application-shell or protected-current-version leakage.
  Desktop/tablet/mobile screenshots and all eleven PDF pages were visually reviewed.
- The first complete runs passed 169/170 on `a939b1b` and 168/170 on `4545d48`; all print cases passed. Existing
  error-body observations failed because Chromium discarded streamed no-store bodies. Test-only buffering preserves
  actual upstream status/headers/bytes and has no retries. A focused 11/12 run then exposed the expected canceled
  sibling request after a parallel 404. Its observer now checks the identical request's ERR_ABORTED and waits for both
  reads before restoring the synthetic ACL. Subsequent focused and full runs passed. Failed reports/traces remain retained.

Ignored final evidence under `e2e/work/artifacts/roadmap-258/`:

- `results.json`: `sha256:8198c66138af5af63d6d767ab9e8c4c06acaf18e60013809ed31879f39faa86f`.
- `quality.log`: `sha256:541ce600a21a8651c99c4cb0182b24c80f5f0b3132b161c7099ea4c164d4de1a`.
- Desktop: `sha256:1cf476412f3b51cc20110eadf1d816b8669e01e19352357c82e4cab8a325f924`.
- Tablet: `sha256:b8e061e59054f8c8b6e35c6e6e569c5de0313ff5c3c5535c08f335010ac99654`.
- Mobile: `sha256:42524d1e6f332e586d4b9e48b631584cc744254ede18120aa979b18265c058c8`.
- Rich PDF: `sha256:15c5bb6c81b7fd75a9b53ad22e1c80496f3b34584ee6bc654a8133b0b7a13785`.
- Historical PDF: `sha256:3e6094137a2b1e78191b7ba08c01d970d0250c78f179f22904e5ac562f428a67`.
- Guidance PDF: `sha256:233a9b4e3b27324c3ed86362813b0fe5f8fa6cb8bbc37dcd9bd0f84eeb1cb495`.
- `pdf-qa/report.json`: `sha256:598c1e210e3cb3f4920d78120b479d36f42bb8f8d8bfb6cf3677b61a3bedb63b`.
- First failed full report: `sha256:18415b02c2ddc62922231905f297ba9dd7dbdf800e0fe64d1171de9d862191f9`.
- Second failed full report: `sha256:0cb6cfd6cad7cc95d1d359f1ba3314e75978d0c4dde43349964bd58a9b1b5cb4`.
- Failed error-focused report: `sha256:8bc6dc421e49ceb88018d48c05dffe94623c0655e64960037ccdaecf2c77d8bf`.

## Previous completed slice: Roadmap 257

Roadmap 257 / PLANS 118 completes explicit saved-text suggestions: select text in a clean current saved version,
propose replacement (including deletion), inspect literal before/after and confirm accept or reject. Acceptance
saves its immutable decision and exact new document version in one PostgreSQL transaction and shared Office tenant
lock. Rejection appends only its decision. Historical anchors never move automatically; stale acceptance conflicts.
Fresh current parent ACLs, write-feature gates, strict revisions and actor-bound exact retries apply to every mutation.
The fourth inspector tab uses memory-only drafts, current capabilities, explicit confirmation, conflict preservation,
uncertain-result retries and close/context invalidation; known success cannot trigger a second write after refresh failure.

Migration 0085 adds append-only `office.text_suggestions` and `office.text_suggestion_decisions`, immutable COMMENT
sources/receipts, forced RLS and exact source/result bindings. A deferred constraint trigger prevents an acceptance
version without its decision. Public saves reject reserved internal acceptance references before any PUT. S3 remains
outside PostgreSQL rollback; focused tests prove metadata rollback and detectable orphans after storage/DB failures.
The restore gate pins all six Office tables, grants, policies, constraints and complete trigger functions, including
the deferred requirement. Continuous keystroke tracking, automatic merge and live collaboration are not implemented.

- On `0d5350d`, all 688 focused backend/API/PostgreSQL/recovery tests passed in 52.37 seconds and ten focused browser
  runs passed in 50.1 seconds. Full Python quality on `9c17a31` passed Ruff, formatting across 684 files, Mypy across
  541 sources and full Pytest; only the known Starlette/AnyIO warning remains.
- The full matrix on `9c17a31` passed 162/162 in 535.956 seconds: 127 browser cases plus 35 model cases, zero skipped,
  unexpected or flaky results. All previous 152 checks remain. Final desktop/tablet/mobile screenshots passed
  independent visual review. Code review and independent recovery review also led to alias-safe success responses,
  preserved-title validation and reserved-reference rejection before the final full run.
- Fresh nonempty recovery restored 67 documents, 109 versions, 36 multi-version documents and 162 source objects.
  Nine review threads/17 events include the complete prior review lifecycle. Ten proposals and seven decisions include
  five acceptances and two rejections. Exact original/replacement bytes, receipts, result content/title/lineage,
  current ACLs, foreign denial and read-only restored services passed. Report
  `sha256:e1ab971a88c43ff06c12544ba24619731b2b8304908da53ab5b73ad8bb017c53`; synthetic backup
  `sha256:06bbf77f9e41db9a7ecbc525bf17fd3e69c08b8dac7840ade2e7f10ecb9f4160`.

Ignored final evidence under `e2e/work/artifacts/roadmap-257/`:

- `results.json`: `sha256:42317e268bb6cd56cff3d85615bc012aed06d28ccd88f99b62228cdc03168e47`.
- Desktop: `sha256:79d78928d16ff5c35fdcbe95640037fbf07e92ba6af8b026b8cf2a6f3108983e`.
- Tablet: `sha256:3325d16574ccea994966ad6e474821595c592a752c99fb0dbac5c7f00000fa79`.
- Mobile: `sha256:199bf6260aea647f747ee875edb8d6b0899598cc87d9ec41786f1ef804ec7e77`.
- `quality.log`: `sha256:6b49b2f2fa706fd0d42baee0a72a19111e404f66309eca3a554830804cd19a21`.

Main migration/release evidence:

- Pre-0085 `collabio-20260921T071612Z.dump`: `sha256:ed83da613feb5792a209bf428630df302804dcfe377af9b89e1e58182de63a83`.
- Post-0085 `collabio-20260921T071618Z.dump`: `sha256:c937926687291d847cd07daaf36034a5318bead0c13926322ac3ba2035934aeb`.
- Foundation-bound PostgreSQL restore: `sha256:1a2d6c846bd5617ffbf20175aed5a97155c85144f5be107b3d64b345a38f5045`.
- Foundation: `sha256:f257c62d06ba81432a909f60161faba69c1d9e3db82f998c4cfdbd02c1294ffd`; 85 migrations/95 tables,
  expanded Office controls and three existing main sources restored, with source seeding explicitly disabled.
- Business release: `sha256:b14e152ee2355a82a1a22cb06457daac58fe2fa0149d32b8df31678e618dca63`; existing CRM/Tasks/Time
  three-slice gate passed without business writes or tenant activation. Office has the separate nonempty proof above.

Primary implementation: `office_suggestions.py`, `office_suggestion_repository.py`, the transaction-scoped document
persist primitive, Office API/UI and migration 0085. Tests include `test_office_suggestion*.py`,
`office_suggestion_recovery.py`, the shared restore gate and `office-suggestions*.spec.mjs`. See ADR-0081,
the Office module document, Work E2E runbook and append-only operations log. The initial restore helper typo stopped
after dump creation and before target modification; its corrected resume verified that dump and completed the proof.

## Previous slice: Roadmap 256

Roadmap 256 / PLANS 117 completes native Office review discussions: comments on an exact saved version or selected
text, replies, resolve/reopen and explicit confirmation. Historical discussions keep their original version and quotation.
The server derives bounded Unicode-safe anchors from exact saved content. Every operation checks current parent rights;
mutations also require the existing write feature, thread revision CAS and actor-bound exact retries. Comments do not
create or modify document versions. Literal bodies/quotations stay in immutable COMMENT SourceObjects, never normal logs.

Migration 0084 adds `office.review_threads` and append-only `office.review_events` with source/receipt bindings, forced
RLS and guarded heads. The comments inspector uses memory-only drafts, paginated discussions, exact-version highlights,
current capabilities, explicit conflict refresh and safe retries after uncertain writes. Late responses are discarded;
compact layouts use a closable scrollable overlay. No editing/deletion of comments, notifications, tracked changes or
live collaboration was introduced. There are now nine Office API operations.

- Initial implementation through `c7cff5d` passed 389 focused backend/API/PostgreSQL/restore tests and full Python quality.
  Ten focused browser cases passed in 44.978 seconds. The first full run passed 150/152; two Chromium response-body
  observation errors affected expected 409/503 cases. `7400b35` captures those real upstream responses unchanged,
  without retrying writes or generating test responses. Final full matrix: 152/152 in 432.486 seconds, zero skipped,
  unexpected or flaky; 117 browser cases plus 35 model cases. All prior 142 checks remain. Final screenshots were
  visually checked by root and an independent UI reviewer.
- Independent restore review found omitted unrelated Office grants/MAINTAIN and unpinned review CHECKs. `1cf9ee9` and
  `552b6b6` capture all direct Office grantees and effective column grants, exact owner/runtime rights and nine canonical state/anchor/byte
  CHECKs. Thirty-seven regressions include three real PostgreSQL grant cases. One old fixture assumed the first grant
  belonged to the runtime; `2305a96` selects that role explicitly. All 269 focused restore/recovery/backup checks passed
  in 23.40 seconds. Full quality on `2305a96`: Ruff/format 674 files, Mypy 532 sources and full Pytest passed, with only
  the known Starlette/AnyIO warning. No product/UI/schema behavior changed after the successful browser run.
- Fresh nonempty PostgreSQL/S3 recovery on `2305a96` restored 57 documents, 93 exact versions, 30 multi-version
  documents and 129 total sources. Nine discussions and 17 events include three selected-text anchors, one historical
  discussion and one complete create/reply/resolve/reopen lifecycle. Exact bytes/quotations/receipts, current ACLs,
  foreign-tenant denial and read-only restored services passed. Report
  `sha256:330a544deb64fbcb374d1c23732660cb7c2f80b8a2f2cc14289b8e2fa59fae92`; synthetic backup
  `sha256:3d9fe80e786c501967d30a5b1e75614cd55e60bfb46e815d926fcb2093e64af6`.

Ignored final evidence under `e2e/work/artifacts/roadmap-256/`:

- `results.json`: `sha256:96f4a596d21e395073967745c1811448fdbc2e04bc7f2f7e20ae4e4075fe156f`.
- Desktop: `sha256:a09972a0509a51e31f1a62e3cb33e966d5d29d728dbc80c96966fe47c1fc6827`.
- Tablet: `sha256:f499a343c87bd0c735c15ce38726b28cc6331a3a2b8f431e9217943f0e2b4452`.
- Mobile: `sha256:4783a6257d6db4f312449298c7ec207682122028aa9a49e088724d3f73564e28`.
- Final quality log: `sha256:4274b75408916a13e6ef41885ce7f3dc2c1a89d21a73cc85a7d3cd5416f3769e`.

Main database migration/release evidence:

- Pre-0084 `collabio-20260918T131039Z.dump`: `sha256:ec98cd064b010c2d905ed64ab97a84a0edc186ed9c1d99ef19499140a0abfc06`.
- Post-0084 `collabio-20260918T131046Z.dump`: `sha256:b3058ce54bb3a0b36ef97af1c031fcca1c0315797a930b0531fb6602ac27602b`.
- Foundation-bound PostgreSQL restore: `sha256:14dfaf92e80eef0a9a6967a06f2a666d79445e03dea423e4e452ec48bab09b68`.
- Foundation: `sha256:4ee5691940bec2e1b2b48623bf8a671e67efaaa8232057a01e913c3ab820b4ce`; 84 migrations, 93 tables,
  expanded Office controls verified and three existing main sources restored. Source seeding was explicitly disabled.
- Business release: `sha256:e8109c8e126d80fd4bd55f16a5c432e8841e5c44a374de654b8e1eaaa354faa4`; existing CRM/Tasks/Time
  three-slice gate passed without business writes or tenant activation. Office has the separate nonempty proof above.

Primary implementation: `office_reviews.py`, `office_review_repository.py`, `office_api.py`, Office UI, migration 0084;
`tests/test_office_review*.py`, the expanded restore verifier/product proof and review E2E cases. See ADR-0080,
`docs/modules/OFFICE_NATIVE_DOCUMENTS.md`, `docs/operations/WORK_E2E.md` and the append-only operations log.

## Previous slice: Roadmap 255

Roadmap 255 / PLANS 116 completes contextual table editing in `/office`: custom size and optional header on insertion,
rows above/below, columns left/right, first-row header toggle and cell/row/column/table selection. Removal requires
explicit confirmation, including whole-table Delete/Backspace; cancellation preserves the draft. Each structural edit
is one undo step separated from typing. Tab moves between cells and creates a bounded new row from its first cell;
when extension is unavailable, focus leaves the table for an available control. Legacy menu actions share the same path.

Native ProseMirror transactions are staged before dispatch. A global document guard also checks keyboard/paste/undo
changes against schema, rectangular geometry, 200 rows/20 columns and existing codepoint/node/depth/canonical-byte
limits. Read-only/history/loading/saving/restoring/uncertain states prohibit edits. Dialogs bind session, revision,
document and selection; context changes discard pending actions. Existing confirmed CAS save alone persists changes.
The inspector closes on entry to tablet width to avoid covering the table; explicit reopening remains available.

- Initial `93cbd71` focused run passed 9/10; the remaining test asserted a disabled option with an unsuitable control
  matcher. `a27c433` checks its native disabled property; all ten focused cases passed in 38.975 seconds. No product
  permission or size check was weakened. Visual review then prompted the tablet fix and regression in `e3cf88c`.
- Full quality on `e3cf88c`: Ruff/format across 665 files, Mypy across 526 source files and full Pytest passed; only the
  known Starlette/AnyIO warning remains. Full matrix: 142/142 in 359.156 seconds, zero skipped/unexpected/flaky,
  consisting of 107 browser cases and 35 model cases. All previous 132 checks remain; eight workflows and two
  responsive runs are new. Final desktop/tablet/mobile screenshots were visually reviewed.
- Proof includes real version saves/reopen/immutable history, preserved marks, structure and cell selections,
  isolated undo/redo, immediate focus, removal cancellation, keyboard-created rows, blocked final-row expansion,
  valid-dimension but excessive canonical bytes, reader/history, pending/uncertain saves with retry and context changes.
- Documentation closeout `58b9f9e` passed all 11 targeted module/KB/roadmap contracts in 59.83 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 12:13:31 UTC.
- No dependency, schema, API, storage or tenant activation change. Item 252 migration/backup/nonempty recovery/
  foundation/business proofs remain retained, not rerun. Primary implementation is the existing Office JS/HTML/CSS;
  tests are `office-tables.spec.mjs` and `office-tables-responsive.spec.mjs`.

Ignored final evidence under `e2e/work/artifacts/roadmap-255/`:

- `results.json`: `sha256:89c132f192d7a3302ab3a48dc201dfdc0f60c007e8334c993e79be9f7df9d2d8`.
- Desktop: `sha256:e939f0f5d8fe69b8536e4c8d23b0a0b85625c33ee3cd74f985dbb41bfb3584c0`.
- Tablet: `sha256:46f02424be9de63d73e4941e1443fa77d975a655c0b466410facf84652335c39`.
- Mobile: `sha256:8c97a0b58cae3e26d342db1bfc17e9257f6aee14b9b871b1b202fe367cc29500`.

## Previous slice: Roadmap 254

Roadmap 254 / PLANS 115 completes literal find/replace in `/office`: Unicode-safe original positions, case and whole-word
options, complete counts, previous/next navigation, current/all replacement, keyboard shortcuts and responsive controls.
Matches span adjacent formatting nodes but never cross paragraphs, hard breaks or cells. Untouched text/structure stays
intact; replacement inherits the first matched character's marks. A labelled 200-match highlight window follows the
active result; all results remain navigable and replaceable. Character/node/depth/canonical-byte limits are checked
before applying changes. No regex/HTML interpretation, background request, new dependency, index or persistence format.

Replacement affects only the local draft as one undo step isolated from adjacent typing. Read-only/history and busy or
uncertain-save states prohibit replacement. Existing confirmed CAS save persists a new version. Loading a document is
excluded from undo history, so undoing its first edit cannot erase the loaded source. Context/panel/workspace clearing,
cancelled discard, no-op, source history and safe retry contracts remain intact.

- Source `1142642` first passed 24 focused checks; one test incorrectly ignored a lowercase match, and undo exposed
  initial content loading as a history event. Both were corrected in `f4c37e5`. All 32 focused checks then passed.
- Full quality on `f4c37e5`: Ruff/format across 665 files, Mypy across 526 source files and full Pytest passed; only the
  known Starlette/AnyIO warning remains. Full matrix: 132/132 in 291.588 seconds, zero skipped/unexpected/flaky,
  consisting of 97 browser cases and 35 model cases. All prior 100 checks remain; nine browser and 23 model cases are new.
- New proof includes actual saved replacements/reopen/version comparison, isolated undo/redo, current/history reader
  restrictions, literal hostile text, complete large result sets, no-op/delete/expansion limits and late context reads.
  Model proof reaches 100,000 matches and checks original Unicode positions, mark boundaries and resource preflight.
  Final desktop/tablet/mobile screenshots were visually reviewed.
- Documentation closeout `d63139c` passed all 11 targeted module/KB/roadmap contracts in 61.97 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 11:32:44 UTC.
- No schema or durable contract change; the item 252 migration/backup/restore/foundation/business evidence below
  remains retained, not rerun. No tenant/pilot/indexing/engine activation. Main code is `office-search.mjs` and the
  existing Office UI; tests are `office-search-model.spec.mjs`, `office-search.spec.mjs`, `office-search-responsive.spec.mjs`.

Ignored final evidence under `e2e/work/artifacts/roadmap-254/`:

- `results.json`: `sha256:e12cf71865e5a013852d6482b6a96a33d5a37c4c031157721d0d980324d32b71`.
- Desktop: `sha256:301e7030dd649df94023e5ac4d2e81d2385cbf10b7fb530ab44b832eeaa91350`.
- Tablet: `sha256:32174cead5fdc1d292439d6633fe2f71f350a73984de4d9c7100287662094ccc`.
- Mobile: `sha256:0cfac05e9a82fd705655c7e9831e868ac334afb313e4f48d24f14e489d508613`.

## Previous slice: Roadmap 253

Roadmap 253 / PLANS 114 adds saved-version comparison and historical takeover to `/office`, using the existing five
Office APIs. Text, titles, format-only changes, lists and tables are compared as literal block content. Bounded alignment
preserves every input block; large approximate results are labelled and paginated. The last 200 history entries may form
a connected partial chain; relative labels avoid invented absolute version numbers.

Historical takeover freshly reads exact historical content, the current head and current write capabilities. It produces
only an in-memory draft based on that fresh head; explicit confirmed CAS save appends a successor without rewriting
history. Read-only users can compare. Access denial clears protected state; transient failure, cancelled discard and a
later competing save preserve existing drafts. Closing, changing selection/context or superseding an operation invalidates
pending responses. Identical takeover creates no dirty state or redundant save. This is block comparison, not tracked
changes or automatic merging.

- Implementation `3aa0069` passed full Ruff/format (665 files), Mypy (526 source files) and Pytest. Only the known
  Starlette/AnyIO warning remains. The focused 27 checks passed before the complete matrix.
- Full matrix: 100/100 in 249.923 seconds, zero skipped, unexpected or flaky; 88 browser cases plus 12 pure model cases.
  All previous 73 browser cases remain green. New coverage includes large/duplicate model inputs, exact comparison,
  fresh-head takeover, CAS conflicts, current ACL/feature removal, cancelled discard, failure retry, bounded real history,
  no-op takeover and late responses. Final desktop/tablet/mobile screenshots passed visual review.
- Documentation closeout `5a15195` passed all 11 targeted module/KB/roadmap contracts in 61.94 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 10:52:56 UTC.
- No new schema, durable record or save endpoint. Item 252's migration 0083, verified backups, nonempty recovery and
  foundation/business proofs below remain retained, not newly rerun. No new engine, tenant or pilot admission.
- Primary changes: `app/suite/ui/office/office.js`, `office-comparison.mjs`, `office.css`, `index.html`;
  `e2e/work/tests/office-comparison-model.spec.mjs`, `office-versions.spec.mjs`, `office-versions-responsive.spec.mjs`;
  Docker bundle/module mounts and metadata-only roadmap capability evidence.

Ignored final evidence under `e2e/work/artifacts/roadmap-253/`:

- `results.json`: `sha256:42448945e2d326b56552c886d3603d69d1dcaf4d416ca4c727bf2e66e3ce8859`.
- Desktop: `sha256:0d28f346e40703ee5aae43f1b97f1d935af540d3757fbe2fc881c6a33037ca24`.
- Tablet: `sha256:7df8d3dd56d2f4b9d5ef1df12664a75ad7dbafc9e0d89ca5cd7f8670b8b9b53e`.
- Mobile: `sha256:33024e5aed9b0ac0b9c68787839cca0fdfe7856c7950cb8f61359e84685c5a3c`.

## Previous slice: Roadmap 252

Roadmap 252 / PLANS 113 delivers `/office`, linked from `/work`: native rich text, headings, lists, tables, templates,
outline, local text search, word count, focus mode, explicit version saves and historical reads. Desktop, tablet and
mobile controls were visually checked. Formatting returns focus synchronously for immediate mouse/keyboard input.
Conflicts and storage failures preserve drafts; context changes and close/reopen discard late responses. Drafts are
memory-only and do not promise crash recovery. DOCX interchange, comments, tracked changes, live collaboration,
spreadsheets, presentations and mail remain open product work; no claim of Office feature parity is made.

- Native content is bounded `collabio_document.v1` JSON. Server-side schema validation rejects unsupported nodes,
  remote resources, arbitrary attributes and excessive size/depth. CSP allows only local assets; no content enters logs.
- Five operations under `/v1/office/documents` enforce tenant/module/read/write gates, current typed object ACLs and
  server-derived ABAC. Read permission does not grant writing. Historical reads and retries recheck current access.
- Migration `0083_office_native_documents.sql` adds document heads and append-only versions with forced RLS, narrow
  column grants, atomic creator ACLs and source/receipt/head binding triggers. Canonical bytes use shared versioned S3.
  Tenant serialization precedes stale-head validation and PUT. PostgreSQL rollback does not roll back S3; post-PUT
  database failure can leave an orphan, covered by reconciliation tests. CAS and exact retry keys prevent lost updates
  and duplicate versions. Explicit human confirmation remains mandatory for each persisted save.
- ProseMirror/Tiptap 3.31.3 is bundled locally using a pinned image and locked dependencies. The runtime retains license
  notices and dependency inventory, without Node execution. Dependency audit reported no vulnerabilities.
- Full quality on `7bba74f`: Ruff and formatting across 665 files, Mypy across 526 source files, full Pytest green;
  only the known Starlette/AnyIO warning remains. The focused Office/API/PostgreSQL/restore/guard matrix passed 246 tests.
- Final browser proof on `5917bdf`: 73/73 in 160.237 seconds, zero skipped, unexpected or flaky cases. It preserves all
  60 Work/KB/CRM regressions and adds 13 Office workflow/policy/responsive cases. Earlier failures and corrections are
  retained in the operations log. The final focus regression checks focus during the control event, without sleeps.
- Documentation closeout `39980c5` passed all 11 targeted module/KB/roadmap contract tests in 59.58 seconds, with only
  the same warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 10:19:15 UTC.
- Final nonempty recovery on `5917bdf`: 13 documents, 18 exact versions, five multi-version documents and 37 total source
  objects restored to separate PostgreSQL/S3 targets. Historical reads, canonical content/receipt hashes, current ACLs
  and foreign-tenant denial pass. Report `sha256:e61e7a26da539fa5a974a4faff62c31eb68502bd5c30f8f941df3effc2ae4cda`;
  synthetic backup `sha256:149e45637e20bafdaf93a76c7643b2ce77f7d1f23d2430888b77b951ea23c7ab`.

Ignored final evidence under `e2e/work/artifacts/roadmap-252/`:

- `results.json`: `sha256:ee074eca0c0897a8da5f232fc694d505b51ddb7413ccda4db4a8c9ee1e7e8792`.
- Desktop: `sha256:3201c529a199e88c6293672846fa66d24c7abc7bce40c7f15ca17a45f7c97c70`.
- Tablet: `sha256:23fb6d65e8d74e6d153f0ef828c23a059a01b1a167b419c434cfe085090d1ed9`.
- Mobile: `sha256:4321a07003b9729d069351d7f4f75f4b1b350482791d6f588e4317749325f144`.

Main database migration/recovery evidence:

- Pre-0083 backup `collabio-20260918T101259Z.dump`,
  `sha256:d0e243c70dcb6dbf6e3503331ee37ddc830059729edea44d67786f83e8b8314a`.
- Post-0083 backup `collabio-20260918T101306Z.dump`,
  `sha256:d82aadb4f0400282df0a4e6e036cf0fc3e60b53032eaf1810d51c1407f581f73`.
- Foundation-bound PostgreSQL restore `sha256:f659f89867d09e483c75ff046b3e0c7632590ad2d1603284c1a27294264e78f1`.
- Foundation `sha256:4fbba77852cc9e625aacc069d54495f69ddbd517f0e539fd49705c1ef47ae3fd`: 83 migrations, 91 tables,
  Office controls verified and three existing main source objects restored. Source seeding was explicitly disabled.
- Business release `sha256:a364a91a0044a62444fd69bfa95280cf01b7375389bd692e862948e32599b835` passed the existing
  three CRM/Tasks/Time slices without business writes or tenant activation. Native Office has the separate proof above.

Primary implementation: `office_document_schema.py`, `office_documents.py`, `office_document_repository.py`,
`office_api.py` under `app/suite/platform/`; `app/suite/ui/office/`; `frontend/office/`; migration 0083;
`tests/test_office_documents*.py`, `tests/office_recovery_proof.py`, `tests/test_office_recovery_proof.py` and Office E2E
cases. See `docs/modules/OFFICE_NATIVE_DOCUMENTS.md`, ADR-0079 and `docs/operations/WORK_E2E.md`.

## Previous slice: Roadmap 251

Roadmap item 251 and PLANS item 112 are complete. The existing account workspace is available in `/work` as an
account-detail dialog with associated contacts and activities. It reuses
`GET /v1/crm/accounts/{account_object_id}/workspace`; no new CRM mutation or schema is added.

- All three CRM feature gates and the existing pilot traffic-scope dependency remain mandatory. Account access is
  checked before child queries; every child requires its own current ACL and a relation to the selected account.
- Unreadable linked IDs remain redacted. JWT/OIDC ignores browser-provided grants. Contact names, email and phone
  remain personal data; the API's metadata-only contract does not make these fields anonymous.
- Successful responses and route-local errors are non-cacheable. Database failures return a constant 503 message;
  audit metadata contains IDs/counts, never CRM field values or note bodies. The UI does not display notes.
- Refresh clears old details before checking permissions again. Close/reopen and context changes invalidate late
  responses. Fields render as literal text; empty contacts and activities have independent messages.
- The guarded browser harness uses real PostgreSQL CRM rows and fresh database ACLs for the synthetic reader.
  Its narrowly scoped ACL administration and request-local database failure controls exist only in test code.
- Quality on `e966989` passed Ruff, formatting across 653 files, Mypy on 516 source files and full Pytest. Only the
  existing Starlette/AnyIO deprecation warning remains.
- All 60 browser cases passed in 130.014 seconds, with zero skipped, unexpected or flaky tests. The ten new CRM cases
  cover child filtering/redaction, literal fields, empty children, missing/forged/foreign permissions, closed pilot,
  account ACL revocation, disabled contacts feature, database failure/retry, late responses and desktop/mobile layout.
  Both viewport screenshots passed visual review; the previous 50 Work/KB cases remain green.
- After the operator approved publishing the described development evidence to the public repository, documentation
  commit `43149aa` was pushed and synchronized to dev001. All 11 targeted KB/module-contract/roadmap tests passed in
  19.88 seconds; health remained ok at 09:01:01 UTC. The disposable test used --no-deps and started no persistent
  service or auxiliary database. The final evidence-only update changes no runtime code or pilot state.

Current proof artifacts are ignored under `e2e/work/artifacts/roadmap-251/`:

- `results.json`: `sha256:64a245368f0e6a4e3665c761550a34e3477ed27ad47eccd56e16680087575455`.
- `work-crm-detail-complete.png`: `sha256:848fe140a83488d340c5f6e5c0f01a8aa58308c639da84d9448c672a3081e8f0`.
- `work-crm-detail-desktop-chromium.png`: `sha256:5587442989c9c890d8250349e20e13beeb92f2e554640c2bd3e6b51088a77a23`.
- `work-crm-detail-mobile-chromium.png`: `sha256:b1bf72c13d9928dd609f8f3f0ad27135c8c4e61603ef6469707e5f48cfd9c910`.

## Previous slice: Roadmap 250

Roadmap item 250 and PLANS item 111 are complete. Authorized ordinary readers can open published Knowledge Base
articles in `/work` with `knowledge_base.articles.read`, without an admin role or write feature.

- `GET /v1/kb/articles/{article_object_id}/content` returns the current article, exact source version, plain-text body,
  audit event ID and false RAG/search flags. Successful content responses and route-local errors use `no-store`.
- Article, current-version and source ACLs are checked before source access. JWT/OIDC ignores forged browser grants.
  Metadata preflight and loaded-byte validation bind exact identity, manifest/content hashes and security metadata.
- Only published article/lifecycle and WIKI/text/plain saved-version sources are supported, bounded to 400,000 bytes
  and 100,000 characters. Missing/denied, corrupt and unavailable sources return generic 404/400/503 responses.
- The read audit includes IDs and evidence hashes, never the article body. The editor shares the integrity helper;
  all existing write gates and approval stages remain intact.
- The dialog displays title, version and change date; literal markup stays plain text. Refresh clears old content
  before revalidation. Closing/reopening or changing context invalidates late responses. Desktop and mobile fit.
- The isolated browser proof uses a seeded ordinary reader, current PostgreSQL ACLs and the blocked API with write
  disabled. New-version access proves migration 0082 ACL inheritance without an extra version grant. Article/version
  revocation, S3 read failure/retry, foreign tenant, malicious markup and delayed-response cases pass.

No schema or durable business-data change was added. The migration 0082 backup/restore/release evidence below is
retained from item 249 and was not rerun for this read slice. No real tenant/runtime activation or pilot opening occurred.

## Previous slice: Roadmap 249 authoring foundation

Roadmap item 249 and PLANS item 110 are complete. The original Work browser slice (item 248/PLANS 109) remains intact.

Knowledge Base create/edit is available in `/work` for tenant-admins with an enabled module and write feature.
The narrow product endpoints construct trusted source metadata and expose the existing authoritative guard:

- `POST /v1/admin/kb/articles/prepare-write`
- `GET /v1/admin/kb/articles/{article_object_id}/edit-content`
- `POST /v1/admin/kb/articles/source-object-write-guard`

The existing dry-run, approve, refresh-preview, execution-skeleton and execute stages remain separate and hash-bound.
The UI carries their evidence between explicit preview, approval and final confirmation; users do not copy hashes.
Draft changes invalidate approval. Stale versions fail with conflict; failed writes preserve the draft and other
Work sources remain independent. Context generations discard old tenant responses and write capabilities.

Security and durability:

- Product metadata is server-created: internal classification, rp-standard, WIKI/text/plain, bounded title/body,
  fresh source/version identity, authenticated creator/owner and canonical security fields.
- Every stage rechecks module/feature, tenant-admin role and authoritative article/current-version/source access.
  Disabled compliance evidence reads remain available through their existing read gate.
- Migration `0082_knowledge_base_version_acls.sql` bootstraps the new article creator's ACL and copies active article
  ACLs to new versions in the same transaction. Trigger functions have pinned search_path and no PUBLIC/runtime
  execute grant; identity collisions and inappropriate preexisting objects fail closed.
- A tenant advisory transaction lock serializes all KB writes, including two first creates in an empty tenant.
  Approved restore state and expected version are checked under that lock before receipts/content writes.
- Source and restore evidence are verified inside the transaction and returned from its committed snapshot; a later
  write cannot cause a committed success to be reported as failed during post-commit evidence refresh.
- PostgreSQL metadata, approval lineage, receipt and exact S3 source versions remain bound. S3 is not part of the
  PostgreSQL transaction: an unexpected database failure after PUT can leave orphaned content, which the existing
  reconciliation/recovery controls detect. Never claim cross-system transactional rollback.
- Audits contain metadata/hashes, and storage/database errors return safe errors without logging article bodies.
- Restore verification binds both KB ACL triggers and their complete function definitions, owners, signatures,
  security mode, search_path, enablement and grants to migration 0082 and compares source/restore snapshots.

## Retained Knowledge Base validation and recovery evidence

On commit `d8d0386`, full quality passed: Ruff, formatting across 652 files, Mypy on 515 source files and full Pytest
to 100 percent. Only the known Starlette/AnyIO deprecation warning remains. This includes the PostgreSQL concurrency,
atomic ACL, API policy, storage-failure and restore-function tamper tests.
The new normal-reader API and isolated-harness policy tests are included. After documentation closeout, `6b1b82f`
passed all 11 targeted KB/module-contract/roadmap tests in 19.99 seconds; health remained ok at 08:19:34 UTC.
Item 249 implementation quality, documentation checks and 41-case browser evidence remain in the operations log.

Item 250 browser report: 50/50 passed in 120.480 seconds, zero skipped, unexpected or flaky tests. Desktop and mobile
reader screenshots were visually checked. Ignored local artifacts are retained under `e2e/work/artifacts/roadmap-250/`:

- `results.json`: `sha256:3dfb92a96f8cd61ec353c96e438ba94608476abc7321da223ea4f65f2b0f0a11`.
- `work-knowledge-reader-complete.png`: `sha256:98e0885f2a1370fa259fddf61dd518ae89dd672bf3f7e625716f913819d0db61`.
- `work-knowledge-reader-desktop-chromium.png`: `sha256:4e61218844b82d6f320a53bdbe9a49485de77273f4128ed0c78e10818dadd07a`.
- `work-knowledge-reader-mobile-chromium.png`: `sha256:9241af34e5fc7011298b80bbbf1544aca505d4828ff12529ec233873cb0c5ef6`.

Retained item 249 post-migration recovery and release proofs on dev001 (not newly executed for read-only items 250/251):

- Backup `collabio-20260918T070901Z.dump`:
  `sha256:9de68a2febdaa66c5f880ee1478d03bf343bea9004da67ee1b34966a875fb253`.
- PostgreSQL restore bound by the foundation gate:
  `sha256:a563ec0e557fe0c83e775c0a776e496b555b77f76015488fb0d8f3c854c283b3`.
- Foundation gate: `sha256:bf17fc1797e44b7a0a54ba6a0155313e7e5686a0537fac8ef22b4a6b0d3f5c06`.
- Business release gate: `sha256:8794acf1da3725851beaccba00adafed108166cf99966e24bec9dc3596fe2def`.

The foundation verified 82 migrations, 89 tables, tenant/IAM and trigger integrity, and exact restoration of three
existing source objects. The business gate remains the existing CRM/Tasks/Time three-slice gate; the KB product proof
is the separate API/PostgreSQL/browser matrix above. No new real-user pilot preflight/admission was created.

The isolated browser profile has tmpfs PostgreSQL and MinIO, internal networking, no host ports, tenant
`tenant-work-e2e` only, memory-only synthetic runtime activation and the normal pilot switch closed.
It ignores browser-supplied KB/CRM readable IDs and resolves current database ACLs on every KB/CRM request.
Its request-local storage failure injection is restricted to the exact synthetic tenant and execute or content-read route.
No failure injection exists in production API code.

The browser matrix is now 60 tests: the previous 41 cases, seven KB reader workflow/policy/race cases, two reader
responsive runs, eight CRM detail cases and two CRM responsive runs. The original 28 independent source-state cases,
closed-pilot route policy proof, real task/time workflow and guarded authoring remain intact. Artifacts and their
hashes are development evidence only.

Pre-0082 backup: `collabio-20260918T062951Z.dump`,
`sha256:d2724821f35c11cb9de0b023696593f70ce9dab69dbb458d003d4860c373b0e5`, checksum/catalog verified.
Migration 0082 was the only new migration applied; 82 migrations and 89 tables were verified after this slice.

Primary code and runbooks:

- `app/suite/platform/crm_workspace.py`, `crm_runtime.py`, `tests/test_crm_workspace_api.py`,
  `tests/work_e2e_crm.py` and `docs/modules/CRM_ACCOUNT_WORKSPACE_VERTICAL_SLICE.md`.
- `app/main.py`; `app/suite/platform/knowledge_base.py`; `knowledge_base_runtime.py`.
- `app/suite/persistence/migrations/0082_knowledge_base_version_acls.sql`.
- `app/suite/operations/postgres_restore_drill.py`.
- `app/suite/ui/work/index.html`, `work.js`, `work.css`.
- `tests/test_knowledge_base_read_api.py`, `test_knowledge_base_product_api.py`, `test_knowledge_base_acl_migration.py`,
  `test_knowledge_base_write_unit_of_work.py`, `test_knowledge_base_pg_repository.py` and `test_postgres_restore_drill.py`.
- `tests/work_e2e_server.py`, `tests/work_e2e_seed.py`, `tests/work_e2e_controls.py`,
  `app/suite/testing/work_e2e_guard.py`, `e2e/work/tests/`.
- `docs/modules/KNOWLEDGE_BASE_READER_VERTICAL_SLICE.md`, `KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md`,
  `KNOWLEDGE_BASE_WRITE_APPROVAL_LEDGER.md`,
  `KNOWLEDGE_BASE_SOURCE_RESTORE_EVIDENCE.md` and `MODULE_IMPLEMENTATION_CONTRACT.md`.
- `docs/operations/WORK_E2E.md`, `BACKUP_FAILOVER.md`, `REMOTE_DEVELOPMENT_HOST.md`.

## Existing product and platform status

- `/office` provides native document authoring with explicit saved-text suggestions and atomic acceptance, version-bound review discussions, contextual table editing, find/replace, immutable history, saved-version comparison and historical takeover
  into an unsaved local draft. Explicitly confirmed save appends a new version, under the closed tenant gates.
- `/roadmap` presents capabilities, including guarded native Office; KB shows authoring and ordinary reading, and CRM includes Work account
  details, with real API route paths.
- `/workspace` provides the module cockpit and controlled foundation workflows.
- `/work` provides Tasks/activity, Time, Tickets, KB and CRM with independent loading/error states and responsive UI.
- Tasks include durable lifecycle, reassignment and due-date changes with append-only evidence and shared mutation
  serialization. Time includes submission, maker-checker decisions, correction and resubmission.
- CRM has PostgreSQL/RLS accounts, contacts, activities and notes; Work exposes account details with authorized
  contacts and activities through the existing account workspace.
- ERP remains deliberately limited. LMS and later modules have contracts, not broad user-facing products.
- AI/RAG/voice control planes exist; productive provider execution remains closed.
- Office/Mail architecture, parser/CDR/preview and fidelity paths exist. LibreOffice evidence is ahead of
  Word/GenOffice; production Quick Edit, WOPI and a complete mail client remain open.
- Platform foundation includes signed OIDC/JWT, server-side principals/roles/groups/ACL/ABAC, Forced RLS, append-only
  audit/checkpoints/WORM evidence, classification/retention/Legal Hold/KMS, versioned S3 recovery, module lifecycle,
  isolated PG restore and combined foundation/business release gates.
- Supply-chain controls retain hashed locks, pinned images/actions, SBOM/provenance, license and vulnerability gates.

## Continuation point

Item 272 is complete. Preserve the single full 345-case acceptance (285 browser/60 model), full quality,
actual eight PDFs/16 pages and exact document/image/crop/wrap/page-break/page-settings recovery.
Continue with Roadmap 273 / PLANS 134 document-owned headers/footers and page numbers: bounded literal text,
explicit numbering choices, accessible preview/reset/isolated undo, exact saved-version history/copies,
current authorization and confirmed CAS saves. Prove actual multi-page placement without body overlap
and fresh nonempty recovery. Section layouts, arbitrary fields, continuous editor pagination and DOCX
remain separate. Preserve legacy bytes, the effective named print-page rule and asymmetric margins.
See ADR-0091/0092/0093/0094/0095 and docs/modules/OFFICE_IMAGES_AND_OBJECTS_CONCEPT.md.
Images retain current parent ACLs; independent copies own freshly authorized assets. Keep the isolated
network-none decoder, source pixels, responsive block fallback and historical manifests intact.
Document-owned format styles preserve direct overrides, isolated undo and exact immutable catalog versions.
Continue native Office before CRM. List indentation/outdent and nearest-list start values preserve content and undo,
with validated keyboard actions and table Tab priority. Automatic numbering continuation/styles remain separate work.
Format transfer supports direct character/paragraph values in one editable document,
with exact selection, default clearing, isolated undo and memory-only ownership. Mobile review drawers remain usable.
Whole-document keyboard replacement across rich tables is fixed and directly tested;
the history case owns a rich starting head and verifies local draft preservation after confirmed replacement.
Character sizes/colors, paragraph formatting, history, comparison, printing, reuse, discussions and explicit suggestions
remain intact. Preserve table-removal confirmation, schema/size guards, undo and other marks/drafts.
Continuous tracked changes, live collaboration and broader Office authoring/layout capabilities remain open.
Preserve fresh current access checks, immutable history, atomic accepted versions, explicit confirmed CAS saves and
memory-only draft semantics. No subsequent roadmap item is declared implemented.
Continue DOCX interchange separately through the existing Quick Edit spike, synthetic corpus and source-blind/CDR validation.
Real Word/GenOffice fidelity results, calibrated thresholds and human review remain outstanding; current runtime
authorization and executable-image admission must precede an engine proof. Productive saves and WOPI remain separate
later release steps. The prohibition on Word/account/firewall interventions on the original workstation still applies.

CRM account onboarding in `/work` through `POST /v1/crm/account-onboardings` and subsequent CRM mutations are deferred
behind Office development. Preserve the completed CRM read workflow and its existing atomic backend contracts.
This priority update changes the implementation order; it does not activate any engine, tenant, pilot or indexing.

For any subsequent code change, run the appropriate focused tests and full quality remotely. For durable schema or
data changes, obtain a verified backup and isolated restore/release proofs before the controlled API rollout.
Restore loader runs with --no-deps against isolated postgres-restore only; foundation checks use
`SUITE_SOURCE_OBJECT_RUNTIME_SEED_DEMO=0` to avoid implicit seed writes. Prefer --no-deps where prerequisites have
already been explicitly started and checked, so Compose cannot silently migrate, bootstrap or recreate the API.
After recording hashes, remove only exact Work-E2E services per the runbook and stop auxiliary test/restore services.
Verify health, ports and other projects, then append the complete operation to the owning project's log.

## Open human/external lanes

- Import/activate `.github/rulesets/main.json` for main; enforcement remains pending in REPOSITORY_GOVERNANCE.md.
- Configure protected GitHub staging/production environments and reviewer/bypass policy.
- Supply accountable real-user purpose/principals/legal basis/privacy/workforce evidence and fresh four-eyes approval.
- Supply actual production topology, PITR, immutable offsite, fenced promotion and cross-site recovery evidence plus
  independent signatures before production continuity can pass.
- Separately authorize any Tickets tenant activation.
- Complete Word/GenOffice fidelity rows, calibration and human review; then separately gated Quick Edit/WOPI/mail work.

## New chat bootstrap

Read AGENTS.md and this document completely; inspect local/remote Git and dev001 rules/state before acting.
Continue the same branch from its verified current HEAD, preserve the user's untracked files and the closed pilot,
and follow the user's next product instruction without inferring permission to activate a tenant.
