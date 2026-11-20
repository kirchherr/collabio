# MVP Foundation Completion Workflow

Stand: 2026-09-17

## Zweck

Der Workspace verbindet die beiden operativ ausfuehrbaren MVP-Gaps
`preview_decisions_pending` und `module_activation_work_items_open` in einem kontrollierten Abschluss-Workflow.
Er ersetzt keine Backend-Autorisierung. Jeder Schreibschritt nutzt weiterhin ausschliesslich die bestehenden,
tenant-sicheren Preview- und Module-Lifecycle-APIs.

## Ablauf

1. Das Cockpit erzeugt aus den aktuellen `foundation_gap_actions`, Work-Items, SourceObject-Flows und Modulzustaenden
   einen tenant-spezifischen Plan.
2. Der Dialog zeigt jede Aufgabe und alle beabsichtigten Statuswechsel. Ein neues Modul wird als
   `provision -> enable` ausgewiesen.
3. Der Bediener bestaetigt den angezeigten Tenant und die Anzahl der Aufgaben durch eine exakte Eingabe und eine
   separate Checkbox.
4. Unmittelbar vor dem ersten Schreibzugriff wird das Cockpit erneut vom Server gelesen. Bei geaenderten Rollen,
   ACLs, Work-Items, Objektversionen, Modulzustaenden oder Gap-Aktionen wird der Plan verworfen.
5. Preview-Aufgaben erfassen Renderer-Sandbox-Evidence und danach eine metadata-only Preview-Decision. Modulaufgaben
   fuehren nur die vorab angezeigten `provision`- und `enable`-Transitionen aus.
6. Nach jedem logischen Arbeitspunkt wird der Fortschritt sichtbar aktualisiert. Nach Abschluss wird der
   authoritative Cockpit-Stand neu geladen und kontrolliert, ob beide Ziel-Gaps entfernt sind.

## Sicherheitsgrenze

- Die UI akzeptiert nur Work-Items mit `metadata_only=true`, `content_included=false`,
  `persistent_task_created=false`, `destructive=false` und `external_side_effect=false`.
- Modulstatuswechsel bleiben an `tenant-admin` oder `security-admin` und die serverseitige Lifecycle-State-Machine
  gebunden.
- Die eingegebene Bestaetigung wird nicht als Fachinhalt persistiert. Die vorhandenen APIs schreiben ihre eigenen
  namespaced Approval-, Audit- und Ledger-Referenzen.
- Der Workflow gibt keine SourceObject-Inhalte frei. `content_release_allowed` bleibt durch die separate Preview-
  Release-Policy bestimmt.
- Admission, Traffic-Freigabe, Pilotstart, Fachmodul-Writes, Automationen sowie externe und destruktive Aktionen sind
  nicht Teil dieses Workflows.

## Fehler- und Wiederanlaufverhalten

Die Operationen sind absichtlich nicht als scheinbar atomare Cross-Domain-Transaktion dargestellt. Ein bereits
erfolgreich auditierter Schritt wird bei einem spaeteren Fehler nicht rueckgaengig gemacht. Der Dialog stoppt, zeigt
den fehlgeschlagenen Arbeitspunkt und verlangt vor einer Fortsetzung einen neuen Cockpit-Plan. Dadurch werden nur die
noch offenen, aktuell autorisierten Schritte erneut angeboten.

## Betriebsgrenze

Deployment und Tests aktivieren keine Module und erzeugen keine Preview-Decisions fuer einen realen Tenant. Eine
Ausfuehrung beginnt ausschliesslich durch die explizite Bestaetigung im geoeffneten Workspace-Dialog.
