# Productivity Pilot Development Proof 2026-07-31

## Classification

This is a controlled development proof on `dev001` for tenant `tenant-demo`. It used one synthetic designated principal and test-only business records. It is not a production acceptance, a real-user pilot, or evidence of general availability.

## Scope

- Runtime environment: `dev`
- Policy operations: exactly seven
- Productive slices: CRM Account Onboarding, Tasks and Activities, Time Tracking
- Designated-principal count: one; the raw principal ID is intentionally omitted from this report
- Effective window: `2026-07-31T13:10:25.561986Z` to `2026-07-31T13:30:25.561986Z`
- Forbidden pilot features enabled: zero
- Destructive or external actions: zero

## Authoritative Control Chain

| Control | Evidence |
| --- | --- |
| Business backend release gate before start | `sha256:fa3e46cc909e984e11c541eb6866b91c4c350b6cb379a5e102a2f18c6974bd0e` |
| Tenant module-state manifest | `sha256:c62ea1f03fbbbb7622ba83091dd2959aaa31f6519762438dae14ff9f4b3563b8` |
| Ready preflight | `sha256:7ae00a76fdf61e56a9c1032adb05419b724ba0105451dd65f164921688de4f8a` |
| Human admission | `sha256:17f7dc92d86afc776653c4fa584df5c3132509d495765fc39a2f446f4d8320c9` |
| Default-deny traffic scope | `sha256:e42cc7228cea4b9c67e7bfeca110bffa7461f8fcb97638972f5b6ef9d09cee67` |
| Seven-operation route scope | `sha256:5d1e12e6631d0bd9258a4784a5b9dda7f606cd7f96b02ef644a72c0c58ea32b3` |
| Start authorization | `sha256:f7ecf2397a14e8c478ebedde68bc24cf316219f21f6d74a92da1cd87d8b347df` |
| Monitoring manifest | `sha256:0e87aedb1659ed9580639425dfd05bb0c38ec6758c3ec7e341588d62bcb02d1e` |
| Rollback manifest | `sha256:69ead77c4086a65dd8db95bcb14b7ddcf4e0c74227b3b9f8ceb06283b655323f` |
| Designated-user runtime window | `sha256:dae4ce17293e45ca4e8b3b2ee4022a9a4c4be249262d46eaad9d9d0e9211993d` |

Admission, traffic-scope, security authorization, and runtime activation were performed by four distinct control actors. Before the window, an in-scope request returned `423 productivity_pilot_start_authorization_required`. A principal outside the designated allowlist returned `403 principal_not_designated_for_productivity_pilot`.

## Operation Outcome

All seven policy operations completed once. The append-only runtime ledger contains seven distinct observation hashes and one tenant-bound principal hash.

| Operation | Outcome |
| --- | --- |
| `POST /v1/crm/account-onboardings` | Atomic commit; receipt `sha256:ac191736bb9e1370db3d75700fa07523740a9f36a9252f3c6c0fc07abaea7892` |
| `POST /v1/tasks/items` | Atomic commit; receipt `sha256:f9b40a94d1ae55c3413d1e64d6250ff12724b22ce072bfbb2777e084b2af741b` |
| `POST /v1/time-tracking/entries` | Atomic commit; receipt `sha256:9c02d8237888a12326e12a9af658b3633a01a0440b29049f59abbd956ebc2bc4` |
| `GET /v1/tasks/items` | One explicitly ACL-readable task returned |
| `GET /v1/tasks/activities` | One explicitly ACL-readable activity returned |
| `GET /v1/time-tracking/entries` | One explicitly ACL-readable entry returned |
| `GET /v1/time-tracking/approvals` | One explicitly ACL-readable approval returned |

## Closure And Recovery

The deployment switch was returned to `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. At `2026-07-31T13:13:32.9228283Z`, the previously designated principal received `423 productivity_pilot_runtime_disabled` on an in-scope route.

The post-window recovery chain produced:

- backup SHA-256 `sha256:6852be0dabed8de26734d29b71dc7914a1b70268c4b7c77a29aabc98f2dbabcf`;
- PostgreSQL restore-drill report `sha256:59854f3449532271ff1d41087b590e802951327b864a3a3e2cc8973708484c83`;
- backend-foundation gate `sha256:df5a61c6ebb3d653c5e855278928b67d0189fb8a1e0abadfebf29177c47aa53b`;
- business-backend release gate `sha256:e5111e6b9834cf7bf1787901007979fb38f25d6cdc9ae3ed3d155569fd867b5b`.

The isolated restore contained one runtime window, all seven unique observations, one principal hash, four CRM records, two Task records, and two Time Tracking records. Both post-window gates reported no blocking reasons.

## Next Boundary

The tenant-scoped `productivity_pilot_closure_report.v1` was persisted after the switch closed. It binds:

- closure evidence `sha256:902a47ed16ab0e8a1a8de9e9a501b873da25b9a32caae38a4a021005a740d4b3`;
- observation manifest `sha256:aa8faf8f1572dd43ac6470a047ce9c92ec64a397404e63ddeb4f2b6113db03c8` with seven exact route observations and one principal hash;
- domain-receipt manifest `sha256:19653ce62f80ac0e16e4ca5155f62a60ac575bfb8c27a0d3e3057fcee432771a` with the three authoritative write receipts;
- the previously refreshed recovery evidence and closed-switch state without content or record mutation.

A second isolated restore after closure verified 65 migrations, 73 tables, exact row counts, and the identical closure hash in the restore target. PostgreSQL restore report `sha256:6ed338bbca4ef387975d6b9f3622040bb91a6c36d03ee1601101db7d73ae78a7`, backend foundation gate `sha256:a13ac0d300562853cf8b9b4f23bedc1102f039ccbfca601a941ffb399293ff47`, and business backend release gate `sha256:9745878212d8d443a6e8d5b51bac32c4b2241507b79366fe55d65e490fe38d2e` were green. The final verified backup hash was `sha256:be1f948bba8115ff7d8e8e1d466da796d3293b9d708f5a49790738ce623c732a`.

The next boundary is a separately approved real-user pilot. Real users must be explicitly nominated and must receive a new admission, current control-evidence set, start authorization, and runtime window. No development-pilot authorization is reusable.
