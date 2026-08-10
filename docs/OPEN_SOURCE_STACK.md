# Open Source Stack Candidates

Stand: 2026-06-10

Dieses Dokument sammelt bewährte Open-Source- und offene Standard-Bausteine. "Empfohlen" bedeutet: gut als erste Richtung. Es ersetzt keine ADR, Lizenzpruefung oder Sicherheitsreview.

## Bewertungslegende

- `default`: bevorzugte Startentscheidung.
- `candidate`: ernsthafter Kandidat, ADR noetig.
- `defer`: spaeter pruefen.
- `avoid-core`: nicht in kritischen Kernpfad legen.

## Platform Core

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Backend API | FastAPI + Pydantic v2 | default | Bereits im Skeleton, schnell, typsicher genug fuer Orchestrierung, gute OpenAPI-Unterstuetzung. |
| Kritische Worker | Rust oder Go | candidate | Fuer Parser-Sandbox, KMS-nahe Tools, Audit-Verifier und High-throughput Worker pruefen. |
| Datenbank | PostgreSQL | default | Reif, transaktional, RLS, Extensions, Backup/Restore, starke Enterprise-Basis. |
| Row-level Defense | PostgreSQL RLS | default | Defense-in-depth, default deny moeglich. Nicht als einzige Authz verwenden. |
| Cache / Coordination | Redis oder KeyDB | candidate | Fuer kurzlebige Koordination, Rate Limits, WebSocket Presence; keine Records. |
| Event Bus | NATS JetStream | candidate | Leichtgewichtig, self-hosted, gut fuer Outbox/Worker/Eventing. Kafka erst bei Bedarf. |
| API Schema | OpenAPI | default | Contract Tests und Admin-/SDK-Generierung. |

## Identity And Authorization

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| IAM / IdP | Keycloak | default | Self-hosted, OIDC/SAML, WebAuthn/MFA, Admin APIs, bewährt. |
| App Policy | Interne Policy Engine | default | Enge Domain-Integration fuer Tenant, Data Class, Retention, AI, Voice, RAG. |
| Policy-as-Code | OPA/Rego | candidate | Stark fuer Kubernetes, CI/CD, IaC, Admission, globale Infrastrukturregeln. |
| Runtime Authz Alternative | Cerbos, Casbin, Cedar | defer | Erst evaluieren, wenn Domain-Policy stabil ist. |

## Audit, Compliance, Lifecycle

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Audit Store | PostgreSQL append-only tables + hash chain | default | Einfach zu verifizieren, transaktional, nah am Domain-Event. |
| Audit Snapshots | WORM Object Store | default | Manipulationsresistente Tages-/Periodensnapshots. |
| Verifier | Eigenes CLI in Python/Rust | default | Muss projekt- und beweislogikspezifisch sein. |
| Compliance Matrix | YAML + Markdown Generator | default | Maschinenlesbar und menschenlesbar. |
| Evidence Export | ZIP + manifest + signatures + hashes | default | Reproduzierbar und tool-unabhaengig. |

## KMS And Crypto

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Crypto API | Eigene Adapter-Schicht | default | Keine direkte Krypto im Business-Code. |
| Dev KMS | Lokaler Software-KMS / OpenBao-Kandidat | candidate | Lizenz, Security und Betriebsmodell pruefen. |
| Enterprise KMS | HSM/PKCS#11, Cloud KMS Adapter, OpenBao/Vault-kompatible Adapter | candidate | Kunden brauchen unterschiedliche Betriebsmodelle. |
| Envelope Encryption | Pflicht | default | Tenant-, Datenklassen- und Objekt-Key-Hierarchie. |
| Key Rotation | Pflicht | default | Muss von Anfang an modelliert werden. |
| Crypto Shredding | Nur policy-gesteuert | default | Nie pauschal fuer GoBD oder Legal Hold. |

## Storage

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Object Storage API | S3-kompatibel | default | Portabel, Object Lock, viele Provider. |
| Dev/Self-hosted Store | MinIO | candidate | S3-kompatibel, Object Lock/Legal Hold; Lizenz und Enterprise-Betrieb pruefen. |
| Metadata Store | PostgreSQL | default | Storage Manifest, Retention, Legal Hold, KMS refs. |
| WORM Mode | Compliance Mode fuer Records | default | Business/Evidence Records muessen unveraenderbar sein. |
| Parser Input/Output | Object Store + sandboxed workers | default | Keine Parser im API-Prozess. |

## Search, Vector, RAG

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Keyword Search MVP | PostgreSQL FTS hinter `KeywordIndex` Boundary | default | Einfacher Start, keine neue Datenbank; API bleibt candidate-only und ACL-gefiltert. |
| Keyword Search Scale | OpenSearch | candidate | Fuer groessere Volltext-/Hybrid-Setups, Betriebskomplexitaet beachten. |
| Vector MVP | pgvector | default | Nah an Metadaten, RLS, Backups und Transaktionen. |
| Vector Scale | Qdrant | candidate | Dedizierte Vector DB, Payload, Filtering, Hybrid Queries, Multitenancy. |
| RAG Framework | Eigene Orchestrierung + kleine Adapter | default | RAG ist Security-kritisch; keine Blackbox im Kern. |
| Evaluation | RAGAS/DeepEval/Custom Tests | candidate | Nur als Testhelfer, nicht als Sicherheitsentscheidung. |
| Reranking | vLLM/Cross-Encoder Adapter | candidate | Nur nach ACL und Source Resolve. |

Hard rule:

```text
search/vector candidate ids -> authoritative ACL -> source fetch -> redaction -> RAG context
```

## Local AI, Voice, Assistants

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| LLM Gateway | Eigenes Gateway | default | Policy, Model Registry, Prompt Registry, Audit, Output Validation. |
| Production Inference | vLLM | candidate | OpenAI-kompatible APIs, Serving, Embeddings/ASR je nach Modell, GPU-freundlich. |
| Lightweight Local | Ollama | candidate | Einfach fuer Dev/KMU/Demos, nicht als alleiniger Enterprise-Standard. |
| CPU/Edge | llama.cpp | defer | Fuer Air-gap/kleine Installationen pruefen. |
| STT | whisper.cpp oder vLLM ASR Adapter | candidate | Nur push-to-talk, Transkripte klassifizieren. |
| TTS | Piper | candidate | Lokale TTS pruefen; Voice-Ausgaben auditieren, aber Audio nicht speichern. |
| Prompt Registry | YAML + DB Registry | default | Prompts nicht im Feature-Code verstreuen. |
| Model Registry | DB + signed model manifests | default | Lizenz, Checksums, Datenklassen, Use Cases, Blocklist. |

## Office And Collaboration

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Rich Text Core | ProseMirror | candidate | Bewaehrt, tief kontrollierbar. |
| Product Editor Layer | Tiptap | candidate | Schnellere Produktentwicklung, ProseMirror-basiert; Lizenz/Pro Features pruefen. |
| CRDT | Yjs | candidate | Bewaehrte CRDT-Basis, Editor-Bindings, netzwerkagnostisch. |
| DOCX Quick Edit Engine | Selektiv evaluierter GenOffice `docx-engine` hinter `OfficeEditAdapter.v1` | pre-build and npm provenance passed; import blocked | Interessante byte-erhaltende Patch-Architektur; 23 Komponenten exakt inventarisiert und ohne Findings gescannt, npm-Signatur/SLSA/Fulcio/Rekor verifiziert, aber erst nach Legal-, reproduzierbarem Image-Build-, Malicious-File-, Fidelity- und Recovery-Gate importierbar. |
| Full Collaboration | Collabora Online ueber separaten WOPI-Adapter | candidate | Self-hosted und LibreOffice-basiert; Sessions, Locks, Tokens, Callbacks und Writes bleiben ausserhalb von Preview und Quick Edit. |
| Full Collaboration Alternative | ONLYOFFICE Docs ueber separaten WOPI-Adapter | defer | Gute OOXML-Ausrichtung; Lizenz, Edition, Einbettung und Betriebsgrenzen vor Auswahl gesondert pruefen. |
| Spreadsheet Engine | Noch offen | research | Formeltreue ist ein eigenes Risiko. |
| DOCX/ODF Parsing | LibreOffice headless / Pandoc / custom workers | research | Nur in isolierten, netzwerklosen Containern. |
| PDF Rendering | LibreOffice / headless Chromium / dedicated workers | research | Kein Renderer im API-Prozess. |

Compliance rule:

```text
CRDT delta != saved version != business record != WORM evidence record
```

## Mail

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| MVP Mail Approach | Gateway/Proxy statt kompletter Mailserver | default | Reduziert Zustell- und Protokollrisiko. |
| Protocols | SMTP, IMAP4rev2, JMAP | candidate | API- und Kompatibilitaetsstrategie per ADR. |
| Mail Security | SPF, DKIM, DMARC RFC 9989/9990/9991, MTA-STS | default | Status speichern und auditieren. |
| MIME Parsing | Sandboxed workers | default | Keine Parser im API-Prozess. |
| Attachment Scan | ClamAV + weitere Scanner | candidate | Pflicht vor Vorschau/Oeffnung. |
| Team Comments | Eigenes Domain-Objekt | default | Nie Teil des RFC-Mailobjekts. |

## Frontend, UX, Accessibility

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Web App | React + TypeScript | candidate | Reifes Oekosystem, Tiptap/Yjs kompatibel. |
| Design System | Eigene Komponenten auf Radix/ARIA Patterns | candidate | Accessibility und kontrollierte UX. |
| Command Palette | Eigener permission-aware Action Registry Client | default | Zero-friction ohne Authz-Bypass. |
| Icons | lucide | candidate | Konsistent, leichtgewichtig. |
| Accessibility Tests | Playwright + axe | candidate | WCAG 2.2 AA ab Phase 1. |
| E2E | Playwright | default | Browseruebergreifend, CI-faehig. |

## Infrastructure And Operations

| Bereich | Empfehlung | Status | Warum |
| --- | --- | --- | --- |
| Dev | Docker Compose | default | Bereits aktiv, reproduzierbar. |
| Production | Helm + Kubernetes | candidate | Enterprise Self-hosting, HA, Network Policies. |
| IaC | Terraform/OpenTofu | candidate | Kundenfreundliche Beispiele. |
| Admission Policies | Kyverno oder OPA Gatekeeper | candidate | Kubernetes Hardening. |
| Observability | OpenTelemetry + Prometheus + Grafana | candidate | Standardisierung, keine sensiblen Logs. |
| Container Signing | Sigstore Cosign | candidate | Supply-chain Evidence. |
| SBOM | CycloneDX | default | SBOM/CBOM/AI/ML-BOM-Pfad. |
| Provenance | SLSA-aligned | default | Release Evidence. |

## Hard No List

Diese Dinge sollen nicht in den Kern:

- Direkte Provider-SDK-Aufrufe aus Feature-Code.
- Direkter Storage-/Vector-/Search-Zugriff aus UI oder Feature-Code.
- Normalisierte Logs mit Prompts, Outputs, Dokumenttexten, Mail Bodies oder Transkripten.
- Always-on Voice.
- Autonomes Senden, Loeschen, Exportieren, Legal-Hold-Setzen oder Key-Destroy.
- Parser im API-Prozess.
- Macros im MVP ausfuehren.
- Cloud-AI als Default.
- Daten in ein Modell trainieren, wenn RAG gemeint ist.
- Embeddings als anonym behandeln.

## First Stack Recommendation

Fuer die naechsten 2-3 Sprints:

```text
Python/FastAPI
PostgreSQL
SQLAlchemy/Alembic oder SQLModel/Alembic
Keycloak dev realm
internal policy engine
PostgreSQL append-only audit table + hash chain
S3-compatible storage adapter interface
MinIO dev service
pgvector ADR
OpenTelemetry skeleton
Ruff + typing + pytest
CycloneDX SBOM
Sigstore/Cosign plan
```

Noch nicht implementieren, bevor die ADRs stehen:

- Voller Mailserver.
- Vollstaendiger Office-Import/Export.
- Qdrant produktiv.
- Kubernetes-Produktionschart.
- Externe AI Provider.
