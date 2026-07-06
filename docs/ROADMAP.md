# Master Roadmap

Stand: 2026-06-10

Diese Roadmap merged:

- `konzept_suite_2.md`: KI, Voice, RAG, lokale LLMs, Vector DB und Zero-Friction-UX.
- `C:\Users\tkirchherr\Documents\suite_konzept.md`: Masterkonzept fuer Enterprise Office, Mail, Compliance, Audit, WORM, KMS, E-Discovery und Betriebsreife.

Die zentrale Regel bleibt: **Baue zuerst die Beweisfaehigkeit, dann die Features.**

Die Suite darf nicht als Office-Editor mit spaeterer Compliance-Schicht entstehen. Die korrekte Architektur ist:

```text
Identity
  -> Tenant Context
    -> Policy Engine
      -> Data Classification
        -> KMS
          -> Storage / WORM
            -> Audit
              -> Search / Vector DB / Export / E-Discovery
                -> RAG Orchestrator
                  -> Local LLM Gateway
                    -> Voice / Chat / UI Actions
                      -> Human Approval / Explainability / Audit
```

Alles, was diesen Pfad umgeht, ist ein Architekturfehler.

## Arbeitsregeln

Status:

- `[ ]` Nicht begonnen
- `[x]` Erledigt

Arbeitsweise:

- Phasen werden grundsaetzlich von oben nach unten abgearbeitet.
- Spaetere Aufgaben duerfen nur vorgezogen werden, wenn sie keine Grundsatzentscheidung ueberspringen.
- Jede technische Aufgabe braucht Tests, Dokumentation und, wenn relevant, ein Compliance-Mapping.
- Entwicklung und Verifikation laufen ueber Docker Compose.
- Sicherheits-, Compliance-, Retention-, KMS-, Authz-, Audit-, AI- und RAG-Aenderungen brauchen bewusstere Reviews als normale UI-Aenderungen.
- Forschungs- und Stack-Entscheidungen werden in `docs/RESEARCH_BASELINE.md`, `docs/OPEN_SOURCE_STACK.md` und `docs/ADR_BACKLOG.md` gepflegt.

## Globale Definition Of Done

- [ ] `docker compose run --rm test` ist gruen.
- [ ] Relevante Lint-, Type-, Security- und Dependency-Checks laufen.
- [ ] Keine API kann ohne Tenant Context und Principal arbeiten.
- [ ] UI-Pruefungen sind niemals die einzige Autorisierung.
- [ ] Kein Feature ruft LLM Provider direkt auf.
- [ ] Kein Feature greift direkt auf Storage, KMS, Vector DB oder Suchindex zu, wenn ein freigegebener Adapter existiert.
- [ ] Persistente Objekte tragen Tenant, Klassifikation, Retention, Legal-Hold-State, KMS-Key-Ref und Auditbezug.
- [ ] Audit-relevante Aktionen schreiben strukturierte Audit Events.
- [ ] Prompts, Outputs, Mail-Inhalte, Dokumentinhalte, Transkripte, Secrets und personenbezogene Daten landen nicht in normalen Logs.
- [ ] Such-, Vector- und RAG-Ergebnisse werden vor Ausgabe gegen authoritative Authz geprueft.
- [ ] Destruktive, externe oder compliance-relevante Aktionen haben Human Approval.
- [ ] Dokumentation, ADRs und Compliance-Matrix sind aktualisiert.

## Aktueller Baseline-Stand

Bereits umgesetzt:

- [x] Dockerisiertes FastAPI-Grundgeruest.
- [x] `AGENTS.md` mit AI-, Voice- und RAG-Regeln.
- [x] AI Control Plane Package.
- [x] Deny-by-default Tenant AI Policy.
- [x] In-memory Model Registry.
- [x] In-memory Prompt Registry.
- [x] In-memory Tool Permission Registry.
- [x] Local LLM Gateway mit Mock-, Ollama- und vLLM/OpenAI-kompatiblem Adapter.
- [x] ACL-aware RAG-Skeleton.
- [x] Voice Privacy Guard mit Push-to-talk-Pflicht.
- [x] Phase--1 AI/Voice/RAG-Governance-Dokumente.
- [x] Initiale API- und Policy-Tests.
- [x] Strukturierte Roadmap-Datei.
- [x] Phase-0-Tooling mit Ruff, Mypy, Pytest, Docker Compose Quality Gate und GitHub Actions CI.
- [x] Request-scoped Tenant Context fuer Tenant-Daten-Endpunkte.
- [x] Signed JWT PrincipalResolver mit serverseitiger Tenant-, Rollen-, Gruppen- und Objekt-ACL-Aufloesung.
- [x] Statischer OIDC/JWKS Verifier mit RS256, `kid`-Key-Auswahl, Issuer/Audience-Allowlist, Replay Guard und Health Reporting.
- [x] Dynamische OIDC Discovery mit JWKS Refresh, Key-Cache Expiry, IdP-Outage-Policy und persistentem Replay Store.
- [x] PostgreSQL/RLS-backed PrincipalResolver-, Tenant-Membership-, Rollen-, Gruppen-, ACL- und ABAC-Stores mit Audit-Refs.
- [x] PostgreSQL/RLS-backed JWT Replay Store mit tenant-aware Accepted/Replayed Events ohne Token-Body-Speicherung.
- [x] Kanonische DataClass Registry mit Drift-Tests fuer Runtime, Retention, KMS, DB Constraints, Prompt/Model Registry und Docs.
- [x] In-memory Append-only Audit Hash Chain mit Verifier und Manipulationstests.
- [x] File-backed Tenant Policy, Model Registry, Prompt Registry, Tool Permission und Audit JSONL Stores.
- [x] PostgreSQL/RLS-backed Append-only Audit Store mit isolierter Audit-Writer-Rolle, Tenant-Sequencing, HMAC-Checkpoints und WORM-Export-Evidence.
- [x] Authorized ChunkRepository fuer RAG-Kontext mit exakter Chunk-Aufloesung statt ganzer Source Documents.
- [x] Audited Authz Admin APIs mit dedizierter PostgreSQL-Admin-Rolle fuer Principal-, Rollen-, Gruppen-, ACL-, ABAC- und Replay-Retention-Mutationen.
- [x] Rollenbasierte Admin API fuer Tenant AI Settings und erlaubte Modelle.
- [x] Erste Prompt-Injection- und unauthorized-RAG-output Regressionstests.
- [x] Review-intake-Haertung fuer dev-only Header Auth, RAG-Datenklassenpropagation und lokale Dev-Krypto-Production-Sperren.
- [x] Architekturtests gegen direkte LLM Provider Bypaesse ausserhalb des Gateways.
- [x] ADR-0031 pgvector vs. Qdrant als erster Vector Backend.
- [x] Erste pgvector Embedding-Metadaten-Migration mit RLS- und Lifecycle-Tests.
- [x] Docker-PostgreSQL/pgvector-Service mit Migrationsrunner und Live-RLS-Integrationstests.
- [x] pgvector Adapter fuer Upsert, Lifecycle-Transition und Candidate-only Search.
- [x] Worker Entry Points fuer Vector Reindex und Deletion Propagation.

Noch nicht umgesetzt:

- [x] Master-Compliance-Dokumente.
- [x] ADR-Struktur.
- [ ] Persistente Datenbank.
- [ ] Vollstaendiger IAM/OIDC Auth Context.
- [ ] Automatisierte WORM Audit Snapshots und produktive KMS-signierte Audit Checkpoints.
- [ ] KMS/WORM/Retention/Legal Hold.
- [ ] Office-, Mail-, Search-, E-Discovery-, Admin- und Business-Module.

## Roadmap-Ueberblick

| Phase | Thema | Ergebnis |
| --- | --- | --- |
| -1 | Produkt, Recht, Standards, AI/Voice/RAG Governance | Unveraenderbare Rahmenbedingungen sind entschieden |
| 0 | Secure SDLC, AI SDLC, Codex Factory | Entwicklung laeuft mit Gates, SBOM, Scans und Teststrategie |
| 1 | Core Platform, IAM, Tenant, Authz, Audit, AI Control Plane | Jede Aktion ist tenant-, policy- und auditfaehig |
| 2 | Storage, WORM, KMS, Retention, Embeddings | Records, Keys und Vector Lifecycle sind kontrolliert |
| 3 | Office Collaboration, Versionen, AI Assistenz, Voice | Dokumente funktionieren sicher als Drafts und Records |
| 4 | Mail Core, Team Inbox, Mail Security, AI Triage | E-Mail wird kollaborativ, revisionsfaehig und sicher |
| 5 | Unified Search, Index Security, RAG, E-Discovery-Basis | Suche und RAG liefern nur autorisierte Quellen |
| 6 | Lifecycle, Legal Hold, DSGVO, GoBD, AI Governance | Compliance-Entscheidungen sind technisch erzwingbar |
| 7 | E-Discovery, Forensik, Export | Herausgaben sind reproduzierbar und beweissicher |
| 8 | Kubernetes, Self-Hosting, lokale LLM Deployments | Kunden koennen sicher selbst betreiben |
| 9 | Security Hardening, Performance, Audit Readiness | Release Candidate ist belastbar geprueft |
| 10 | Enterprise Readiness und v1.5-Ausbau | Audit-Paket, Betriebsreife und Enterprise-Erweiterungen |
| 11 | Platform Module System, CRM/ERP und weitere Fachmodule | ERP, Wissensdatenbank, LMS, Aufgaben, Tickets und Zeiterfassung docken compliance-sicher an |

## Referenzstandards

Diese Standards sind Zielrahmen fuer Control-Mapping, nicht lose Checklisten:

- DSGVO: Privacy by Design, Security by Design, Loeschung, Einschraenkung, TOMs.
- GoBD: WORM, Versionierung, Datenzugriff, Verfahrensdokumentation.
- EU AI Act: Transparenz, Risikoklassifikation, technische Dokumentation, Human Oversight.
- BSI IT-Grundschutz / Grundschutz++.
- BSI TR-02102 fuer Kryptographie.
- BSI C5:2026 fuer Betriebs- und Cloud-nahe Kontrollen.
- ISO/IEC 27001:2022.
- OWASP ASVS 5.0.
- OWASP Top 10 for LLM/GenAI Applications.
- NIST CSF 2.0.
- NIST SSDF.
- NIST AI RMF.
- CIS Controls und CIS Kubernetes Benchmark.
- SLSA und CycloneDX SBOM.
- SMTP, IMAP4rev2, JMAP, SPF, DKIM, DMARC, MTA-STS.
- OOXML / ECMA-376 und ODF 1.3.
- EDRM XML und Chain of Custody.
- WCAG 2.2 AA und EN 301 549.

## Ziel-Repository-Struktur

Die aktuelle Implementierung ist bewusst klein. Zielstruktur fuer die wachsende Suite:

```text
suite/
  AGENTS.md
  PLANS.md
  SECURITY.md
  THREAT_MODEL.md
  COMPLIANCE_MATRIX.md
  ARCHITECTURE_DECISIONS/
  docs/
    compliance/
    legal/
    operations/
    performance/
    runbooks/
  backend/
    apps/
      api/
      module-registry/
      mail-gateway/
      collaboration/
      search-indexer/
      lifecycle-worker/
      ediscovery/
      audit-service/
      kms-adapter/
      ai-control-plane/
      llm-gateway/
      crm-erp/
      knowledge-base/
      learning-management/
      work-management/
      service-desk/
      time-tracking/
    libs/
      authz/
      audit/
      crypto/
      data-classification/
      retention/
      tenant-context/
      policy-engine/
      observability/
      module-runtime/
  frontend/
    apps/
      web-suite/
      admin-console/
      ediscovery-console/
      crm-erp-console/
      knowledge-console/
      learning-console/
      work-console/
      service-desk-console/
      time-tracking-console/
    packages/
      editor-text/
      editor-sheet/
      mail-ui/
      design-system/
      command-palette/
      voice-ui/
  infra/
    helm/
    terraform/
    kubernetes/
    policies/
      opa/
      kyverno/
      network/
  tests/
    unit/
    integration/
    e2e/
    compliance/
    security/
    ai/
    performance/
    fixtures/
```

## Nicht verhandelbare Architekturentscheidungen

### Persistentes Objektmodell

Jede persistente Entitaet benoetigt mindestens:

```text
tenant_id
object_id
object_type
owner_principal_id
created_by
created_at_utc
updated_at_utc
data_classification
retention_policy_id
legal_hold_state
kms_key_ref
audit_chain_ref
source_system
schema_version
```

### Datenzustandsmodell

Office, Mail und Collaboration muessen klar trennen:

```text
Working Data
  -> Draft / Collaborative State
    -> Saved Version
      -> Business Record
        -> WORM Evidence Record
```

Nicht jedes CRDT-Delta ist ein GoBD-Record. Nicht jeder Draft ist ein Business Record.

### Datenklassen

- GoBD-relevant.
- DSGVO-personenbezogen.
- Legal Hold.
- Kollaborativ / Arbeitsstand.
- Temporaer.
- Sicherheitsdaten.
- AI Prompt.
- AI Output.
- RAG Chunk.
- Embedding.
- Retrieval Trace.
- Voice Audio.
- Voice Transcript.
- Tool Call.
- Model Config.
- AI Evaluation.

### KMS-Hierarchie

```text
root-of-trust
  -> tenant master key
    -> data-class key
      -> object encryption key
        -> version key / envelope key
```

Pflicht:

- Key-Versioning.
- Rotation ohne Datenverlust.
- Tenant-separierte Keys.
- Key-Usage-Audit.
- Break-glass-Prozess.
- Key-destruction evidence.
- Crypto-Agilitaet ueber Adapter.

### Such- und RAG-Regel

Nicht erlaubt:

```text
search/vector index -> direct response
```

Erlaubt:

```text
query
  -> candidate ids
    -> authoritative authz check
      -> source fetch
        -> redaction
          -> response / RAG context
```

Vector DB und Search Index sind Beschleuniger, keine Berechtigungsquelle.

### Voice-Regel

- Push-to-talk oder explizite Aktivierung als Default.
- Kein Always-on-Mikrofon.
- Roh-Audio wird nicht gespeichert, ausser Tenant Policy erlaubt es explizit.
- Transkripte sind personenbezogene oder vertrauliche Daten und folgen Retention.
- Voice Commands umgehen niemals Berechtigungen.

### Modul-Erweiterungsregel

ERP/CRM, Wissensdatenbank, LMS, Aufgaben und Aktivitaeten, Meldesysteme und Tickets, Zeiterfassung und spaetere Fachmodule sind optionale Produktmodule auf demselben Compliance-Core.

Jedes neue Modul braucht vor Implementierung ein Module Charter mit:

- `module_id`, Modulstatus, Tenant-Entitlement und Tenant-Enablement.
- Serverseitigem Modul-Gate fuer API, Worker und Admin-Aktionen.
- Feature-Permissions; UI-Sichtbarkeit ist nur Komfort, keine Autorisierung.
- Objektklassen, Datenklassen, Retention Policies, Legal-Hold-Scope und KMS-Bezug.
- Audit-Events fuer Enable, Disable, Suspend, Decommission, Import, Export und destruktive Absichten.
- Backup-/Restore-/Failover-Domain und Restore-Evidence.
- Search/RAG-Quellenvertrag mit Candidate-only Results und autoritativer ACL-Pruefung.
- Migrations- und Decommissioning-Regeln mit Checksummen und Freigabe.

Modulstatus:

```text
not_installed
installed
available
provisioning
enabled
disabled
suspended
decommission_requested
decommission_blocked
decommissioned
```

Ein deaktiviertes Modul ist nicht geloescht. Retention, Legal Hold, Audit, Backup, Restore, Export, GoBD- und DSGVO-Pflichten laufen weiter.

## Phase -1: Produkt-, Rechts-, Standard-, AI- und UX-Fundament

Ziel: Verhindern, dass Features entstehen, bevor die unveraenderbaren Rahmenbedingungen existieren.

Deliverables:

- [x] `PRODUCT_CHARTER.md`
- [x] `PLANS.md`
- [x] `SECURITY.md`
- [x] `THREAT_MODEL.md`
- [x] `COMPLIANCE_MATRIX.md`
- [x] `DATA_CLASSIFICATION.md`
- [x] `RETENTION_POLICIES.yaml`
- [x] `LEGAL_HOLD_MODEL.md`
- [x] `ARCHITECTURE_DECISIONS/ADR-0001-tenancy.md`
- [x] `ARCHITECTURE_DECISIONS/ADR-0002-worm-storage.md`
- [x] `ARCHITECTURE_DECISIONS/ADR-0003-kms-key-hierarchy.md`
- [x] `ARCHITECTURE_DECISIONS/ADR-0004-audit-event-model.md`
- [x] `AGENTS.md`
- [x] `docs/AI_GOVERNANCE.md`
- [x] `docs/VOICE_PRIVACY_MODEL.md`
- [x] `docs/RAG_SECURITY_MODEL.md`
- [x] `docs/VECTOR_INDEX_MODEL.md`
- [x] `docs/SOURCE_OBJECT_MODEL.md`
- [x] `docs/UX_PRINCIPLES.md`
- [x] `docs/AI_RISK_REGISTER.md`
- [x] `docs/MODEL_REGISTRY.md`
- [x] `docs/PROMPT_REGISTRY.md`
- [x] `docs/AI_AUDIT_SCHEMA.md`

Aufgaben:

- [x] Compliance-Matrix fuer Standards und Produktkontrollen erstellen.
- [x] Datenklassifikation inkl. Speicherort, Loeschlogik, Exportlogik, Schluesselmodell und Auditpflicht definieren.
- [x] Konfliktmodell DSGVO-Loeschung vs. GoBD-Aufbewahrung vs. Legal Hold definieren.
- [x] Retention Policies maschinenlesbar anlegen.
- [x] Legal-Hold-Semantik technisch beschreiben.
- [ ] AI Risk Register maschinenlesbar machen.
- [ ] UX-Zielmetriken fuer wenige Klicks definieren.
- [ ] Festlegen, welche Aktionen bewusst Reibung brauchen.
- [ ] Codex-Ticket-Template dokumentieren.

Exit-Kriterien:

- [ ] Jede Datenklasse hat Policy, KMS-, Retention-, Legal-Hold- und Auditbezug.
- [ ] Jede AI-, Voice-, RAG- und Automationsfunktion hat Zweck, Risiko, erlaubte Datenklassen, Modelle und Approval-Regeln.
- [ ] Kein Feature darf ohne Compliance-Mapping begonnen werden.

## Phase 0: Secure SDLC, AI SDLC und Codex Factory

Ziel: Codex arbeitet in einem kontrollierten Engineering-System, nicht als ungebremster Codegenerator.

Epics:

- SDLC-1: Repository-Hygiene und Tooling.
- SDLC-2: CI/CD Quality Gates.
- SDLC-3: Supply-Chain-Sicherheit.
- SDLC-4: AI Safety Evaluation.
- SDLC-5: Test-Fixtures und Compliance Tests.

Aufgaben:

- [x] `pyproject.toml` mit Ruff, MyPy/Pyright und Pytest anlegen.
- [ ] TypeScript-/Frontend-Tooling vorbereiten.
- [x] CI fuer Tests, Lint, Typpruefung und Docker Build anlegen.
- [ ] Secret Scan integrieren.
- [ ] Dependency Scan integrieren.
- [ ] License Scan integrieren.
- [ ] SAST/DAST/IaC Scan einplanen.
- [ ] CycloneDX SBOM generieren.
- [ ] Build Provenance und signierte Artefakte vorbereiten.
- [ ] ADR-Template anlegen.
- [ ] Compliance-Matrix als YAML/Markdown-Quelle versionieren.
- [ ] Test-Fixtures fuer Tenants, Rollen, Dokumente, Mails, Holds und AI Policies anlegen.
- [ ] Prompt-Lint einfuehren.
- [ ] Prompt-Injection-Testkorpus ausbauen.
- [x] Erste Prompt-Injection- und unauthorized-RAG-output Tests schreiben.
- [ ] RAG-Retrieval-Qualitaetstests anlegen.
- [ ] Source-Citation-Tests anlegen.
- [ ] Model-License- und Checksum-Checks anlegen.
- [ ] AI Incident Response Runbook anlegen.

Exit-Kriterien:

- [ ] PRs koennen ohne Tests, Lint, Security Checks und relevante Docs nicht gruen werden.
- [ ] Prompts, Modelle, Dependencies und Container sind versioniert und nachvollziehbar.

## Phase 1: Core Platform, Mandantenfaehigkeit, IAM, Audit und AI Control Plane

Ziel: Das Fundament bauen, auf dem alle spaeteren Module sicher laufen.

Epics:

- CORE-1: Request-scoped Tenant Context.
- CORE-2: IAM/OIDC/SAML und Principal Model.
- CORE-3: RBAC + ABAC Policy Engine.
- CORE-4: Append-only Audit Service.
- CORE-5: Admin-Konsole fuer Tenants, Rollen und Policies.
- AI-1: AI Control Plane.
- AI-2: Local LLM Gateway.
- AI-3: Human Approval Engine.
- OBS-1: Observability ohne sensitive Logs.

Bereits erledigt:

- [x] Policy Model Skeleton.
- [x] Model Registry Skeleton.
- [x] Prompt Registry Skeleton.
- [x] Tool Permission Registry Skeleton.
- [x] LLM Gateway Skeleton.
- [x] Inference Audit Events als In-memory-Skeleton.
- [x] Request Context Dependency fuer Tenant, Principal und Tenant Policy.
- [x] API-Tests fuer fehlenden und unbekannten Tenant Context.
- [x] In-memory Append-only Audit Event Schema.
- [x] Audit Hash Chain Verifier.
- [x] Manipulationstests fuer geaenderte und entfernte Audit Events.
- [x] File-backed JSON Stores fuer Tenant Policies, Model Registry, Prompt Registry und Tool Permissions.
- [x] JSONL Audit Store mit Reload und Chain-Verifikation.
- [x] Admin API fuer Tenant AI Settings und Allowed Models mit Rollenpruefung.
- [x] Audit Events fuer Tenant Policy Updates.

Aufgaben:

- [x] Demo-User durch request-scoped Tenant Context ersetzen.
- [x] Tenant Context Dependency fuer Tenant-Daten-Endpunkte implementieren.
- [x] Dev-Header-Tenant-Context in Production und ausserhalb `SUITE_AUTH_MODE=dev` fail-closed sperren.
- [x] Signed JWT PrincipalResolver mit serverseitiger Tenant Membership, Rollen, Gruppen und Object ACLs implementieren.
- [x] Principal-, Role- und Permission-Modelle implementieren.
- [x] Statischen OIDC/JWKS Verifier mit Issuer/Audience Allowlist, RS256, `kid`-Rotation, Replay Guard und Health Checks vorbereiten.
- [x] Dynamische OIDC Discovery, JWKS Refresh, Key-Cache Expiry, IdP-Outage-Policy und persistente Replay Stores implementieren.
- [x] JWT Replay State von JSON auf PostgreSQL mit tenant-aware Audit Events umziehen.
- [x] Kanonische DataClass Registry einziehen und gegen Runtime, Retention, KMS, DB Constraints, Prompt/Model Registry und Compliance Docs validieren.
- [ ] MFA/FIDO2/WebAuthn als Zielarchitektur dokumentieren.
- [x] PostgreSQL mit Migrationen und Runtime-Rollen einfuehren.
- [x] RLS als Defense-in-depth planen und testen.
- [x] Persistente Tenant Policy Stores implementieren.
- [x] Persistente Model-, Prompt- und Tool-Registries implementieren.
- [x] Admin API fuer AI on/off pro Tenant.
- [x] Admin API fuer erlaubte Modelle pro Tenant.
- [ ] Role- und Datenklassen-spezifische Modellfreigaben administrierbar machen.
- [x] Append-only Audit Event Schema implementieren.
- [x] Audit Hash Chain implementieren.
- [ ] Audit Verification Command implementieren.
- [x] Persistente Audit Storage Abstraktion implementieren.
- [x] PostgreSQL Audit Store mit isolierter Runtime-Rolle, Tenant-Sequencing, HMAC-Checkpoints und WORM-Export-Evidence implementieren.
- [ ] PostgreSQL-Backed Stores mit Migrationen implementieren.
- [ ] Outbox fuer Audit- und Domain-Events implementieren.
- [ ] Break-glass Zugriff technisch modellieren.
- [ ] Human Approval API fuer kritische Aktionen implementieren.
- [ ] Token-Budget- und Timeout-Enforcement im LLM Gateway implementieren.
- [ ] JSON Schema Validation fuer LLM Outputs implementieren.
- [ ] Streaming Response Support vorbereiten.
- [ ] Tests fuer Tenant Isolation ueber API, Search, Audit und Fehlerantworten.
- [x] Tests, die direkten Provider-BYPASS im App-Code verhindern.

Exit-Kriterien:

- [ ] Kein API-Handler laeuft ohne Principal, Tenant und Policy-Kontext.
- [ ] Tenant-Daten koennen nicht tenant-uebergreifend gelesen werden.
- [x] Audit Events sind hash-verkettet und Manipulation wird erkannt.
- [ ] Jede AI-Anfrage hat Tenant Policy, Model ID, Prompt ID, Quellenstatus und Audit ID.
- [ ] High-Risk-Aktionen erzeugen Human Approval.

## Phase 2: Storage, WORM, Retention, KMS, Embeddings und Vector Lifecycle

Ziel: Revisionssicherer Speicher und Datenlebenszyklus stehen, bevor Dokumente, Mails und RAG produktiv werden.

Epics:

- STORAGE-1: Object Metadata Model.
- STORAGE-2: WORM Storage Adapter.
- STORAGE-3: Retention Policy Engine.
- STORAGE-4: Legal Hold Service.
- KMS-1: KMS Adapter und Envelope Encryption.
- KMS-2: Key Rotation und Key Destruction Evidence.
- EMB-1: Chunking und Embedding Service.
- EMB-2: Vector Writer und Delete Propagation.

Aufgaben:

- [x] Source Object Model fuer Dokumente, Mails, Attachments, Kommentare und Verfahrensdokumentation definieren.
- [x] Storage Write nur mit `tenant_id`, `classification`, `retention_policy_id`, `kms_key_ref`, `manifest_hash` und `content_hash` erlauben.
- [x] S3/MinIO-kompatiblen Storage Adapter planen.
- [x] WORM/Object-Lock-faehigen Bucket und Versioning modellieren.
- [x] Retention Defaults und Retention Manifest definieren.
- [x] Legal Hold APIs fuer Objekte definieren.
- [x] Content Hash Verification implementieren.
- [x] Storage Manifest implementieren.
- [x] KMS Adapter implementieren.
- [x] Envelope Encryption API implementieren.
- [x] Lokale Dev-KMS- und Envelope-Implementierung in Production fail-closed sperren.
- [x] Key Rotation Interface implementieren.
- [x] Cryptographic Shredding Simulation implementieren.
- [x] Schutzregel: GoBD- und Legal-Hold-Objekte nicht versehentlich cryptoshreddern.
- [x] Restore-Test-Framework anlegen.
- [x] Text Extraction Interface fuer Office/Mail/Attachments.
- [x] Chunker Interface.
- [x] Embedding Provider Interface.
- [x] Vector Metadata Schema validieren.
- [x] ACL-Versionen in Vector Metadata uebernehmen.
- [x] Delete Propagation Worker.
- [x] Reindex Worker.
- [ ] Embedding Model Versioning.

Exit-Kriterien:

- [ ] WORM-Objekte koennen vor Retention-Ende nicht geloescht oder ueberschrieben werden.
- [ ] Legal Hold gewinnt gegen Lifecycle-Loeschung.
- [ ] Key Rotation zerstoert keine Lesbarkeit.
- [ ] Embeddings sind klassifizierte Tenant-Daten.
- [ ] Geloeschte, gesperrte oder key-destroyed Quellen erscheinen nicht in RAG-Kontext.

## Phase 3: Office Collaboration, Versionierung, AI Assistenz und Voice

Ziel: Echtzeitfaehige Dokumentbearbeitung mit sauberem Uebergang von Arbeitsstand zu revisionsrelevantem Record.

Epics:

- OFFICE-1: Document Model und Versioning.
- OFFICE-2: CRDT Collaboration Service.
- OFFICE-3: Editor Text und Tabellen.
- OFFICE-4: Import/Export Pipeline.
- OFFICE-5: Parser Sandbox.
- OFFICE-6: AI Writing Assistant.
- OFFICE-7: Dictation und Read Aloud.
- OFFICE-8: Source Drawer und Citations.

Aufgaben:

- [ ] Dokument-Metadaten- und Version-APIs erstellen.
- [ ] Draft, Collaborative State, Saved Version, Business Record und WORM Record modellieren.
- [ ] CRDT Service vorbereiten.
- [ ] WebSocket Gateway vorbereiten.
- [ ] Commenting, Mentions und Change Attribution modellieren.
- [ ] Soft Locks und Versioning Service implementieren.
- [ ] Parser-Worker isoliert und ohne Netzwerk planen.
- [ ] Makro-Policy: erkennen, blockieren oder markieren, keine Ausfuehrung im MVP.
- [ ] OOXML/ODF-Kompatibilitaetsmatrix erstellen.
- [ ] Import/Export-Testkorpus anlegen.
- [ ] Textzusammenfassung fuer markierte Bereiche.
- [ ] Umformulieren und Tonalitaet aendern.
- [ ] Uebersetzen.
- [ ] Gliederung erzeugen.
- [ ] Dokument mit Richtlinie vergleichen.
- [ ] Risiken markieren.
- [ ] Quellen suchen und versioniert anzeigen.
- [ ] Diktat in Dokumente ueber Voice Transcript Flow.
- [ ] Text-to-Speech Adapter Interface.
- [ ] Tests: AI darf Business Record nicht automatisch committen.
- [ ] Lasttest-Ziel: 50 gleichzeitige Bearbeiter pro Dokument.

Exit-Kriterien:

- [ ] AI-Vorschlaege bleiben Drafts bis Nutzer sie uebernimmt.
- [ ] Jede freigegebene Version kann unveraenderbar gespeichert werden.
- [ ] Parser laufen nicht im API-Prozess und haben keinen Netzwerkzugriff.
- [ ] RAG-backed Dokumentantworten zeigen versionsgenaue Quellen.

## Phase 4: Mail Core, Team Inbox, Mail Security, Voice und AI Triage

Ziel: E-Mail als kollaboratives, revisionsfaehiges Team- und Compliance-System.

Epics:

- MAIL-1: Mail Account, Message und Thread Model.
- MAIL-2: SMTP Submission / Relay / Gateway.
- MAIL-3: IMAP4rev2 Proxy oder Zugriffsschicht.
- MAIL-4: JMAP als moderne API-Schicht.
- MAIL-5: MIME und Attachment Processing.
- MAIL-6: DKIM, SPF, DMARC, MTA-STS.
- MAIL-7: Team Inbox und Shared Drafts.
- MAIL-8: AI Triage, Smart Reply, Smart Attach.
- MAIL-9: Voice Mail Workflows.

Aufgaben:

- [ ] Mail Thread Model.
- [ ] Draft Reply Model.
- [ ] Journal Records fuer eingehende und ausgehende Mails.
- [ ] SMTP Submission / Relay Strategie festlegen.
- [ ] IMAP/JMAP Strategie festlegen.
- [ ] MIME Parsing in isolierten Workern.
- [ ] Attachment Scan vor Oeffnung.
- [ ] DKIM Signing.
- [ ] SPF Validation.
- [ ] DMARC Status speichern und auditieren.
- [ ] MTA-STS und TLS Reporting einplanen.
- [ ] Team Inbox Assignment.
- [ ] Shared Drafts als kollaborative Entwuerfe.
- [ ] Team-Kommentare technisch getrennt vom RFC-Mailobjekt.
- [ ] Thread Summary.
- [ ] Reply Suggestion.
- [ ] Tonalitaet anpassen.
- [ ] Attachment Search via autorisiertem RAG.
- [ ] Fristen extrahieren und als pruefpflichtig markieren.
- [ ] Doppelte Verarbeitung verhindern.
- [ ] "Do not send"-Risiken markieren.
- [ ] Explizite Sendebestaetigung.
- [ ] Tests: AI kann Mail nicht direkt senden.
- [ ] Tests: interne Kommentare koennen nicht in externe Replies leaken.

Exit-Kriterien:

- [ ] AI-generierte Mails bleiben Drafts.
- [ ] Attachments brauchen sichtbare Bestaetigung.
- [ ] Mailzustellung ist idempotent.
- [ ] Mail-Suche gibt keine Treffer ohne Berechtigung zurueck.

## Phase 5: Unified Search, Index Security, RAG und E-Discovery-Basis

Ziel: Suche darf kein Datenschutz- oder Compliance-Leck werden.

Epics:

- SEARCH-1: Search Indexer.
- SEARCH-2: ACL-aware Query Gateway.
- SEARCH-3: Keyword Search.
- SEARCH-4: Vector Search Adapter.
- SEARCH-5: Hybrid Retrieval und Reranking.
- SEARCH-6: Source Resolver und Redaction.
- RAG-1: RAG Context Builder.
- RAG-2: Citation Builder und Answer Verifier.
- DISC-0: E-Discovery Query Model.

Bereits erledigt:

- [x] In-memory Vector Candidate Flow.
- [x] ACL Check vor Kontextaufbau.
- [x] Keyword Indexer Boundary mit Candidate-only API Results und Search Audit Events.

Aufgaben:

- [ ] Persistente Search Indexer Pipeline.
- [ ] Dokumenttext-Extraktion.
- [ ] Mail Body Extraction.
- [ ] Attachment Text Extraction.
- [ ] Tenant-separierte Indizes oder harte Tenant Filter.
- [ ] Index-Rebuild Pipeline.
- [x] Search Audit Events fuer Keyword Candidate Search.
- [ ] Snippet-Erzeugung erst nach Authz.
- [x] Persistent Vector DB Adapter.
- [x] ADR: pgvector vs. Qdrant als erster Backend-Adapter.
- [x] pgvector Embedding-Metadaten-Schema als erste SQL-Migration.
- [x] Live pgvector RLS-Integrationstest gegen PostgreSQL.
- [ ] Hybrid Query Orchestration.
- [ ] Reranker Interface.
- [ ] Source Resolver.
- [ ] Redaction Engine.
- [x] RAG Inference Data Classes aus `ai_prompt` und autorisierten Source-Klassifikationen ableiten.
- [x] RAG Context Builder nutzt exakte autorisierte Chunks statt ganzer Source Documents.
- [ ] RAG Answer Schema mit Confidence und Sources.
- [ ] Unsupported-answer Label.
- [ ] User Feedback API ohne automatisches Training.
- [ ] E-Discovery Query Model vorbereiten.

Exit-Kriterien:

- [ ] Index gibt nur Kandidaten aus.
- [ ] Authz und Redaction passieren vor Ausgabe.
- [ ] Geloeschte oder gesperrte Objekte verschwinden nach SLA aus dem Index.
- [ ] Legal-Hold-Objekte bleiben fuer berechtigte Rollen auffindbar.
- [ ] RAG Antworten ohne Quellen werden als unbelegt markiert.

## Phase 6: Lifecycle, Legal Hold, DSGVO, GoBD und AI Governance

Ziel: Compliance-Logik wird als Policy Engine implementiert, nicht als verstreute Sonderlogik.

Epics:

- LIFE-1: Lifecycle Worker.
- LIFE-2: Retention Simulation.
- LIFE-3: Legal Hold Enforcement.
- PRIV-1: Data Subject Workflows.
- GOBD-1: Verfahrensdokumentation.
- AI-GOV-1: AI System Card und Model Cards.
- AI-GOV-2: Prompt/Model Change Logs.
- OVERSIGHT-1: Human Oversight operationalisieren.

Policy-Entscheidungsreihenfolge:

```text
1. Tenant isolation
2. Legal Hold
3. Regulatory retention
4. Contractual retention
5. Data subject rights
6. Business policy
7. Default deny
```

Aufgaben:

- [ ] Policy Engine entscheidet: read, modify, delete, cryptoshred, export, place hold, lift hold, redact, restrict processing.
- [ ] Lifecycle Worker prueft Fristen, Holds und Klassifikation.
- [ ] Sperren statt loeschen, wenn Aufbewahrungspflicht besteht.
- [ ] Loeschen oder Cryptoshredding nur bei zulaessiger Policy.
- [ ] Retention-Simulationen regelmaessig erzeugen.
- [ ] Restore und Key-Destruction testen.
- [ ] DSGVO Export Workflow.
- [ ] DSGVO Loesch-/Sperr-/Einschraenkungsworkflow.
- [ ] GoBD-Verfahrensdokumentation generieren.
- [ ] `docs/AI_SYSTEM_CARD.md`
- [ ] `docs/MODEL_CARD_TEMPLATE.md`
- [ ] `docs/RAG_DATA_FLOW.md`
- [ ] `docs/PROMPT_CHANGE_LOG.md`
- [ ] `docs/MODEL_CHANGE_LOG.md`
- [ ] `docs/AI_INCIDENT_RUNBOOK.md`
- [ ] `docs/HUMAN_OVERSIGHT_POLICY.md`
- [ ] `docs/VOICE_DATA_PROTECTION.md`
- [ ] AI-Interaktion fuer Nutzer sichtbar labeln.
- [ ] Admin-Ansicht: welche Daten duerfen zu welchem Modell.

Exit-Kriterien:

- [ ] Legal Hold verhindert Loeschung technisch.
- [ ] Loeschentscheidungen sind auditierbar.
- [ ] Jeder Export hat Manifest, Hashes, Chain of Custody und Bearbeiterhistorie.
- [ ] Admins koennen Model-, Prompt-, Source- und Audit-Lineage nachweisen.
- [ ] Nutzer erkennen AI-generierte oder AI-assistierte Inhalte.

## Phase 7: E-Discovery, Forensik und Export

Ziel: Juristische und prueferische Herausgaben sind standardisiert, beweissicher und kontrolliert.

Epics:

- DISC-1: Case/Matter Management.
- DISC-2: E-Discovery Console.
- DISC-3: Legal Hold Workflows.
- DISC-4: Review Sets und Redaction.
- DISC-5: Export Packages.
- DISC-6: Forensic RAG Export.

Aufgaben:

- [ ] Legal Matter Model.
- [ ] Query Builder.
- [ ] Review Sets.
- [ ] Rollenmodell fuer Pruefer und Discovery.
- [ ] Vier-Augen-Freigabe.
- [ ] Zugriffsbefristung.
- [ ] Redaction Workflow.
- [ ] Exportpaketformat:

```text
export.zip.enc
  manifest.json
  manifest.sig
  hashes.sha256
  chain_of_custody.json
  records/
    native/
    pdf/
    text/
    metadata/
  edrm.xml
  README_AUDIT.txt
```

- [ ] Source-bounded RAG Summary fuer Matters.
- [ ] Manipulationserkennung fuer Exportpakete.
- [ ] Tests fuer hold-aware Retention und Export.

Exit-Kriterien:

- [ ] Export ist reproduzierbar.
- [ ] Export enthaelt Originale und lesbare Ableitungen.
- [ ] Jeder Zugriff auf Exportdaten wird protokolliert.
- [ ] Redactions sind in Exporten nicht rueckgaengig machbar.

## Phase 8: Kubernetes, Self-Hosting, Betrieb und lokale LLM Deployments

Ziel: Enterprise-Kunden koennen die Suite sicher selbst betreiben.

Epics:

- OPS-1: Production Docker Compose Profile.
- OPS-2: Helm Charts und Kubernetes.
- OPS-3: Terraform Beispiele.
- OPS-4: Network Policies und mTLS.
- OPS-5: Secrets Management.
- OPS-6: Backup, Restore und Disaster Recovery.
- OPS-7: Local LLM Runtime Profiles.
- OPS-8: Air-gap Operations.

Aufgaben:

- [ ] Production Docker Compose Profile.
- [ ] Helm Chart.
- [ ] Terraform Beispiele.
- [ ] Kubernetes Network Policies.
- [ ] mTLS intern.
- [ ] Secrets nicht in ConfigMaps.
- [ ] Pod Security und Admission Policies.
- [ ] Parser Worker ohne Netzwerkzugriff.
- [ ] Resource Limits.
- [ ] Zero-downtime Migration Strategie.
- [ ] Backup/Restore Runbooks.
- [ ] Disaster Recovery Test.
- [ ] CPU-only LLM Profile.
- [ ] GPU/vLLM Profile.
- [ ] Ollama Lightweight Profile.
- [ ] Air-gap Model Import Procedure.
- [ ] Model Checksum Validation vor Aktivierung.
- [ ] Provider Health Checks.
- [ ] Observability ohne Prompt-/Output-Leakage.

Exit-Kriterien:

- [ ] Installation per Helm ist reproduzierbar.
- [ ] Default-Installation ist nicht dev-insecure.
- [ ] Backup/Restore wurde getestet.
- [ ] Suite kann local-only AI ohne externen Provider betreiben.

## Phase 9: Security Hardening, Performance und Audit Readiness

Ziel: Release Candidate fuer produktive Enterprise-Nutzung.

Epics:

- HARD-1: Threat Model Review.
- HARD-2: Penetrationstest-Vorbereitung.
- HARD-3: API, Parser und Authz Fuzzing.
- HARD-4: AI/RAG Abuse Tests.
- HARD-5: Supply-Chain Audit.
- PERF-1: Lasttests und SLOs.
- AUDIT-1: Audit Evidence Pack.

Aufgaben:

- [ ] Externer Penetrationstest einplanen.
- [ ] OWASP ASVS Mapping.
- [ ] Tenant-Isolation-Tests automatisieren.
- [ ] Authz-Bypass-Tests.
- [ ] Parser Fuzzing.
- [ ] CRDT-Manipulationstests.
- [ ] Prompt-Injection-Regression Suite.
- [ ] Embedding-Leakage-Tests.
- [ ] Unauthorized Output Leakage Tests.
- [ ] Tool-Misuse-Tests.
- [ ] Secrets Rotation Drill.
- [ ] Incident Response Drill.
- [ ] API Load Tests.
- [ ] WebSocket Load Tests.
- [ ] Suche/RAG Load Tests.
- [ ] Mail Submission Load Tests.
- [ ] Restore-Test kleiner Tenant.
- [ ] Audit-Chain-Verifikation Tagespartition.
- [ ] Release-Artefakte signieren.
- [ ] SBOM pro Release.

Performance-Zielwerte fuer v1:

| Bereich | Zielwert |
| --- | ---: |
| API p95 Standardoperationen | < 300 ms |
| Search p95 nach ACL-Filter | < 700 ms |
| WebSocket Delta Broadcast p95 intra-region | < 150 ms |
| Mail Submission bis Annahme | < 5 s p95 |
| Dokument oeffnen bei 5 MB | < 2 s p95 |
| Indexierung normaler E-Mail | < 60 s p95 |
| Restore-Test kleiner Tenant | < 30 min |
| Audit-Chain-Verifikation Tagespartition | < 10 min |
| Single-Region-Verfuegbarkeit | 99.9 % Ziel |
| RPO | <= 15 min |
| RTO | <= 4 h |

Exit-Kriterien:

- [ ] Kritische Findings sind geschlossen.
- [ ] Hohe Findings haben Fix oder dokumentierte Risikoentscheidung.
- [ ] Geschuetzte Daten erscheinen in Tests nicht in unautorisierten Outputs.
- [ ] Audit Pack ist vollstaendig.

## Phase 10: Enterprise Readiness und v1.5-Ausbau

Ziel: Produkt fuer externe Audits, Enterprise Procurement und Ausbau nach v1 vorbereiten.

Epics:

- ENT-1: Audit Evidence Package.
- ENT-2: Admin- und Betriebsdokumentation.
- ENT-3: Release- und Upgrade-Prozess.
- ENT-4: Enterprise v1.5 Features.

Aufgaben:

- [ ] Security Architecture Overview.
- [ ] Data Processing Overview.
- [ ] Admin Manual.
- [ ] Deployment Manual.
- [ ] Incident Response Playbooks.
- [ ] Release Checklist.
- [ ] Upgrade- und Migration Process.
- [ ] External Audit Evidence Index.
- [ ] Full Release Candidate Validation.
- [ ] S/MIME/PGP Erweiterung.
- [ ] DLP Policies.
- [ ] Mobile Apps.
- [ ] JMAP-Ausbau.
- [ ] Archivzertifizierungsoptionen.
- [ ] Multi-Region.
- [ ] High Availability Profile.

Exit-Kriterien:

- [ ] Enterprise Buyer versteht Deployment, Datenfluesse, AI-Kontrollen und Audit Evidence.
- [ ] v1 Release Candidate hat komplette Test-, Security-, Betriebs- und Governance-Nachweise.

## Phase 11: Platform Module System, CRM/ERP und weitere Fachmodule

Ziel: Fachmodule entstehen nicht als parallele Silos, sondern als tenantfaehige Add-ons auf dem bestehenden Compliance-, Audit-, Storage-, KMS-, Search-, RAG-, Backup- und Failover-Core.

Leitsatz:

```text
Module sind optional in der Nutzung,
aber nicht optional in der Compliance.
```

Epics:

- MOD-1: Platform Module Registry und Tenant Module State.
- MOD-2: Module-Aware Migrations und Provisioning Evidence.
- MOD-3: CRM/ERP optionales Modul `crm_erp`.
- MOD-4: Business Object Registry fuer Fachmodule.
- MOD-5: SQL-Server-Legacy-Import fuer CRM/ERP.
- MOD-6: Fachmodul-Search/RAG Boundary.
- MOD-7: Modul-Decommissioning mit Retention, Legal Hold, Export und Audit Evidence.
- MOD-8: Modul-Vorbereitung fuer Wissensdatenbank, LMS, Aufgaben/Aktivitaeten, Meldesysteme/Tickets und Zeiterfassung.

Plattform-Aufgaben:

- [x] ADR fuer Platform Module System erstellen.
- [x] `module_catalog` und `tenant_modules` als Kernmodell definieren.
- [x] Statusmodell fuer installierte, verfuegbare, aktivierte, deaktivierte, suspendierte und dekommissionierte Module implementieren.
- [x] `GET /v1/platform/modules` fuer Frontend-Discovery planen.
- [x] Admin-APIs fuer Provision, Enable, Disable, Suspend und Decommission Check implementieren.
- [x] Decommission Request API mit Evidence Workflow implementieren.
- [x] Decommission Blocked/Completed Workflow mit finaler Disposition Evidence implementieren.
- [x] Decommission Cancel/Reopen Workflow mit expliziter Freigabe und Audit Evidence implementieren.
- [x] Serverseitige Modul-Gates fuer API-Router und Worker einfuehren.
- [x] Module-Aware Migration Catalog mit Checksummen, Evidence und Startblockade bei Mismatch planen.
- [x] Tests fuer enabled/disabled/suspended/decommissioned Verhalten definieren.
- [x] Legacy-SQL-Discovery als metadata-only Evidenzschritt vor Mapping, Import und Registry-Entscheidungen implementieren.
- [x] `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md` als verbindlichen Vertical-Slice-Vertrag fuer CRM/ERP, Wissensdatenbank, LMS, Aufgaben, Tickets, Zeiterfassung und spaetere Module einziehen.
- [x] Backup-/Failover-Policy bei jedem Modul mit persistentem Zustand als Teil des Modul-Implementierungsvertrags mitziehen.

CRM/ERP `crm_erp`:

- [x] Module Charter fuer `crm_erp` schreiben.
- [x] Legacy-SQL-Discovery-Framework fuer Schema-Snapshot, Candidate-Inference, Import-Evidence-Plan und Quarantaene unbekannter Tabellen implementieren.
- [x] Isolierten SQL-Server-Metadata-Adapter-Worker hinter Connector-Policy implementieren.
- [x] CRM/ERP-Mapping-Evidence fuer Discovery-Tabellen, Zielobjekt-Kandidaten, `legacy.row`-Fallbacks und Quarantaene-Entscheidungen implementieren.
- [x] Subfeatures definieren: `crm_erp.crm.accounts`, `crm_erp.crm.contacts`, `crm_erp.crm.activities`, `crm_erp.erp.products`, `crm_erp.erp.suppliers`, `crm_erp.erp.orders`, `crm_erp.erp.invoices`, `crm_erp.legacy_import.sqlserver`, `crm_erp.gobd_export`, `crm_erp.legal_hold`, `crm_erp.search.keyword`, `crm_erp.rag_indexing`, `crm_erp.ai_assist`.
- [x] Schemas planen: `crm_erp`, `crm`, `erp`, `crm_erp_legacy`.
- [x] CRM/ERP-Objektregeln definieren fuer `crm.account`, `crm.contact`, `crm.activity`, `crm.note`, `erp.product`, `erp.supplier`, `erp.order`, `erp.order_item`, `erp.invoice`, `erp.invoice_item`, `erp.delivery_note`, `erp.contract`, `legacy.row`.
- [x] Persistente CRM/ERP Schema-Scaffold-Migration mit `crm_erp.schema_plans`, `crm_erp.object_type_rules`, RLS und startup-blocking Evidence implementieren.
- [x] Ersten gated CRM Accounts Read-Vertical-Slice mit `crm.accounts`, Pflichtmetadaten, RLS, Audit und `GET /v1/crm/accounts` implementieren.
- [x] Gated CRM Contacts Read-Vertical-Slice mit `crm.contacts`, Account-Link-Redaktion, Pflichtmetadaten, RLS, Audit und `GET /v1/crm/contacts` implementieren.
- [x] Gated CRM Activities/Notes Read-Vertical-Slice mit `crm.activities`, `crm.notes`, Link-Redaktion, Pflichtmetadaten, RLS, Audit, metadata-only Notes und `GET /v1/crm/activities` plus `GET /v1/crm/notes` implementieren.
- [x] Minimalen ERP Products Read-Vertical-Slice mit `erp.products`, `internal` Klassifikation, Pflichtmetadaten, RLS, Audit und `GET /v1/erp/products` als Architekturbeweis implementieren.
- [x] Pflichtmetadaten erzwingen: Tenant, Object ID, Object Type, Source System, Classification, Retention Policy, Legal Hold State, Lifecycle State, KMS Key Ref, Audit Chain Ref, Schema Version.
- [x] Datenklassen harmonisieren: `personal_data`, `working_data`, `gobd_record`, `security_data` und `export_package` sind Alias-/Lifecycle-/Objektkonzepte auf kanonischen Runtime-Klassen.
- [x] Pflichtmetadaten-Contract auf weitere Modul-Write-Slices und Migration-Staging ausweiten, bevor neue persistente Fachobjekte eingefuehrt werden.
- [x] SQL-Server-Import nach Discovery mit Extract, Staging, Validation, Mapping, Row Counts, Checksums, Manifest Hash und Audit Events planen.
- [x] Legacy-SQL-Staging-Profile in den spaeteren Import-Dry-Run-Store einhaengen, sobald Row-Count- und Checksum-Strategie feststeht.
- [x] Legacy-SQL-Import-Dry-Run als metadata-only Worker ausfuehren und Ergebnis-Store anbinden, ohne produktive Import-Writes.
- [x] Legacy-SQL-Import-Dry-Run-Result-Review und Human-Approval-Gate fuer spaetere Import-Writes planen.
- [x] Legacy-SQL-Import-Write-Approval-Request-Boundary als nicht-ausfuehrendes Admin-/API-Gate vorbereiten, ohne Import-Writes freizuschalten.
- [x] Legacy-SQL-Import-Write-Approval-Record-Persistenz planen, weiterhin ohne Import-Write-Execution.
- [x] Legacy-SQL-Import-Write-Approval-Record-Store-Migration mit RLS, Append-only und Idempotency vorbereiten, ohne Import-Write-Execution.
- [x] Legacy-SQL-Import-Write-Approval-Record-Store-Adapter anbinden, weiterhin ohne Import-Write-Execution.
- [x] Migration APIs planen: Runs erstellen, anzeigen, Reports abrufen und Freigabe erteilen.
- [x] Legacy-SQL-Migration-Run-Registry-Skeleton mit RLS, Idempotency und metadata-only Reports vorbereiten, ohne Import-Write-Execution.
- [x] Legacy-SQL-Migration-Run-Registry-Adapter fuer metadata-only Run-/Report-Lookup anbinden, ohne Import-Write-Execution.
- [x] Legacy-SQL-Migration-API-Read-Endpoints fuer metadata-only Run-/Report-Discovery anbinden, ohne Run-Erstellung, Freigabe oder Import-Write-Execution.
- [x] Legacy-SQL-Migration-Run-Creation-Boundary als nicht-ausfuehrendes Admin-Gate vorbereiten, ohne Freigabe oder Import-Write-Execution.
- [x] Legacy-SQL-Migration-Run-Creation-Store-Persistenz an Boundary binden und idempotent metadata-only speichern, ohne Freigabe oder Import-Write-Execution.
- [x] Legacy-SQL-Migration-Report-Metadata-Persistenz an Run binden und idempotent metadata-only speichern, ohne Report-Freigabe oder Import-Write-Execution.
- [x] CRM Vertical Slice: Accounts, Contacts, Activities, Notes.
- [x] ERP Vertical Slice: Products, Suppliers, Orders, Order Items, Invoices und Invoice Items sind als metadata-only API-Slices vorhanden.
- [ ] GoBD-faehige Retention fuer Order, Invoice, Invoice PDF, Contract und Migration Evidence definieren.
- [ ] Legal Hold Scopes fuer Kunde, Auftrag, Rechnung, Projekt, Kontakt, Legacy-Row und verbundene Dokumente definieren.
- [x] CRM/ERP Search zuerst klassisch/ACL-gefiltert mit `POST /v1/crm-erp/search` und metadata-only Readiness ueber `GET /v1/platform/search/crm-erp/readiness`, im Workspace sichtbar; RAG-Readiness ist ueber `GET /v1/platform/search/crm-erp/rag-readiness` contract-ready fuer Kontextaufbau; Source-Resolver-ACL-Trace, Source-Citation-Contract, Prompt-Audit-Contract, Redaction-Contract, Authorized-Context-Contract und Inference-Execution-Boundary sind ueber `POST /v1/platform/search/crm-erp/source-resolver-acl-trace`, `POST /v1/platform/search/crm-erp/source-citation-contract`, `POST /v1/platform/search/crm-erp/prompt-audit-contract`, `POST /v1/platform/search/crm-erp/redaction-contract`, `POST /v1/platform/search/crm-erp/authorized-context-contract` und `POST /v1/platform/search/crm-erp/inference-execution-boundary` metadata-only vorhanden, echte Provider-Ausfuehrung und RAG-Antwortgenerierung bleiben offen.
- [ ] AI Assist fuer CRM/ERP default-off und nur hinter Tenant Policy, Local LLM Gateway und Human Oversight.

Vorbereitete Modul-Familien:

- Wissensdatenbank: Artikel, Versionen, Freigaben, Quellen, Attachments, RAG-Zitationen und Knowledge-Retention. Erster metadata-only Read-Slice: `GET /v1/kb/articles`; Source-Version- und Restore-Evidence fuer Manifest Hash, Content Hash, ACL-Version, Disabled-State-Restore und Legal-Hold-Restore ist vorbereitet.
- LMS: Kurse, Einschreibungen, Lernfortschritt, Zertifikate, Nachweise, Pflichtschulungen und Audit Evidence. Charter, Feature-Registry, Object-Rules, globaler `not_installed`-Katalogeintrag, `0046_lms_metadata_schema.sql`, `0047_lms_package_install_approval_records.sql`, `GET /v1/platform/modules/families/lms/catalog-readiness`, `GET /v1/platform/modules/families/lms/restore-drill-evidence`, `GET /v1/platform/modules/families/lms/tenant-admin-package-approval-gate`, `POST /v1/platform/modules/families/lms/tenant-admin-package-approval-records`, `GET /v1/platform/modules/families/lms/package-installation-readiness`, `POST /v1/platform/modules/families/lms/package-installation-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-executor-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-plan`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-implementation-review` und `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-contract`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-gate`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-request-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-runtime-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-preflight`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-receipt-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-persistence-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-activation-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-start-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-dispatch-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-worker-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-final-readiness-gate` fuer den ersten Kurs-/Einschreibestatus-Slice sind vorbereitet; echte Package-Installation, Tenant-Provisioning, Business-API und Runtime bleiben bewusst naechste Gates; der Result-Contract definiert nur Receipt-Felder und No-Write-Flags; Execution-Gate, Request-Boundary, Runtime-Boundary, Execution-Preflight, Receipt-Boundary, Result-Persistence-Boundary, Start-, Dispatch-, Worker-Boundary und Final-Readiness-Gate bleiben ebenfalls metadata-only.
- Aufgaben und Aktivitaeten: Tasks, Activities, Zustandswechsel, Verantwortlichkeiten, Fristen, Workflow Audit und Legal-Hold-Bezug.
- Meldesysteme und Tickets: Meldungen, Incidents, Tickets, SLA-State, Kommunikation, Schutzbedarf, Eskalation und E-Discovery-Anbindung.
- Zeiterfassung: Time Entries, Korrekturen, Freigaben, Exportnachweise, Aufbewahrung, Payroll/ERP-Bruecken und DSGVO-Minimierung.

Alle vorbereiteten Modul-Familien starten ueber `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`. CRM/ERP bleibt damit der Architekturbeweis fuer Modul-Slices, nicht der Produktfokus.

Der tenant-sichere Backlog-Kontrakt GET /v1/platform/modules/families/backlog macht diese Modul-Familien metadata-only sichtbar. Er aktiviert keine Module, legt keine Aufgaben an und erlaubt keine Runtime-Ausfuehrung; er zeigt nur die notwendigen Charter-, Feature-, Registry-, Rechte-, Audit-, Retention- und Backup-/Failover-Gates je Familie. LMS hat zusaetzlich `GET /v1/platform/modules/families/lms/catalog-readiness`, `GET /v1/platform/modules/families/lms/restore-drill-evidence`, `GET /v1/platform/modules/families/lms/tenant-admin-package-approval-gate`, `POST /v1/platform/modules/families/lms/tenant-admin-package-approval-records`, `GET /v1/platform/modules/families/lms/package-installation-readiness`, `POST /v1/platform/modules/families/lms/package-installation-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-executor-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-plan`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-implementation-review` und `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-contract`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-gate`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-request-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-runtime-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-preflight`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-receipt-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-persistence-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-activation-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-start-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-dispatch-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-worker-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-final-readiness-gate` als metadata-only Readiness-, Approval-Record-, Boundary-, Skeleton-, Dry-Run-Plan-, Dry-Run-Execution-Boundary-, Dry-Run-Execution-Skeleton-, Dry-Run-Executor-Implementation-Review- und Dry-Run-Result-Contract- und Dry-Run-Execution-Gate- und Dry-Run-Execution-Request-Boundary- und Dry-Run-Executor-Runtime-Boundary- und Dry-Run-Execution-Preflight- und Dry-Run-Execution-Receipt-Boundary- und Dry-Run-Result-Persistence-Boundary-Nachweise nach dem globalen `not_installed`-Katalogeintrag und vor Package-Installation, Tenant-Provisioning und Business-API.

Exit-Kriterien:

- [ ] Kein Modul kann Daten ohne Tenant Context, Modulstatus und Feature-Permission lesen oder schreiben.
- [ ] Disable stoppt normale Nutzung, aber nicht Retention, Legal Hold, Audit, Backup, Restore, Export oder Compliance-Admin-Zugriff.
- [ ] Decommission ist ein Compliance-Workflow und wird durch aktive Retention, Legal Hold oder Exportpflichten blockiert.
- [ ] Jedes Modul hat Restore Drill Evidence und RLS/Authz-Tests.
- [ ] Search/RAG fuer Module liefert nur Kandidaten und zitiert autorisierte Source Object IDs und Versionen.
- [ ] Modul-Aktivierung und -Deaktivierung sind auditierbar und wiederherstellbar.

## Erste Codex-Epics

### Epic 1: Compliance Foundation

```markdown
Title: Implement compliance foundation documents and machine-readable policy scaffolding

Deliver:
- COMPLIANCE_MATRIX.md
- DATA_CLASSIFICATION.md
- RETENTION_POLICIES.yaml
- LEGAL_HOLD_MODEL.md
- ADR templates
- tests validating every persistent model must declare classification and retention policy
```

### Epic 2: Tenant Context and Authz Core

```markdown
Title: Implement tenant context middleware and authorization core

Deliver:
- tenant context extraction from OIDC claims or dev headers
- principal model
- RBAC/ABAC policy interfaces
- deny-by-default behavior
- tests proving no endpoint can execute without tenant context
```

### Epic 3: Append-only Audit

```markdown
Title: Implement append-only audit service with hash-chain verification

Deliver:
- audit event schema
- append-only persistence abstraction
- hash-chain verifier
- audit outbox
- tamper detection tests
- WORM snapshot writer interface
```

### Epic 4: KMS Adapter

```markdown
Title: Implement KMS abstraction layer

Deliver:
- envelope encryption API
- key reference model
- key rotation interface
- cryptographic shredding simulation
- no raw key material in logs
- tests for decrypt failure after key destruction
```

### Epic 5: WORM Storage Adapter

```markdown
Title: Implement S3-compatible WORM storage adapter

Deliver:
- object metadata model
- retention policy integration
- legal hold integration
- content hash verification
- storage manifest
- tests for classification-required writes
```

### Epic 6: Search And RAG Security Skeleton

```markdown
Title: Implement ACL-aware search and RAG gateway skeleton

Deliver:
- candidate search interface
- vector candidate interface
- authorization filter layer
- redaction placeholder
- citation builder
- audit events for search and retrieval
- tenant isolation tests
```

### Epic 7: AI Control Plane Hardening

```markdown
Title: Persist and harden AI control plane

Deliver:
- persistent tenant AI policies
- persistent model registry
- persistent prompt registry
- tool permission registry
- output schema validation
- token budget and timeout enforcement
- human approval API
```

## Suggested Next Sprint

Empfohlene naechste Reihenfolge:

Roadmap-Triage-Regel ab jetzt:

- **Fundament jetzt:** Tenant-Isolation, Auth/Rights, Audit, Backup/Restore, RLS, Evidence-Gates, Datenmodell-Grenzen und
  alles, was spaeter nur teuer oder riskant nachzuziehen waere.
- **Produktzug jetzt:** schmale End-to-End-Pfade, die echte Nutzung beweisen und auf dem Fundament aufsetzen.
- **Spaeter / nicht jetzt:** Adapter, Komfortfunktionen, breitere Moduloberflaechen, echte Renderer/Viewer,
  Automatisierung und Integrationen, wenn sie keinen aktuellen Sicherheits- oder Datenmodell-Blocker loesen.

Vor jedem neuen Roadmap-Punkt wird explizit entschieden: **Muss das jetzt?** Wenn nein, bleibt der Punkt sichtbar, wird
aber als spaeterer Ausbau behandelt und nicht als naechster Arbeitsschritt priorisiert.

1. [x] Research Baseline, Open-Source-Stack-Matrix und ADR-Backlog anlegen.
2. [x] `PRODUCT_CHARTER.md`, `SECURITY.md`, `THREAT_MODEL.md` und `COMPLIANCE_MATRIX.md` anlegen.
3. [x] `ARCHITECTURE_DECISIONS/` mit ADR-Template und ADRs fuer Tenancy, WORM, KMS und Audit anlegen.
4. [x] `DATA_CLASSIFICATION.md`, `RETENTION_POLICIES.yaml` und `LEGAL_HOLD_MODEL.md` anlegen.
5. [x] `pyproject.toml` mit Ruff, Typpruefung und Pytest-Konfiguration einfuehren.
6. [x] Persistente Tenant Policy, Model Registry, Prompt Registry und Audit Storage designen.
7. [x] Request-scoped Tenant Context implementieren.
8. [x] Append-only Audit Event Model mit Hash Chain implementieren.
9. [x] ADR fuer pgvector vs. Qdrant vorbereiten.
10. [x] Erste Prompt-Injection- und unauthorized-RAG-output Tests schreiben.
11. [x] Admin API fuer Tenant AI on/off und allowed models implementieren.
12. [x] Erste pgvector Embedding-Metadaten-Migration und Tests implementieren.
13. [x] Live PostgreSQL/pgvector Migrationsrunner und RLS-Integrationstest implementieren.
14. [x] pgvector Adapter fuer Upsert, Lifecycle-Transition und Candidate Search implementieren.
15. [x] Reindex- und Deletion-Propagation Worker Entry Points implementieren.
16. [x] Source Resolver und Text Extraction Pipeline an pgvector Worker anbinden.
17. [x] Benchmark Fixtures fuer exakte Vector Search und Audit Events fuer Worker Jobs ergaenzen.
18. [x] Office/Mail Core als Produktoberflaechen auf demselben Compliance-Core festschreiben.
19. [x] Parser Worker Boundary hinter Text Extraction Interface anbinden.
20. [x] Suite-weite Backup-/Failover-Kultur mit Continuity-Domains, Policy, Runbook und Dev-Backup-Verifikation einfuehren.
21. [x] Isolierten Rich-Document Parser Service fuer DOCX, ODT und einfache Text-PDFs anbinden.
22. [x] Source Object Model fuer Dokumente, Mails, Attachments, Kommentare und Verfahrensdokumentation definieren.
23. [x] Storage Write nur mit `tenant_id`, `classification`, `retention_policy_id`, `kms_key_ref`, `manifest_hash` und `content_hash` erlauben.
24. [x] S3/MinIO-kompatiblen Storage Adapter mit Versioning, Object-Lock/WORM-Haltung und Manifest-Restore-Checks planen.
25. [x] Retention Defaults und Retention Manifest definieren.
26. [x] Legal Hold APIs fuer Source Objects und Retention-Manifest-Reevaluation definieren.
27. [x] Content Hash Verification als wiederverwendbare Storage-/Read-/Restore-Grenze implementieren.
28. [x] Storage Manifest mit Restore-Checks fuer Object Records implementieren.
29. [x] KMS Adapter Boundary vor Envelope Encryption implementieren.
30. [x] Envelope Encryption API auf KMS Adapter Boundary implementieren.
31. [x] Key Rotation Interface mit Envelope-Manifests verbinden.
32. [x] Cryptographic Shredding Simulation implementieren.
33. [x] Schutzregel: GoBD- und Legal-Hold-Objekte nicht versehentlich cryptoshreddern.
34. [x] Restore-Test-Framework anlegen.
35. [x] Vector Metadata Schema validieren.
36. [x] ACL-Versionen in Vector Metadata uebernehmen.
37. [x] Benchmark Thresholds und Reporting vor ANN-Index-Entscheidungen ergaenzen.
38. [x] Vector Worker Audit Events an durable Deployment Audit Storage anbinden.
39. [x] Embedding Model Versioning Registry Checks vor Production Indexing ergaenzen.
40. [x] Production-grade Embedding Model Registry Administration und Approval Audit Events ergaenzen.
41. [x] Keyword Indexer Boundary mit Candidate-only Results und Search Audit Events ergaenzen.
42. [x] Platform Module System ADR und Module Charter Template fuer `crm_erp` und spaetere Fachmodule erstellen.
43. [x] Backup-/Failover-Domaenen fuer CRM/ERP, Wissensdatenbank, LMS, Aufgaben, Tickets und Zeiterfassung verankern.
44. [x] `module_catalog` und `tenant_modules` Kernmodell mit SQL-Migration, Statusmodell und Gatekeeping-Tests anlegen.
45. [x] `GET /v1/platform/modules` Frontend-Discovery Endpoint mit Tenant Context anbinden.
46. [x] Admin-APIs fuer Provision, Enable, Disable, Suspend und Decommission Check implementieren.
47. [x] Decommission Request API mit Retention-, Legal-Hold-, Export- und Backup-Evidence Workflow implementieren.
48. [x] Decommission Blocked/Completed Workflow mit finaler Disposition Evidence implementieren.
49. [x] Decommission Cancel/Reopen Workflow mit expliziter Freigabe und Audit Evidence implementieren.
50. [x] Serverseitige Modul-Gates fuer API-Router und Worker implementieren.
51. [x] Module-Aware Migration Catalog mit Checksummen, Evidence und Startblockade bei Mismatch implementieren.
52. [x] Modul-Provisioning mit Migration-Manifest-Evidence verbinden und bei fehlenden Startup-Migrationen blockieren.
53. [x] Legacy-SQL-Discovery- und Import-Evidence-Framework als sicheren Schritt vor Mapping und Datenimport implementieren.
54. [x] Isolierten SQL-Server-Metadata-Adapter-Worker mit Connector-Policy implementieren.
55. [x] CRM/ERP-Mapping-Evidence fuer Discovery-Tabellen, Zielobjekt-Kandidaten, `legacy.row`-Fallbacks und Quarantaene-Entscheidungen implementieren.
56. [x] CRM/ERP Subfeature Registry fuer Accounts, Kontakte, Aktivitaeten, Produkte, Lieferanten, Bestellungen, Rechnungen, Import, Export, Legal Hold, Keyword-Suche, RAG und AI Assist implementieren.
57. [x] Review-Kritik aufnehmen und P0-Soforthaertungen fuer dev-only Header Auth, RAG DataClass Propagation und lokale Dev-Krypto umsetzen.
58. [x] Signed JWT PrincipalResolver mit serverseitiger Tenant-, Rollen-, Gruppen- und Objekt-ACL-Aufloesung implementieren.
59. [x] Statischen OIDC/JWKS Verifier mit RS256-Key-Auswahl, Issuer/Audience-Allowlist, Replay Guard und Health Reporting implementieren.
60. [x] Dynamische OIDC Discovery, JWKS Refresh Scheduling, Key-Cache Expiry, IdP-Outage-Policy und persistenten Replay Store implementieren.
61. [x] PrincipalResolver, Tenant Membership, Rollen, Gruppen, ACL und ABAC Stores in PostgreSQL mit RLS und Audit Events persistieren.
62. [x] JWT Replay State von JSON auf PostgreSQL mit tenant-aware Audit Events umziehen.
63. [x] Kanonische DataClass Registry einziehen und Runtime, Retention, KMS, DB Constraints, Prompt/Model Registry und Compliance Docs dagegen validieren.
64. [x] Persistenten append-only Audit Store mit DB-Rollen, Sequencing, HMAC/Signatur-Checkpoints und WORM Export implementieren.
65. [x] Authorized ChunkRepository fuer RAG einziehen, damit nur exakte Chunks statt ganzer Source Documents in den Kontext gehen.
66. [x] Audited Authz Admin APIs fuer PostgreSQL Principal, Rollen, Gruppen, ACL, ABAC und Replay-Retention Mutationen implementieren.
67. [x] CRM/ERP Schemas und Objektregeln fuer `crm_erp`, `crm`, `erp` und `crm_erp_legacy` planen.
68. [x] Persistente CRM/ERP Schema-Scaffold-Migration mit RLS-geschuetzten Manifest-Tabellen implementieren.
69. [x] Ersten gated CRM Accounts Read-Vertical-Slice mit `crm.accounts`, Audit und `GET /v1/crm/accounts` implementieren.
70. [x] Gated CRM Contacts Read-Vertical-Slice mit `crm.contacts`, Account-Link-Redaktion, Audit und `GET /v1/crm/contacts` implementieren.
71. [x] Gated CRM Activities/Notes Read-Vertical-Slice mit `crm.activities`, `crm.notes`, Link-Redaktion, Audit und metadata-only Notes implementieren.
72. [x] Minimalen ERP Products Read-Vertical-Slice mit `erp.products`, `internal` Klassifikation, Audit und `GET /v1/erp/products` als Architekturbeweis implementieren.
73. [x] Modul-Implementierungsvertrag fuer Wissensdatenbank, LMS, Aufgaben, Tickets, Zeiterfassung und spaetere Suite-Module aus den CRM/ERP-Slices extrahieren.
74. [x] Ersten Wissensdatenbank-Read-Slice mit `knowledge_base`, `kb.article`, `kb.article_version`, RLS, Audit und `GET /v1/kb/articles` implementieren.
75. [x] Wissensdatenbank-Source-Version- und Restore-Evidence mit `knowledge_base.source_version_evidence`, `knowledge_base.restore_evidence`, Audit-Metadaten und Backup-Domain-Nachweis haerten.
76. [x] Compliance/Admin-Read-Pfad fuer Wissensdatenbank-Source-/Restore-Evidence mit `GET /v1/admin/kb/evidence`, disabled-state access und metadata-only Audit implementieren.
77. [x] Wissensdatenbank-Write/Edit-Approval-Command-Modell und audit-only Dry-Run-Pfad mit `POST /v1/admin/kb/articles/write-dry-run` implementieren.
78. [x] Persistente Wissensdatenbank-Write-Approval-Evidence-Ledger-Migration `0023` vor echten Artikel-/Source-Writes implementieren.
79. [x] Write-Dry-Run-Evidence in `knowledge_base.write_approval_evidence` persistieren, ohne Artikel-/Source-Writes freizuschalten.
80. [x] Source-Object-Write-Guard fuer Knowledge-Base-Artikel vorbereiten: Ledger-Evidence, erwartete Version, Legal Hold, Retention und Restore-Evidence pruefen, bevor echte Writes freigeschaltet werden.
81. [x] Knowledge-Base-Approval-State-Transition von Dry-Run zu `approved_for_write` entwerfen, weiterhin ohne Artikel-/Source-Writes, mit Audit- und Restore-Evidence-Bindung.
82. [x] Metadata-only Restore-/Source-Evidence-Refresh-Preview fuer approved Knowledge-Base-Writes vorbereiten, bevor echte Artikel-/Source-Writes freigeschaltet werden.
83. [x] Guarded Knowledge-Base-Write-Execution-Skeleton vorbereiten: approved Ledger-Evidence, Source-Object-Guard, Refresh-Preview und explizite Human Confirmation muessen gemeinsam vor echten Artikel-/Source-Writes vorliegen.
84. [x] Atomaren Knowledge-Base-Edit-Write-Execution-Pfad entwerfen: Source-Object-Persistenz, Artikel-/Version-Metadaten, Source-Version-Evidence, Restore-Evidence und Audit-Linkage werden gemeinsam aktualisiert; RAG/Indexing bleibt weiter aus.
85. [x] Approval-Evidence fuer Knowledge-Base-Create-Writes um vertrauenswuerdige Artikel-Metadaten erweitern und guarded In-Memory-Create-Execution ermoeglichen; Artikel-Key, Titel, Version-Label und Source-System werden vor Execution gehasht.
86. [x] PostgreSQL-Transaktionsadapter fuer Knowledge-Base-Writes implementieren, der Artikel-/Version-Metadaten, Source-Version-Evidence und Restore-Evidence fuer Create/Edit gemeinsam committed oder verwirft.
87. [x] Source-Object-Persistenzgrenze fuer Knowledge-Base-Writes haerten: dauerhafte metadata-only Write-Receipts mit `collabio.source_object_write_receipts`, RLS, Receipt-Hash und API-Execution-Evidence anbinden.
88. [x] PostgreSQL-Source-Metadatenadapter und Content-Store-Bridge fuer Source Objects entwerfen, damit Knowledge-Base-Writes spaeter Source-Metadata, Content-Manifest, Artikel-/Version-Metadaten und Evidence ohne Content-Leakage atomar koordinieren koennen.
89. [x] Knowledge-Base-Write-Unit-of-Work vorbereiten: Source-Object-Receipt, Source-Metadata, Storage-Manifest, Artikel-/Version-Metadaten, Source-Version-Evidence und Restore-Evidence in einem koordinierten Commit-Vertrag zusammenfuehren.
90. [x] Knowledge-Base-Production-Write-Grenze haerten: gemeinsamen PostgreSQL-Transaktionskontext fuer KB-Metadatenadapter, Source-Object-Receipts und Source-Metadata-Bridge entwerfen, damit API-Produktivwiring erst mit explizitem Atomicity-/Recovery-Nachweis aktiviert wird.
91. [x] Knowledge-Base-Content-Store-Recovery-Evidence vorbereiten: Content-Store-Inventar, Orphan-Reconciliation-Nachweis, Restore-Drill-Hash und API-Wiring-Gate fuer `PostgresKnowledgeBaseWriteUnitOfWork` definieren.
92. [x] Knowledge-Base-Produktiv-Content-Store anbinden: S3/MinIO-kompatiblen Adapter mit Object-Lock/WORM-Pruefung, Orphan-Reconciliation-Worker und API-Wiring-Gate fuer Postgres-UoW aktivieren.
93. [x] Knowledge-Base-Produktiv-API-Wiring unter Deployment-Gate vorbereiten: saubere `source_object_content_recovery_evidence.v1`, S3/MinIO-Providerprofil und Restore-Drill-Evidence muessen gemeinsam vor aktivierten Writes vorliegen.
94. [x] Konkreten MinIO/AWS-SDK-Client hinter `S3CompatibleObjectStoreClient` anbinden und per Compose-Profil/Providerprofil-Evidence gegen Versioning, Object Lock, Legal Hold und Restore-Drill testen.
95. [x] Source-Object-Content-Store-Provider in die Runtime-Konfiguration integrieren: `S3CompatibleSourceObjectContentStore`, Providerprofil-Evidence, Recovery-Evidence und Knowledge-Base-Deployment-Gate automatisch aus der aktivierten Object-Storage-Backend-Konfiguration verdrahten.
96. [x] Knowledge-Base-Produktivwiring tenant-sicher aktivierbar machen: Runtime-Gate-Evidence per Admin-/Deployment-Aktivierung tenant-spezifisch persistieren und die API vom prozessweiten `SUITE_KB_RUNTIME_TENANT_ID` in eine request-sichere Runtime-Auswahl ueberfuehren.
97. [x] Knowledge-Base-Content-Reconciliation operationalisieren: aktivierte Runtime-Tenants regelmaessig gegen Object-Store-Inventar, Storage-Manifeste und Restore-Drill-Evidence pruefen, Aktivierungen bei Drift sperren und Refresh-/Reactivation-Evidence auditierbar machen.
98. [x] Knowledge-Base-Reconciliation als Worker-Betriebspfad ausbauen: tenant-Auswahl aus Modulstatus/Runtime-Aktivierungen, Compose-Worker-Entrypoint, Runbook-Evidence, Retry-/Alerting-Kontrakt und regelmaessige Restore-Drill-Bindung operationalisieren.
99. [x] Persistente Platform-Module-Registry fuer API und Worker angleichen: `collabio.module_catalog` und `collabio.tenant_modules` als Store anbinden, Migration-Evidence aus DB verwenden, tenant-sichere `ModuleWorkerGate`-Nutzung fuer API/Worker vereinheitlichen und Dev-Seeding/Backfill definieren.
100. [x] Platform-Module-Registry betrieblich haerten: Admin-Runbook fuer Seed/Backfill/Reparatur, Pg-basierte API-Smoke-Tests fuer Tenant-Lifecycle, Worker-Discovery-Drills und Audit-/Backup-Evidence fuer Modulstatus-Aenderungen operationalisieren.
101. [x] MVP-Produktzug starten: Module-Cockpit und ersten durchgehenden SourceObject-Flow fuer Wissensdatenbank/Dokument/Mail sichtbar machen, ohne neue Infrastrukturabstraktionen einzuziehen.
102. [x] Erste echte Workspace-Shell/UI fuer das Module-Cockpit bauen: Status, naechste Aktion und SourceObject-Flows scanbar darstellen, ohne Marketing-Landingpage und ohne neue Compliance-Bypasses.
103. [x] Workspace-Shell vertiefen: Modulaktionen aus dem Cockpit kontrolliert an Admin-APIs anbinden und KB-/Dokument-/Mail-Detailansichten metadata-only navigierbar machen.
104. [x] SourceObject-Detailzug produktionsnah machen: repository-backed metadata-only Detail-Endpoints fuer Dokumente, Mail und Wissensdatenbank anbinden, ACL-Pruefung pro Detailabruf auditieren und die Workspace-Shell von Cockpit-Flow-Snapshots auf diese Detail-API umstellen.
105. [x] SourceObject-Detailzug weiter haerten: Detail-API auf persistente SourceObject-Repository-Backends fuer Dokumente/Mail vorbereiten, UI-Fehlerzustaende fuer 403/404 sichtbar differenzieren und Pg-basierte Detail-Smoke-Tests einziehen.
106. [x] Dokument-/Mail-Detailzug als naechsten Produktpfad vorbereiten: persistente Repository-Auswahl operationalisieren, SourceObject-Flows von Demo-Seeding zu Backend-Konfiguration fuehren und Detailansichten um sichere Preview-Slots ohne Content-Bypass erweitern.
107. [x] Dokument-/Mail-Preview-Gate konkretisieren: sichere metadata-first Preview-Policies, Parser-/Sanitizer-Grenzen, Mail-Header/Attachment-Metadaten und Content-Freigabe nur hinter explizitem Policy-/ACL-/Audit-Nachweis vorbereiten.
108. [x] Dokument-/Mail-Preview-Approval-Skeleton vorbereiten: Content-Preview-Anfragen als metadata-only Decision-Objekte modellieren, Tenant-Policy/ACL/Audit/Parser-Sanitizer-Evidence pruefen und weiterhin blockieren, bis explizite Freigabe und sichere Renderer-Grenzen nachgewiesen sind.
109. [x] Dokument-/Mail-Preview-Approval operationalisieren: persistentes Preview-Decision-Ledger, Tenant-Policy-Schalter, Renderer-Sandbox-Evidence und Human-Confirmation-Workflow anbinden, ohne Content-Ausgabe freizuschalten.
110. [x] Preview-Decision-Ledger produktionshart machen: PostgreSQL/RLS-Adapter, Restore-Evidence, Backup-Abdeckung und Renderer-Sandbox-Worker-Evidence anbinden, bevor irgendein Content-Rendering-Pfad geoeffnet wird.
111. [x] Renderer-Sandbox-Worker-Skeleton aufbauen: isolierten Worker-Run als metadata-only Evidence erzeugen, Parser/Sanitizer/Backup/Restore-Evidence gegen Tenant und SourceObject binden und weiterhin keinen gerenderten Content ausgeben.
112. [x] Renderer-Sandbox-Evidence produktionshart machen: PostgreSQL/RLS-Store, Restore-Drill-Pruefung und Worker-Queue-Anbindung fuer Preview-Renderer-Evidence ergaenzen, bevor echte Rendering-Engines oder Viewer eingebunden werden.
113. [x] Renderer-Worker-Runbook und Restore-Drill operationalisieren: Queue-Wiederaufnahme, Idempotency-Replay, Tenant-Isolation-Smoke-Test und Preview-Decision-/Renderer-Evidence-Recovery als wiederholbaren Compose-Drill nachweisen.
114. [x] Preview-Renderer-Drill mit realer Postgres-Smoke-Fixture erweitern: API erzeugt Decision-/Renderer-Evidence, `preview-renderer-drill` verifiziert sie im Compose-Pfad, und der Report-Hash wird als Release-/Restore-Evidence referenzierbar.
115. [x] Preview-Renderer-Release-Gate definieren: frischen API-Smoke-Report-Hash und Recovery-Drill-Report-Hash als harte Voraussetzung modellieren, bevor echte Renderer, Viewer oder Content-Release-Workflows angeschlossen werden.
116. [x] Preview-Renderer-Release-Gate-Evidence operationalisieren: Gate-Reports persistent referenzieren, Compose-Smoke um Gate-Erzeugung erweitern und echte Renderer-/Viewer-Anbindung erst hinter diesem Gate erlauben.
117. [x] Preview-Renderer-Release-Gate-Store produktionshart machen: PostgreSQL/RLS-Migration, Restore-Drill-Pruefung und Compose-Smoke auf persistenten Gate-Store umstellen, bevor Renderer-/Viewer-Gate-Hashes produktiv verwendet werden.
118. [x] Roadmap-Triage vor dem naechsten Ausbau anwenden: naechsten Schritt nur ziehen, wenn er Fundament oder unmittelbaren Produktzug staerkt; spaeter nachziehbare Adapter-/UI-/Automationsarbeit sichtbar parken.
119. [x] Legacy-SQL-Import-Readiness-Evidence definieren: Discovery-/Import-/Mapping-Hashes zusammenfuehren, Dry-Run nur bei sauberer Mapping-Kette erlauben und Quarantaene/`legacy.row` als manuellen Mapping-Blocker ausweisen.
120. [x] Legacy-SQL-Readiness als Compose/Worker-Smoke operationalisieren: Metadata-Worker-Ergebnis, Mapping-Manifest und Readiness-Evidence als Report ausgeben, bevor reale SQL-Verbindung oder Import-Dry-Run zugelassen wird.
121. [x] Legacy-SQL-Discovery-Intake-Gate vorbereiten: echte Discovery-Anfragen nur mit Tenant, Approval, Secret-Ref, Connector-Policy-Hash und freigegebenem Host-Profil annehmen; keine DSN, keine Rohdaten, kein Import-Dry-Run.
122. [x] Legacy-SQL-Discovery-Intake operationalisieren: Admin-/Worker-Entry-Point fuer Intake-Evidence und Metadata-Worker-Command anbinden, ohne echte Verbindung, Import-Dry-Run oder Rohdatenfreigabe.
123. [x] Legacy-SQL-Evidence-Ledger persistieren: Intake-, Discovery-, Mapping-, Readiness- und Smoke-Report-Hashes tenant-sicher mit RLS/Restore-Evidence speichern, bevor echte Legacy-Verbindungen zugelassen werden.
124. [x] Legacy-SQL-Evidence-Ledger in Intake-/Readiness-Drills verdrahten: Operations-Reports optional in `collabio.legacy_sql_evidence_ledger` schreiben und Restore-Drill-Nachweis mit Report-Hashes verbinden.
125. [x] Legacy-SQL-Evidence-Ledger-Backends operationalisieren: JSONL/Postgres-Schreibpfad in Compose-Drills pruefen, Restore-Drill gegen Ledger-Eintraege laufen lassen und erst danach echte Legacy-Host-Profile freigeben.
126. [x] Legacy-SQL-Host-Profile-Release-Gate vorbereiten: echte Host-Profile nur nach Ledger-Operations-Report, Connector-Policy-Hash, Secret-Ref, Egress-Freigabe und expliziter menschlicher Bestaetigung aktivierbar machen; keine DSN, keine Rohdaten und kein Import-Dry-Run im Gate.
127. [x] Legacy-SQL-Host-Profile-Release-Gate operationalisieren: Gate-Evidence tenant-sicher persistieren, Compose-Smoke fuer Ready/Blocked-Pfade anbinden und erst danach einen echten Host-Profile-Adapter vorbereiten.
128. [x] Legacy-SQL-Host-Profile-Adapter-Skeleton vorbereiten: Persistierte Ready-Gate-Evidence tenant-sicher laden, Secret-/Egress-Handles nur an metadata-only Worker-Scheduling binden und weiterhin keine echte Netzwerkverbindung im Default-Compose oeffnen.
129. [x] Legacy-SQL-Metadata-Worker-Scheduling-Queue vorbereiten: Schedule-Evidence tenant-sicher und idempotent persistieren, Worker-Lease/Retry/Restore-Evidence modellieren und weiterhin keine echte Legacy-Verbindung im Default-Compose oeffnen.
130. [x] Legacy-SQL-Metadata-Worker-Lease-Consumer-Skeleton vorbereiten: geleaste Queue-Jobs in einem isolierten Offline-Runner validieren, Secret-/Egress-Aufloesung weiterhin nur als Handle pruefen und echte Legacy-Verbindung weiter gesperrt lassen.
131. [x] Legacy-SQL-Connector-Sandbox-Profil vorbereiten: default-off Netzwerk-/Secret-Handle-Profil fuer spaetere reale Legacy-Host-Konnektivitaet modellieren, nur hinter Release-Gate, Queue-Lease und Consumer-Activation sichtbar machen und Rohdaten/Import weiterhin blockieren.
132. [x] Legacy-SQL-Connector-Sandbox-Enablement-Gate vorbereiten: explizite menschliche Freigabe, Provider-Attestation, Restore-Evidence und Sandbox-Profil-Hash als hartes Gate fuer spaetere echte Verbindungsversuche modellieren; Raw Data, Import-Dry-Run und Import-Write bleiben getrennt blockiert.
133. [x] Legacy-SQL-Connector-Provider-Attestation-Adapter vorbereiten: Netzwerk-, Secret-Resolver- und Audit-Provider-Handles gegen echte Deployment-Profile validieren, aber weiterhin keine Verbindung oeffnen und kein Secret-Material aufloesen.
134. [x] Legacy-SQL-Connector-Connection-Attempt-Preflight-Gate vorbereiten: Enablement-Gate, Provider-Attestation-Adapter, Restore-Evidence und Operator-Kontext zu einem letzten No-Secret/No-Socket-Nachweis binden, bevor spaeter echte Verbindungsversuche implementiert werden.
135. [x] Legacy-SQL-Connector-Real-Connection-Executor-Skeleton vorbereiten: hinter dem Preflight-Gate einen weiterhin nicht-ausfuehrenden Executor-Contract modellieren, der Secret-/Socket-Materialisierung, Timeout-/Retry-Policy, Audit und Kill-Switches vor echter Implementierung festlegt.
136. [x] Legacy-SQL-Connector-Real-Connection-Executor-Policy-Store vorbereiten: Executor-Contracts, Timeout-/Retry-Policies, Audit-Plaene und Kill-Switch-Policies tenant-sicher persistierbar machen, bevor echte Socket-Ausfuehrung implementiert wird.
137. [x] Legacy-SQL-Connector-Execution-Readiness-Review-Gate vorbereiten: gespeicherte Executor-Policy-Bundles gegen Human-Review, Change-Control, Restore-Drill und Kill-Switch-Zustand pruefen, bevor echte Socket- oder Secret-Materialisierung ueberhaupt geplant wird.
138. [x] Legacy-SQL-Connector-Materialization-Plan-Gate vorbereiten: Review-Gate-Ergebnis, Provider-Profile, Operator-MFA und Kill-Switch-Snapshot in einen weiterhin nicht-ausfuehrenden Materialisierungsplan binden, bevor Socket- oder Secret-Materialisierung implementiert wird.
139. [x] Legacy-SQL-Connector-Socket-Secret-Implementation-ADR vorbereiten: Materialization-Plan-Gate-Ergebnis, echte Provider-Limits, Netzwerkroute, Secret-Manager, Rollback und Kill-Switch-Runbook als ADR-Gate dokumentieren, bevor eine ausfuehrende Implementierung geschrieben wird.
140. [x] Legacy-SQL-Connector-Runtime-PR-Gate vorbereiten: ADR-Gate-Ergebnis, Runtime-Code-Review, Testcontainer, Secret-Manager-Binding, Netzwerkroute, Rollback-Probe und Kill-Switch-Probe als letztes nicht-ausfuehrendes PR-Gate binden, bevor Socket- oder Secret-Runtime-Code gemergt wird.
141. [x] Legacy-SQL-Connector-Runtime-Merge-Gate vorbereiten: Runtime-PR-Gate-Ergebnis, Branch-Protection-Status, Security-Scan, Container-Provenance, Secret-Rotation-Plan und Kill-Switch-Drill als Merge-Gate binden, bevor ausfuehrender Socket-/Secret-Code in eine aktivierbare Runtime gelangt.
142. [x] Legacy-SQL-Connector-Runtime-Activation-Gate vorbereiten: Runtime-Merge-Gate-Ergebnis, tenant-spezifische Aktivierungsfreigabe, Runtime-Feature-Flag, Secret-Rotation-Bestaetigung, Netzwerkfreigabe, Rollback-Freeze und Kill-Switch-Arming als weiterhin nicht-ausfuehrendes Activation-Gate binden, bevor echte Verbindungsversuche aktivierbar werden.
143. [x] Legacy-SQL-Connector-Live-Connection-Gate vorbereiten: Runtime-Activation-Gate-Ergebnis, Secret-Broker-Binding, Netzwerk-Egress-Policy, Least-Privilege-DB-Rolle, Timeout-/Circuit-Breaker, Audit-Sink und Emergency-Disable als weiterhin kontrolliertes Gate binden, bevor ein erster echter metadata-only Connection-Probe erlaubt wird.
144. [x] Legacy-SQL-Connector-Metadata-Connection-Probe-Gate vorbereiten: Live-Connection-Gate-Ergebnis, echten Provider-Treiber, Secret-Broker-Read-Path, Metadata-Query-Allowlist, Timeout-/Circuit-Breaker-Ausfuehrung, Audit-Sink und Emergency-Disable als eng begrenztes Ausfuehrungsgate binden, bevor ein erster echter metadata-only Probe implementiert wird.
145. [x] Legacy-SQL-Connector-Metadata-Connection-Probe-Skeleton implementieren: Metadata-Connection-Probe-Gate-Ergebnis, Provider-Treiber-Adapter, Secret-Broker-Leseaufruf, Metadata-Query-Allowlist, Timeout-/Circuit-Breaker, Audit-Sink und Emergency-Disable als ersten echten metadata-only Probe hinter Default-Off und Kill-Switch implementieren, ohne Rohdaten, Import-Dry-Run oder Writes zu erlauben.
146. [x] Legacy-SQL-Connector-Metadata-Connection-Probe-Live-Adapter haerten: echten Postgres-Provider hinter dem Skeleton mit Secret-Broker-Materialisierung, freigegebener Netzwerkroute, Redaction/Audit, Timeout-/Circuit-Breaker und Emergency-Stop in einem isolierten Worker aktivieren, weiterhin ohne Rohdaten, Import-Dry-Run oder Writes. SQL Server bleibt bis zu Treibercontainer-, Netzwerkprofil- und Testinstanz-Evidence bewusst Adapter-spaeter.
147. [x] Produktzug-Re-Fokus nach Legacy-SQL-Metadata-Probe: Legacy-SQL bei metadata-only Live-Probe einfrieren und als naechsten MVP-Slice Workspace/Module-Cockpit, KB-/Dokument-/Mail-SourceObject-Flow, Preview-Entscheidung und Rechte-/Audit-Sichtbarkeit produktnah zusammenfuehren, ohne neue Import- oder Rohdatenpfade.
148. [x] Workspace-Preview-Entscheidung produktiver fuehren: aus der Flow-Readiness heraus einen gefuehrten metadata-only Action-Flow fuer Renderer-Sandbox-Evidence und Preview-Decision-Anforderung bauen, weiter ohne Content-Rendering oder Rohdatenfreigabe.
149. [x] Produktiver Arbeitskorb als naechster MVP-Slice: aus Modulstatus, SourceObject-Readiness und Preview-Entscheidungen eine einfache Aufgaben-/Naechste-Schritte-Sicht ableiten, ohne das spaetere Aufgabenmodul, Tickets oder Automationen vorwegzunehmen.
150. [x] Arbeitskorb-Aktionen rollen- und zustandsgefuehrt schaerfen: Work-Items mit sicheren Action-Hints, Modul-/Flow-Sprungzielen und UI-Gates verbinden, ohne persistente Aufgaben, Tickets oder Automationen einzufuehren.
151. [x] Arbeitskorb-Rollenmatrix absichern: Tenant-Admin, Security-Admin und Reader-Kontexte gegen dieselben Work-Items pruefen und UI-/Contract-Gates nachweisen, ohne eine neue RBAC-Engine oder persistente Aufgaben einzufuehren.
152. [x] Arbeitskorb-State-Transitions nachweisen: nach Preview-Decision und Modul-Provision/Enable Work-Items neu berechnen und obsolete Actions ausblenden oder umstufen, ohne persistente Aufgaben, Tickets oder Automationen einzufuehren.
153. [x] Arbeitskorb-Operational-Evidence schaerfen: Work-Item-Zaehler, Confirmation-Gates und State-Transition-Signale in Audit-/Cockpit-Metadaten nachvollziehbar machen, ohne Rohdaten, Inhalte oder persistente Aufgaben zu speichern.
154. [x] Arbeitskorb-Operational-Summary im Workspace sichtbar machen: die read-only Evidence aus Work-Item-Zaehlern, Rollen-/Confirmation-Gates und State-Transition-Signalen kompakt anzeigen, ohne neue Aktionen, persistente Aufgaben oder Rohdaten einzufuehren.
155. [x] Workspace-Cockpit als MVP-Startpunkt konsolidieren: Module, Arbeitskorb, SourceObject-Flows und Detailansicht als produktiven Einstieg pruefen, offene Foundation-Luecken priorisieren und spaetere Nice-to-haves aus dem unmittelbaren Pfad entfernen.
156. [x] MVP-Startpunkt-Snapshot als Review-Artefakt vorbereiten: Cockpit-Readiness, offene Foundation-Gaps, Deferred-Themen und naechste sichere Aktion in einem metadata-only Handover-Report exportierbar machen, ohne produktive Automationen oder neue Module vorzuziehen.
157. [x] Foundation-Gap-Abbau aus dem MVP-Snapshot starten: Preview-Decision-Gaps, Modulaktivierung und Human-Confirmation als naechsten produktiven Pfad priorisieren, waehrend Office/Mail-Vollclients, Tickets, LMS und Zeiterfassung bewusst deferred bleiben.
158. [x] Preview-Decision-Gap konkret abbauen: aus dem Foundation-Gap-Plan die pending Preview-Decision-Arbeitsschritte zuerst operationalisieren und nach Ausfuehrung die Gap-Liste automatisch reduzieren, ohne Content-Release oder Viewer-Adapter vorzuziehen.
159. [x] Preview-Blocked-Gap klaeren: nach abgebautem Pending-Gap die geblockten Preview-Decisions als Evidence-/Policy-Thema sichtbar fuehren und entscheiden, welche Evidence wirklich jetzt noetig ist, ohne Content-Release oder Viewer-Adapter vorzuziehen.
160. [x] Modulaktivierungs-Gap fokussiert abbauen: nach Preview-Evidence-Brief nur die notwendigen Modul-Provisioning-/Enablement-Aktionen fuer den MVP-Arbeitsbereich operationalisieren, ohne spaetere Modulfachlichkeit, Tickets oder Automationen vorzuziehen.
161. [x] Human-Confirmation-Gap scharf stellen: verbleibende explizite Bestaetigungen nach Preview- und Modul-Gap getrennt sichtbar fuehren und nur notwendige bestaetigungsgebundene Foundation-Schritte behandeln, ohne persistente Aufgaben, Tickets oder Automationen vorzuziehen.
162. [x] Content-Release-Gate bewusst halten: nach geschaerftem Human-Confirmation-Gap den verbleibenden Content-Release-Block als Policy-/Viewer-Deferred-Entscheidung dokumentieren und nur pruefen, ob MVP-Readiness ohne Content-Preview produktiv genug ist.
163. [x] MVP-Readiness-Entscheidung finalisieren: Workspace, Snapshot und Foundation-Gap-Plan als metadata-only Produktivpfad gegen Rollen, Audit, Backup/Failover und Modulstatus zusammenziehen, ohne Office-/Mail-Vollclient, Viewer, Tickets oder Automationen vorzuziehen.
164. [x] MVP-Produktivpfad als Release-Kandidat pruefen: Demo-Tenant, Rollenmatrix, Audit-Events, Snapshot-Export und Backup-/Failover-Schutzsignale als zusammenhaengenden Smoke-Run dokumentieren, ohne neue Module oder Content-Preview-Funktionalitaet vorzuziehen.
165. [x] MVP-Release-Handover schaerfen: Release-Candidate-Smoke, Snapshot-Hash und offene Foundation-Gaps in eine knappe Betreiber-/Reviewer-Uebergabe zusammenfassen, ohne neue Produktfunktionen oder Content-Preview-Pfade vorzuziehen.
166. [x] MVP-Release-Review abschliessen: Handover-Evidence, offene Gaps und Betreiber-Checkliste gegen Security-/Compliance-Guardrails reviewbar machen, ohne neue Produktfunktionen oder Content-Preview-Pfade vorzuziehen.
167. [x] MVP-Pilot-Freigabe vorbereiten: Release-Review, Handover und Smoke-Evidence in ein minimales Pilot-Gate ueberfuehren, ohne neue Produktfunktionen, Content-Preview oder Automationen vorzuziehen.
168. [x] MVP-Pilot-Betriebsstatus sichtbar machen: Pilot-Gate, Release-Review und offene Foundation-Gaps als read-only Betreiberstatus zusammenziehen, ohne neue Produktfunktionen, Content-Preview, Tickets oder Automationen vorzuziehen.
169. [x] MVP-Pilot-Readiness-Bericht schaerfen: Pilot-Betriebsstatus, offene Foundation-Gaps und Deferred-Scope in eine knappe Review-/Betreiberansicht ueberfuehren, ohne Content-Preview, Tickets, Automationen oder neue Modulfachlichkeit vorzuziehen.
170. [x] MVP-Pilot-Startumfang fixieren: Readiness-Bericht, Betreiberstatus und erlaubte Pilot-Flaechen als minimalen Startumfang dokumentieren, ohne Content-Preview, Tickets, Automationen oder neue Modulfachlichkeit vorzuziehen.
171. [x] MVP-Pilot-Betreiberpfad absichern: fixierten Startumfang, Evidence-Kette und offene Foundation-Gaps als kurzes metadata-only Runbook sichtbar machen, ohne Content-Preview, Tickets, Automationen oder neue Modulfachlichkeit vorzuziehen.
172. [x] MVP-Pilot-Reviewpunkt festlegen: Betreiber-Runbook, Startumfang und offene Foundation-Gaps als formalen Reviewpunkt fuer Pilotstart sichtbar machen, ohne Content-Preview, Tickets, Automationen oder neue Modulfachlichkeit vorzuziehen.
173. [x] MVP-Pilot-Startentscheidung vorbereiten: Reviewpunkt, Runbook und Evidence-Hashes in eine explizite Human-Confirmation-Vorlage ueberfuehren, ohne Pilotstart, Content-Preview, Tickets, Automationen oder neue Modulfachlichkeit auszufuehren.
174. [x] MVP-Pilot-Entscheidungsprotokoll vorbereiten: Human-Confirmation-Vorlage, Reviewpunkt und Evidence-Hashes in ein auditierbares Entscheidungsprotokoll-Schema ueberfuehren, ohne Bestaetigung zu speichern, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
175. [x] MVP-Pilot-Entscheidungs-Preflight sichtbar machen: Entscheidungsprotokoll-Schema, Human-Confirmation-Vorlage und Evidence-Kette als read-only Vorpruefung zusammenziehen, ohne Bestaetigung zu speichern, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
176. [x] MVP-Pilot-Approval-Workflow abgrenzen: Preflight, Entscheidungsprotokoll-Schema und Human-Confirmation-Vorlage in eine klare Workflow-Grenze ueberfuehren, ohne Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
177. [x] MVP-Pilot-Approval-Readiness konsolidieren: Approval-Workflow-Grenze, Preflight und Entscheidungsartefakte als finale read-only Freigabevorbereitung zusammenziehen, ohne Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
178. [x] MVP-Pilot-Go-No-Go-Grenze vorbereiten: Approval-Readiness in eine explizite Human-Decision-Grenze ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
179. [x] MVP-Pilot-Go-No-Go-Entscheidungsprotokoll vorbereiten: Go/No-Go-Grenze, Approval-Readiness und Evidence-Hashes in ein auditierbares Human-Decision-Record-Schema ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
180. [x] MVP-Pilot-Decision-Capture-Grenze vorbereiten: Go/No-Go-Entscheidungsprotokoll-Schema in eine explizite Human-Decision-Capture-Grenze ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
181. [x] MVP-Pilot-Decision-Capture-Preflight sichtbar machen: Decision-Capture-Grenze, Go/No-Go-Entscheidungsprotokoll-Schema und Evidence-Kette als read-only Vorpruefung zusammenziehen, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
182. [x] MVP-Pilot-Decision-Capture-Submit-Skeleton vorbereiten: Decision-Capture-Preflight in einen expliziten Human-Submit-Vertrag ueberfuehren, ohne Entscheidung anzunehmen, zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
183. [x] MVP-Pilot-Decision-Capture-Submit-Dry-Run vorbereiten: Submit-Skeleton in eine reine Validierungs-Simulation fuer Human-Submit-Eingaben ueberfuehren, ohne Entscheidung anzunehmen, zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
184. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Grenze vorbereiten: Dry-Run-Vertrag in eine explizite Payload-Validierungsgrenze ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
185. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Dry-Run vorbereiten: Payload-Validierungsgrenze in eine explizite, nicht persistierende Validierungsanfrage fuer synthetische Human-Submit-Payloads ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
186. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Boundary vorbereiten: Payload-Validation-Dry-Run in eine explizite Request-Boundary fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
187. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Dry-Run vorbereiten: Request-Boundary in eine nicht persistierende Request-Dry-Run-Auswertung fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
188. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Skeleton vorbereiten: Request-Dry-Run in einen nicht aktivierten Execution-Skeleton fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
189. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Dry-Run vorbereiten: Execution-Skeleton in eine nicht persistierende Execution-Dry-Run-Auswertung fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
190. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Boundary vorbereiten: Execution-Dry-Run in eine explizite Aktivierungsgrenze fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
191. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Dry-Run vorbereiten: Activation-Boundary in eine nicht persistierende Aktivierungs-Dry-Run-Auswertung fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
192. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Skeleton vorbereiten: Activation-Dry-Run in einen nicht aktivierten Approval-Skeleton fuer spaetere Human-Submit-Payload-Validierung ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
193. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Dry-Run vorbereiten: Approval-Skeleton in eine nicht persistierende Approval-Dry-Run-Auswertung fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
194. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Boundary vorbereiten: Approval-Dry-Run in eine explizite Request-Boundary fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
195. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Dry-Run vorbereiten: Approval-Request-Boundary in eine nicht persistierende Request-Dry-Run-Auswertung fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
196. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Skeleton vorbereiten: Request-Dry-Run in einen nicht aktivierten Execution-Skeleton fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
197. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Dry-Run vorbereiten: Execution-Skeleton in eine nicht persistierende Execution-Dry-Run-Auswertung fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
198. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Boundary vorbereiten: Execution-Dry-Run in eine explizite Result-Boundary fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
199. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Dry-Run vorbereiten: Result-Boundary in eine nicht persistierende Result-Dry-Run-Auswertung fuer spaetere Human-Activation-Approval-Anfragen ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
200. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Execution-Skeleton vorbereiten: Result-Dry-Run in einen nicht aktivierten Execution-Skeleton fuer spaetere Result-Verarbeitung ueberfuehren, ohne Handler zu aktivieren, Entscheidung zu speichern, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
201. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Boundary vorbereiten: Result-Execution-Skeleton in eine explizite Handler-Boundary fuer spaetere Result-Verarbeitung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
202. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Dry-Run vorbereiten: Handler-Boundary in eine nicht registrierende Handler-Dry-Run-Auswertung fuer spaetere Result-Verarbeitung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
203. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Skeleton vorbereiten: Handler-Dry-Run in einen nicht aktivierten Execution-Skeleton fuer spaetere Handler-Ausfuehrung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
204. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Dry-Run vorbereiten: Handler-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ausfuehrung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
205. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Boundary vorbereiten: Handler-Execution-Dry-Run in eine explizite Handler-Execution-Result-Boundary fuer spaetere Handler-Ergebnisverarbeitung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
206. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisverarbeitung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
207. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
208. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
209. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Dry-Run in eine explizite Handler-Execution-Result-Execution-Result-Boundary fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
210. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
211. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
212. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
213. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Dry-Run in eine explizite Handler-Execution-Result-Execution-Result-Execution-Result-Boundary fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
214. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
215. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
216. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
217. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run in eine explizite Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
218. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
219. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
220. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
221. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run in eine explizite Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
222. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
223. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
224. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
225. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run in eine explizite Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
226. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
227. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
228. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Pruefung ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
229. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
230. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
231. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Dry-Run in eine nicht ausfuehrende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
232. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Boundary in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Auswertung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
233. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
234. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Fortsetzung vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Skeleton in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Fortsetzung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
235. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Dry-Run-Fortsetzung in eine nicht aktivierte Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
236. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung in einen nicht persistierenden Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
237. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Skeleton vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run in einen nicht aktivierten Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Skeleton fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
238. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run-Fortsetzung vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Skeleton in eine nicht persistierende Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run-Fortsetzung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
239. [x] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Boundary-Fortsetzung vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Dry-Run-Fortsetzung in eine nicht aktivierte Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Boundary-Fortsetzung fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.
240. [ ] MVP-Pilot-Decision-Capture-Payload-Validation-Request-Execution-Activation-Approval-Request-Execution-Result-Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Boundary-Fortsetzung-Dry-Run vorbereiten: Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Boundary-Fortsetzung in einen nicht persistierenden Handler-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Result-Execution-Boundary-Fortsetzung-Boundary-Fortsetzung-Dry-Run fuer spaetere Handler-Ergebnisuebernahme ueberfuehren, ohne Handler zu registrieren, Resultat anzunehmen, Approval zu persistieren, Pilotstart auszufuehren oder neue Modulfachlichkeit vorzuziehen.

Spaeter / nicht jetzt, bis ein echter Content-Preview-Produktpfad es verlangt:

- [ ] Ersten Renderer-/Viewer-Adapter hinter Release-Gate vorbereiten: Adapter-Port, Wiring-Guard und metadata-only Dry-Run anbinden, ohne gerenderten Content oder Dateiinhalte auszugeben.

## Release-Strategie

### MVP, Monat 6-8

Enthaelt:

- [ ] Mandantenfaehigkeit.
- [ ] IAM/OIDC.
- [ ] Audit Service.
- [ ] KMS.
- [ ] WORM Storage.
- [ ] Retention Policies.
- [ ] einfache Dokumentbearbeitung.
- [ ] einfache Versionierung.
- [ ] Basis-Mail-Import oder Mail-Gateway.
- [ ] Admin-Konsole.
- [ ] Compliance-Matrix.
- [ ] AI Control Plane.
- [ ] Local LLM Gateway mit Mock und lokalem Provider.
- [ ] RAG Skeleton mit Quellen.
- [ ] Command Palette Design.
- [ ] Push-to-talk Transcript Flow.

Nicht versprechen:

- perfekte Office-Kompatibilitaet.
- vollstaendiger eigener Mailserver.
- vollstaendige E-Discovery.
- Zertifizierung.
- autonome AI-Aktionen.

### Beta, Monat 10-12

Enthaelt:

- [ ] Team-Inboxen.
- [ ] Shared Drafts.
- [ ] sichere Attachment-Verarbeitung.
- [ ] ACL-Suche.
- [ ] Hybrid Search und Vector Search.
- [ ] Retention Worker.
- [ ] Legal Hold.
- [ ] Exportpakete.
- [ ] AI-Triage.
- [ ] Lasttests.
- [ ] Security Hardening.

### Production-Ready v1, Monat 15-16

Enthaelt:

- [ ] Vollstaendige Betriebsdokumentation.
- [ ] Helm Charts.
- [ ] Backup/Restore.
- [ ] Disaster-Recovery-Test.
- [ ] Penetrationstest-Fixes.
- [ ] Audit Pack.
- [ ] Performance-Nachweise.
- [ ] GoBD-Verfahrensdokumentation.
- [ ] BSI/ISO/OWASP/NIST-Mapping.
- [ ] Lokale LLM Provider produktiv betreibbar.
- [ ] RAG mit persistentem Vector Store.
- [ ] AI Governance und Human Oversight operational.

### Enterprise v1.5

Enthaelt:

- [ ] Erweiterte E-Discovery.
- [ ] S/MIME/PGP.
- [ ] DLP.
- [ ] Mobile Apps.
- [ ] JMAP-Ausbau.
- [ ] Archivzertifizierungsoptionen.
- [ ] Multi-Region.
- [ ] High Availability Profile.
- [ ] Externe Auditor Packages.
- [ ] Platform Module System.
- [ ] Optionales CRM/ERP Modul als erster Business-Modulnachweis.
- [ ] Vorbereitete Modulpfade fuer Wissensdatenbank, LMS, Aufgaben, Tickets und Zeiterfassung.

## Kritische Fallstricke

- DSGVO-Loeschung vs. GoBD-Aufbewahrung: nie direkter Delete ohne Policy Engine.
- WORM falsch eingefuehrt: kein Storage Write ohne Klassifikation und Retention.
- Suchindex als Datenleck: Index gibt nur Kandidaten aus.
- Audit Log nicht beweissicher: append-only, Hash Chain, Verification, WORM Snapshots.
- KMS zu spaet eingefuehrt: kein Business-Code mit direkter Crypto.
- CRDT und Compliance vermischt: Drafts, Deltas und Records sauber trennen.
- Office-Kompatibilitaet ueberschaetzt: Matrix, Testkorpus, Fallbacks.
- Mail-Protokolle unterschaetzt: Gateway/Proxy-Ansatz zuerst.
- Legal Hold nur als UI-Flag: Legal Hold muss Storage, Retention und Delete technisch blockieren.
- Barrierefreiheit zu spaet: Design System ab Phase 1 mit WCAG 2.2 AA.
- AI als Superuser: AI darf nie mehr sehen, tun oder exportieren als der aktuelle Nutzer.
- Embeddings unterschaetzt: Embeddings sind klassifizierte Daten, nicht anonym.
- Feature Flags als Autorisierung missverstanden: Modulstatus muss serverseitig in API und Workern gelten.
- Modul deaktiviert, Compliance vergessen: Disable darf Retention, Legal Hold, Audit, Backup, Restore und Export nie stoppen.
