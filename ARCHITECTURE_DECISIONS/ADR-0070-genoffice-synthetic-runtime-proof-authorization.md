# ADR-0070: GenOffice Synthetic Runtime Proof Authorization

Status: accepted
Date: 2026-08-12

## Context

ADR-0069 admits one reproducible development worker image but deliberately leaves its entry point status-only. An image
signature is not permission to execute a parser. Runtime evaluation introduces a separate attack surface: hostile ZIP
containers, deeply nested XML, external OOXML relationships, active content, resource exhaustion, sandbox escape,
temporary plaintext and output persistence.

The present organization cannot honestly satisfy a two-person control. The technical path must therefore be complete
and testable without inventing a second approver or quietly treating the solo-founder build exception as runtime
approval.

## Decision

- Introduce an independent `genoffice_runtime_signer_policy.v1` whose sole purpose is
  `synthetic_docx_fidelity_proof`. It requires exactly one active `product_owner` and one active
  `security_compliance_owner`, with different people and different Ed25519 keys.
- Sign a canonical runtime payload independently with both keys. The payload expires after at most 24 hours and is
  bounded by the worker-image admission expiry.
- Bind the payload to the exact worker admission report, image configuration, image archive, image SBOM,
  vulnerability report, synthetic corpus manifest and sandbox profile.
- Permit only the named synthetic fixtures. General worker execution, tenant content, source import, durable document
  writes, network access, Hosted Service, On-Prem distribution and production remain false.
- Generate the corpus independently in Collabio. It contains formatting/table fidelity, deeply nested XML,
  an external relationship, a declared ZIP bomb and an inert macro marker. Active content is preflight-only and may
  never reach the engine.
- Pin the sandbox to the separately named gVisor `runsc-kvm` runtime on verified bare metal, `network_mode: none`,
  read-only root and corpus, no capabilities, no new
  privileges, fixed UID/GID, CPU/memory/PID limits and one noexec transient tmpfs.
- Prove the sandbox separately before engine execution. The probe verifies Docker HostConfig, failed outbound socket
  and DNS attempts, read-only boundaries and scratch cleanup while explicitly reporting `engine_executed=false` and
  `runtime_authorization_granted=false`.
- Keep the current worker entry point status-only. A later proof harness may be added only as a newly rebuilt and
  attested image generation, after a real two-person envelope exists.

## Consequences

- Corpus and isolation engineering can proceed now without weakening the human-control requirement.
- No current artifact authorizes GenOffice execution. Schemas and tests demonstrate that two valid independent
  signatures can open only a short-lived synthetic proof scope.
- Changing a fixture, sandbox setting, worker image or security report invalidates the request and requires new
  signatures.
- gVisor reduces host-kernel exposure but does not replace parser hardening, resource controls, content preflight,
  cleanup evidence or secure architecture.

## Recovery Contract

Back up the corpus bytes and manifest, sandbox profile and probe evidence, public signer policy, canonical request and
message, public signature responses, authorization envelope and final authorization report as one immutable
generation. Restore recalculates all hashes, verifies both signatures and confirms that the authorization was valid at
the recorded proof time. Private keys, worker scratch and generated document content are excluded. An expired restored
authorization remains audit evidence and never becomes executable again.

## References

- `docs/operations/GENOFFICE_SYNTHETIC_RUNTIME_PROOF.md`
- `app/suite/operations/genoffice_runtime_proof_authorization.py`
- `docs/operations/backup_failover_policy.json`
- [gVisor Docker quick start](https://gvisor.dev/docs/user_guide/quick_start/docker/)
- [gVisor networking](https://gvisor.dev/docs/user_guide/networking/)
- [gVisor security model](https://gvisor.dev/docs/architecture_guide/security/)
