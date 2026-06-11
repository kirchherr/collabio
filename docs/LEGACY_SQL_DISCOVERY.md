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
- Dry-Run-Report mit Row Counts, Checksums, Validierungsfehlern und Audit-Referenz.
- Human Approval fuer produktive Migration.

Rohdatenimport, destruktive Aktionen und automatische Zielobjektanlage bleiben default-off. Dieser Default gilt auch fuer spaetere Module wie Wissensdatenbank, LMS, Aufgaben, Tickets und Zeiterfassung.

## Zukunftssichere Erweiterung

Die Discovery ist nicht auf SQL Server beschraenkt. Das Modell kennt Connector-Arten fuer SQL Server, PostgreSQL, MySQL, Oracle, SQLite und `unknown`. Neue Adapter muessen dieselbe metadata-only Grenze einhalten und duerfen Provider-spezifische Details nur als validierte Metadaten einbringen.

Der naechste technische Schritt ist die CRM/ERP-Mapping-Evidence: Tabellen aus Discovery-Manifests werden bewusst auf Zielobjekte, `legacy.row`-Fallback oder Quarantaene abgebildet, bevor Subfeature-Registry und Import-Dry-Run starten.
