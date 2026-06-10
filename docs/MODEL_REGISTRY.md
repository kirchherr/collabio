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
