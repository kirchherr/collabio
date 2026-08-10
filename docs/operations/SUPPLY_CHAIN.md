# Supply Chain Security

This runbook defines the minimum software-supply-chain evidence for Collabio. It applies to application dependencies,
the runtime container image, CI actions, SBOMs, and tagged release artifacts.

## Non-negotiable Rules

- **requirements.txt**, **requirements-dev.txt**, and **requirements-preview.txt** declare direct constraints;
  **requirements.lock**, **requirements-dev.lock**, and **requirements-preview.lock** pin the complete transitive
  graphs and every accepted distribution hash.
- Docker builds install only lockfiles with **pip --require-hashes**. A declaration change without a regenerated lock
  fails CI before the development image is built.
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
- A tagged release is not complete without its GHCR OCI digest, runtime archive, SBOM, checksums, provenance
  attestation, and SBOM attestation.
- Deployment admission and promotion use OCI digests. Mutable registry tags are discovery aliases, never trust anchors.
- Scan output and SBOMs contain component metadata only. Secrets, credentials, source content, or tenant data must never be added.

## Dependency Locks

The lock generator is uv 0.12.2 in an official Python 3.12 Alpine image pinned by manifest digest. It is available
only through the **tooling** Compose profile and is not copied into development or runtime images.

Regenerate all locks after changing a direct declaration:

~~~bash
docker compose --profile tooling run --rm dependency-lock-runtime
docker compose --profile tooling run --rm dependency-lock-dev
docker compose --profile tooling run --rm dependency-lock-preview
docker compose build
docker compose run --rm quality
~~~

Review the direct and transitive version changes before commit. Lock regeneration is intentionally networked;
application, test, and release containers consume the resulting committed files without resolving a new dependency
graph. CI runs the same three generators and rejects any lock drift with **git diff --exit-code**.

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

Pushing a **v*** tag starts **.github/workflows/release-provenance.yml**. The workflow rejects dependency-lock drift,
reruns the complete Docker Compose quality gate, builds and scans the runtime image, and only then authenticates to
GHCR. The exact tested image is pushed as the release tag and **sha-commit**. The workflow records its immutable OCI
digest, exports the same local image as an archive, creates the CycloneDX SBOM and **SHA256SUMS**, then creates two OCI
attestations:

- SLSA-compatible build provenance bound to the GHCR image digest.
- A CycloneDX SBOM attestation bound to the same GHCR image digest.

GitHub artifact attestations use OIDC-backed Sigstore signing. No long-lived signing key is stored in the repository or
workflow. Release evidence is retained for 90 days; production release storage must copy it into the release evidence
retention domain before expiry.

Verify a registry image by digest against this repository and release workflow:

~~~bash
gh attestation verify oci://ghcr.io/kirchherr/collabio@sha256:<digest> \
  --repo kirchherr/collabio \
  --signer-workflow github.com/kirchherr/collabio/.github/workflows/release-provenance.yml \
  --source-ref refs/tags/vX.Y.Z \
  --deny-self-hosted-runners
sha256sum --check SHA256SUMS
~~~

The verifier must confirm the expected repository, workflow identity, tag, and digest before deployment admission.

## Staging And Production Promotion

**.github/workflows/promote-release.yml** is a manual registry-promotion boundary. It never builds an image and never
accepts a tag as the artifact identity. Its required inputs are the release OCI digest, the matching **v*** tag, a
target environment, and a reviewed change reference.

Repository administrators must create protected GitHub Environments named **staging** and **production**:

1. Configure required reviewers and prevent self-review where the repository plan supports it.
2. Restrict deployment branches to **main** and disable administrator bypass where supported.
3. Add the environment variable **PROMOTION_POLICY_CONFIGURED=true** only after those controls are active.
4. Keep registry credentials environment-scoped; the current GHCR path uses the short-lived workflow GITHUB_TOKEN.

The workflow fails closed unless it runs from **main** and the environment variable confirms that the external
protection was configured. After the environment approval, it:

1. proves that the release tag currently resolves to the requested digest;
2. verifies release provenance and the CycloneDX attestation against the exact release signer workflow and tag;
3. requires a signed staging-promotion attestation before any production promotion;
4. creates a metadata-only promotion admission and signs it through GitHub OIDC;
5. pushes an environment-and-release tag plus the mutable environment discovery alias;
6. retains the admission record, promoted references, optional staging-verification result, and checksums.

Consumers and deployment manifests must still pull **ghcr.io/kirchherr/collabio@sha256:digest**. Staging, production,
and environment-release tags are operator conveniences and cannot replace digest verification.

Promotion is software-release admission only. It does not deploy infrastructure, open the productivity runtime switch,
change DNS or traffic, authorize failover, satisfy production-continuity evidence, or write tenant/business data. A
production deployment needs both an admitted image digest and the independently green production continuity gate.

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
