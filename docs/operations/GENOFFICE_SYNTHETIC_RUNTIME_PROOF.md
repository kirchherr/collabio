# GenOffice Synthetic Runtime Proof

This boundary prepares the first GenOffice engine evaluation without opening tenant, import or production use. The
corpus and sandbox proof can be completed by the solo founder. Engine execution still requires two real people and two
independent Ed25519 signatures.

## What Exists Now

- deterministic five-file synthetic OOXML corpus;
- hash-bound `runsc` no-egress sandbox profile;
- Docker HostConfig and in-container isolation-probe contract;
- 24-hour two-person runtime request, response, envelope and report contracts;
- Compose profile `office-worker-runtime-proof`;
- a status-only worker image that still exits with code `78`.

The sandbox report proves isolation controls only. It sets `engine_executed=false` and
`runtime_authorization_granted=false`; it cannot be presented as a fidelity result.

## Synthetic Corpus

The generator creates only deterministic, public, non-personal fixtures:

| Fixture | Boundary | Engine |
| --- | --- | --- |
| `minimal-formatting.docx` | parse/save fidelity for text formatting and a table | allowed after approval |
| `deep-xml-passthrough.docx` | parser resilience and byte-preserving passthrough | allowed after approval |
| `remote-relationship-no-egress.docx` | external relationship must never be fetched | allowed after approval |
| `declared-zip-bomb.docx` | declared 600 MiB parts must be rejected | allowed after approval |
| `active-content-preflight-rejection.docm` | inert macro marker must be rejected before parsing | forbidden |

Any byte change produces a different artifact and manifest hash and invalidates an existing signing request.

## Materialize Public Evidence

Run only on `dev001`, from `/home/extern/collabio`, with Compose project `collabio`. Inspect projects, containers and
ports first and hold the coordination locks required by `/home/extern/AGENTS.md`.

Prepare dedicated generation directories with mode `0700`, then run the control service separately for each write-once
artifact:

```bash
SUITE_GENOFFICE_RUNTIME_PROOF_MODE=corpus \
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-runtime-proof-control

SUITE_GENOFFICE_RUNTIME_PROOF_MODE=sandbox-profile \
docker compose -p collabio --profile office-worker-runtime-proof run --rm --no-deps \
  genoffice-runtime-proof-control
```

`SUITE_GENOFFICE_RUNTIME_CORPUS_HOST_DIR` and `SUITE_GENOFFICE_RUNTIME_EVIDENCE_HOST_DIR` must point at the new
generation. Never reuse an older output directory.

## Sandbox Probe

Create, inspect and then start the exact probe container. Do not replace the Docker inspect document with handwritten
JSON.

```bash
docker compose -p collabio --profile office-worker-runtime-proof create \
  genoffice-runtime-sandbox-probe
docker inspect collabio-genoffice-runtime-sandbox-probe-1 \
  > "$SUITE_GENOFFICE_RUNTIME_EVIDENCE_HOST_DIR/genoffice-runtime-sandbox-probe.inspect.json"
docker compose -p collabio --profile office-worker-runtime-proof start \
  genoffice-runtime-sandbox-probe
docker compose -p collabio --profile office-worker-runtime-proof logs --no-log-prefix \
  genoffice-runtime-sandbox-probe \
  > "$SUITE_GENOFFICE_RUNTIME_EVIDENCE_HOST_DIR/genoffice-runtime-sandbox-probe-report.json"
```

Grant UID `10003` read-only ACL access to the corpus, profile and inspect evidence before container creation. The
evidence bind itself remains read-only; the operator captures the single canonical JSON line from Docker logs into the
write-once report. The verifier requires `Runtime=runsc`, `NetworkMode=none`, a read-only root, `CapDrop=ALL`,
no-new-privileges, the exact CPU/memory/PID limits, read-only corpus and exact tmpfs. It then requires network/DNS
failure and empty scratch.

### Current dev001 Result

The 12 August 2026 preflight is fail-closed. Docker created the exact probe container and its inspect evidence confirms
`User=10003:10003`, `Runtime=runsc`, `NetworkMode=none` and `ReadonlyRootfs=true`. Starting the container failed before
its process was created with a `runsc` sandbox startup EOF. A separate minimal Alpine container using `runsc` also
failed before process creation with `fork/exec /proc/self/exe: resource temporarily unavailable`. Host PID, memory,
disk and user-namespace limits were not exhausted at observation time.

No in-container probe report exists for this attempt, no engine executed and no runtime authorization was granted.
Do not substitute `runc`, weaken the profile or treat Docker inspect evidence alone as an isolation proof. Repair or
replace the `dev001` gVisor installation, then repeat the complete create-inspect-start sequence in a new immutable
evidence generation.

The host diagnosis identified Ubuntu's AppArmor restriction for unprivileged user namespaces as an immediate blocker.
Keep the primary global AppArmor userns restriction enabled. Install the repository-controlled, path-bound exception for the
package-managed `/usr/bin/runsc`; it grants only the AppArmor `userns` permission and does not restart Docker:

```bash
cd /home/extern/collabio
sudo ./security/apparmor/install-runsc-profile.sh
sudo ./security/apparmor/verify-runsc-profile.sh
```

The installer validates the Debian package owner, root ownership, mode and profile syntax. It refuses to overwrite a
different host profile. The verifier requires exact repository/host bytes, a loaded profile and the primary Ubuntu
AppArmor unprivileged-userns restriction still set to `1`. It records the separate unprivileged-unconfined restriction
without changing it; on the shared `dev001` host this additional control is currently `0` and needs a separate
cross-project impact review. Installing the profile is host preparation only and grants no Collabio runtime
authorization.

On the bare-metal `dev001` host, the default `systrap` platform still fails before process creation after that profile
is loaded. Keep the existing `runsc` Docker runtime unchanged and add the independently named `runsc-kvm` runtime:

```bash
cd /home/extern/collabio
flock /home/extern/.codex-coordination/docker.lock \
  sudo ./security/gvisor/install-runsc-kvm-runtime.py
sudo ./security/gvisor/verify-runsc-kvm-runtime.py
```

The installer requires verified bare metal, `/dev/kvm`, loaded vendor KVM modules, package-managed `runsc`, the exact
loaded AppArmor profile and the enabled primary userns restriction. It adds only `runsc-kvm` with `--platform=kvm`,
validates a
temporary daemon configuration before atomic replacement, keeps a root-only rollback copy, reloads rather than
restarts Docker and fails if any previously running container disappears. The GenOffice probe is pinned to this named
runtime; existing Collabio, Tricert and Webcut runtime selection does not change.

## Two-Person Ceremony

Enroll two different accountable humans in `genoffice_runtime_signer_policy.v1`. Key generation and signing happen in
the approved external KMS/HSM or signing workstation; Collabio receives only raw public keys and detached signature
responses.

Create the canonical request with `SUITE_GENOFFICE_RUNTIME_PROOF_MODE=request`. It binds:

- current worker image admission and its expiry;
- image configuration/archive, SBOM and vulnerability report;
- corpus and sandbox profile;
- exact fixture split between engine and preflight-only processing;
- risk acceptance, change control and a maximum 24-hour window.

Each assigned signer verifies the request and message hashes and returns one
`genoffice_runtime_signature_response.v1`. Run `assemble`, then `verify`. Missing, duplicated, swapped, expired,
tampered or wrong-key responses fail closed. A solo-founder key used in both roles is invalid even when both signatures
are cryptographically valid.

## Still Blocked

The following are intentionally not implemented or authorized by this boundary:

- changing or bypassing the status-only worker entry point;
- parsing any fixture before two-person authorization;
- tenant or customer document processing;
- source import or persistent document writes;
- fidelity claims, Word/LibreOffice comparison or safe export;
- Hosted Service, On-Prem distribution or production.

The next implementation is a newly attested proof harness and image generation. It consumes only a currently valid
runtime authorization report, processes the four engine-authorized fixtures in `runsc`, emits content-free hashes and
metrics, destroys scratch, and remains incapable of product writes.

## Backup And Restore

Preserve every public file in one immutable generation: corpus, manifest, sandbox profile, raw Docker inspect evidence,
probe report, public signer policy/key material, request, exact message, responses, envelope and authorization report.
Exclude private keys and scratch. A restore must re-run schema/hash/signature checks and prove all general execution,
tenant, import, network, persistence, distribution and production flags are still false. Restored or expired approvals
never authorize a new run.
