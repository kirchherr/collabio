# ADR-0215: Bounded native Office embedded DOCX images

## Status

Accepted for the bounded development preview. Ordinary tenant/pilot/production admission and productive DOCX
import/export remain closed.

## Decision

- First prove the existing path with a synthetic DOCX stored in the isolated PostgreSQL/S3 harness. Browser discovery,
  exact-version preview, socket parsing and explicitly confirmed native save must use real responses.
- Admit at most eight image occurrences, one MiB aggregate encoded media and four million aggregate decoded pixels.
  Existing per-image limits (4096 per axis, four million pixels) and parser transport/archive limits also apply.
- Accept only a single inline DrawingML picture in an otherwise empty ordinary body paragraph. Preserve source order;
  reject mixed text/pictures, anchors, pictures in headings/lists/tables, crop/effects/transforms, VML and ambiguous
  drawing structures. Section geometry and Word layout fidelity remain separate work.
- Resolve unique package-local image relationships from `word/_rels/document.xml.rels` only. Targets must be canonical
  direct `media/` filenames with PNG/JPEG extensions and matching package content types. Reject external images,
  traversal, absolute paths, encodings, duplicate IDs/ZIP members, missing targets and MIME/signature mismatches.
  Neither API nor parser fetches a URL. The isolated parser emits bounded hash-bound media bytes without decoding.
- Independently validate the complete parser block, raw hash, byte/count limits and normalized text equality in the API.
  Normalize through the existing isolated image decoder and trusted RGBA-to-PNG reconstruction. Preserve alpha; keep
  filenames, EXIF, original media and arbitrary DrawingML out of saved assets and normal logs.
- The unsaved preview carries deterministic temporary image identities and normalized PNG renditions only in response
  memory. No source content or asset is persisted by preview. Temporary identities bind the exact source/version,
  structure and normalized content and cannot authorize an asset fetch.
- At explicitly confirmed native Create, freshly authorize and reparse the exact source, verify provenance and each
  temporary reference, prevent classification downgrade, then copy normalized bytes into ordinary document-owned
  assets using the existing tenant write lock and PostgreSQL transaction. Existing CAS saves reject foreign references.
  Exact retries return committed renditions; a retry must not create duplicate assets. Saved assets subsequently use
  only the existing authorized parent ACL/content route, immutable versions, recovery and print contracts.
- Information classification remains attached to the imported native document; storage assets retain the existing
  internal storage envelope and inherit the authoritative parent ACL. This does not convert information classification
  into a new storage/KMS policy. No source or extracted bodies enter audit/ordinary logs.

## Consequences

This closes a deliberately small embedded PNG/JPEG lane without a migration or new store. Unsupported structures fail
closed. S3 PUTs are outside the PostgreSQL transaction and existing orphan reconciliation still applies. Rich DrawingML,
vector media, linked images, full-fidelity import/export, WOPI, automatic persistence and external engines remain closed.
The existing parser still requires nonempty body text; picture-only packages remain outside this preview contract.
Nonrectangular masks, inset fills, nonzero local offsets and explicitly hidden pictures fail closed. Source authorization
is repeated after decoder work without broadening ACL mutation rights or the existing Office-only expiry policy.
