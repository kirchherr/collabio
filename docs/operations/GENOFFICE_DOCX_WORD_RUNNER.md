# GenOffice DOCX Microsoft Word Interactive Runner

This runbook produces unsigned Microsoft Word evidence for one ADR-0072 synthetic fixture. It never accepts tenant
content and never uses a private signing key. Word runs only in a visible logged-on Windows desktop; preparation and
source-blind collection run in Docker on `dev001`.

## Boundary

- Word execution is forbidden on production systems, operator workstations and any host holding signing custody.
- Use a dedicated, isolated, non-production Windows VM with no tenant credentials, shared clipboard, shared folders or
  host-drive passthrough. Transfer only reviewed synthetic assignments and the exact public handoff.
- Valid fixtures: `formatting-table-fidelity`, `headers-comments-footnotes-fidelity`,
  `unknown-markup-passthrough`.
- The Word account is the dedicated local account `collabio-word-runner` with no Microsoft/Office identity.
- The account must not be able to access `C:\Users\tkirchherr\.collabio\signing`.
- An outbound Windows Firewall rule must block the measured `WINWORD.EXE` path for every destination and profile.
- Preflight and execution must use byte-identical copies of `Invoke-CollabioWordFidelity.ps1`.
- The script embeds the reviewed policy, study-plan, corpus-manifest and three fixture hashes as execution trust anchors.
- Assignment lifetime is eight hours. A fresh assignment is required after expiry or any host/script drift.
- The handoff and collector output directories must exist and be empty.

## One-Time Windows Setup

Run the reviewed host bootstrap only inside the dedicated non-production Windows VM from an elevated Windows
PowerShell console. It creates or converges the dedicated
standard account, removes every local group membership except built-in Users, creates a tightly ACL-bound public
workspace, explicitly denies that account access to signing custody and binds an outbound deny rule to the measured
`WINWORD.EXE`. Passwords are entered twice as `SecureString` and are neither serialized nor logged. The write-once
report contains metadata and hashes only.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\windows\Initialize-CollabioWordFidelityHost.ps1 `
  -Mode Apply `
  -OutputPath .\word-host-bootstrap-report.json
```

The script rejects an existing account with another purpose and a drifted same-name firewall rule. After manual
review, use `-AdoptExistingAccount` or `-ReplaceDriftedFirewallRule` explicitly; use `-RotatePassword` only for a
deliberate credential rotation. Audit without mutation is available with `-Mode Audit` and a fresh output path.

Never perform this setup on the operator workstation or a production system. Log on locally once as
`collabio-word-runner` to initialize its profile. Do not sign the account into Office,
OneDrive, Entra ID or a Microsoft account. If Word requires user-bound cloud activation, stop: that host is not an
eligible isolated runner until approved device-based licensing is available. Remote interactive use remains outside
this procedure.

## 1. Host Preflight

Log on locally as `collabio-word-runner`. Confirm Word is closed. Run from a PowerShell console in that visible session:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\Invoke-CollabioWordFidelity.ps1 `
  -Mode Preflight `
  -OutputPath .\host-readiness-report.json
```

Exit code `0` means `host_ready=true`. Exit code `2` is fail-closed; inspect only `blocking_reasons`. Never edit the
report. Transfer the public report to `dev001`; do not transfer the account profile, credentials, Office cache or any
file below the signing-custody directory.

## 2. Prepare On dev001

Follow `/home/extern/AGENTS.md`, inspect active Compose projects, containers and ports, and hold `build.lock` before
`docker.lock` where both are needed. Create an empty assignment directory and set:

```bash
export SUITE_GENOFFICE_FIDELITY_WORD_HOST_REPORT_PATH=/absolute/path/host-readiness-report.json
export SUITE_GENOFFICE_FIDELITY_WORD_ASSIGNMENT_HOST_DIR=/absolute/path/assignment
export SUITE_GENOFFICE_FIDELITY_WORD_FIXTURE_ID=formatting-table-fidelity
docker compose -p collabio --profile office-worker-runtime-proof run --rm \
  genoffice-docx-fidelity-word-prepare
```

Repeat with a fresh empty generation for each fixture. The service rejects a blocked host report, script drift, an
unknown fixture or a non-empty output.

## 3. Interactive Word Run

Transfer the complete assignment to a runner-account-readable Windows directory. Log on as the dedicated account,
create an empty handoff directory and invoke the script embedded in that assignment:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\assignment\runner\Invoke-CollabioWordFidelity.ps1 `
  -Mode Run `
  -AssignmentRoot .\assignment `
  -HandoffRoot .\interactive-handoff
```

Word must be visibly open before confirmation. Cancel if any unexpected prompt, identity, protected-content request,
add-in UI or non-synthetic content appears. The runner publishes exactly four files only after Word exits cleanly.

## 4. Collect On dev001

Transfer only the four public handoff files to an empty generation on `dev001`. Build and inspect the collector image,
then use its immutable digest:

```bash
docker compose -p collabio --profile office-worker-runtime-proof build \
  genoffice-docx-fidelity-word-collector-image
docker image inspect collabio/genoffice-docx-fidelity-word-collector:dev --format '{{.Id}}'
export SUITE_GENOFFICE_FIDELITY_WORD_COLLECTOR_IMAGE_REF=sha256:<verified-digest>
export SUITE_GENOFFICE_FIDELITY_WORD_ASSIGNMENT_HOST_DIR=/absolute/path/assignment
export SUITE_GENOFFICE_FIDELITY_WORD_HANDOFF_HOST_DIR=/absolute/path/interactive-handoff
export SUITE_GENOFFICE_FIDELITY_WORD_OUTPUT_HOST_DIR=/absolute/path/output
docker compose -p collabio --profile office-worker-runtime-proof run --rm --pull never \
  genoffice-docx-fidelity-word-collector
```

The collector output contains `evidence/` and `handoff/`. The latter contains an unsigned payload, canonical signature
message and collector report. Continue with `GENOFFICE_DOCX_FIDELITY_SIGNING_CEREMONY.md`, then run the independent
ADR-0073 evidence verifier.

## Recovery And Claims

Retain the exact public host report, assignment, four-file Windows handoff, collector image digest, evidence tree,
unsigned payload/message, detached public signature response, signed envelope and independent verification report.
Rebuild every hash and receipt inventory after restore. Exclude the dedicated Windows profile, `%TEMP%`, Office cache,
credentials, DPAPI ciphertext, private keys and transient raster buffers.

Until all three Word rows are signed and independently verified, the study remains `3/9`. Even `6/9` does not prove
cross-engine compatibility, calibrated thresholds, human review or Quick Edit production readiness.
