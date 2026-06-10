# Vector Index Model

Every chunk must carry metadata equivalent to:

```json
{
  "tenant_id": "tenant-id",
  "source_object_id": "object-id",
  "source_object_type": "document|mail|attachment|comment|wiki|procedure_doc",
  "source_version_id": "version-id",
  "chunk_id": "chunk-id",
  "classification": "internal",
  "retention_policy_id": "retention-policy-id",
  "legal_hold_state": "none|active",
  "acl_hash": "sha256:...",
  "acl_version": 1,
  "created_at_utc": "2026-06-10T00:00:00Z",
  "embedding_model_id": "embedding-model-id",
  "embedding_model_version": "1",
  "content_hash": "sha256:..."
}
```

Embeddings are classified data. They are not anonymous by default and must follow tenant isolation, retention, legal hold, deletion, and audit policies.

