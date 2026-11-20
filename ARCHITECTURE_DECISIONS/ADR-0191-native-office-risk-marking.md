# ADR-0191: Native Office risk marking

Status: Accepted
Date: 2026-10-10

## Context

Users need help finding potential legal, financial, privacy, security, operational and commitment risks in a saved
document. A model can miss risks, invent findings or cite the wrong passage. The feature therefore needs exact
server-derived source anchors and must remain an untrusted review aid rather than a compliance decision or edit.

## Decision

Add a read-gated `POST /v1/office/documents/{object_id}/ai/risk-markings` endpoint. It accepts only the exact current
saved version ID. It accepts no source body, free instruction, category choice, model, provider, prompt or action.

The server revalidates authoritative read access and current-version identity, then enumerates bounded native text
runs with stable one-based block numbers and exact ProseMirror UTF-16 anchors. The source is rejected when empty or
over 16,000 characters. Only a tenant-allowed, drafting-approved local model behind the Local LLM Gateway is
eligible. Confidential and restricted documents stay closed unless tenant, model and the exact approved prompt all
admit confidential data.

The fixed prompt treats the indexed document as untrusted data and forbids legal, regulatory or compliance
decisions. Output is exactly `STATUS: clear`, or `STATUS: risks` followed by one through eight lines of
`RISK: severity|category|block_number|short explanation`. Severity and category use fixed allowlists. Invalid,
duplicate, unknown, oversized or malformed findings fail closed.

The model never supplies source text or positions. For each validated block number, the server returns the exact
source excerpt and anchor it derived before inference. The browser displays a dismissible read-only report and lets
the user select and scroll to each exact passage. No suggestion, version, annotation, action or compliance decision
is created. Results remain visibly untrusted, transient and excluded from search and RAG indexing. Audit stores only
bounded identifiers, classification-independent counts and hashes, never source, prompt or output bodies.

## Consequences

This adds no migration, durable risk record, document decoration, automatic edit, action execution, compliance
certification, indexing, cloud provider or production admission. Versioned source search, voice and text-to-speech
remain separate roadmap items.
