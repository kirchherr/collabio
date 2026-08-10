# Preview Conversion Production Admission

Stand: 2026-08-10

## Zweck

Die Preview-Konvertierung verarbeitet nicht vertrauenswuerdige Office- und PDF-Dateien. Der technische
`source_object_preview_conversion_execution_gate.v1`-Vertrag reicht deshalb allein nicht fuer einen
Produktions-Dispatch. Er beschreibt den Worker und bindet dessen Laufzeitparameter, kann aber keine realen externen
Dienste, Release-Signaturen oder Browser-Deployment-Nachweise ersetzen.

`preview_conversion_production_admission_gate.v1` ist die zusaetzliche produktive Zulassungsgrenze. Sie bleibt
fail-closed, bis alle folgenden Nachweise gleichzeitig frisch, hashgebunden und von drei getrennten Rollen signiert
sind:

1. ein produktives gVisor-, Kata- oder Firecracker-Hostprofil mit realem Isolationstest;
2. ein tenant-sicher gerouteter Malware-Dienst und ein fail-closed CDR-Dienst mit EICAR- und
   Active-Content-Neutralisierungstest;
3. der exakte Preview-Worker-Image-Digest mit verifizierter Provenance, verifiziertem SBOM, Vulnerability- und
   License-Gate;
4. ein erfolgreicher, nicht-leerer Derived-Preview-Recovery-Report;
5. ein eigener HTTPS-Origin fuer PDF.js mit Browser-Header-Test, restriktiver CSP und minimalem iframe-Sandboxprofil;
6. drei gueltige Ed25519-Signaturen der Rollen `release`, `security` und `operations` ueber dasselbe kanonische
   DSSE/in-toto-Evidence-Bundle.

Das Gate gibt nur den Conversion-Dispatch frei. `preview_serving_allowed` bleibt immer `false`; die bestehende
Preview-Renderer-Release-Gate, ACL-Revalidierung und Content-Release-Grenze bleiben fuer die Anzeige separat
verpflichtend.

## Sicherheitsentscheidung

Die Umsetzung folgt OWASPs Defense-in-Depth-Empfehlung fuer Uploads: Typ-, Groessen- und Signaturpruefung werden mit
Antivirus/Sandbox und, soweit fuer das Format geeignet, CDR kombiniert. Kein einzelner Scanner gilt als
Sicherheitsbeweis. Siehe [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

Fuer den Worker werden Provenance und SBOM getrennt erzeugt und attestiert. Zulassung verlangt die kryptografische
Verifikation gegen den exakten OCI-Digest, die erwartete Repository- und Builder-Identitaet sowie eine aktuelle
Trust Root. Das entspricht der [SLSA-Verifikation](https://slsa.dev/spec/v1.2/verifying-artifacts) und der
[GitHub-Attestation-Verifikation](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).
Offline-Umgebungen verwenden ein mitgefuehrtes Attestation-Bundle und eine aktuelle Trust Root nach
[GitHubs Offline-Verfahren](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline).

PDF.js laeuft als JavaScript mit Browser-Rechten. Der Viewer wird deshalb nicht im Anwendungs-Origin betrieben.
MDN weist darauf hin, dass untrusted Inhalte auch bei direktem Oeffnen aus einem getrennten Origin ausgeliefert
werden sollen; die Kombination `allow-scripts` und `allow-same-origin` ist bei einem gleich-originigen Parent nicht
ausreichend. Siehe [MDN iframe security](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)
und [OWASP CSP](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html).

## Provider-Strategie

Die Gate ist provider-neutral. Der erste produktive Adapter soll ClamAV/`clamd` fuer Malware-Erkennung verwenden;
Signaturen muessen durch `freshclam` aktualisiert und ihre Frische nachgewiesen werden. Der Collabio-eigene
ClamAV-`INSTREAM`-Adapter, interne Compose-Dienst und Clean-/EICAR-Smoke sind inzwischen als
development-only Eingang implementiert. Sie erfuellen die produktive Evidence noch nicht, weil signierte
Signaturdatenbank-Provenance, HA-/Failover-Nachweis und produktive Netzwerkpolicy weiterhin fehlen.

Der Collabio-eigene Pixel-CDR-Pfad ist development-only real implementiert und auf `dev001` nachgewiesen. Ein erster
`runsc`-Prozess rendert das nicht vertrauenswuerdige Dokument in exakt validierte rohe RGB-Seiten; ein zweiter
`runsc`-Prozess rekonstruiert daraus das PDF, ohne Source-Volume, Netzwerk, Credentials oder Bilddatei-Parser. Manifest,
Seitenreihenfolge, Dimensionen, Byte-Laengen und Hashes sind fail-closed gebunden. Die Architektur folgt dem bewaehrten
[Dangerzone-Modell](https://dangerzone.rocks/about/), ohne Dangerzone selbst einzubetten. Damit bleiben verschachtelte
Container-Runtimes und die AGPL-3.0-Integrationsfrage ausserhalb des Collabio-Runtime-Kerns. Fuer Produktion fehlen
weiterhin unabhaengige Active-Content-Fixtures, CDR-HA-/Failover-Evidence, Engine-Provenance und die signierte
Drei-Rollen-Zulassung. Details: `docs/operations/PREVIEW_CDR.md`.

Ein kommerzieller CDR-Dienst kann denselben Vertrag implementieren. Anbieterwechsel veraendern weder Gate noch
Worker-Protokoll, sondern nur Deployment-, Profil-, Test- und Versionsnachweise.

## Evidence und Signatur

Die Dateien enthalten ausschliesslich Metadaten, Hashes, oeffentliche Schluessel und Signaturen. Dokumentinhalte,
Secrets, private Schluessel, Scanner-Ausgaben mit Inhalt oder Provider-Credentials sind verboten.

Erforderliche Eingaben:

- `preview-conversion-production-evidence.json`
- `preview-conversion-execution-gate.json`
- `derived-preview-recovery-drill.json`
- `preview-conversion-production-attestation.dsse.json`
- `preview-conversion-signers.json` aus einem deployment-kontrollierten Trust Store

Die drei Signaturen muessen von unterschiedlichen Principals stammen. Widerruf, abgelaufene Keys, ungueltige
Signaturen, ein fremder Tenant, ein anderer Image-Digest, ein anderer Runtime-/Scanner-/CDR-/CSP-Hash, synthetische
Provider oder Evidence aelter als das konfigurierte Fenster blockieren die Freigabe.

## Ausfuehrung

Die Compose-Gate hat kein Netzwerk, ein read-only Root-Filesystem, keine Linux-Capabilities und keine Credentials:

```bash
docker compose --profile preview-production-admission run --rm \
  preview-conversion-production-admission-gate
```

Das Ergebnis wird als `backups/preview-conversion-production-admission-gate.json` geschrieben. Ein blockiertes Gate
beendet sich mit Exit-Code `2`. Der produktive `preview-conversion-worker` startet nur mit
`--production-admission-required`. Er liest Gate, Evidence-Bundle, Recovery-Report, DSSE-Envelope und den aktuellen
oeffentlichen Signer-Truststore read-only, reproduziert die Gate deterministisch und verifiziert alle drei
Signaturen erneut zum Dispatch-Zeitpunkt. Danach prueft er Gate-Hash, Tenant, Execution-Gate, Worker-Digest und
Gueltigkeitsfenster. Der Auftrag selbst wird vor dem Dispatch ueber
`bind_preview_conversion_command_to_production_admission(...)` an den Gate-Hash gebunden; der Worker-Result erbt
diesen Hash.

Ohne echte Produktionsnachweise wird keine Gate-Datei erzeugt und keine Freigabe behauptet.
