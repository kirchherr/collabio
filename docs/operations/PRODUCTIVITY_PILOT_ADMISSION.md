# Productivity Pilot Admission

## Purpose

productivity_pilot_admission_record.v1 records an explicit Tenant-Admin decision for one tenant and one authoritative productivity_pilot_preflight_gate.v1. It is a pre-start control only. It does not activate modules, change feature state, enforce traffic, start the pilot, or execute business writes.

## Authoritative Binding

The preflight gate persists ready metadata in collabio.productivity_pilot_preflight_reports. RLS exposes a report only to tenants listed in its candidate set. POST /v1/platform/productivity-pilot/admissions resolves that server-side record and rejects caller-provided policy, business-release, or tenant-module hashes that do not match it.

Every admission binds:

- tenant and admission ID;
- preflight, policy, business-release, and tenant-module-state hashes;
- idempotency and command hashes;
- change, confirmation, monitoring-owner, rollback-owner, and audit references;
- actor and timestamp;
- the hash of the exact confirmation statement.

The confirmation text itself is never persisted in the admission record and is never written to the normal audit log.

## Storage And Rights

Migration 0061_productivity_pilot_admission.sql creates:

- collabio.productivity_pilot_preflight_reports;
- collabio.productivity_pilot_admission_records.

Both tables use forced RLS and reject updates and deletes through policies and database triggers. collabio_authz_admin may read tenant-visible preflight evidence and may select/insert tenant-scoped admission records. collabio_app receives no table grant.

## API

The caller must have tenant-admin or security-admin and submit the exact confirmation statement exported as PRODUCTIVITY_PILOT_ADMISSION_CONFIRMATION_STATEMENT.

Successful creation returns HTTP 201. Repeating the same tenant-scoped idempotency reference and command returns the existing evidence with idempotent_replay=true. A changed command, reused preflight, missing tenant evidence, or hash mismatch fails closed.

The response always keeps these values false:

- pilot_start_allowed
- traffic_scope_enforced
- tenant_state_changed
- module_activation_executed
- feature_state_changed
- business_write_executed
- destructive_action_executed
- external_side_effect_executed
- content_included

## Recovery Contract

PostgreSQL backup and restore evidence must preserve both tables, row counts, forced RLS, append-only policies and triggers, and the exact collabio_authz_admin grants. backend_foundation_completion_gate.v1 blocks when productivity_pilot_admission_controls_verified=false.

The next independent gate is tenant- and route-specific traffic-scope enforcement. Pilot start authorization remains separate after that gate.

## Current Runtime Proof

The isolated development proof on 2026-07-30 passed for tenant-demo:

- migration count: 61;
- restored PostgreSQL table count: 68;
- backend foundation gate: sha256:de8b549e99fed5b0a0ad21434ce2e9055cc1f8064bdaa299bba1303e4b1c6eab;
- productivity pilot admission restore controls: verified;
- business release gate: sha256:8eb3074aeb99220e66a92055dd4c0942eb0b6e0dc9b17ce256e30bfde2abb4f2;
- authoritative preflight gate: sha256:51ce7d873398b80f24144fe0b7dffb847cd1dbb7c40d55331f130c86c798d7ac;
- admission evidence: sha256:c0b3f55814dc58d582ba40282d3649100e936e9932d079ee21cac46e5084b839;
- idempotent replay: verified against the same evidence hash;
- module states before and after: unchanged;
- CRM accounts before and after: 3;
- Tasks before and after: 1;
- Time entries before and after: 1;
- admission rows before and after: 0 to 1;
- pilot start allowed: false;
- traffic scope enforced: false.

These hashes prove this development run only. Every changed policy, release, tenant module state, recovery, or admission requires fresh evidence.