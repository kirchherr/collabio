# Business Backend Release Gate

## Purpose

`business_backend_release_gate.v1` is the operational release boundary for the first productive backend package. It binds the existing backend foundation proof to the live API contract and the PostgreSQL module catalog without reading or emitting business content.

The package currently contains:

- CRM atomic account onboarding (`0057`)
- Tasks and Activities (`0050`, `0059`)
- Time Tracking (`0060`)

## Run

Use the isolated restore profile:

```bash
docker compose --profile restore-drill run --rm business-backend-release-gate
```

Compose first rebuilds `backend_foundation_completion_gate.v1` and writes its canonical hash-verified report to the backup evidence volume. The release gate then verifies:

- the backend foundation report hash and green state;
- live API health and every required operation in `/openapi.json`;
- installed module catalog entries and required migration versions;
- matching migrations in the immutable code catalog;
- PostgreSQL backend configuration for all three write services;
- restore-verified write controls for CRM, Tasks and Time Tracking.

## Fail-Closed Boundary

Any missing route, module entry, migration, PostgreSQL backend, restore control, API health signal, or valid foundation hash blocks release. The command exits with status `2` when blocked.

The evidence is metadata-only. It does not activate a tenant, create a business row, execute a write flow, or include source content. Tenant selection, production traffic, monitoring, rollback authorization, HA promotion, PITR and cross-site failover remain separate pilot and deployment decisions.

## Current Runtime Proof

The isolated development proof on 2026-07-30 passed all `3/3` slices:

- backend foundation gate: `sha256:bc7221c1fe39f78d02d9c4e83d43723d8bcbb35bca7c73a714b002e067f809d4`
- business backend release gate: `sha256:b4da6b5abcf6b9f129f5ba5829416fa6d13291e2be54d820ce5251bc21f4b462`
- module catalog manifest: `sha256:d5d815a69b37a430d92a8d2a8d9614b3f1933bb2bfd9399663fad6384b621b9f`

These hashes prove that run only; every release or recovery must generate fresh evidence.