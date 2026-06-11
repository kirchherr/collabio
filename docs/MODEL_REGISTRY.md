# Model Registry

The MVP model registry is implemented in code as an in-memory registry. Production should replace it with a versioned administrative store.

## Required fields

- model_id
- provider
- deployment
- license
- checksum
- allowed_data_classes
- max_context_tokens
- supports_tools
- supports_json_mode
- supports_embeddings
- approved_for
- blocked_for

## MVP model

```json
{
  "model_id": "mock-summarizer",
  "provider": "mock",
  "deployment": "local",
  "license": "internal-test-only",
  "checksum": "sha256:mock",
  "allowed_data_classes": ["internal", "personal"],
  "max_context_tokens": 4096,
  "supports_json_mode": true,
  "approved_for": ["summarization", "drafting", "rag"],
  "blocked_for": []
}
```

The code also includes provider adapters for:

- `mock`: deterministic local test provider
- `ollama`: local Ollama HTTP API
- `vllm`: OpenAI-compatible HTTP API, suitable for vLLM

Only models explicitly allowed by tenant policy can be used.

## Embedding model versions

Embedding models used by source indexing have a separate versioned registry surface because vectors are durable classified data.

Required fields:

- embedding_model_id
- embedding_model_version
- provider
- deployment
- dimensions
- distance_metric
- checksum
- approved_for_data_classes
- approved_at_utc
- retired_at_utc

Source indexing must resolve the exact embedding model ID and version before writing vector chunks. The model version must be approved, not retired, approved for the source data classification, and dimension-compatible with the embedding provider output. The pgvector-backed registry reads this state from `collabio.embedding_models`.
