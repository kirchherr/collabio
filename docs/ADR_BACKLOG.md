# ADR Backlog

Stand: 2026-06-10

ADR = Architecture Decision Record. Jede Entscheidung, die spaeter teuer zu aendern ist, bekommt ein ADR.

## Template

```markdown
# ADR-XXXX: Title

Status: proposed | accepted | superseded
Date: YYYY-MM-DD

## Context

What pressure, requirement, risk, or constraint forces a decision?

## Decision

What do we choose?

## Consequences

What becomes easier, harder, safer, riskier?

## Alternatives Considered

Which options did we reject and why?

## Compliance Mapping

Which controls, laws, standards, or roadmap requirements does this support?

## Verification

How do tests, CI, docs, or operations prove this decision is honored?
```

## Phase -1 ADRs

- [x] ADR-0001: Tenancy model and tenant context propagation.
- [x] ADR-0002: WORM storage and object lock strategy.
- [x] ADR-0003: KMS key hierarchy and crypto adapter boundary.
- [x] ADR-0004: Append-only audit event model and hash chain.
- [x] ADR-0005: Data classes and object lifecycle states.
- [ ] ADR-0006: Working data vs. business records vs. evidence records.
- [ ] ADR-0007: Compliance matrix format and release evidence.
- [x] ADR-0008: AI Control Plane boundary.
- [ ] ADR-0009: Voice privacy model.
- [x] ADR-0010: RAG security model and candidate-only vector search.

## Phase 0 ADRs

- [ ] ADR-0011: Monorepo layout and package boundaries.
- [ ] ADR-0012: Python/TypeScript/Rust/Go responsibility split.
- [ ] ADR-0013: CI gates and required checks.
- [ ] ADR-0014: SBOM, provenance and container signing.
- [ ] ADR-0015: Dependency and license policy.
- [ ] ADR-0016: Test taxonomy: unit, integration, e2e, compliance, security, AI, performance.

## Phase 1 ADRs

- [ ] ADR-0017: IAM strategy: Keycloak and OIDC/SAML adapter boundary.
- [ ] ADR-0018: Runtime authorization: internal policy engine vs. OPA/Cerbos/Casbin/Cedar.
- [ ] ADR-0019: PostgreSQL RLS defense-in-depth strategy.
- [ ] ADR-0020: Audit persistence, runtime DB permissions and tamper verification.
- [ ] ADR-0021: Outbox/event bus choice.
- [ ] ADR-0022: Human approval model.
- [ ] ADR-0023: Observability data classification.

## Phase 2 ADRs

- [x] ADR-0024: S3-compatible object storage and MinIO/AWS compatibility target.
- [x] ADR-0025: Retention policy engine.
- [ ] ADR-0026: Legal hold semantics.
- [ ] ADR-0027: Envelope encryption implementation.
- [ ] ADR-0028: Dev KMS and enterprise KMS adapter strategy.
- [ ] ADR-0029: Text extraction and parser sandbox model.
- [ ] ADR-0030: Embedding metadata schema.
- [x] ADR-0031: pgvector vs. Qdrant first vector backend.

## Phase 3 ADRs

- [ ] ADR-0032: Text editor foundation: ProseMirror direct vs. Tiptap.
- [ ] ADR-0033: CRDT strategy: Yjs and persistence model.
- [ ] ADR-0034: Document record commit semantics.
- [ ] ADR-0035: OOXML/ODF import/export scope.
- [ ] ADR-0036: Macro policy.
- [ ] ADR-0037: Spreadsheet engine strategy.
- [ ] ADR-0038: Document AI assistant action model.

## Phase 4 ADRs

- [ ] ADR-0039: Mail gateway/proxy strategy vs. full mail server.
- [ ] ADR-0040: IMAP4rev2/JMAP/API strategy.
- [ ] ADR-0041: MIME and attachment processing sandbox.
- [ ] ADR-0042: Mail security evidence model: SPF/DKIM/DMARC/MTA-STS.
- [ ] ADR-0043: Team inbox and comments domain separation.
- [ ] ADR-0044: Mail AI drafting and send confirmation.

## Phase 5 ADRs

- [ ] ADR-0045: Keyword search backend.
- [ ] ADR-0046: Search authorization gateway.
- [ ] ADR-0047: Hybrid search and reranking.
- [ ] ADR-0048: Source citation schema.
- [ ] ADR-0049: RAG answer confidence and unsupported-answer labeling.
- [ ] ADR-0050: User feedback and no-training-by-default policy.

## Phase 6+ ADRs

- [ ] ADR-0051: DSGVO export/deletion/restriction workflows.
- [ ] ADR-0052: GoBD Verfahrensdokumentation generator.
- [ ] ADR-0053: E-Discovery export package format.
- [ ] ADR-0054: Kubernetes production deployment.
- [ ] ADR-0055: Air-gap model import and verification.
- [ ] ADR-0056: High availability and multi-region strategy.
- [ ] ADR-0057: Enterprise audit evidence pack.

## Immediate ADR Priority

Start with:

1. [x] ADR-0001 Tenancy model.
2. [x] ADR-0005 Data classes.
3. [x] ADR-0004 Audit event model.
4. [x] ADR-0003 KMS key hierarchy.
5. [x] ADR-0002 WORM storage.
6. [x] ADR-0031 pgvector vs. Qdrant.
7. [ ] ADR-0017 IAM strategy.
