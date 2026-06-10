# AI Governance

## Principles

- AI is a controlled capability, not a superuser.
- Tenant policy decides whether AI is enabled.
- Model access is restricted by tenant, role, purpose, and data class.
- LLM output is untrusted until validated.
- AI prepares actions by default; it does not execute destructive or external actions without explicit approval.

## Required records

- Model registry entry
- Prompt registry entry
- Data class allowance
- Purpose
- Risk level
- Audit requirements
- Human approval requirement
- Evaluation evidence

## MVP gates

- Direct provider calls outside the gateway are forbidden.
- Prompt and output bodies are not written to normal logs.
- Every inference request writes an audit event containing hashes, model ID, prompt ID, sources, and purpose.
- Protected data classes must fail closed.
- Tool use is deny-by-default and must be registered in the tool permission registry.
