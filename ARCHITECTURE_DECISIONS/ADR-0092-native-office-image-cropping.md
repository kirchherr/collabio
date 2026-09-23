# ADR-0092: Non-destructive native image cropping

Date: 2026-09-23
Status: implementation; acceptance pending

Extend the ADR-0091 image node with an optional `crop` object containing exactly
integer `x`, `y`, `width`, `height` in normalized source-image pixels. Origins are
nonnegative, sizes positive, and the rectangle must fit entirely within pixelWidth/
pixelHeight. No floating point, percentages, negative/outside coordinates or new URL
is admitted. Absence means the whole image; UI reset omits the optional property,
preserving legacy canonical bytes. The editor's internal null default is omitted
before serialization; explicit null is not an admitted API crop.

Display width/height describe the resulting viewport. Aspect lock follows the crop's
ratio; changing/resetting crop keeps display width where possible and adjusts height
within existing display limits. Without the lock, the existing viewport dimensions
remain. A pointer selection on the original image and bounded numeric fields share
one geometry validator. Arrow keys move the selection; Shift moves ten pixels.
Cancel discards dialog changes; apply is one selection/context-bound undo action.

The original authenticated rendition and its hashes never change. A clipped viewport
renders the exact rectangle in editor, dialog preview and browser print. Captions and
alternative text retain their normal semantics; the selection surface is only a
temporary editing aid. Comparison reports crop geometry. Save/history/copy preserve
it in the immutable document manifest. Crop is presentation, not redaction: readers
can still obtain the complete source image, including the cropped-away pixels.

No new endpoint, dependency, decoder behavior, SQL migration or asset is introduced.
All current parent ACLs, fresh print reads, owned-copy rules and closed admission
remain. Acceptance requires strict geometry/legacy-byte tests, real browser pointer/
keyboard/numeric/undo/history/copy/print tests, actual PDF visual review and a fresh
nonempty restore including cropped and reset versions before API rollout.
