# ADR-0066: Internal OSS Admission For The GenOffice Development Candidate

Status: accepted
Date: 2026-08-11

## Context

ADR-0065 created a complete, reproducible legal evidence dossier but assumed access to a qualified external legal
reviewer. That role is not available during the current development phase. Treating an automated scan or an AI response
as legal advice would create false assurance and would make the compliance claim weaker.

The pinned candidate nevertheless has unusually strong objective evidence: exact source and dependency bytes, complete
license texts, NOTICE and trademark evidence, excluded enterprise code, explicit compound-license semantics,
cryptographic npm provenance, SBOM and vulnerability results. The project needs a controlled way to accept the remaining
development risk without silently opening production or distribution.

## Decision

- Keep ADR-0065 and its immutable dossier as the factual evidence layer. Do not rewrite it as an approval.
- Replace the unavailable external legal decision for the development phase with
  `genoffice_internal_oss_decision_envelope.v1`.
- Require two distinct internal people in the roles `product_owner` and `security_compliance_owner`. Each signs the exact
  canonical decision payload with an Ed25519 key authorized by a separately hash-bound signer policy. Signature
  verification stays behind the Suite KMS adapter.
- The internal decision is a documented risk acceptance, not a legal opinion. It must bind the exact dossier, generated
  third-party notice, source and prohibited scopes, trademark policy, all dependency resolutions and reevaluation
  triggers.
- Select MIT for `jszip`; preserve both MIT and Zlib obligations for `pako`; preserve Apache-2.0 LICENSE and NOTICE;
  exclude `ee/**`; and use Collabio branding only.
- Generate `GENOFFICE_THIRD_PARTY_NOTICES.txt` deterministically from the integrity-verified archives. Never install a
  package, execute upstream code or use a network while rendering it.
- An approved internal record may open only build-context materialization and a reproducible worker build for
  `development_evaluation`. Product source import, engine execution, tenant content, hosted service, On-Prem
  distribution and production remain closed.
- Reevaluate on source commit, source scope, dependency or license, NOTICE artifact, trademark use, usage profile or
  signer-policy changes. Any hash drift closes admission automatically.
- Keep legal consultation as an optional escalation path. Custom or unknown licenses, AGPL, trademark use, enterprise
  code, hosted production and binary/On-Prem distribution cannot inherit the development decision.

## Consequences

- Development is no longer blocked on an unavailable external role.
- No person, automation or AI is represented as providing legal advice.
- The exact accountable people, policy, signatures, choices and risk reference remain auditable.
- A successful admission permits building an isolated development candidate, not serving or distributing it.
- The Office adapter remains replaceable. ECMA-376 and independently licensed engines remain viable alternatives.

## References

- https://www.apache.org/licenses/LICENSE-2.0
- https://www.apache.org/legal/apply-license.html
- https://spdx.github.io/spdx-spec/v3.0.1/annexes/spdx-license-expressions/
- https://ecma-international.org/publications-and-standards/standards/ecma-376/
- https://github.com/dotnet/Open-XML-SDK
- https://www.collaboraonline.com/terms/collabora-online-mplv2/
- https://github.com/ONLYOFFICE/DocumentServer/blob/master/LICENSE
