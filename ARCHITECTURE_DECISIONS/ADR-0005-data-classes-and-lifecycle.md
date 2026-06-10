# ADR-0005: Data Classes And Lifecycle States

Status: accepted
Date: 2026-06-10

## Context

Office, mail, AI, RAG, voice, search, and e-discovery workflows create many forms of data with different legal and technical treatment. Without a shared classification model, deletion, retention, KMS, audit, and export behavior becomes inconsistent.

## Decision

The data classes in `DATA_CLASSIFICATION.md` are the initial canonical taxonomy.

Core lifecycle order:

```text
Working Data
  -> Draft / Collaborative State
    -> Saved Version
      -> Business Record
        -> WORM Evidence Record
```

Policy conflict order:

```text
1. Tenant isolation
2. Legal Hold
3. Regulatory retention
4. Contractual retention
5. Data subject rights
6. Business policy
7. Default deny
```

Derived objects inherit the highest sensitivity of their sources unless an explicit policy permits downgrading.

## Consequences

- Persistent models must declare classification and retention policy.
- RAG chunks and embeddings are classified data.
- AI outputs remain draft-like until accepted by a user.
- Exports are separate classified objects with their own chain of custody.

## Alternatives Considered

- Free-form labels: rejected because policy and tests require stable identifiers.
- Treat embeddings as anonymous: rejected because embeddings may leak semantic information.
- Treat all document states as records: rejected because collaboration and GoBD semantics would conflict.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-003, CM-004, CM-005, CM-010, CM-011, CM-013
- DSGVO: classification, deletion, restriction
- GoBD: records and retention
- EU AI Act: AI data governance and transparency

## Verification

- Schema tests for persistent objects.
- Retention policy tests by class.
- RAG tests for inherited source classifications.
- AI output tests proving draft state until user acceptance.

