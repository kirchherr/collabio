# Real-user Productivity Pilot Readiness

Stand: 2026-08-14

## Zweck

`productivity_pilot_real_user_readiness.v1` ist das tenant-sichere, rein lesende Lagebild fuer den
Realnutzer-Pilot. Es fasst die bereits vorhandenen append-only Kontroll-Ledger zu genau einem
aktuellen Pilotzyklus zusammen und nennt den naechsten zulaessigen Schritt.

Das Read Model erzeugt keine Nomination, Admission, Startfreigabe, Runtime-Aktivierung oder
Closure. Es aendert den deploymentweiten Kill-Switch nicht und fuehrt weder Fachschreibvorgaenge
noch externe oder destruktive Aktionen aus.

## API

- `GET /v1/platform/productivity-pilot/real-user-readiness`
- Zugriff: `tenant-admin` oder `security-admin`
- Ergebnis: Metadaten, Evidenz-Hashes, Zeitpunkte, Zaehler, Blocker und naechste Aktion
- Ausgeschlossen: Klartext-Principal-IDs, Dokument- oder Fachdaten, Request-/Response-Bodies und
  Secrets

Jeder erfolgreiche Read wird mit Tenant, Stufe, Zaehlern, Evidenz-Hashes und Ergebnis-Hash
auditiert. Der Actor wird durch den bestehenden Audit-Kontext erfasst und nicht in das Read Model
kopiert.

## Lebenszyklus

Das Read Model unterscheidet:

1. `nomination_required`
2. `admission_required`
3. `start_chain_required`
4. `runtime_window_required`
5. `runtime_active`
6. `closure_required`
7. `closed`

Vor jeder Einstufung werden die Evidenz-Hashes von Nomination, Admission, Startfreigabe,
Runtime-Fenster, Beobachtungen und Closure neu berechnet. Bindungen zwischen Teilnehmermanifest,
Zeitfenstern, Preflight, Route Scope und den jeweiligen Vorgänger-Hashes werden erneut geprüft.

Ein gueltiger Beleg aus einem frueheren Zyklus ist kein aktueller Beleg. Er wird als vorheriger
Zyklus ausgewiesen und nicht in `available_evidence` uebernommen. Ein manipulierter Hash oder eine
widerspruechliche Bindung schliesst den Endpunkt mit `503`.

## Betriebsregel

Vor jedem menschlichen Pilotschritt zuerst das Read Model abrufen und nur die dort genannte
Evidenzstufe bearbeiten. `runtime_activation_authorized` bleibt in diesem Read Model immer
`false`; die ausfuehrenden Grenzen verlangen weiterhin ihre eigenen Human-Approval-,
Production-Continuity- und Kill-Switch-Pruefungen.

Ohne reale Nomination zeigt der aktuelle Entwicklungsstand erwartungsgemaess
`nomination_required`. Es werden keine Platzhalterpersonen und keine Scheinevidenz erzeugt.

## Backup und Wiederanlauf

Das Read Model besitzt keine eigene Persistenz. Es wird nach Neustart oder Failover aus den
append-only Pilot-Ledgern rekonstruiert. Die bestehenden Backup-/Restore-Vertraege fuer diese
Ledger bleiben daher autoritativ; das Read Model ist nach Restore erneut abzurufen und muss
denselben aktuellen Zyklus sowie dieselben Evidenz-Hashes ableiten.
