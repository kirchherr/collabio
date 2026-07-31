# Productivity Pilot Preflight

## Purpose

`productivity_pilot_preflight_gate.v1` prepares a controlled pilot for CRM account onboarding, Tasks and Activities, and Time Tracking. It consumes the persisted, hash-verified `business_backend_release_gate.v1` report and reads only tenant module metadata from PostgreSQL.

The preflight never starts a pilot. A green result means the selected tenants and operational contracts are eligible for a separate human admission and traffic-scope enforcement step.

## Policy

`docs/operations/productivity_pilot_policy.json` defines:

- a maximum of three candidate tenants;
- the three allowed productive slices and seven API operations;
- required and forbidden tenant feature flags;
- five monitoring controls;
- four non-destructive rollback controls;
- mandatory human admission and traffic-scope enforcement;
- forbidden automatic tenant activation and destructive rollback.

Changes to the policy alter its canonical SHA-256 and require review.

## Run

Use the isolated restore profile and select tenants explicitly:

```bash
SUITE_PRODUCTIVITY_PILOT_TENANT_IDS=tenant-demo \
  docker compose --profile restore-drill run --rm productivity-pilot-preflight-gate
```

The dependency chain regenerates PostgreSQL and object-storage restore evidence, persists the backend and business release reports, verifies the live API contract, and then checks the selected tenant module states and feature scope.

A blocked preflight exits with status `2`. Missing tenant state, disabled modules, missing required features, enabled forbidden features, release hash drift, route-scope drift, or incomplete monitoring/rollback contracts all fail closed.

## Non-Executing Boundary

Even when `preflight_ready=true`, the following remain false:

- `human_admission_recorded`
- `traffic_scope_enforced`
- `pilot_start_allowed`
- `tenant_state_changed`
- `business_write_executed`
- `destructive_actions_allowed`
- `external_side_effect_allowed`

Ready preflight reports are persisted as authoritative, tenant-visible metadata for the append-only admission endpoint described in docs/operations/PRODUCTIVITY_PILOT_ADMISSION.md. Admission, traffic-scope enforcement, and time-bounded start authorization remain separate controls. No activation may be inferred from this document or its persisted evidence; managed traffic still requires the complete evidence chain and an open deployment runtime switch.

## Current Runtime Proof

The isolated development proof on 2026-07-30 passed for `tenant-demo`:

- selected tenants ready: `1/1`
- productive slices ready: `3/3`
- monitoring controls: `5`
- rollback controls: `4`
- business release gate: `sha256:8eb3074aeb99220e66a92055dd4c0942eb0b6e0dc9b17ce256e30bfde2abb4f2`
- pilot policy: `sha256:112ca01a2e483743310feebbac652c5cbbc6df061f007b86b4d22849175ff457`
- tenant module state manifest: `sha256:445362da208ff065f556eee498a60542587a2fb2c2caac5fc6f86fb20a9c83ab`
- preflight gate: `sha256:51ce7d873398b80f24144fe0b7dffb847cd1dbb7c40d55331f130c86c798d7ac`

These hashes prove this development run only. Every release, recovery, tenant selection, or policy change requires fresh evidence.