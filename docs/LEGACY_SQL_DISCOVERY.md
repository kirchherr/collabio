# Legacy SQL Discovery

Ziel: Alte SQL-Systeme werden zuerst beweisbar verstanden, bevor Mapping, Import, Modul-Registry oder Produktlogik festgelegt werden.

Dieser Schritt ist absichtlich metadata-only. Er darf keine Rohdaten, Beispielzeilen, Vorschauwerte oder Zellinhalte transportieren. Damit bleibt die Discovery auch dann vertretbar, wenn das alte System fachlich, rechtlich oder technisch noch unklar ist.

## Erlaubte Discovery-Daten

- Connector-Typ, Tenant, Modul, Source-System-Referenz und Freigabe-/Audit-Referenzen.
- Connection-Fingerprint als Hash, niemals Secret oder DSN.
- Schema-, Tabellen-, View-, Spalten-, Index-, Constraint-, Primary-Key- und Foreign-Key-Metadaten.
- Datentyp, Nullability, Laenge, Precision, Scale und Identity/Default-Presence.
- Optionale aggregierte Row-Count-Schaetzungen, wenn die Tenant-Policy diese zulaesst.
- Hashes von Discovery-Snapshot, Manifest und Import-Evidence-Plan.

## Verbotene Discovery-Daten

- Rohzeilen, Sample Rows, Preview Values, Cell Values oder konkrete Feldwerte.
- SQL-Statements, Stored-Procedure-Body-Ausgaben oder freie Query-Texte im Manifest.
- Secrets, DSNs, Zugangsdaten oder Klartext-Connection-Strings.
- Personenbezogene Altdaten in normalen Logs, Audit-Kommentaren oder Observability-Feldern.

## Ablauf

1. Ein Tenant-Admin oder Compliance-Admin erstellt eine `LegacySqlDiscoveryRequest`.
2. Ein isolierter Connector-Worker liest nur Metadaten aus dem Altsystem.
3. Die Metadaten werden als `LegacySqlSchemaSnapshot` validiert.
4. `LegacySqlDiscoveryService` erzeugt ein hashbares Discovery-Manifest.
5. Tabellen werden nur anhand von Namen, Spaltenstruktur und Keys als Kandidaten eingeordnet.
6. Unsichere oder unbekannte Tabellen werden als `legacy.row` markiert und quarantined.
7. Der Import-Evidence-Plan verlangt Dry Run und explizite Freigabe.

## SQL-Server-Metadata-Worker

`app/suite/platform/legacy_sql_server_metadata.py` implementiert die erste konkrete Worker-Grenze fuer SQL Server. Der Worker ist treiberneutral: Er kennt nur ein Query-Executor-Protokoll und bekommt ausschliesslich eine Secret-Referenz, niemals DSN oder Passwort.

`docs/legacy_sql_connector_policy.json` legt fest:

- nur `sqlserver` als Connector-Kind fuer diesen Worker
- isolierter Worker ist Pflicht
- Netzwerkzugriff nur zu freigegebenen Legacy-Hosts
- keine Raw-Row-Reads, keine Sample Values, keine Stored-Procedure-Body-Reads
- nur erlaubte Query-Namen und Metadatenquellen aus `INFORMATION_SCHEMA` und `sys`
- Audit Events fuer Started, Completed und Failed ohne Nutzdaten

Das Docker-Compose-Profil enthaelt `legacy-sql-metadata-worker` als read-only, capability-losen Offline-Policy-Check mit `network_mode: none`. Produktiver Legacy-Zugriff muss spaeter ueber ein eigenes, restriktives Connector-Netzwerkprofil laufen.

## Import-Gates

Ein Import darf erst starten, wenn folgende Evidenz vorliegt:

- Discovery-Manifest mit Snapshot-Hash.
- Import-Evidence-Plan mit Quarantaene-Liste.
- Mapping-Entscheidung fuer jede Tabelle oder bewusstes `legacy.row`-Fallback.
- CRM/ERP-Mapping-Manifest mit Zielobjekt, Feature-Gate, Klassifikation und Retention Policy pro Tabelle.
- Legacy-Import-Readiness-Evidence mit Discovery-, Import-Plan- und Mapping-Hash.
- Dry-Run-Report mit Row Counts, Checksums, Validierungsfehlern und Audit-Referenz.
- Human Approval fuer produktive Migration.

Die Readiness-Evidence darf nur einen metadata-only Dry Run erlauben. Quarantaene-Tabellen, `legacy.row`-Fallbacks
oder eine gebrochene Hash-Kette blockieren den Dry Run bis zur manuellen Mapping-Klaerung.

Rohdatenimport, produktive Import-Writes, destruktive Aktionen und automatische Zielobjektanlage bleiben default-off.
Dieser Default gilt auch fuer spaetere Module wie Wissensdatenbank, LMS, Aufgaben, Tickets und Zeiterfassung.

## CRM/ERP-Mapping-Evidence

`app/suite/platform/crm_erp_legacy_mapping.py` erzeugt das erste fachliche Mapping-Manifest fuer `crm_erp`. Es verbindet Discovery-Manifest und Import-Evidence-Plan, ohne Altdaten zu laden.

Jede Tabelle erhaelt eine Entscheidung:

- `map_to_target`: nur fuer sichere Kandidaten oder explizit genehmigte Overrides.
- `map_to_legacy_row`: konservativer Fallback fuer unbekannte oder schwache Kandidaten.
- `quarantine`: keine fachliche Nutzung bis zur manuellen Entscheidung.
- `defer`: bewusst vertagt, aber weiterhin als `legacy.row` nachvollziehbar.

Das Manifest enthaelt Zielobjekt, Feature-Gate, Data Class, Retention Policy, Quarantaene-Status, Approval-Referenz und Hash. Es erlaubt weiterhin keinen Rohdatenimport und keine destruktiven Aktionen.

`build_crm_erp_legacy_import_readiness_evidence` fasst Discovery-Manifest, Import-Evidence-Plan und Mapping-Manifest
zu einem Dry-Run-Gate zusammen. Nur eine konsistente Evidence-Kette ohne Quarantaene- oder `legacy.row`-Blocker wird als
`ready_for_dry_run` markiert; alle anderen Zustaende bleiben manuell reviewpflichtig oder hart blockiert.

`docker compose run --rm legacy-sql-readiness-smoke` erzeugt einen metadata-only `legacy_sql_readiness_smoke_report.v1`
aus einer internen SQL-Server-Metadaten-Fixture. Der Smoke nutzt den isolierten Metadata-Worker, prueft die Hash-Kette
bis zur Readiness-Evidence und beweist beide Gate-Zustaende: Quarantaene blockiert Dry-Run, eine genehmigte Mapping-
Korrektur erlaubt ausschliesslich metadata-only Dry-Run. Der Report enthaelt keine Tabellen-/Spaltennamen,
Secret-Referenzen oder Rohdaten.

## Discovery-Intake-Gate

`app/suite/platform/legacy_sql_discovery_intake.py` ist die Annahmegrenze fuer echte Discovery-Anfragen. Das Gate nimmt
nur Tenant, Modul, Source-System-Referenz, Approval, Audit-Referenz, Connector-Policy-Hash und ein freigegebenes
Host-Profil an. Die eigentliche Secret-Referenz kommt ausschliesslich aus dem Host-Profil und wird nicht in der
Intake-Evidence ausgegeben.

Das Gate erzeugt erst dann ein `LegacySqlServerMetadataDiscoveryCommand`, wenn Request und Host-Profil exakt
zusammenpassen. Blockiert werden insbesondere DSN-Werte, Rohdaten-/Sample-/Stored-Procedure-Body-Anfragen,
Import-Dry-Runs, Import-Writes, destruktive Aktionen, Policy-Hash-Mismatch und Row-Count-Anfragen ohne Host-Freigabe.

`docker compose run --rm legacy-sql-discovery-intake` operationalisiert dieses Gate als metadata-only Drill. Der Report
`legacy_sql_discovery_intake_operations_report.v1` enthaelt Intake-Evidence-Hash, Status und einen Hash der redigierten
Metadata-Worker-Command-Ansicht. Secret-Referenzen, DSN-Werte, echte Verbindungen, Import-Dry-Runs und Import-Writes
bleiben ausserhalb des Reports und ausserhalb dieses Pfads.

## Evidence-Ledger

`app/suite/platform/legacy_sql_evidence_ledger.py` speichert Legacy-SQL-Evidence als tenant-sichere, append-only
Hash-Eintraege. Migration `0034_legacy_sql_evidence_ledger.sql` legt dafuer
`collabio.legacy_sql_evidence_ledger` mit RLS, No-Update-/No-Delete-Policies und Restore-Evidence-Hash an.

Das Ledger nimmt Intake-, Discovery-, Import-Plan-, Mapping-, Readiness- und Smoke-Report-Hashes auf. Es speichert keine
Report-Payloads, keine Tabelleninhalte, keine Sample Values, keine DSNs und keine Secret-Referenzen. Jeder Eintrag bindet
eine `restore_evidence_hash`, damit Restore-Drills spaeter beweisen koennen, welche Legacy-Migrations-Evidence wieder
verfuegbar ist, bevor echte Legacy-Verbindungen oder Import-Dry-Runs freigegeben werden.

Die Drills schreiben nur optional in dieses Ledger. Fuer lokale/CI-Nachweise kann `SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE=true`
gesetzt werden; dann sind zusaetzlich `SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH` und entweder
`SUITE_LEGACY_SQL_EVIDENCE_LEDGER_PATH` fuer JSONL oder `SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN`/`SUITE_DATABASE_DSN` fuer
Postgres erforderlich. Ohne diesen Schalter bleiben die Reports reine stdout-Evidence, mit Schalter werden nur Report-,
Intake-, Command-, Discovery-, Mapping- und Readiness-Hashes persistiert.

`docker compose run --rm legacy-sql-evidence-ledger-drill` operationalisiert den JSONL- und PostgreSQL-Schreibpfad als
metadata-only Restore-Nachweis. Der Drill schreibt die Intake- und Readiness-Report-Hashes, laedt sie tenant-scoped
wieder, prueft Restore-Hash-Bindung, Tenant-Isolation und Duplicate-Append-Sperre und erzeugt
`legacy_sql_evidence_ledger_operations_report.v1`. Erst ein gruener Report ist die technische Vorbedingung fuer echte
Legacy-Host-Profile; er oeffnet selbst keine reale Verbindung.

`legacy_sql_host_profile_release_gate.v1` ist das naechste Wiring-Gate fuer echte Host-Profile. Es akzeptiert nur einen
frischen Ledger-Operations-Report, den Connector-Policy-Hash, Host-Profil-Ref, freigegebene Egress-Ref, gehashte
Secret-Ref-Bindung und eine explizite menschliche Bestaetigung. Das Gate aktiviert nur metadata-only Discovery-Profile:
keine DSN, keine Rohdaten, kein Import-Dry-Run, kein Import-Write und keine destruktive Aktion. Der erste echte
Host-Profil-Adapter muss `require_legacy_sql_host_profile_release_gate_for_wiring` aufrufen.

Migration `0035_legacy_sql_host_profile_release_gate_evidence.sql` persistiert diese Gate-Evidence in
`collabio.legacy_sql_host_profile_release_gate_evidence` mit Tenant-RLS, Append-only-Policies und metadata-only Checks.
`docker compose run --rm legacy-sql-host-profile-release-gate-smoke` operationalisiert den Pfad: Der Smoke erzeugt erst
einen frischen Ledger-Operations-Report, schreibt danach eine ready und eine blocked Gate-Evidence in den
PostgreSQL-Store und prueft, dass nur die ready Evidence den Wiring-Guard passieren kann. Damit wird vor einem echten
Host-Profil-Adapter nicht nur die Modelllogik, sondern auch Persistenz, Tenant-Isolation, Restore-Evidence-Anbindung und
Blocked-Path-Verhalten nachgewiesen.

`app/suite/platform/legacy_sql_host_profile_adapter.py` ist der erste Adapter-Skeleton hinter diesem Gate. Er laedt die
persistierte Gate-Evidence tenant-scoped, prueft Host-Profil, Connector-Policy, Egress-Ref, Fingerprint und gehashte
Secret-Ref-Bindung und erzeugt nur `legacy_sql_host_profile_adapter_schedule.v1`. Diese Evidence enthaelt eine
redigierte Metadata-Worker-Command-Ansicht und einen Command-Hash, aber keine Secret-Ref, keine DSN, keine Rohdaten und
keine Import-Freigabe. `docker compose run --rm legacy-sql-host-profile-adapter-smoke` beweist zusaetzlich, dass eine
blocked Gate-Evidence nicht planbar ist und der Default-Compose-Pfad keine Legacy-SQL-Netzwerkverbindung oeffnet.

`app/suite/platform/legacy_sql_metadata_worker_queue.py` persistiert diese Schedule-Evidence als tenant-sichere,
idempotente Queue-Jobs. Migration `0036_legacy_sql_metadata_worker_queue.sql` legt
`collabio.legacy_sql_metadata_worker_queue` mit RLS, Idempotency-Key, Lease-/Retry-Status, Restore-Evidence-Hash und
metadata-only JSON-Checks an. Die Queue speichert nur redigierte Schedule-Evidence, Job-Hashes und Worker-Steuerdaten:
keine DSN, keine Secret-Ref, keine Tabelleninhalte, keine Rohdaten und keine Import-Payloads.

`docker compose run --rm legacy-sql-metadata-worker-queue-drill` operationalisiert den Pfad. Der Drill erzeugt eine
frische ready Release-Gate-Evidence, plant daraus Schedule-Evidence, persistiert den Queue-Job idempotent im
PostgreSQL/RLS-Store, leased ihn einmal, schreibt Retry-Evidence mit Restore-Hash-Bindung und beweist Tenant-Isolation
sowie blocked-gate rejection. Auch dieser Drill oeffnet im Default-Compose keine Legacy-SQL-Netzwerkverbindung.

## Zukunftssichere Erweiterung

Die Discovery ist nicht auf SQL Server beschraenkt. Das Modell kennt Connector-Arten fuer SQL Server, PostgreSQL, MySQL, Oracle, SQLite und `unknown`. Neue Adapter muessen dieselbe metadata-only Grenze einhalten und duerfen Provider-spezifische Details nur als validierte Metadaten einbringen.

Der naechste technische Schritt ist ein isolierter Lease-Consumer-Skeleton fuer diese Queue. Er darf geleaste Jobs nur
validieren und redigierte Worker-Befehle vorbereiten; echte Verbindung, Rohdaten, Import-Dry-Run und Import-Writes
bleiben weiterhin getrennte spaetere Gates.
