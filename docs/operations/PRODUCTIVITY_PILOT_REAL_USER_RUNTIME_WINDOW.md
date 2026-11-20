# Real-user Productivity Pilot Runtime Window

Stand: 2026-08-04

## Zweck

Diese Grenze verbindet eine unabhaengig genehmigte Realnutzer-Aufnahme mit einer frischen
Productivity-Pilot-Startkette, ohne Klartext-Principal-IDs in Runtime- oder Beobachtungsbelegen zu
persistieren. Sie ist eine technische Voraussetzung fuer einen spaeteren, bewusst freigegebenen
Realnutzer-Pilot. Sie oeffnet den deploymentweiten Runtime-Kill-Switch nicht.

## Sicherheitskette

Eine Aktivierung ist nur moeglich, wenn alle folgenden Bedingungen gleichzeitig gelten:

1. Der aufrufende Actor besitzt die autoritativ aufgeloeste Rolle `tenant-admin`.
2. Der deploymentweite Schalter `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED` ist explizit gesetzt.
3. Aktuelle Nomination und Security-Admission sind hashvalide und exakt miteinander verbunden.
4. Die aktuelle Startfreigabe wurde nach der Realnutzer-Admission erstellt, nutzt denselben
   Preflight-Hash und liegt vollstaendig im genehmigten Realnutzer-Zeitfenster.
5. Alle uebergebenen Principal-IDs werden nur fuer diesen Request gegen das Tenant-IAM aufgeloest.
6. Die resultierenden tenant-gebundenen Principal-Hashes entsprechen exakt der Admission.
7. Die aktuellen autoritativen Rollen entsprechen exakt dem Rollen-Snapshot der Nomination.
8. Runtime-Operator, Nominator, Security-Approver, Start-Authorizer und Pilot-Teilnehmer sind getrennt.

Nach einer vorhandenen Realnutzer-Admission lehnt der API-Pfad neue Runtime-v1-Fenster ab. Der
Request-Gate verwendet dann ausschliesslich die hash-only Realnutzer-Runtime.

## Persistenz

Migration `0067_productivity_pilot_real_user_runtime_window.sql` erstellt:

- `collabio.productivity_pilot_real_user_runtime_windows`;
- `collabio.productivity_pilot_real_user_runtime_observations`.

Migration `0068_productivity_pilot_real_user_runtime_policy_name.sql` ersetzt den von PostgreSQL
automatisch gekuerzten Delete-Policy-Namen durch einen expliziten, stabilen Identifier.

Migration `0071_productivity_pilot_real_user_runtime_owner_ref.sql` verhindert zusaetzlich, dass
Klartextidentitaeten ueber `operations_owner_ref` in das hash-only Window-Ledger gelangen.

Beide Tabellen sind tenant-isoliert, erzwingen RLS, sind per Policy und Trigger append-only und
erlauben der Runtime-Rolle nur `SELECT` und `INSERT`. Runtime-Fenster enthalten nur
`designated_principal_hashes` und `activated_by_principal_hash`. Beobachtungen enthalten nur den
tenant-gebundenen `principal_id_hash`, Operation, Zeit und Evidenzbindungen. Request-/Response-Bodies,
Passwoerter, Bestaetigungstexte und Klartext-Principal-IDs sind durch Modell- und SQL-Grenzen verboten.

## Laufzeitpruefung

Jeder verwaltete API-Zugriff prueft erneut:

- Kill-Switch, Zeitfenster und freigegebene Route;
- aktuelle Start-, Admission- und Nomination-Evidenz;
- aktiven Tenant-Principal;
- unveraenderte autoritative Rollen;
- Zugehoerigkeit zum genehmigten Hash-Manifest.

Nur erfolgreiche Entscheidungen erzeugen eine metadata-only Beobachtung. Rollen-Drift, deaktivierte
Principals, fremde Routen, fremde Principals, abgelaufene Fenster oder ein geschlossener Kill-Switch
werden fail-closed abgewiesen.

## API

- `POST /v1/platform/productivity-pilot/real-user-runtime-windows`
- `GET /v1/platform/productivity-pilot/real-user-runtime-windows/current`

Der POST-Body darf Principal-IDs enthalten, damit das autoritative IAM aufgeloest werden kann. Diese
IDs sind transient und erscheinen weder im Response noch im Audit-Metadatum oder Datenbankbeleg.

## Betriebsreihenfolge

1. Entwicklungs-Pilot und Closure bleiben unveraendert erhalten.
2. Tenant-Admin nominiert reale Teilnehmer mit Zweck-, Privacy- und Rollenbelegen.
3. Security-Admin genehmigt nach frischem Preflight, Backup und Restore.
4. Admission, Traffic Scope und Startfreigabe werden neu erzeugt; Entwicklungsbelege werden nicht
   wiederverwendet.
5. Vor dem ersten Live-Oeffnen des Kill-Switches wird der vorhandene hash-only Realnutzer-Closure-Pfad
   aus `docs/operations/PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT.md` mit Backup und isoliertem
   Restore abgenommen.
6. Erst nach dieser technischen Abnahme und den realen Human-/Privacy-Freigaben kann ein zeitlich
   begrenztes Realnutzer-Runtime-Fenster aktiviert werden.

Bis Schritt 6 bleibt der Runtime-Schalter geschlossen. Die vorhandene API und Migration sind
Vorbereitung, keine Freigabe fuer reale Produktivdaten.
