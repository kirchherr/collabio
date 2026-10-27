# ADR-0117: Bounded typography for native Office shapes

Status: Accepted
Date: 2026-10-05

## Context

Native shapes preserve literal text and fixed alignment, but meaningful diagrams also need a controlled visual
hierarchy inside shapes. Accepting font names, arbitrary CSS or free style strings would create inconsistent output,
expand the parser surface and weaken responsive and print fidelity.

## Decision

A shape may optionally store `fontSize` as an integer from 10 through 72 pixels except 16, `textColor` as one of
`white`, `slate`, `red`, `orange`, `yellow`, `green`, `teal`, `blue`, `purple` or `black`, and `textStyle` as `bold`,
`italic` or `boldItalic`. The canonical 16-pixel size, automatic contrast-aware color and normal style are represented
by absence. Explicit defaults, transparent text, booleans, unknown keys, font families, URLs, CSS, markup and values
outside the bounds fail closed in both browser and server validation.

The editor exposes a numeric size field and fixed color and style selectors. Preview, accessible description, editor,
comparison and static print consume the same validated attributes. The attributes remain owned by each member when a
shape enters, leaves or changes position inside a group. Edits use the existing isolated shape transaction and
confirmed version save behavior.

## Consequences

Authors can build legible labels and visual hierarchy without loading fonts or executable presentation. Font family,
font embedding, arbitrary weight, underline, rich text runs inside a shape, automatic contrast scoring and DOCX
DrawingML typography remain separate decisions.
