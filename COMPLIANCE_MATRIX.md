# Compliance Matrix

Status: initial
Date: 2026-06-10

This matrix maps external requirements and internal controls to product capabilities. It is intentionally incomplete and must become machine-readable during Phase 0.

## Control Families

| Control ID | Area | Requirement | Product control | Evidence target | Status |
| --- | --- | --- | --- | --- | --- |
| CM-001 | Tenancy | Tenant data must be isolated | Tenant context, authz, DB RLS, tenant-scoped storage/indexes | Tenant isolation tests | planned |
| CM-002 | Authorization | UI checks are insufficient | Server-side policy engine | Authz test suite | planned |
| CM-003 | Data classification | Persistent data must be classified | Data classification model | Classification schema/tests | planned |
| CM-004 | Retention | Records need retention policy | Retention policy engine | Retention simulation | planned |
| CM-005 | Legal Hold | Holds override lifecycle deletion | Legal hold service and storage lock | Hold-aware deletion tests | planned |
| CM-006 | WORM | Business/evidence records require immutability | S3-compatible object lock | Object lock integration tests | planned |
| CM-007 | Audit | Security and lifecycle actions need evidence | Append-only audit with hash chain | Audit verifier | planned |
| CM-008 | KMS | Keys must be tenant- and class-aware | KMS adapter and envelope encryption | Key rotation tests | planned |
| CM-009 | Search security | Search must not leak unauthorized data | Candidate search, ACL check, redaction | Search leakage tests | planned |
| CM-010 | Vector security | Embeddings are classified data | Vector metadata and ACL-aware retrieval | RAG leakage tests | partial |
| CM-011 | AI governance | AI must follow tenant policy | AI Control Plane | AI policy tests | partial |
| CM-012 | Human oversight | Critical actions require approval | Approval engine | Approval workflow tests | planned |
| CM-013 | Voice privacy | Voice capture must be explicit | Push-to-talk guard | Voice tests | partial |
| CM-014 | Supply chain | Artifacts need provenance | SBOM, signing, pinned deps | Release evidence | planned |
| CM-015 | Parser safety | Untrusted files need isolation | Networkless parser workers | Sandbox tests | planned |

## Standards Mapping

| Standard | Relevant themes | Internal controls |
| --- | --- | --- |
| DSGVO | Privacy by design, security, deletion, restriction, TOMs | CM-001, CM-003, CM-004, CM-008, CM-009, CM-010 |
| GoBD | Immutability, traceability, data access, procedural documentation | CM-004, CM-005, CM-006, CM-007 |
| EU AI Act | Risk classification, transparency, logging, human oversight, robustness | CM-011, CM-012, CM-010, CM-013 |
| NIST CSF 2.0 | Govern, Identify, Protect, Detect, Respond, Recover | all controls |
| NIST SSDF | Secure development and vulnerability reduction | CM-014 plus SDLC controls |
| NIST AI RMF | Trustworthy AI risk management | CM-011, CM-012 |
| OWASP ASVS 5.0 | Web app security requirements | CM-001, CM-002, CM-008, CM-014 |
| OWASP LLM/GenAI | Prompt injection, data leakage, tool misuse, vector weaknesses | CM-010, CM-011, CM-012 |
| SLSA | Build provenance and tamper resistance | CM-014 |
| CycloneDX | SBOM/CBOM/AI/ML-BOM evidence | CM-014 |
| WCAG 2.2 AA | Accessibility | Design-system controls, to be added |

## Release Rule

No feature that creates, modifies, deletes, searches, exports, indexes, embeds, summarizes, sends, or stores tenant data is complete until this matrix has a row or linked control covering its compliance impact.

