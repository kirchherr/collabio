# ADR-0064: GenOffice npm Cryptographic Provenance Admission

Status: accepted
Date: 2026-08-10

## Context

ADR-0063 proves the bytes, dependency inventory, pre-build SBOM, and vulnerability state of the selected GenOffice
DOCX candidate. The npm registry metadata for its vendored `emf-converter@2.0.2` also advertises an ECDSA registry
signature, an npm publish attestation, and SLSA v1 provenance. Metadata presence is not cryptographic verification and
cannot establish the build identity.

Verification needs current npm/Sigstore trust material and therefore network access. Policy evaluation and source
admission must remain reproducible, inspectable, and independent from that networked process.

## Decision

- Use official Node.js 24.18.0 LTS with npm 11.16.0, pinned by OCI digest. Install exactly one locked package with
  lifecycle scripts disabled in a read-only, non-root, credential-less one-shot container.
- Run `npm audit signatures --json --include-attestations` on a dedicated outbound-only Compose network. Retain the
  complete verified Sigstore bundles and a receipt binding the Node, npm, and image identities.
- Evaluate the result in a separate no-network Python admission container. Require exactly one verified package, no
  missing or invalid package, both npm publish and SLSA v1 predicates, the exact package PURL and SHA-512 subject, and
  two complete Rekor inclusion records.
- Pin the Fulcio leaf certificate fingerprint and validate its SAN plus standard Sigstore OIDs for GitHub-hosted
  runner, public repository, immutable repository/owner IDs, source commit, source ref, workflow, invocation, trigger,
  and npm deployment environment.
- Keep legal approval, source import, engine execution, worker build, production use, and tenant content access false.
  Provenance links published bytes to a build identity; it does not prove benign code or a reproducible build.

## Evidence

The accepted npm verifier output has SHA-256
`f86895f2045f6c9916e04cd43ef46afd5f0741e68c99bc62c4da89fa5b651434`. It verifies
`pkg:npm/emf-converter@2.0.2` at SHA-512
`40b52e7dbe393f72e53ae742a22cc1b49a4ef1c070f0b6b21f49a4be446f223bcc95bea3ba7c0fd045e0524743c9950417641211950f57cacef034b9aec26690`.
The SLSA statement identifies source commit `9aca5abf16662f93a453a07378768ddd87a8541d`, GitHub-hosted workflow
`.github/workflows/publish.yml`, and run `30234322001/attempts/1`. The Fulcio certificate SHA-256 is
`b26c2c25ff00d5cfd69b3156d66b84e4d13a88e28522227386486405948506d4`. The resulting admission report is
`sha256:c85feac5fa9788ef10a4076034d2443c230e8536ee5c02de61b8cfe9ea114aa3`.

## Consequences

- Registry signature, npm publish attestation, SLSA provenance, certificate identity, and transparency-log inclusion
  are now automated evidence rather than manual claims.
- Network acquisition and offline admission have separate least-privilege containers and evidence hashes.
- Re-verification requires the exact pinned verifier image or a reviewed update with new evidence.
- Source import remains blocked until legal review and a reproducible isolated worker build with image-derived SBOM,
  vulnerability decision, signed provenance, and runtime security/fidelity evidence are complete.

## References

- https://docs.npmjs.com/cli/v11/commands/npm-audit/
- https://docs.npmjs.com/generating-provenance-statements/
- https://github.com/npm/provenance
- https://github.com/sigstore/fulcio/blob/main/docs/oid-info.md
- https://slsa.dev/spec/v1.0/provenance
