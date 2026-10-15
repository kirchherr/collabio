# ADR-0107: Bounded native image transforms

Status: Accepted
Date: 2026-10-01

## Context

Native images retain immutable document-owned PNG/JPEG renditions, crop, wrapping and anchored layers. Users also need
common orientation corrections without uploading a newly edited file. Persisting arbitrary CSS transforms, matrices or
angles would expand the active-format surface and make responsive layout, printing and interchange ambiguous.

## Decision

An image may optionally store exactly `transform = {rotation, flipX, flipY}`. `rotation` is one of `0`, `90`, `180`
or `270` degrees clockwise. `flipX` and `flipY` are booleans. Unknown keys, strings, numeric booleans, arbitrary angles,
CSS and an explicit identity transform fail before persistence. The identity is represented only by omitting the
optional property, preserving legacy canonical bytes.

The editor exposes a labelled rotation selector and independent horizontal and vertical mirror controls. Preview,
editor, comparison and print derive presentation only from the validated values. Quarter turns exchange the reserved
width and height; a responsive frame scales the original visual as one unit, so flow and narrow layouts reserve the
rotated bounds. Crop remains non-destructive and precedes the visual transform. Caption, alternative text, immutable
asset identity and authorization are unchanged.

Applying a change creates one isolated undo transaction. Confirmed CAS saves append immutable document versions.
History, independent copies, print and recovery retain exact orientation. Reset omits `transform`. Recovery requires a
consecutive 90-degree-plus-horizontal-mirror version, a 270-degree-plus-both-mirrors version and an identity reset for
the same owned rendition, with unchanged crop, wrap and position.

## Consequences

Users can rotate in quarter turns and mirror images without modifying source pixels or introducing executable content.
Arbitrary-angle rotation, freeform transformation matrices, wrap contours, grouped objects, absolute physical-page
anchors and DOCX anchor interchange require separate decisions and measured fidelity work.
