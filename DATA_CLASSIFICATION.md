# Data Classification

Status: canonical-registry-active
Date: 2026-06-11

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

## Canonical Runtime Data Classes

The active registry is `suite.compliance.data_classes`. Runtime enums, KMS policy, retention policy, vector DB constraints, prompt/model registries, and this document must stay in sync.

| Class | Examples | Storage | Deletion | KMS | Audit | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `public` | published help text, public procedure snippets | encrypted or public bucket by policy | policy-based | tenant + class | optional by policy | Still tenant-scoped when persisted |
| `internal` | drafts, CRDT deltas, non-sensitive working records, model config | encrypted | policy-based delete or restrict | tenant + class | required for sensitive actions | `working_data` is a lifecycle concept, not a data class |
| `personal` | contacts, user metadata, activity records, personal CRM data | encrypted | policy-based delete or restrict | tenant + class | required | DSGVO workflows apply |
| `confidential` | privileged business data, security evidence, retrieval traces, export packages | encrypted | policy-based restrict or evidence review | tenant + class | required | Use for sensitive evidence until a narrower class exists |
| `gobd` | invoices, business mail, tax-relevant records | WORM | after retention only | tenant + class + object | required | Former `gobd_record`; never cryptoshred before retention permits |
| `legal_hold` | dispute or audit matter records | WORM + hold | blocked until hold lifted and policy permits | tenant + class + object | required | Legal hold wins over lifecycle deletion |
| `ai_prompt` | user prompt, task instruction | encrypted | retention-limited | tenant + AI class | hash + metadata required | Prompt bodies must not enter normal logs |
| `ai_output` | summaries, drafts, labels | draft/versioned | policy-based | tenant + AI class | required | Untrusted until validated |
| `rag_chunk` | extracted document/mail text chunk | follows source | follows source | follows source | required | Chunk text is source-derived and must be ACL-checked |
| `embedding` | vector representation | vector store | delete/reindex with source | tenant + embedding class | required | Not anonymous by default |
| `voice_transcript` | transcribed speech | encrypted | retention-limited | tenant + voice class | required | Raw audio storage remains forbidden unless tenant policy explicitly allows it |

## Legacy Planning Terms

Earlier planning terms are aliases or object/lifecycle concepts, not active runtime classes:

| Planning term | Canonical handling |
| --- | --- |
| `temporary` | retention/lifecycle policy over `public` or `internal` |
| `working_data` | lifecycle state over `internal`, `personal`, or `confidential` |
| `personal_data` | `personal` |
| `gobd_record` | `gobd` |
| `security_data` | usually `confidential` plus audit object type |
| `retrieval_trace` | usually `confidential` plus retrieval/audit object type |
| `tool_call` | usually `confidential` plus audit event type |
| `model_config` | `internal` unless tenant policy marks it more sensitive |
| `ai_evaluation` | `internal` release evidence unless it includes protected data |
| `export_package` | `confidential`, `gobd`, `legal_hold`, or `personal` based on contained records |
| `voice_audio` | not stored by default; future storage must add explicit policy before activation |

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
