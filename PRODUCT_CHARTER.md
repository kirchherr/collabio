# Product Charter

## Mission

Build a self-hosted, B2B-only, enterprise-grade collaborative Office and Mail Suite with compliance, auditability, privacy, retention, WORM storage, Legal Hold, local AI, RAG, voice interaction, and secure operations by design.

The product promise is not "AI-powered office software." The promise is:

> A self-hosted, compliance-capable enterprise work suite where documents, mail, knowledge retrieval, voice, and local AI operate inside tenant isolation, policy enforcement, auditability, and human oversight.

## Non-Negotiable Product Principles

- Compliance is part of the core architecture, not a separate module.
- Tenant isolation is mandatory across API, database, storage, search, vector indexes, audit logs, exports, and AI context.
- Every persistent object must carry classification, retention, legal hold, KMS, and audit metadata.
- AI may prepare work, but it must not autonomously execute destructive, external, or compliance-relevant actions.
- RAG retrieves authorized context at runtime; it does not train models on tenant data.
- Voice is explicit and privacy-first; always-on capture is out of scope by default.
- Drafts, collaborative working data, business records, and evidence records are separate states.
- Search and vector databases are candidate engines, not authorization sources.
- Business and evidence records must be reproducible, exportable, and verifiable.

## Target Users

- Regulated businesses that need self-hosted office, mail, and knowledge workflows.
- Legal, finance, tax, compliance, and audit-heavy teams.
- Public-sector or critical-infrastructure-adjacent organizations that cannot rely on uncontrolled cloud AI.
- Enterprises that need local AI and RAG without breaking tenant boundaries or audit obligations.

## MVP Scope

- Tenant-aware backend foundation.
- IAM/OIDC integration path.
- Policy and data classification model.
- Append-only audit model.
- KMS and WORM storage architecture.
- Retention and legal hold model.
- AI Control Plane and Local LLM Gateway.
- RAG skeleton with source citations and ACL checks.
- Voice transcript guardrails.
- Basic document and mail workflows only after the above foundations exist.

## Explicit Non-Goals For MVP

- Full Microsoft Office fidelity.
- A complete standalone mail server.
- Autonomous AI sending, deletion, export, legal hold, or key destruction.
- Cloud AI as a default path.
- Training models on tenant data.
- Always-on voice capture.
- Emotion detection or voice biometrics.
- Certification claim before external audit evidence exists.

## Product Risk Posture

The product prefers a slower workflow over an unsafe workflow when an action affects:

- External communication.
- Records or evidence.
- Legal hold.
- Retention.
- Deletion or cryptographic shredding.
- Export.
- KMS keys.
- High-risk AI decisions.

The suite should be fast for safe drafting and search, but deliberately resistant to accidental compliance damage.

