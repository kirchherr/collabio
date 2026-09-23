# ADR-0093: Native image text wrapping

Date: 2026-09-23
Status: implementation; acceptance pending

Add optional image `wrap` metadata with exactly `side` (left/right) and integer
`gap` (0 through 48 CSS pixels). Absence preserves the previous block layout and
canonical bytes. UI reset omits the property; explicit API null is rejected. The
existing alignment remains the block fallback and is independent of wrap side.

The image node's ordered position is the anchor. Only subsequent top-level paragraphs
wrap. Headings, lists, tables, quotes, code, rules and the next image clear both sides.
Moving the node moves its anchor; text is never reordered. Nested images in lists,
quotes and cells retain metadata but use the block fallback. No page coordinate,
overlap, absolute positioning or implicit cross-container anchor is stored.

Editor, preview and print use the same bounded float rules. Wrapping reserves at most
45% of the text column for the image, scales its displayed image height to at most
480px and applies the chosen gap on the text-facing side and below. The caption stays
with the image and wraps within its width. At column widths of 480px or less the
image becomes a block, retaining the user's stored dimensions, crop and wrap choice.
Layout changes never rewrite the document or create undo entries. The dialog explains
these limits and previews wrapping with sample text before applying one guarded undo
transaction. Keyboard-accessible selects/numeric fields, cancel and block reset apply.

Print uses the physical page's text-column width, independent of the screen viewport.
Image and caption request break-inside avoidance; a figure fitting a page moves to
the next page when necessary. Over-page captions remain subject to the browser's
fragmentation rules; no universal pagination/fidelity guarantee is made. Actual
left/right, crop, paragraph clearance and multi-page PDF checks are required.
References: [CSS floats](https://www.w3.org/TR/CSS22/visuren.html#floats) and
[CSS fragmentation](https://www.w3.org/TR/css-break-3/#break-within).

Save/history/comparison/owned copies preserve exact optional layout. Source pixels,
parent ACLs, confirmed CAS saves and crop semantics stay unchanged. No endpoint,
SQL migration, dependency, decoder or tenant admission change is required. A rollback
must retain compatible readers and historical metadata while closing further writes.
Fresh nonempty PostgreSQL/S3 recovery must prove left, right and reset versions of
the same owned image along consecutive predecessor links before API rollout.
