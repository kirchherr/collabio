# ADR-0156: Arbitrary-angle native Office shape rotation

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office shapes support an optional whole-degree rotation from 1 through 359. Zero degrees remains the
canonical absence, preserving existing document bytes. Browser and server reject booleans, fractions, negative
values, values above 359, transform matrices, CSS strings, URLs and unexpected object keys. The former quarter-turn
values remain valid instances of the expanded contract.

The responsive shape dialog accepts an exact degree value. A selected shape also exposes a focusable rotation handle:
pointer or touch movement follows the angle around the shape center with one-degree precision, arrow keys move one
degree, Shift plus an arrow moves 15 degrees, Home returns to zero, and a click retains the convenient 90-degree step.
A completed gesture is one isolated undo transaction; cancellation and invalid input do not mutate the draft.

Normal-flow and wrapped shapes reserve the exact axis-aligned bounding box derived from their validated dimensions
and angle. The same trusted numeric geometry is used for group members and semantic print/PDF. Positioned shapes keep
their logical anchor and rotate inside it. Static CSS consumes only numeric custom properties written by product code;
document content cannot provide style expressions. The existing 90/270 compatibility marker remains available while
all non-180-degree rotations use the generalized bounded layout path.

Confirmed save, immutable history, comparison, independent shape and group duplication and print preserve the exact
integer angle. No SQL migration or new recovery store is required because the existing immutable native-document JSON
already owns the value. No endpoint, dependency, external request, provider, worker, transform matrix, separate text
rotation, physical page anchor, DOCX DrawingML interchange or ordinary tenant admission is introduced.

Acceptance requires independent browser/server rejection, exact bounding-box model checks and responsive desktop and
mobile workflows covering dialog, keyboard, pointer, undo/redo, confirmed save, history and print.
