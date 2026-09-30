# ADR-0104: Native Office document references

## Status

Accepted

## Context

Collabio Office supports document-local references, but a writer could not bind selected text to an exact version of
another native document. Storing a title or treating an earlier list result as lasting authorization would leak
metadata after an ACL change. A global backlink index would add a separate discovery and deletion-propagation surface.

## Decision

The native format adds the bounded inline `documentReference` mark. It stores only an exact `targetObjectId` and
immutable `targetVersionId`; titles, permissions and rendered status are never stored in the source document. IDs
have strict native grammars, at most 100 marks are accepted, and the mark cannot overlap code, links or local
cross-references.

The read-only outbound-reference API re-reads the exact authorized source version. It then resolves every distinct
target through the ordinary repository tenant, current ACL and exact-version checks. A resolved target may return its
historical version title and whether that version is current. A missing object, missing version and unauthorized
target all return the same `unavailable` state without a title. Audit events contain only source IDs, version IDs and
counts.

The editor lists only currently readable documents and stores the selected current version. Opening an existing
reference calls the resolver again immediately before navigating to the exact version. Unsaved references cannot be
opened. Loading and every print refresh also resolve against current ACLs. Print emits inert semantic spans, never a
cross-document URI or PDF action. Copies retain exact identities and become safely unavailable when their reader
lacks target access.

No new table or backlink is introduced. Resolution is derived from the immutable source version and authoritative
target repositories, so revocation and deletion take effect without denormalized cleanup.

## Consequences

- A later target edit cannot silently retarget an existing source reference.
- Revoked, deleted and unknown targets are indistinguishable to the source reader and expose no title oracle.
- Exact historical references remain usable while the target version exists and the current target ACL permits it.
- Global backlinks, reference discovery, transitive graphs, URL previews and DOCX relationships remain separate.
