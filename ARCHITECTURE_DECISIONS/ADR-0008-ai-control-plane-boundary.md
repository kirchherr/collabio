# ADR-0008: AI Control Plane Boundary

Status: accepted
Date: 2026-06-10

## Context

AI features can accidentally become privileged cross-system actors. The suite must ensure AI cannot see, do, export, summarize, or attach more than the current user and tenant policy permit.

## Decision

No feature may call an LLM provider directly. All model calls must pass through:

```text
AI Control Plane
  -> Tenant Policy
    -> Model Registry
      -> Prompt Registry
        -> Tool Permission Registry
          -> Local LLM Gateway
            -> Audit
```

LLM output is untrusted until validated. Tool calls require registered permissions. Destructive, external, or compliance-relevant tool calls require human approval.

## Consequences

- Feature teams build AI actions, not provider calls.
- Model, prompt, tool, data class, purpose, and audit metadata are mandatory.
- Cloud AI providers are disabled unless tenant policy explicitly permits them.

## Alternatives Considered

- Direct SDK use in features: rejected due to audit, policy, and data leakage risk.
- Single global AI switch: rejected because controls must vary by tenant, role, model, purpose, and data class.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-010, CM-011, CM-012
- EU AI Act: transparency, logging, human oversight
- OWASP LLM/GenAI: excessive agency, sensitive disclosure, prompt injection

## Verification

- Static or test-level checks for provider bypass.
- Policy tests for disabled AI, blocked models, blocked data classes, and blocked tools.
- Audit tests for inference metadata.
- Approval tests for high-risk actions.

