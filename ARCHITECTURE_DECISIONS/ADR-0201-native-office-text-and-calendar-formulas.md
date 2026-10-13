# ADR-0201: Native Office text and calendar formulas

## Status

Accepted on 2026-10-13.

## Decision

Native Office extends its bounded formula grammar with quoted text literals, text-valued cells and named ranges,
exact text lookup and deterministic calendar functions. Double quotes delimit a literal and a doubled quote escapes
one quote. German function names and semicolon separators normalize to canonical English formulas before persistence,
while literal spelling, punctuation and case remain unchanged.

`CONCAT`/`VERKETTEN`, `LEFT`/`LINKS`, `RIGHT`/`RECHTS` and `LEN`/`LÄNGE` operate on bounded scalar values.
`XLOOKUP`/`XVERWEIS` accepts equal-sized local or named ranges and compares numbers as numbers and text as exact text.
Empty cells resolve to empty text; numeric operators may coerce only empty text to zero. Text results are limited to
512 characters, reject control characters and cannot begin with `#`, which remains reserved for formula errors.

`EDATE`/`EDATUM`, `EOMONTH`/`MONATSENDE`, `DAYS`/`TAGE` and `WEEKDAY`/`WOCHENTAG` use integer UTC day numbers.
Month shifts clip to the last valid day, month offsets stay within 120,000 months and supported calendar results stay
within years 1900 through 9999. `WEEKDAY` returns ISO weekday numbers from Monday 1 through Sunday 7. These functions
do not depend on locale, timezone, current time or an external service.

The browser recalculates the draft inside the existing document-wide dependency graph. The server independently
parses every formula, resolves every table and named range and recalculates every stored scalar result before a
confirmed immutable version save. Structural reference and named-range remapping ignores reference-looking text
inside literals. Invalid syntax, unsafe text, missing references, type mismatches, calendar overflow and stale or
forged results fail closed.

## Consequences

The block reuses the native document JSON and requires no migration, external spreadsheet engine, network source or
new durable state. Approximate and wildcard lookup, locale-dependent parsing, volatile current-time functions,
external workbook links, macros and automatic saves or actions remain outside this decision.
