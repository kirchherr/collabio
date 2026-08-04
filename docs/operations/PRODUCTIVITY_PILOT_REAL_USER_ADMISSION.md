# Real-User Productivity Pilot Admission

## Purpose

This boundary prepares a real-user productivity pilot without activating modules, authorizing
traffic, opening the runtime switch, or executing a business write. It separates tenant-owned
participant nomination from independent security admission and keeps the development pilot
evidence chain immutable.

The data contract follows GDPR purpose limitation, data minimization, storage limitation,
security, and accountability. A DPIA is conditional on the documented risk assessment outcome;
it is not treated as a universal checkbox. See [GDPR Article 5 and Article 35](https://eur-lex.europa.eu/eli/reg/2016/679/oj).
Access decisions continue to use authoritative tenant identity and role state in line with
least-privilege, per-request authorization principles from
[NIST SP 800-207](https://doi.org/10.6028/NIST.SP.800-207).

This is a technical control contract, not legal advice. The controller remains responsible for
selecting and documenting the applicable lawful basis and employee-participation requirements.

## API Boundary

- `POST /v1/platform/productivity-pilot/real-user-nominations` requires `tenant-admin`.
- `GET /v1/platform/productivity-pilot/real-user-nominations/current` requires tenant or security administration.
- `POST /v1/platform/productivity-pilot/real-user-admissions` requires `security-admin`.
- `GET /v1/platform/productivity-pilot/real-user-admissions/current` requires tenant or security administration.

Every write requires the exact confirmation statement exported by the service model. Replays are
idempotent only when the complete command hash matches.

## Nomination Contract

The tenant administrator supplies:

- the current append-only development-pilot closure hash;
- an explicit purpose code and controlled purpose reference;
- the controller-selected lawful-basis reference;
- a privacy-risk assessment and retention policy;
- one to 25 active tenant principals with required roles;
- per-participant transparency/notice and training evidence references;
- a time-bounded schedule of at most 30 days;
- conditional DPIA and works-council evidence where the preceding assessment requires it.

Principal IDs are used only for authoritative lookup against active tenant membership and role
assignments. They are not persisted in the nomination record or its audit metadata. The append-only
record stores tenant-bound principal hashes, role manifests, notice/training evidence hashes, and a
participant manifest hash. The nominator cannot be a participant.

## Independent Admission

The security administrator must resubmit the nominated principals. The service resolves current
IAM state again and requires the resulting participant manifest to be identical. Admission also
requires:

- a new ready preflight checked after nomination and no more than 24 hours before approval;
- matching policy, business-release, and tenant-module-state hashes;
- post-nomination backup, PostgreSQL restore, and backend-foundation hashes;
- security-review and privacy-approval references;
- an approver distinct from both the tenant nominator and every participant.

The resulting admission remains metadata-only with
`runtime_activation_allowed=false` and `traffic_authorization_allowed=false`. Development admission,
start authorization, runtime window, and synthetic principals are not reused.

## Persistence And Recovery

Migration `0066_productivity_pilot_real_user_admission.sql` creates:

- `collabio.productivity_pilot_real_user_nominations`;
- `collabio.productivity_pilot_real_user_admissions`.

Both tables enforce tenant RLS, `SELECT`/`INSERT` only for `collabio_authz_admin`, no update or hard
delete policies, and mutation-rejecting triggers. JSON checks reject raw principal IDs, confirmation
statements, passwords, raw payloads, and request/response bodies. The PostgreSQL restore drill treats
both tables as mandatory pilot control state and verifies exact row recovery.

## Operational Sequence

1. Keep `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`.
2. Identify the tenant-owned purpose, lawful basis, retention, privacy risk, and workforce process.
3. Nominate active principals through the API; do not place principal IDs in tickets or normal logs.
4. Refresh preflight, backup, isolated restore, foundation, and business-release evidence.
5. Record independent security admission.
6. Create a completely new traffic-scope and start chain after admission. Development evidence is
   not reused.
7. Use only the hash-only runtime contract in
   `docs/operations/PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW.md`; Runtime v1 is technically blocked.
8. Use and verify the separate hash-only real-user closure in
   `docs/operations/PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT.md`, including backup and isolated
   restore, before the deployment kill-switch is opened for real users.

No current deployment has performed steps 3 through 8 for real users.
