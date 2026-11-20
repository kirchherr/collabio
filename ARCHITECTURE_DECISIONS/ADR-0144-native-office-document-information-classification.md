# ADR-0144: Native Office document information classification

Status: Accepted
Date: 2026-10-08

## Context

Collabio already has canonical runtime data classes for storage, retention, legal hold, AI and RAG controls. Those
classes are technical compliance metadata and cannot express the familiar document labels Öffentlich, Intern,
Vertraulich and Streng vertraulich without collapsing independent retention and regulatory concerns into one field.
ISO/IEC 27001 requires an organization to define and handle information classification according to its needs, but it
does not prescribe these four literal labels.

## Decision

Add a separate, bounded `information_classification` to native Office documents and every immutable document version:
`public`, `internal`, `confidential` or `restricted`, displayed in German as Öffentlich, Intern, Vertraulich and Streng
vertraulich. New documents default to Intern for backward compatibility. The canonical SourceObject
`data_classification` remains `internal`; retention, legal hold, KMS selection and source lifecycle therefore retain
their existing independent contracts.

Store the selected value in `office.documents` and `office.document_versions` through migration 0086. Bind the mutable
head value to the referenced immutable version in the database trigger and include the value in actor-bound command
hashes, API views, history, audit metadata and restore-control verification. A classification never grants read or
write access; current tenant, feature and authoritative ACL checks remain mandatory.

Allow an authorized writer to retain or increase protection. Reserve creation as Öffentlich and every reduction in
protection for `tenant-admin`. Keep the existing explicit confirmed-save and optimistic current-version checks for
every change. The editor exposes the selection during creation and editing, shows historical version values, carries
it through reuse and restore, compares changes between versions, and prints the saved version's visible label.

## Consequences

Authors get a clear four-level information-handling label without weakening ACLs or misusing regulatory data classes.
Every saved transition is immutable, auditable and covered by PostgreSQL restore verification. Publishing and
downgrading remain privileged. Classification-specific sharing policies, DLP enforcement, watermarks beyond the print
label and tenant-configurable taxonomies remain separate future decisions.
