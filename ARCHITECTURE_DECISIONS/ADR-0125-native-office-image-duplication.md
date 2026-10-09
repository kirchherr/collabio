# ADR-0125: Independent duplication of standalone native Office images

Status: Accepted
Date: 2026-10-05

## Context

Authors can duplicate complete image groups, but reusing one standalone image still requires another upload or an
indirect document-copy workflow. Reusing the original asset identity would couple both placements to one retained
binding, and a freely positioned copy placed at the same coordinates would be hidden directly behind its source.

## Decision

The image dialog exposes a focusable **Bild duplizieren** action for a selected ungrouped image. A dedicated endpoint
rechecks current tenant and write authorization, validates the immutable source bytes and creates a fresh
document-owned asset and version in one transaction. The existing 200 retained-asset and 40 document-image limits
apply before a draft copy is inserted.

The editor accepts only a complete response with the same document, normalized pixel hash and dimensions plus fresh
asset and version identities. It then resolves the original selection again and inserts the copy directly after the
source in one undo transaction. Numbered copies receive a fresh figure ID. Dimensions, crop, wrapping, transform,
alignment, alternative text, caption and decorative state remain exact. A freely positioned copy keeps its layer and
moves by 40 horizontal and 24 vertical logical units, reversing direction near the permitted edge so it remains
visible inside the existing bounds.

Failed, incomplete, stale, unauthorized or invalid responses leave the draft unchanged. Confirmed compare-and-swap
save remains the only document mutation. Created image objects retain the existing receipt, ACL, retention,
legal-hold, backup and recovery contracts.

## Consequences

Authors can reuse one image without shared asset or figure identities, including wrapped and freely positioned
images. A transport failure can leave a validated retained asset without a draft reference, so the existing
200-asset bound remains the safety limit until a separately confirmed retention-aware cleanup workflow exists.
Grouped-member duplication, arbitrary drag placement, wrap contours, physical page anchors and DOCX DrawingML
interchange remain separate decisions.
