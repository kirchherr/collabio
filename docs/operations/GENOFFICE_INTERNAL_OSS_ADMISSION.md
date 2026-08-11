# GenOffice Internal OSS Admission

## Purpose

This gate replaces the unavailable external legal review for the isolated development candidate. It records an internal
Open Source compliance and risk decision. It does not claim legal advice or production clearance.

The immutable input remains the ADR-0065 dossier
`sha256:eb523d13b0cb10fea752c4e0d549a9c06f2736e4f3f38721bb7b0ba948614c5a`.

## Usage Profiles

| Profile | Internal decision effect |
| --- | --- |
| `development_evaluation` | May permit exact build-context materialization and a reproducible isolated worker build. |
| `hosted_service` | Blocked. Requires a separate product and deployment decision. |
| `on_prem_distribution` | Blocked. Requires a separate distribution review. |
| `production` | Blocked. Requires image, security, fidelity, recovery and production admission. |

Tenant content, source import into the Collabio product tree, engine execution and service activation remain blocked in
all outputs of this gate.

## Deterministic Notice

`genoffice-third-party-notice-builder` runs without a network and reads archives without filesystem extraction. It
produces:

- `GENOFFICE_THIRD_PARTY_NOTICES.txt`;
- `genoffice-third-party-notice-report.json`.

The artifact contains the pinned Apache-2.0 LICENSE and NOTICE, the vendored EMF converter license and the required legal
texts for all 21 runtime dependencies. It records MIT as the selected `jszip` distribution option and both MIT and Zlib
for `pako`. Enterprise terms are evidence of exclusion and are not copied into the distributable notice.

## Internal Decision

The generated `genoffice_internal_oss_decision_envelope.v1` schema requires:

- the exact dossier, notice-report and notice-artifact hashes;
- the exact allowed and prohibited source scopes;
- Collabio-only branding and explicit Apache-2.0, NOTICE and patent-term acknowledgements;
- all 21 dependency resolutions;
- the risk-acceptance and change-control references;
- complete reevaluation triggers;
- detached Ed25519 approvals by two different people in the roles `product_owner` and
  `security_compliance_owner`.

The separate signer policy binds signer IDs, roles, key IDs and public keys. The verifier accesses cryptography only
through the Suite KMS adapter. The repository contains schemas, never private keys and never invented human approvals.

## Runbook

After the standard `dev001` preflight and with `build.lock` before `docker.lock`:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-third-party-notice-builder

docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-schema
```

After two internal signers have created `genoffice-internal-oss-decision.json` and an operator has installed the public
`genoffice-internal-oss-signer-policy.json`:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-internal-oss-admission
```

The admission exits `2` for missing, malformed, stale, same-person, unauthorized or invalidly signed evidence. A green
report opens only the development worker-build gate.

## Verified Evidence Snapshot

The reproducible 2026-08-11 run on `dev001` produced:

- 23-component, 27-file `GENOFFICE_THIRD_PARTY_NOTICES.txt`:
  `sha256:e6dada57493fc5161dc4c5364f36feab11298fc887f5253eb1f03b3920239162`;
- notice report: `sha256:878e93a174a9deeae9c137a0229210c45dd636c9763cda9d430d42e6ad07fdc7`;
- decision-envelope schema: `sha256:86c20d932f1666794bd2e67121c917da49ff4cfed40e70e730040008e5a7c698`;
- signer-policy schema: `sha256:c5eb255d880075ed408bfe48d73e09156c58f31ee146ebc37e47c499ff700ed3`.

A second independent builder execution produced the identical notice bytes. No decision envelope, signer policy or
admission report is committed because no human identity, public key or approval has been supplied. The development
worker build therefore remains correctly blocked.

## Alternatives

Collabora remains the preferred later WOPI candidate for full collaboration, but its official terms distinguish source
and executable forms. ONLYOFFICE Community Edition uses AGPLv3 with additional terms. Neither removes the need for a
deliberate compliance decision. ECMA-376 plus the MIT-licensed Open XML SDK remains the independent long-term format
manipulation path; the SDK is a low-level document API rather than a ready browser office suite.
