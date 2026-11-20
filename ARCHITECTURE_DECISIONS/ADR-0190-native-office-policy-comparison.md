# ADR-0190: Native Office policy comparison

Status: Accepted
Date: 2026-10-10

## Context

Users need to compare a saved document with a readable policy without copying either body into a browser-supplied
prompt. A model comparison can miss obligations or invent compliance, so it must remain an untrusted review aid and
must cite the exact policy version used. It must never approve compliance or change either document.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/policy-comparisons` endpoint. It accepts only the exact
current source version ID and the object and exact current version IDs of a different policy document. It accepts no
source body, policy body, free instruction, model, provider, prompt or requested outcome.

The server revalidates authoritative read access to both documents, loads both immutable versions and derives their
native text. Both sources must be nonempty, current and individually bounded to 16,000 characters; an over-limit
source fails closed instead of being silently truncated. The higher source classification controls inference. Only a
tenant-allowed, drafting-approved local model behind the Local LLM Gateway is eligible. Confidential and restricted
sources stay closed unless tenant, model and the exact approved prompt all admit confidential data.

The fixed approved prompt treats both delimited sources as untrusted data and forbids legal or regulatory approval.
Output has a strict grammar: one `STATUS: conform|deviation|unclear` line followed by one through eleven bounded
`FINDING:` or `RECOMMENDATION:` lines, including at least one finding. Invalid, oversized or malformed output fails
closed.

The response remains visibly untrusted, transient and non-indexable. It binds the source version and hash to an exact
policy object, version, title and hash after ACL validation. Audit stores only bounded identifiers, status, counts and
input/output hashes; document and model bodies stay out of normal logs and audit. The browser displays a dismissible
read-only report and exact policy citation. No suggestion, version, approval, record transition or follow-up action is
created.

## Consequences

This adds no migration, compliance certification, free prompt, cloud provider, durable comparison, automatic edit,
automatic approval, action execution, search/RAG indexing or production admission. Risk marking, source-backed RAG,
voice and text-to-speech remain separate roadmap items.
