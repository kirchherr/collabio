# Business Backend Release Gate

## Purpose

`business_backend_release_gate.v1` is the operational release boundary for the first productive backend package. It binds the existing backend foundation proof to the live API contract and the PostgreSQL module catalog without reading or emitting business content.

The package currently contains:

- CRM atomic account onboarding (`0057`)
- Tasks and Activities creation, serialized lifecycle transitions, reassignment, and due-date amendments (`0050`, `0059`, `0077`, `0079`, `0081`)
- Time Tracking creation, submission, maker-checker decisions, correction, and bound resubmission (`0060`, `0078`, `0080`)

## Run

Use the isolated restore profile:

```bash
docker compose --profile restore-drill run --rm business-backend-release-gate
```

Compose first rebuilds `backend_foundation_completion_gate.v1` and writes its canonical hash-verified report to the backup evidence volume. The release gate verifies the package and persists its own canonical report as `/backups/business-backend-release-gate.json` for downstream gates. It verifies:

- the backend foundation report hash and green state;
- live API health and every required operation in `/openapi.json`;
- installed module catalog entries and required migration versions;
- matching migrations in the immutable code catalog;
- PostgreSQL backend configuration for all three write services;
- restore-verified write controls for CRM, Tasks and Time Tracking.

## Fail-Closed Boundary

Any missing route, module entry, migration, PostgreSQL backend, restore control, API health signal, or valid foundation hash blocks release. The command exits with status `2` when blocked.

The evidence is metadata-only. It does not activate a tenant, create a business row, execute a write flow, or include source content. Tenant selection, production traffic, monitoring, rollback authorization, HA promotion, PITR and cross-site failover remain separate pilot and deployment decisions.

The release route set may be broader than an existing pilot policy. Pilot preflight therefore proves
that every policy-allowed route is present in the released API, while traffic enforcement continues
to default-deny every released route that the policy does not explicitly list.

## Current Runtime Proof

The isolated development proof on 2026-09-17 passed all `3/3` slices with 81 migrations and 89
tables restored to independent PostgreSQL/Object Storage targets:

- backup: `sha256:060a533512494089917ad8adb0eb52926c906c9c7ac09ac65126ee4507c45857`
- PostgreSQL restore drill: `sha256:ae43607cf60f1e775873cf928758c9a74dd41a0e9a572bb7925f9b95550317cb`
- backend foundation gate: `sha256:9df727336638f1ed9ce5cfb784f3147c7745b1cc2db3e20c8cb938a526bda8f5`
- business backend release gate: `sha256:14a680363d1d2c8d6be29c8796f3bbb63577e8a7eaaf2deb68845ea0e8ea1300`
- module catalog manifest: `sha256:1acb727cddf3d42a7055bf3f16783eea05e502e7b70178370da418394dff03e8`

These hashes prove that run only; every release or recovery must generate fresh evidence.

The next non-executing boundary is docs/operations/PRODUCTIVITY_PILOT_PREFLIGHT.md.
