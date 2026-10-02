# Real-user Productivity Pilot Closure Report

Stand: 2026-08-04

## Zweck

`productivity_pilot_real_user_closure_report.v1` ist die separate append-only Abschlussgrenze fuer
ein Realnutzer-Pilotfenster. Sie muss vorhanden und technisch abgenommen sein, bevor ein spaeterer
Realnutzer-Pilot den deploymentweiten Kill-Switch oeffnen darf. Die Grenze selbst oeffnet keinen
Traffic und fuehrt weder Fachschreibvorgaenge noch Loeschungen oder externe Aktionen aus.

## Sicherheitskette

Ein Abschluss wird nur akzeptiert, wenn:

1. der aufrufende Actor die autoritative Rolle `security-admin` besitzt;
2. `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0` gilt;
3. Runtime-Fenster, Admission, Nomination und Startfreigabe hashvalide und exakt verbunden sind;
4. der Closure-Actor von Nominator, Admission-Approver, Start-Authorizer, Runtime-Operator und allen
   Teilnehmern getrennt ist;
5. alle Runtime-Beobachtungen hashvalide, tenant-gebunden, innerhalb des Fensters und auf
   freigegebene Routen sowie designierte Principal-Hashes beschraenkt sind;
6. jeder persistierte Pilot-Schreibbeleg durch eine passende Beobachtung desselben Principal-Hashes
   und derselben Operation gedeckt ist;
7. frische metadata-only Backup-, Restore-, Foundation- und Business-Release-Nachweise die exakten
   Window-, Observation- und Receipt-Zaehler bestaetigen.

Ein aktiviertes, aber unbenutztes Fenster kann mit null Beobachtungen und null Domain-Receipts
geschlossen werden. Der Abschluss erfindet keine Aktivitaet und blockiert keinen Sicherheitsstopp,
nur weil ein geplanter Pilot nicht begonnen wurde.

## Hash-only Persistenz

Migration `0069_productivity_pilot_real_user_closure_report.sql` erstellt
`collabio.productivity_pilot_real_user_closure_reports`. Migration
`0070_productivity_pilot_real_user_closure_owner_refs.sql` verbietet raw Principal-Schemes auch
fuer direkte Datenbank-Inserts. Die Tabelle erzwingt Tenant-RLS, besitzt nur
`SELECT`/`INSERT` fuer `collabio_authz_admin` und verhindert Update sowie Hard Delete durch Policy und
Trigger.

Persistiert werden ausschliesslich:

- IDs der Kontrollobjekte und deren Evidenz-Hashes;
- tenant-gebundene Principal-Hashes;
- Operations- und Zaehlerzusammenfassungen;
- Observation- und Domain-Receipt-Manifeste;
- Recovery- und Freigabe-Hashes;
- typisierte Referenzen ohne Bestaetigungstext oder Nutzinhalt.

Klartext-Principal-IDs, `closed_by`, `created_by`, Request-/Response-Bodies, Passwoerter und der
Human-Confirmation-Text sind im JSON-Beleg durch SQL-Checks verboten.

## API

- `POST /v1/platform/productivity-pilot/real-user-closure-reports`
- `GET /v1/platform/productivity-pilot/real-user-closure-reports/current`

Beide Routen sind tenant-sicher und fuer `security-admin` reserviert. Audit-Metadaten enthalten nur
Hashes, IDs, Zaehler und boolesche Kontrollresultate.

## Betriebsreihenfolge

1. Runtime-Kill-Switch schliessen und den geschlossenen Zustand pruefen.
2. Letzten Window-/Observation-/Domain-Receipt-Stand sichern.
3. Backup isoliert wiederherstellen und Foundation- sowie Business-Release-Gate ausfuehren.
4. Closure als unabhaengiger Security-Admin mit den frischen Recovery-Hashes schreiben.
5. Closure-Beleg erneut sichern und isoliert wiederherstellen.
6. Restore-Ziele stoppen; Runtime-Schalter geschlossen lassen.

Jede spaetere Erweiterung benoetigt eine neue Nomination, Admission, Startfreigabe und ein neues
Runtime-Fenster. Weder Entwicklungs- noch fruehere Realnutzer-Belege autorisieren eine Fortsetzung.
