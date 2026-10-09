# ADR-0105: Native Office backlinks

## Status

Accepted

## Context

An authorized reader can follow an outbound Office document reference, but the referenced document did not show which
other documents currently point to its exact version. A persistent backlink index would duplicate authorization and
deletion state. Counting or naming inaccessible source documents would also create a metadata oracle.

## Decision

The document service derives backlinks from current versions of native Office documents that the current user may
read. It first reauthorizes the target object and exact target version. Every candidate source is then fetched again
through the ordinary tenant and current authoritative ACL checks, its current immutable version is read, and only an
exact target object/version match is returned. The response contains the current source object ID, current source
version ID, current title and bounded reference count; it never contains source content or inaccessible-source
counts.

Each request scans at most 50 authorized source documents and returns at most 50 backlinks. A signed continuation
cursor is bound to tenant, actor, roles, target object, target version and page size. Empty intermediate pages remain
explicit and may offer a further bounded scan. The editor binds every response to the active tenant, target document,
target version and session. Deliberate navigation opens the exact returned source version through the normal read
path, which checks authorization again.

Backlinks are derived on demand. No backlink table, global content index, deletion queue or authorization snapshot is
introduced. Audit events contain target identity and aggregate scan/result counts only; source titles and document
content are excluded. Printing does not request or render backlinks.

## Consequences

- Revocation or deletion removes a source from subsequent results without index cleanup.
- A reader cannot infer inaccessible source existence, count or title from the endpoint.
- Results describe exact-version references from current readable source versions; historical source versions do not
  appear as current backlinks.
- Large readable document sets require deliberate bounded pagination and can contain empty intermediate pages.
- Transitive graph discovery, content-wide reference search, persistent indexing and DOCX relationships remain
  separate work.
