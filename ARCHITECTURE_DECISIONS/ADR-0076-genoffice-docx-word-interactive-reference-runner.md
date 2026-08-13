# ADR-0076: GenOffice DOCX Word Interactive Reference Runner

- Status: Accepted
- Date: 2026-08-13
- Scope: Synthetic Office Quick Edit fidelity evidence only
- Supersedes: none
- Extends: ADR-0071, ADR-0072, ADR-0073, ADR-0075

## Context

ADR-0072 requires Microsoft Word reference results for three synthetic DOCX fixtures. Word is valuable as the format
owner's desktop implementation, but Microsoft does not support Office client automation from unattended,
non-interactive applications, services, DCOM or server-side processes. Office assumes an interactive desktop and a
user profile and may display modal UI. Running `WINWORD.EXE` in Docker, as a service, through Task Scheduler without a
logged-on user, or as a multi-tenant conversion backend is therefore outside this architecture.

The Word runner also cannot share the operator's Office identity, tenant credentials or locally held Fidelity signing
keys. Evidence processing must remain reproducible on `dev001`, where Word cannot run. The design consequently needs
an explicit desktop execution boundary and a separate source-blind collector.

## Decision

Collabio adds a two-stage Microsoft Word reference path.

The Windows stage is `tools/windows/Invoke-CollabioWordFidelity.ps1`. It has only `Preflight` and `Run` modes and must
execute in a logged-on, non-session-zero desktop under the dedicated local `collabio-word-runner` account. Preflight
fails closed unless all of the following are true:

1. The account is local and has the exact dedicated name.
2. No known Office, OneAuth, AAD or stored Office identity is present in that account profile.
3. The operator Fidelity signing-custody directory is inaccessible.
4. Microsoft Word is installed and no Word process is already running.
5. An active outbound Windows Firewall rule blocks `WINWORD.EXE` for every destination.
6. The runner script, Word executable, Windows build, PowerShell version and canonical font inventory are measured.

Preflight writes a public metadata-only `genoffice_docx_word_host_readiness_report.v1`. It contains no document
content, credentials or key material. A blocked report is useful diagnostic evidence but cannot create an assignment.

The no-network `dev001` prepare service accepts only `host_ready=true`, verifies the exact runner-script hash and
materializes one write-once, eight-hour assignment. The assignment contains the canonical policy, study plan, corpus
manifest, one exact synthetic fixture and one exact runner script. Tenant content, tenant credentials, private keys,
external side effects, unattended execution and product writes are forbidden by schema.

During `Run`, the Windows script revalidates the exact assignment tree, request hash and lifetime, source hash,
synthetic corpus binding and current host state. The reviewed policy, plan, corpus and three fixture hashes are
compiled into the script as trust anchors, so a self-consistently rehashed foreign assignment cannot reach Word. It
sets Word `AutomationSecurity` to
`msoAutomationSecurityForceDisable`, opens the source read-only without adding it to recent files, keeps Word visible,
exports a source reference PDF, and requires an explicit modal confirmation. It then uses `SaveAs2` for a DOCX
round-trip and exports the candidate PDF with the same Word process. The original automation-security setting is
restored and Word must exit before any write-once handoff is published.

The Windows handoff contains exactly `output.docx`, `reference.pdf`, `candidate.pdf` and a metadata-only interactive
receipt. It is unsigned. The runner never reads or uses an Ed25519 key.

The `word-fidelity-collector` image on `dev001` consumes the original assignment and public Windows handoff under
`runsc-kvm`, with no network, read-only input mounts, read-only root, dropped capabilities, no-new-privileges and a
bounded private `tmpfs`. It performs source-blind output preflight, structural fingerprinting, Open XML SDK 3.5.1
validation against Office 2021, PDF rasterization at 144 DPI, integer visual comparison, exact evidence inventory and
canonical signature-message generation. The collector has no Word installation, Office profile, tenant credential or
private key.

ADR-0075 performs detached signing after collection, and ADR-0073 independently verifies all retained evidence bytes.
No stage may infer a compatibility claim, calibrated threshold, human review result or Quick Edit completion merely
from successful Word execution.

## Rejected Alternatives

- Unattended Word in a Windows service, scheduled background task, DCOM host, VM service or container: unsupported by
  Microsoft and incompatible with the required visible human confirmation.
- Word under the operator's normal account: Office identities, cached tenant credentials and signing custody would
  share one trust boundary.
- Signing inside the Word script: this would mix engine execution and key custody and make the handoff non-auditable.
- Rendering the source with a different engine: reference and candidate PDFs must come from the same measured Word
  instance before cross-engine comparison.
- Sending raw documents to a cloud Office or AI API: unnecessary for the synthetic baseline and forbidden without a
  separate tenant policy and data-processing decision.

## Consequences

- Word remains a manual reference instrument, not a Collabio runtime dependency or scalable conversion service.
- The dedicated account and outbound firewall rule are host prerequisites and require an operator setup step.
- A real result exists only after interactive execution, isolated collection, detached signing and independent
  evidence verification.
- The current authenticated matrix remains `3/9` until all three Word results are actually produced and verified.
- Public schemas, assignments, receipts, outputs and evidence are recoverable records. Office profiles, temporary
  workspaces, credentials, DPAPI ciphertext and every private-key representation are excluded from backup transfer.

## References

- [Microsoft: Considerations for server-side Automation of Office](https://support.microsoft.com/en-US/Visio/considerations-for-server-side-automation-of-office)
- [Word Application.AutomationSecurity](https://learn.microsoft.com/en-us/office/vba/api/word.application.automationsecurity)
- [Word Document.SaveAs2](https://learn.microsoft.com/en-us/office/vba/api/word.saveas2)
- [Word Document.ExportAsFixedFormat](https://learn.microsoft.com/en-us/office/vba/api/word.document.exportasfixedformat)
