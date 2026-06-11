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
- [x] In-memory Append-only Audit Hash Chain mit Verifier und Manipulationstests.
- [x] File-backed Tenant Policy, Model Registry, Prompt Registry, Tool Permission und Audit JSONL Stores.
- [x] Rollenbasierte Admin API fuer Tenant AI Settings und erlaubte Modelle.
- [x] Erste Prompt-Injection- und unauthorized-RAG-output Regressionstests.
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
- [ ] Produktionsfaehiger Audit Storage mit DB-Rollen, WORM Snapshots und Checkpoints.
- [ ] KMS/WORM/Retention/Legal Hold.
- [ ] Office-, Mail-, Search-, E-Discovery- und Admin-Module.

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
      mail-gateway/
      collaboration/
      search-indexer/
      lifecycle-worker/
      ediscovery/
      audit-service/
      kms-adapter/
      ai-control-plane/
      llm-gateway/
    libs/
      authz/
      audit/
      crypto/
      data-classification/
      retention/
      tenant-context/
      policy-engine/
      observability/
  frontend/
    apps/
      web-suite/
      admin-console/
      ediscovery-console/
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
- [ ] Principal-, Role- und Permission-Modelle implementieren.
- [ ] OIDC-Claims-Mapping vorbereiten.
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
- [x] Key Rotation Interface implementieren.
- [ ] Cryptographic Shredding Simulation implementieren.
- [ ] Schutzregel: GoBD- und Legal-Hold-Objekte nicht versehentlich cryptoshreddern.
- [ ] Restore-Test-Framework anlegen.
- [x] Text Extraction Interface fuer Office/Mail/Attachments.
- [x] Chunker Interface.
- [x] Embedding Provider Interface.
- [ ] Vector Metadata Schema validieren.
- [ ] ACL-Versionen in Vector Metadata uebernehmen.
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

Aufgaben:

- [ ] Persistente Search Indexer Pipeline.
- [ ] Dokumenttext-Extraktion.
- [ ] Mail Body Extraction.
- [ ] Attachment Text Extraction.
- [ ] Tenant-separierte Indizes oder harte Tenant Filter.
- [ ] Index-Rebuild Pipeline.
- [ ] Search Audit Events.
- [ ] Snippet-Erzeugung erst nach Authz.
- [x] Persistent Vector DB Adapter.
- [x] ADR: pgvector vs. Qdrant als erster Backend-Adapter.
- [x] pgvector Embedding-Metadaten-Schema als erste SQL-Migration.
- [x] Live pgvector RLS-Integrationstest gegen PostgreSQL.
- [ ] Hybrid Query Orchestration.
- [ ] Reranker Interface.
- [ ] Source Resolver.
- [ ] Redaction Engine.
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
32. [ ] Cryptographic Shredding Simulation implementieren.

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
