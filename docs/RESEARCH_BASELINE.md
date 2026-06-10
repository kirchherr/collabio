# Research Baseline

Stand: 2026-06-10

Zweck dieses Dokuments: eine gemeinsame Wissensbasis fuer die Umsetzung der Compliance-First Enterprise Suite schaffen. Es ist kein Rechtsgutachten und kein Zertifizierungsnachweis, sondern die technische Recherche- und Entscheidungsgrundlage fuer Architektur, Epics und ADRs.

## Leitthese

Wir bauen keine Office-Suite, die Compliance-Funktionen bekommt. Wir bauen eine beweisfaehige, mandantenfaehige, auditierbare Plattform, auf der Office, Mail, Suche, RAG, Voice und KI sicher laufen duerfen.

Der Kernpfad bleibt:

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

## Zukunftssicherheits-Kriterien

Jede Technologie, jedes Modul und jede Abhaengigkeit wird gegen diese Kriterien bewertet:

- Offene Standards oder klare Interoperabilitaet.
- Open Source bevorzugt, aber Lizenz und Governance muessen zur kommerziellen Enterprise-Nutzung passen.
- Austauschbare Adapter statt direkter Vendor-Bindung.
- Mandantenfaehigkeit nicht nur in der UI, sondern in API, DB, Storage, Search, Vector DB, Audit und Export.
- Default deny.
- Defense in depth: Applikationslogik plus Datenbank-/Storage-/Infra-Kontrollen.
- Crypto agility: keine Krypto direkt im Business-Code.
- Auditierbarkeit: Entscheidungen muessen reproduzierbar und pruefbar sein.
- Air-gap- und Self-hosting-Faehigkeit.
- Keine versteckte Cloud-Abhaengigkeit in Kernfunktionen.
- Keine sensiblen Inhalte in normalen Logs.
- Tests fuer Missbrauchsfaelle, nicht nur Happy Path.

## Recht und Compliance

### DSGVO

Technische Konsequenzen:

- Privacy by Design und Security by Design werden als Architektur-Constraints behandelt.
- Jede Datenklasse braucht Rechtsgrundlage, Retention, Loesch-/Sperrlogik, Exportlogik und TOM-Bezug.
- Direktes Loeschen ist nie nur ein CRUD-Endpunkt, sondern eine Policy-Entscheidung.
- Verschluesselung, Pseudonymisierung, Wiederherstellbarkeit und Wirksamkeitstests muessen in Betrieb und CI/CD nachweisbar werden.

Referenz:

- https://eur-lex.europa.eu/eli/reg/2016/679/oj

### GoBD

Der Referenzstand muss die BMF-Aenderung vom 14.07.2025 beruecksichtigen. Die BMF-Seite beschreibt die Anpassung der Grundsaetze zur ordnungsmaessigen Fuehrung und Aufbewahrung von Buechern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff.

Technische Konsequenzen:

- Business Records und Evidence Records duerfen nicht mit kollaborativen Drafts verwechselt werden.
- WORM, Versionierung, Exportmanifest, Hashes und Verfahrensdokumentation gehoeren in den Kern.
- GoBD- und Legal-Hold-Daten duerfen nicht pauschal cryptoshredded werden.

Referenz:

- https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Weitere_Steuerthemen/Abgabenordnung/2025-07-14-GoBD-2-aenderung.html

### EU AI Act

Die EU-Kommission beschreibt den AI Act als risikobasiertes Regelwerk mit Risikostufen, Transparenzpflichten, Anforderungen an Hochrisiko-Systeme und Governance. Fuer uns relevant:

- Wir muessen Rollen unterscheiden: Provider, Deployer, Integrator, Admin, Tenant.
- Hochrisiko-Use-Cases werden im MVP ausgeschlossen oder gesondert klassifiziert.
- Transparenz, Logging, Dokumentation, menschliche Aufsicht, Robustheit, Cybersecurity und Genauigkeit muessen technisch vorgesehen werden.
- Die EU-Kommission nennt als Zeitlinie unter anderem Inkrafttreten am 01.08.2024, Verbote und AI-Literacy ab 02.02.2025, GPAI-Regeln ab 02.08.2025 und weitere Anwendungsschritte ab 2026/2027/2028. Diese Zeitlinie ist regulatorisch volatil und muss vor Release erneut geprueft werden.

Referenz:

- https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- https://eur-lex.europa.eu/eli/reg/2024/1689/oj

### NIST CSF 2.0

Die Suite soll ihr Sicherheitsprogramm an Govern, Identify, Protect, Detect, Respond und Recover ausrichten. NIST stellt CSF 2.0, Quick Start Guides, Profile und Mappings bereit.

Technische Konsequenzen:

- Compliance-Matrix bekommt CSF-Funktion, Kategorie und Evidenzspalte.
- Governance und Supply Chain werden gleichwertig zu klassischen Schutzmassnahmen.

Referenz:

- https://www.nist.gov/cyberframework

### NIST SSDF

NIST SP 800-218 empfiehlt ein Secure Software Development Framework mit Praktiken, die in SDLCs integriert werden koennen, um Schwachstellen zu reduzieren und Ursachen zukuenftiger Schwachstellen zu adressieren.

Technische Konsequenzen:

- CI/CD muss Secure SDLC erzwingen.
- SBOM, Provenance, Reviews, Threat Modeling, Vulnerability Response und Release Evidence sind Pflicht.

Referenz:

- https://csrc.nist.gov/pubs/sp/800/218/final

### NIST AI RMF

NIST AI RMF ist fuer freiwilliges AI-Risikomanagement gedacht und hilft, Trustworthiness in Design, Entwicklung, Nutzung und Bewertung von AI-Systemen einzubauen. Fuer Generative AI existiert ein Profil.

Technische Konsequenzen:

- AI Risk Register und AI Evaluation Harness muessen Release-Gates werden.
- Generative-AI-spezifische Risiken wie Halluzination, Prompt Injection, Datenabfluss, Tool Misuse und Modell-Lieferkette gehoeren in CI.

Referenz:

- https://www.nist.gov/itl/ai-risk-management-framework

### OWASP ASVS 5.0

ASVS liefert pruefbare Anforderungen fuer Web-Anwendungssicherheit und ist als Requirements- und Test-Mapping nutzbar.

Technische Konsequenzen:

- API, Auth, Session, Input Validation, Crypto, Error Handling, Logging und Config muessen ASVS-IDs bekommen.
- Wir sollten Requirements immer mit Versionsprefix referenzieren, z. B. `v5.0.0-...`.

Referenz:

- https://owasp.org/www-project-application-security-verification-standard/

### OWASP LLM / GenAI

Technische Konsequenzen:

- Prompt Injection, Sensitive Information Disclosure, Supply Chain, Data/Model Poisoning, Improper Output Handling, Excessive Agency, System Prompt Leakage und Vector/Embedding Weaknesses werden eigene Testfamilien.
- LLM Output bleibt untrusted.
- Tool-Calls sind Policy- und Audit-Objekte.

Referenz:

- https://owasp.org/www-project-top-10-for-large-language-model-applications/

### Mail-Standards

DMARC ist nicht mehr nur RFC 7489. Fuer die Roadmap sind RFC 9989, RFC 9990 und RFC 9991 als aktuelle DMARC-Familie zu fuehren. Mail Core muss ausserdem SMTP, IMAP4rev2, JMAP, SPF, DKIM und MTA-STS beruecksichtigen.

Technische Konsequenzen:

- Mail-Security-Ergebnisse werden persistent gespeichert und auditierbar.
- Team-Kommentare duerfen technisch nie Teil des RFC-Mailobjekts werden.

Referenzen:

- https://datatracker.ietf.org/doc/rfc9989/
- https://datatracker.ietf.org/doc/rfc9990/
- https://datatracker.ietf.org/doc/rfc9991/

## Architektur-Fakten aus der Recherche

### PostgreSQL Row-Level Security

PostgreSQL RLS kann zeilenbasierte Policies fuer SELECT/INSERT/UPDATE/DELETE erzwingen. Wenn RLS aktiv ist und keine Policy existiert, gilt default deny. Wichtig: Superuser und Rollen mit `BYPASSRLS` umgehen RLS; RLS ersetzt daher keine Applikations-Authz.

Entscheidung:

- PostgreSQL wird als primaere relationale Datenbank empfohlen.
- RLS wird als zweite Schutzschicht verwendet, nicht als einzige Schutzschicht.

Referenz:

- https://www.postgresql.org/docs/current/ddl-rowsecurity.html

### WORM und Object Lock

S3 Object Lock nutzt ein Write-Once-Read-Many-Modell gegen Loeschen oder Ueberschreiben fuer einen Zeitraum oder unbefristet. MinIO beschreibt S3-kompatible Object Locking-/Retention-Konzepte, Versionierung, Retention Modes und Legal Holds.

Entscheidung:

- Storage Adapter muss WORM/Object-Lock-faehig sein.
- Keine produktiven Business Records ohne Storage Manifest und Retention-Metadaten.
- Legal Hold muss Storage-seitig und Policy-seitig wirken.

Referenzen:

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- https://min.io/docs/minio/linux/administration/object-management/object-retention.html

### Policy Engine

OPA ist ein CNCF-graduated, allgemeiner Policy-as-Code-Ansatz, der Policy-Entscheidungen vom Enforcement entkoppelt. Es passt stark fuer Infrastruktur, Kubernetes, CI/CD, Admission Controls und globale Policy-Auswertung.

Entscheidung:

- Kurzfristig: interne Policy Engine fuer Request/Authz/AI-Kontrollen, weil wir eng mit Domain-Modellen, Audit und DB arbeiten.
- Mittelfristig: OPA fuer Infrastructure-as-Code, Kubernetes Admission, CI/CD und optional externe Policy-Evaluation.
- Runtime-Authz kann spaeter OPA/Cedar/Cerbos/Casbin evaluieren; ADR erforderlich.

Referenz:

- https://www.openpolicyagent.org/docs

### IAM

Keycloak bietet OIDC/SAML, Administration, zentrale Auth und fine-grained Authorization Services. Es ist ein CNCF-Incubation-Projekt.

Entscheidung:

- Nicht selbst IdP bauen.
- Keycloak als erster Self-hosted-IAM-Kandidat.
- Suite bleibt trotzdem OIDC/SAML-kompatibel und adapterfaehig.

Referenz:

- https://www.keycloak.org/documentation

### Vector Search

pgvector bringt Vector Search direkt in PostgreSQL und unterstuetzt unter anderem exakte und approximative Suche, HNSW und IVFFlat. Qdrant bietet dedizierte Vektor-Suche, Payloads, Filtering, Hybrid Queries, Multitenancy und Betriebsfeatures.

Entscheidung:

- MVP: pgvector bevorzugt, weil Metadaten, Tenant-Kontext, Transaktionen, Backups und RLS nahe beieinander liegen.
- Skalierungs-ADR: Qdrant als dedizierte Vector DB pruefen, sobald Datenmenge, Latenz oder Hybrid-Suche pgvector ueberfordern.
- In beiden Faellen: Vector Search liefert nur Kandidaten.

Referenzen:

- https://github.com/pgvector/pgvector
- https://qdrant.tech/documentation/

### Local LLM Gateway

vLLM stellt Online Serving und OpenAI-kompatible APIs fuer Chat, Completions, Responses, Embeddings, Transcriptions und weitere Endpunkte bereit. Ollama bietet eine einfache lokale API fuer Modellverwaltung und Inferenz.

Entscheidung:

- Gateway-Adapter bleiben Pflicht.
- vLLM ist erster Produktionskandidat fuer GPU/self-hosted Inferenz.
- Ollama ist sinnvoll fuer lokale Entwicklung, KMU, Demos und Lightweight-Deployments.
- Alle Provider muessen Model Registry, Policy, Token Budget, Timeout, Audit und Output Validation passieren.

Referenzen:

- https://docs.vllm.ai/en/latest/serving/online_serving/
- https://github.com/ollama/ollama/blob/main/docs/api.md

### Collaboration / Office Editor

Yjs ist ein CRDT fuer kollaborative Anwendungen und unterstuetzt automatische Konfliktauflösung, verschiedene Editor-Bindings und netzwerkagnostische Provider. ProseMirror ist ein etabliertes Toolkit fuer rich-text editorische Modelle; Tiptap ist ein headless Editor auf ProseMirror-Basis mit Erweiterungen, Kollaboration und On-Prem-Angeboten.

Entscheidung:

- Office MVP: ProseMirror/Tiptap fuer Texteditor evaluieren.
- Collaboration: Yjs als CRDT-Kandidat, aber Compliance-Grenze sauber ziehen: CRDT-Deltas sind Working Data, keine Business Records.
- Import/Export und Parser muessen isolierte Worker sein.

Referenzen:

- https://docs.yjs.dev/
- https://prosemirror.net/docs/
- https://tiptap.dev/docs

### Observability

OpenTelemetry ist der Standardpfad fuer Traces, Metrics und Logs. Fuer uns gilt: Observability darf keine sensiblen Inhalte enthalten.

Entscheidung:

- OpenTelemetry fuer Spans, Metrics und strukturierte Events.
- Prompt, Output, Transcript, Mail Body, Document Body und Secrets nur als Hash/ID/Klassifikation in Observability.

Referenz:

- https://opentelemetry.io/docs/what-is-opentelemetry/

### Supply Chain

SLSA adressiert Integritaet und Schutz vor Manipulation in Software Supply Chains. CycloneDX ist ein BOM-Standard mit SBOM, CBOM, VEX und AI/ML-BOM-Faehigkeiten. Sigstore/Cosign deckt Signieren und Verifizieren von Artefakten ab.

Entscheidung:

- SBOM ab Phase 0.
- Signierte Container und Release-Artefakte.
- Provenance als Release-Artefakt.
- Spaeter: AI/ML-BOM fuer Modelle, Embeddings, Datasets und Evaluations.

Referenzen:

- https://slsa.dev/
- https://cyclonedx.org/
- https://docs.sigstore.dev/

## Open Research Gaps

Diese Punkte muessen vor Produktionsreife weiter recherchiert oder juristisch/technisch validiert werden:

- Vollstaendiges GoBD-Anforderungsmapping aus dem BMF-PDF.
- BSI TR-02102 konkrete Algorithmen-/Schluessellaengen-Matrix.
- BSI C5:2026 Control Mapping.
- EU AI Act Omnibus-/Timeline-Aenderungen vor Release erneut pruefen.
- Lizenzanalyse fuer MinIO, Tiptap Pro/Cloud, AGPL-Komponenten, OpenBao/Vault, Qdrant Enterprise Features.
- eIDAS 2 / EUDI Wallet Relevanz fuer spaetere Enterprise-/Public-Sector-Identitaet.
- Nationale Betriebsrats-/Arbeitsrecht-Themen fuer Voice, AI-Telemetrie, Monitoring und Productivity Analytics.
- Data Act / Data Governance Act / CRA / NIS2 Relevanz fuer Zielkunden.
- Archivzertifizierung und konkrete Anforderungen deutscher Pruefer.

