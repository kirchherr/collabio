# Supply Chain Security

This runbook defines the minimum software-supply-chain evidence for Collabio. It applies to application dependencies,
the runtime container image, CI actions, SBOMs, and tagged release artifacts.

## Non-negotiable Rules

- Every third-party GitHub Action uses an immutable commit SHA. The readable version comment is informational only.
- No scan may silently continue after a policy failure.
- Runtime base images use an immutable manifest digest; Dependabot proposes digest updates for review.
- High and critical runtime vulnerabilities block CI, including vulnerabilities without a published fix.
- A `not_affected` result is accepted only through an exact, reviewable OpenVEX statement backed by an executable
  code-reachability guard and a non-expired decision-register entry.
- Repository and runtime-image scans cover vulnerabilities, secrets, and infrastructure misconfiguration.
- License evidence includes unknown, restricted, and forbidden findings. Forbidden licenses block CI.
- Embedded third-party build SBOMs are excluded from runtime evaluation; installed package metadata and the complete
  image filesystem remain authoritative scan inputs.
- The CycloneDX SBOM is generated from the built runtime image, not only from the input requirement file.
- A tagged release is not complete without its runtime archive, SBOM, checksums, provenance attestation, and SBOM attestation.
- Scan output and SBOMs contain component metadata only. Secrets, credentials, source content, or tenant data must never be added.

## Pull Request And Main Gate

The `supply-chain` job in `.github/workflows/ci.yml` runs after the Docker Compose quality gate:

1. Build the `runtime` Docker target.
2. Scan the repository with Trivy for vulnerable dependencies, secrets, and misconfiguration.
3. Scan the built runtime image for high and critical vulnerabilities, secrets, and misconfiguration.
4. Produce license evidence and reject licenses classified as forbidden.
5. Generate `artifacts/collabio-runtime.cdx.json` in CycloneDX JSON format.
6. Hash all generated evidence and retain it as a CI artifact for 30 days.

The image scan is authoritative for shipped Python and operating-system dependencies because it evaluates the resolved,
installed runtime rather than only direct declarations in `requirements.txt`.

Trivy skips only `**/*.dist-info/sboms/*.json` and `**/pip/_vendor/bom.cdx.json`. These vendor files describe build
environments and can contain components that are not installed in the image. The gate still scans every installed
`*.dist-info/METADATA` record, operating-system package, application file, and image configuration. Any new skip
pattern requires the same review and tests as a vulnerability exception.

## Tagged Releases

Pushing a `v*` tag starts `.github/workflows/release-provenance.yml`. The workflow reruns the complete Docker Compose
quality gate, builds and scans the runtime image, exports the exact image archive, creates the CycloneDX SBOM and
`SHA256SUMS`, then creates two GitHub artifact attestations:

- SLSA-compatible build provenance for the runtime archive.
- A CycloneDX SBOM attestation bound to the same archive.

GitHub artifact attestations use OIDC-backed Sigstore signing. No long-lived signing key is stored in the repository or
workflow. Release evidence is retained for 90 days; production release storage must copy it into the release evidence
retention domain before expiry.

Verify a downloaded runtime archive against this repository:

```bash
gh attestation verify collabio-runtime-vX.Y.Z.tar -R kirchherr/collabio
sha256sum --check SHA256SUMS
```

The verifier must confirm the expected repository, workflow identity, tag, and digest before deployment admission.

## Exceptions

Do not weaken a workflow inline to make a build green. Every vulnerability, secret, misconfiguration, or license
exception requires an owner, reason, exact scope, expiry date, upstream reference, compensating control, and approving
security reviewer. Exceptions must use the narrowest supported Trivy rule or path and must never suppress an entire
scanner. Expired exceptions fail the next release review and are removed rather than renewed automatically.

An OpenVEX `not_affected` decision is not a general vulnerability exception. It is valid only for the exact package
URL, version, vulnerability, and execution-path assessment in `security/vex/`. The paired decision-register entry
records role ownership, upstream evidence, compensating control, review date, and hard expiry. CI fails after expiry or
as soon as prohibited vulnerable functionality enters application code. A dependency update, upstream-advisory change,
or new use of the affected API requires a new assessment and a versioned VEX statement.

## Tool Updates

Dependabot proposes GitHub Action updates. Trivy versions and Action SHAs are reviewed together. An update is accepted
only after workflow-policy tests pass and the official release notes show no incompatible scanner, SBOM, or attestation
change. The immutable SHA is resolved from the official upstream tag and recorded with the readable version comment.
