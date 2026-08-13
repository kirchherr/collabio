# GenOffice Synthetic Runtime Proof

This boundary prepares the first GenOffice engine evaluation without opening tenant, import or production use. The
corpus and sandbox proof can be completed by the solo founder. Engine execution still requires two real people and two
independent Ed25519 signatures.

## What Exists Now

- deterministic five-file synthetic OOXML corpus;
- hash-bound `runsc-kvm` no-egress sandbox profile;
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
  > /tmp/genoffice-runtime-sandbox-probe.inspect.json
docker compose -p collabio --profile office-worker-runtime-proof run -T --rm --no-deps \
  genoffice-runtime-proof-access-preparer \
  > /tmp/genoffice-runtime-proof-access-receipt.json
docker compose -p collabio --profile office-worker-runtime-proof start \
  genoffice-runtime-sandbox-probe
docker compose -p collabio --profile office-worker-runtime-proof logs --no-log-prefix \
  genoffice-runtime-sandbox-probe \
  > /tmp/genoffice-runtime-sandbox-probe-report.json
```

Validate each temporary JSON file before moving it into its absent final path with mode `0600`. The temporary path is
intentional: shell redirection must not create a zero-byte file inside the evidence generation before the access
preparer inventories unrelated evidence. Use `-T` so Compose cannot consume the remaining operator script as TTY
input. Capture the final exited container state before removal. Preflight and lock steps are omitted from the compact
example but remain mandatory around every lifecycle operation.

The access preparer runs as a confined root helper with no network, a read-only root filesystem, no Docker socket and
only `CHOWN`, read-only `DAC_READ_SEARCH`, and `FOWNER`. Root is required because Docker does not retain those
effective capabilities across `exec` for the non-root artifact owner. The helper validates the expected host owner,
canonical corpus, profile and raw inspect bytes before changing metadata, rejects symlinks and ownership drift, and
changes only the known synthetic inputs to group `10003` with modes `0640/0750`.
It proves content hashes were preserved and unrelated host evidence was untouched. Do not substitute POSIX ACLs:
gVisor `directfs` did not expose the host ACL grant to the sandbox on `dev001`. Do not make the evidence world-readable.

The evidence bind itself remains read-only in the probe; the operator captures the single canonical JSON line from
Docker logs into the write-once report. The verifier requires a digest-addressed image, `Runtime=runsc-kvm`,
`NetworkMode=none`, a read-only root, `CapDrop=ALL`, no added capabilities, no privileged mode, no host devices,
no-new-privileges, the exact CPU/memory/PID limits, exact read-only `/corpus` and `/evidence` bind mounts and exact
tmpfs. Probe code must come from the image rather than a host application bind. In process it requires every
capability set exposed by `/proc/self/status` to be zero; when gVisor exposes `NoNewPrivs`, its value must be `1`.
It then requires network/DNS failure and empty scratch.

### Current dev001 Result

Generations 01 through 03 are preserved as fail-closed evidence. They exposed the original `systrap` startup failure,
the fact that gVisor `directfs` does not expose the host POSIX ACL grant, and one transient KVM sandbox-start EOF.
Generation 04 completed the narrower first in-container proof. Self-review then identified that its verifier code came
from a host bind and did not prove an exact mount/device inventory. Generation 05 preserved the strict new check's
fail-closed result while confirming that this gVisor build omits the optional `NoNewPrivs` status line even though all
five process capability sets are zero. Failed states remain separate from the final generation.

Generation `runtime-proof-preflight-20260813-06` is the completed hardened proof. Its exact container
`666e3f3c5b95...` used image `sha256:b68e4ad5d72698586013c0c6e9d0d5f13a0f92c5a0ff0463775482b4e9892646`,
exited `0`, and verified its own hostname against the full container ID in the raw inspect document. The immutable
evidence chain is:

- corpus manifest `sha256:2d0d98971107053a42c7318bf397b3a7fb674cfc758268ff486e5331d81577eb`;
- sandbox profile `sha256:9fe2c1bd9037ca7ef62d43fb5e763249af806e0394ac6084c1cd212323a4ec40`;
- inspect file SHA-256 `bb5dfc7dedb18e3a9eab62136cd76df9537b876b86f2a6f333ffd07548f1d544`;
- access-receipt file SHA-256 `f041a27dd053f2e2ddfeed190a0cf5fcdade81084406fc660198c4c13d8ac0ab`;
- probe-report file SHA-256 `f7f58d21015c0c5688cd3eff91582fe64c9238baf0669ddbb61b057386c29d1e`;
- final-state file SHA-256 `fb137db647ca8348b5c46565cb1858c87e454559bcc54249f75fee0862945b63`;
- internal probe report `sha256:e87ce2ed574e69ff1801b7c6ec0669e16f13341d366dfdf49b460fdff8ad5cfd`.

The report verifies container identity, image-bound probe code, exact read-only mount inventory, absent host devices,
`runsc-kvm`, no network or DNS, read-only root and corpus, empty process capabilities, no-new-privileges HostConfig,
exact CPU/memory/PID limits and clean scratch. It still states `engine_executed=false`,
`tenant_content_included=false`, `external_network_used=false` and `runtime_authorization_granted=false`.

The root host-verifier receipt remains incomplete until a non-empty JSON result from
`security/gvisor/verify-runsc-kvm-runtime.py` has been schema-checked and moved write-once into Generation 06. An empty
or failed redirect is diagnostic evidence only and must never be counted as verification.

The host diagnosis identified Ubuntu's AppArmor restriction for unprivileged user namespaces as an immediate blocker.
Keep the primary global AppArmor userns restriction enabled. Install the repository-controlled, path-bound exception
for the package-managed `/usr/bin/runsc`; it grants only the AppArmor `userns` permission and does not restart Docker:

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
validates a temporary daemon configuration before atomic replacement, keeps a root-only rollback copy, reloads rather than
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
