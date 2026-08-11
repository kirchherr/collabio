# ADR-0065: GenOffice Legal Review Dossier And Human Decision Boundary

Status: accepted
Date: 2026-08-11

## Context

ADR-0062 through ADR-0064 prove the pinned source snapshot, selected source scope, runtime dependency inventory,
vendored byte provenance, pre-build SBOM/vulnerability state, and npm/SLSA/Sigstore provenance. Package license fields
and license-file presence are useful inventory but are not a legal review. They do not preserve every exact runtime
license text, resolve compound expressions, approve NOTICE content, or grant trademark permission.

The GenOffice upstream README also states that `ee/**` has separate enterprise terms and that the GenOffice and
Genspark names and logos are Mainfunc, Inc. trademarks. A worker build must not begin on an implicit or automated legal
assumption.

## Decision

- Add a credential-less collection zone that downloads only the 21 exact runtime package URLs from the reviewed npm
  lock evidence. Verify every archive against the pinned npm `sha512` integrity before retaining it. Do not install
  packages or execute npm, Node, lifecycle scripts, or upstream code.
- Treat a package-declared license without full distributable text as incomplete. For `@nodable/entities@3.0.0`, bind
  npm `gitHead d2070d76...` and repository identity to the exact Codeload source archive SHA-256 `2707baf0...`; use only
  its root MIT license as supplemental legal evidence. The source archive is not an engine import or build input.
- Add a separate no-network legal evidence gate. It reads archives selectively without filesystem extraction and binds
  exact hashes for root LICENSE/NOTICE/trademark evidence, the excluded enterprise license, vendored license, and every
  runtime package legal file.
- Treat SPDX `OR` and `AND` semantics explicitly. The `jszip` distribution choice and cumulative `pako` MIT and Zlib
  obligations remain human decisions. Unknown license expressions fail closed.
- Generate a deterministic `genoffice_legal_review_dossier_report.v1` and
  `genoffice_legal_decision_record.v1` JSON Schema. The schema requires reviewer identity, professional role, legal and
  change references, exact scopes, trademark resolution, distributable NOTICE hash, per-question/per-dependency
  resolutions, and detached-signature verification evidence.
- Do not create or simulate the human decision record. Keep legal review, source import, engine execution, worker build,
  image SBOM admission, and production use false until independently verified evidence opens each later gate.
- Retain package archives, collection report, dossier, decision schema, and any future signed decision as immutable
  supply-chain/release-recovery artifacts. They contain no tenant or Office document content.

## Consequences

- Counsel receives an exact, reproducible review set instead of package metadata or a hand-maintained spreadsheet.
- Registry acquisition and legal evaluation have distinct network and trust boundaries.
- Trademark and enterprise-code exclusions become release invariants, not naming conventions.
- A successful automated dossier means only `human_review_ready`; it cannot set `legal_review_complete`.
- The reproducible worker build remains correctly blocked until the signed human decision is verified. Image-derived
  SBOM, vulnerability, malicious-file, fidelity, sandbox, and recovery evidence remain separate gates afterward.

## References

- https://www.apache.org/licenses/LICENSE-2.0
- https://www.apache.org/legal/apply-license.html
- https://spdx.github.io/spdx-spec/v3.0.1/annexes/spdx-license-expressions/
- https://github.com/genspark-ai/genoffice/tree/fd33934dab1fdf8666af3f88b9794e7b4e19474a
