# ADR-0091: Document-owned native image renditions

Date: 2026-09-23
Status: accepted for development; implementation, recovery and decoder/API rollout verified

Native Office needs an upload, insert, edit, save, reopen and print loop. The existing
versioned source store already supplies tenant separation, hashes, receipts, retention,
KMS and exact S3 recovery. Reuse it without a second binary store or SQL migration.

Each normalized image is an immutable `attachment` source with its own random object
and version IDs and a required parent native document. Its effective ACL is the current
authoritative parent document ACL. Independent asset grants and cross-document sharing
are not supported. Upload requires current parent write permission; content requires
current parent read permission. A foreign parent never reveals an asset or thumbnail.

The canonical document JSON is the version's reference manifest: each image node binds
parent ID, asset ID, version ID, source manifest hash, content hash and exact pixel size.
Up to 40 in-flow block images have bounded dimensions, alignment, literal alt/caption,
an explicit decorative choice and an aspect-lock preference. Save verifies all sources
under the existing tenant write lock before persisting the new version and receipt.
Explicit Create with an authorized source image copies its normalized bytes into a new
asset owned by the newly created document in that metadata transaction. Idempotent replay
returns the committed rewritten manifest. Later source ACL revocation does not revoke
the independently owned copy. Ordinary Save rejects cross-document image references.

Uploads require an existing saved document and explicit upload action. They do not
advance its head. Originals, filenames and EXIF are not persisted. Up to 200 retained
uploads per document bound abandoned assets; cancellation/removal does not delete them.
Retention-aware orphan deletion is a separate confirmed lifecycle workflow. PostgreSQL
transactions cannot roll back S3 PUTs; existing reconciliation remains required.

Pillow 12.3.0 from the existing hash-locked preview dependency is isolated in a dedicated
credential-free `network_mode: none` container. The API connects only through a shared
Unix socket. PNG/JPEG signature and MIME must agree; input is limited to 8 MiB, decoded
images to 4096 pixels per axis and four million pixels. Animation, SVG and external URLs
are rejected. Each decode uses a fresh subprocess with address-space, CPU, file-size and
wall-clock bounds. The container drops all capabilities, is non-root/read-only, has a
bounded tmpfs and no API/database/storage secrets or host socket. Only raw RGBA pixels
cross back; the API constructs a minimal PNG from validated dimensions and exact byte
count. This reuses Pillow without bringing the DOCX/PDF converter into the API.

The editor and print preview use authenticated no-store fetches and short-lived blob URLs,
revoked on destruction/context close. No asset URLs or binary bodies enter native JSON.
Printing fetches the exact saved manifest and every rendition again, waits for decoding
and fails visibly if an asset cannot be loaded. No fallback source or external fetch exists.
Search/review/suggestion offsets treat images as single leaf nodes; captions are properties,
not text runs. All mutations retain draft/undo semantics and confirmed CAS Save.

First-slice scope excludes floating/wrapped images, crop, SVG, original-file recovery,
image upload before first Save, shared media libraries, active objects and DOCX interchange.
The normal tenant/pilot/indexing/engine gates remain closed. Acceptance requires real
decoder/browser tests, malformed/limit/ACL/reuse cases, PDF/visual inspection and a fresh
nonempty document-plus-asset PostgreSQL/S3 recovery proof before rollout.

Operate the decoder through the explicit `office-images` Compose profile; it has no host
port. Existing saved-image reads do not need the decoder, but uploads fail closed when it
is unavailable. After image versions exist, a downgrade to a pre-image native schema is
not a compatible reader rollback. Disable further writes and retain a compatible reader
while repairing the decoder; never delete assets or rewrite historical manifests as a
rollback shortcut. Exact document-plus-asset recovery remains the durable recovery path.
