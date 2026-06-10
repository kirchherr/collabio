# Data Classification

Status: initial
Date: 2026-06-10

## Required Metadata

Every persistent object must carry:

```text
tenant_id
object_id
object_type
data_classification
retention_policy_id
legal_hold_state
kms_key_ref
audit_chain_ref
schema_version
created_at_utc
updated_at_utc
```

## Core Data Classes

| Class | Examples | Storage | Deletion | KMS | Audit | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `gobd_record` | invoices, business mail, tax-relevant records | WORM | after retention only | tenant + class + object | required | Never cryptoshred before legal retention permits |
| `personal_data` | contacts, user metadata, activity records | encrypted | policy-based delete or restrict | tenant + class | required | DSGVO workflows apply |
| `legal_hold` | dispute or audit matter records | WORM + hold | blocked until hold lifted and policy permits | tenant + class + object | required | Legal hold wins over lifecycle deletion |
| `working_data` | drafts, CRDT deltas, comments in progress | versioned non-WORM | policy-based | tenant + class | required for sensitive actions | May become records later |
| `temporary` | cache, previews, transient snippets | short-lived | automatic | tenant + class when sensitive | minimal | Must not be sole evidence |
| `security_data` | audit, auth, admin actions | append-only | very restricted | tenant + security class | required | Tamper-evident |
| `export_package` | e-discovery export, audit pack | encrypted WORM candidate | policy-based | export-specific key | required | Must include manifest and chain of custody |

## AI And Voice Data Classes

| Class | Examples | Storage | Deletion | KMS | Audit | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `ai_prompt` | user prompt, task instruction | encrypted | retention-limited | tenant + AI class | hash + metadata required | Prompt bodies must not enter normal logs |
| `ai_output` | summaries, drafts, labels | draft/versioned | policy-based | tenant + AI class | required | Untrusted until validated |
| `rag_chunk` | extracted document/mail text chunk | follows source | follows source | follows source | required | Classification inherits source class |
| `embedding` | vector representation | vector store | delete/reindex with source | tenant + embedding class | required | Not anonymous by default |
| `retrieval_trace` | used sources and chunks | audit/evidence | policy-based | tenant + audit class | required | E-discovery relevant |
| `voice_audio` | raw microphone audio | disabled by default | tenant policy only | tenant + voice class | required if stored | Raw storage requires explicit policy |
| `voice_transcript` | transcribed speech | encrypted | retention-limited | tenant + voice class | required | Personal data |
| `tool_call` | AI action request | audit/evidence | policy-based | audit class | required | Destructive actions need approval |
| `model_config` | model, checksum, provider | registry | versioned | config protection | required | No unverified model activation |
| `ai_evaluation` | tests, scores, failures | release evidence | versioned | project evidence | required | Release-relevant |

## Lifecycle Conflict Order

When policies conflict, evaluate in this order:

```text
1. Tenant isolation
2. Legal Hold
3. Regulatory retention
4. Contractual retention
5. Data subject rights
6. Business policy
7. Default deny
```

## Classification Rules

- If an object is derived from a source, it inherits the highest sensitivity of the source unless explicitly downgraded by policy.
- Embeddings and snippets are not anonymous by default.
- Redacted exports are separate objects with their own metadata and provenance.
- A draft can become a record only through an explicit record-commit workflow.
- AI-generated text remains draft-level until accepted by a user.

