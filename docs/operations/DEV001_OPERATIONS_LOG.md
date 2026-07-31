# dev001 Collabio Operations Log

This append-only operator log records Collabio Docker lifecycle, migration, restore, and port-affecting work on `dev001`. Collabio uses `/home/extern/collabio` and the explicit Compose project name `collabio`. Tricert resources are outside this log and must not be touched.

| UTC date | Operation | Scope and result | Coordination |
| --- | --- | --- | --- |
| 2026-07-31 | Backfill: deployed controlled-pilot proof baseline | Collabio checkout reached commit `238c5c2`; API and PostgreSQL services were used for the technical productivity-pilot proof. | Backfilled after `/home/extern/AGENTS.md` coordination rule was discovered; original lock status was not recorded. |
| 2026-07-31 | Backfill: runtime switch opened and closed | A bounded designated synthetic-principal window executed the seven authorized operations. The switch was returned to `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`; an in-scope request then failed closed with HTTP 423. | Backfilled from `PRODUCTIVITY_PILOT_DEVELOPMENT_PROOF_20260731.md`; original lock status was not recorded. |
| 2026-07-31 | Backfill: backup and isolated restore drill | Backup `sha256:6852be0dabed8de26734d29b71dc7914a1b70268c4b7c77a29aabc98f2dbabcf` restored one runtime window, seven observations, and three domain receipts; backend and business gates passed. | Backfilled from persisted proof; original lock status was not recorded. |

## Required Entry Format

Every future lifecycle operation records the UTC timestamp, commit, exact Compose project, affected services, preflight inspection result, acquired lock order, command purpose, outcome, and evidence hashes where applicable. Heavy builds or tests acquire `build.lock`; Compose lifecycle, restore, or port work acquires `docker.lock`; when both are required, `build.lock` is acquired first.
