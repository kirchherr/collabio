# ADR-0129: Native inert Office document objects

Status: Accepted
Date: 2026-10-06

## Context

Native Office already supported inline references to an exact saved document version and ACL-safe outbound resolution
and backlinks. Authors still lacked a visible block object for placing another Office document in the document flow.
Persisting a copied title, rendering active foreign content or following a moving target during load would leak metadata
or make an immutable historical version render differently over time.

## Decision

Add one top-level atomic `documentCard` block. It stores only an exact `targetObjectId`, exact `targetVersionId` and a
bounded mode: `snapshot` or `linked`. It stores no title, URL, HTML, preview body, credentials or executable payload.
Document cards and inline document references share the existing maximum of 100 occurrences and the same authoritative
reference/backlink inventory.

Both modes always render the saved target version. Snapshot mode stays fixed. Linked mode may move to the target's
current saved version only after the author opens the object controls and explicitly chooses **Auf aktuelle Version
aktualisieren**. This creates an ordinary visible draft change and never changes a saved source version silently.

Every display resolves the target through the source document's exact-version outbound-reference endpoint. The server
rechecks current tenant membership and target ACLs before returning a title. Missing, revoked or foreign targets render
only **Dokumentobjekt nicht verfügbar**. Audit and normal logs contain IDs and bounded counts, never resolved titles or
document bodies.

The object is inert. It cannot execute OLE, ActiveX, macros, scripts, iframes or remote content. Opening a target is an
explicit action and is disabled while the source draft is dirty. Move earlier/later, duplicate and remove are focusable
actions and each successful mutation is one isolated undo step. Duplicate preserves the exact reference; it does not
copy or grant access to the target.

Confirmed compare-and-swap save remains the only durable mutation. Editor, comparison, print, history, reload and
backlinks consume the same exact reference stored in the existing immutable Office version JSON. No relational schema
or object-storage format changes.

## Consequences

Authors can compose documents from visible, accessible document objects without granting an embedded runtime or
creating metadata snapshots that outlive access. Linked objects are predictable because refresh is always deliberate.
The existing exact Office-version recovery already preserves the block, and reference recovery continues through the
shared authoritative walker. Rich previews, embedded file objects, native sheets/slides, transitive reference graphs,
persistent backlink indexes, automatic updates and DOCX/OLE interchange remain separate decisions.
