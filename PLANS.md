# Plans

This file tracks the active implementation sequence. The canonical roadmap is `docs/ROADMAP.md`.

## Current Journey

Theme: Build proof capability before product surface.

Current sprint:

1. [x] Research baseline, stack candidates, and ADR backlog.
2. [x] Product charter, security policy, threat model, compliance matrix.
3. [x] Data classification, retention policies, legal hold model.
4. [x] ADR template and initial ADRs.
5. [x] Phase 0 engineering tooling.
6. [x] Request-scoped tenant context.
7. [ ] Append-only audit model.

## Next Engineering Step

After the request-scoped tenant context is in place:

- Add compliance tests that assert persistent models declare classification and retention fields.
- Introduce append-only audit chain storage.
- Replace in-memory tenant policies with persistent tenant policy storage.
