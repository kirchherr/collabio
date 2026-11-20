# ADR-0184: Native Office import compatibility matrix

Date: 2026-10-10

Status: Accepted

## Context

ADR-0182 defines the isolated parser-worker plan and ADR-0183 enforces active-content rejection before extraction.
Neither decision describes which ordinary features survive the current development parser. A successful text result
must not be mistaken for full DOCX, ODT or PDF fidelity, and unsupported parts must be visible before an import or
export pipeline is admitted.

## Decision

Expose `office_import_compatibility_matrix.v1` as a tenant-scoped, Office-read-gated, metadata-only endpoint. It
accepts no bytes, source object identifier or source version. Its thirteen feature rows cover DOCX, ODT and PDF and
use only five states: bounded text support, flattened text, blocked active content, visible review marker and
unsupported. Every row sets fidelity preservation to false.

Describe DOCX main-document paragraphs as bounded text support; flatten heading, list and table-cell text; mark
headers, footers, notes, comments, drawings and revisions unsupported. Describe ODT paragraph and heading text as
bounded support and flatten lists, tables, styles, fields and annotations. Describe basic PDF literal strings as
flattened and scans, complex fonts, layout, forms and accessibility structure as unsupported.

Reuse ADR-0183 for active-content outcomes: DOCX VBA/ActiveX/OLE/templates, ODT scripts and PDF JavaScript/actions/
embedded files stay blocked before extraction, while nonexecuting signature and external-link indicators stay
visible review markers. The matrix endpoint itself performs no parsing and accepts no content.

Return a noncacheable response and audit only schema, matrix state, bounded entry/format/block/mark counts and closed
import/export/fidelity flags. Keep import dispatch, export, round-trip fidelity claims and production admission false.

## Consequences

The UI and API now communicate the present feature boundary without overstating successful text extraction. The
matrix is a reviewable contract for the next test corpus, not an interchange engine or production admission.

Real representative and malicious fixtures, expected extracted and exported derivatives, deterministic hashes,
license/provenance records, recovery evidence and engine admission remain required. This ADR adds no migration,
content intake, parser dispatch, export, round-trip-fidelity claim or production release.
