# ADR-0068: Expiring GenOffice Solo-Founder Development Exception

Status: accepted
Date: 2026-08-11

## Context

ADR-0066 defines the preferred two-person internal OSS admission. Collabio currently has one accountable founder, so
the required separation cannot be performed honestly. Inventing a second identity or allowing one person to occupy both
roles would destroy the control while claiming that it exists. Permanently blocking all isolated development would also
prevent the evidence needed to evaluate the candidate safely.

NIST SP 800-53 AC-5 treats separation of duties as a risk control, and the NIST definition of compensating controls
allows alternative controls that provide comparable protection. BSI implementation guidance likewise recognizes that
smaller institutions may need documented, regularly reviewed mitigation controls when personnel separation is not
possible. This exception is an internal technical risk decision, not legal advice or production approval.

## Decision

- Preserve the ADR-0066 two-person ceremony and its schemas unchanged.
- Add a separate `genoffice_solo_founder_exception_report.v1` authorization mode. It never reports two-person control
  as satisfied.
- Require one named `founder_risk_owner`, one dedicated raw 32-byte Ed25519 public key and a detached signature created
  outside Collabio. Private-key ingestion and signature creation remain prohibited inside Suite services.
- Bind the signature to the pinned legal dossier, deterministic third-party NOTICE, exact source scope, blocked usage
  profiles, risk-acceptance reference, change-control reference and the full exception boundary.
- Limit each exception to at most 30 days. The verifier and every build-context materialization reject a future or
  expired exception.
- Permit only deterministic, no-network build-context materialization and a later isolated reproducible worker build.
- Keep source import, engine execution, tenant content, Hosted Service, On-Prem distribution and production use false.
- Require real `product_owner` and `security_compliance_owner` reauthorization before any runtime, pilot, distribution
  or production boundary is considered.
- Persist policy, request, canonical message and final report as private mode `0600` write-once evidence. Missing public
  key or signature-response binds fail before container creation.
- Version the build-context report and embedded manifest to v2. They record exactly one authorization mode and reject
  ambiguous or mixed evidence.

## Consequences

- A one-person project can continue evidence-producing development without pretending to have organizational
  separation that does not exist.
- The exception is visibly weaker than two-person approval, short-lived and technically incapable of opening runtime
  or tenant-data processing.
- Renewal requires a new signed request and reevaluation of the pinned evidence. Existing artifacts are not overwritten.
- Adding a second accountable person later does not require weakening or migrating the preferred ADR-0066 path.
- Certification or customer requirements may reject this compensating control; such a requirement closes the exception
  rather than being silently reinterpreted.

## Recovery Contract

Back up the public signer policy, request, exact signature-message bytes, structured signature response and final
exception report together with all referenced public evidence. Restore verification recalculates every hash, rechecks
the validity window and confirms all runtime flags remain false. Never back up the signing private key with Collabio.

## References

- https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
- https://csrc.nist.gov/glossary/term/compensating_controls
- https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/Umsetzungshinweise/Umsetzungshinweise_2022/Umsetzungshinweis_zum_Baustein_APP_4_2_SAP_ERP_System.pdf
