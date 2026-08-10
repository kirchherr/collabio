# Preview Content Disarm And Reconstruction

Stand: 2026-08-10

## Purpose

Collabio treats every Office document and PDF as hostile input. The development conversion path therefore no longer
hands a LibreOffice-generated PDF directly to the trusted importer. It applies a fail-closed pixel CDR boundary first:
the source is rendered to pixels in one isolated process, and a second isolated process creates a new PDF from only
validated raw RGB bytes.

This architecture follows the established Dangerzone trust model: open the untrusted document in a no-network
sandbox, cross the trust boundary as pixels, and rebuild a safe PDF. Dangerzone remains an important external
reference, but it is not embedded as a Collabio runtime dependency. Its current container-in-container model and
AGPL-3.0 license require separate operational and license review. Collabio instead uses its existing pinned
LibreOffice, Poppler, QPDF, gVisor and SourceObject controls behind a provider-neutral CDR contract.

References:

- [Dangerzone architecture](https://dangerzone.rocks/about/)
- [Dangerzone source and license](https://github.com/freedomofpress/dangerzone)
- [Pillow release documentation](https://pillow.readthedocs.io/en/stable/releasenotes/)
- [Alpine package inventory](https://pkgs.alpinelinux.org/packages)

## Trust Boundaries

1. The trusted stager verifies tenant, ACL, source version, malware result, execution gate and image digest. It writes
   the immutable request to the control volume and the exact source bytes to the input volume.
2. `preview-conversion-*-cdr-renderer` runs under `runsc`, without network or credentials. It can read control and
   source input and can write only the CDR volume. LibreOffice or the direct-PDF route creates an intermediate PDF;
   QPDF and PDFInfo validate it; Poppler emits one PPM page per admitted page.
3. The renderer accepts only binary P6 PPM with exact dimensions and byte length. It strips the PPM header and writes
   only `page-NNNNNN.rgb` plus `manifest.json`. The manifest binds tenant, source, command, gate, image, tool versions,
   font baseline, page order, dimensions, byte lengths and SHA-256 hashes.
4. `preview-conversion-*-worker` is the CDR rebuilder. It runs in a separate `runsc` container with no input-volume
   mount, no source bytes, no network and no credentials. It validates the complete manifest and directory inventory,
   then uses `Pillow.Image.frombytes` on the already validated RGB buffers. It never calls an image file parser.
5. The rebuilt PDF is checked by QPDF, PDFInfo, raw active-content indicators and object-level active-name inspection.
   The trusted importer independently validates all bindings before persisting a versioned derived SourceObject.

The production-shaped combined `--once` path is rejected when production admission is required. Production must use
the separated renderer and rebuilder services.

## Fail-Closed Rules

- Missing, extra, duplicated, unordered or symlinked CDR files fail the job.
- A manifest hash, page hash, byte length, aggregate size, dimension or command binding mismatch fails the job.
- Page count, dimensions, input size, output size, wall-clock time, memory and temporary storage remain bounded by the
  admitted command. CDR dimensions are additionally capped at 4096 pixels per side.
- The CDR manifest is metadata-only. Source bytes, PDF bytes, RGB bytes, stdout and stderr are excluded from durable
  evidence and normal logs.
- Renderer or rebuilder failure produces no derived object. The trusted importer never accepts a partial bundle.
- Dispatch and serving remain disabled unless their independent admission gates pass.

## Supply Chain

Pillow is isolated in `requirements-preview.txt` and `requirements-preview.lock`; it is not added to the general API
or development dependency graph. The lock contains every accepted SHA-256 distribution hash and is regenerated with:

```bash
docker compose --profile tooling run --rm dependency-lock-preview
```

CI and release workflows regenerate all three dependency locks and reject drift before image build. The preview image
still pins the Python base digest and exact Alpine versions for LibreOffice, Poppler, QPDF and fonts. Production uses
the published preview image only by OCI digest with verified SBOM and provenance.

## Backup And Failover

Raw RGB bundles, intermediate PDFs and process workspaces are transient security-zone data. They are never backup or
replication inputs and must be empty after success or failure. Durable recovery state consists of the source and
derived SourceObject versions, storage manifests, execution gate, source preflight, `source_object_preview_conversion_result.v3`,
CDR profile and manifest hashes, conversion-job evidence, write receipt and derived-preview lineage receipt.

After restore, `derived-preview-recovery-drill` revalidates the current and historical result schemas and reconciles
the durable source-to-derived lineage. A missing derived PDF may be regenerated only from the exact retained source
version under a fresh execution gate, producing a new result, object version and lineage receipt. A CDR bundle itself
is never restored or reused.

The development proof `preview-proof-20260810-093819` established the separated boundary on `dev001` with image
`sha256:fe38fcd309b57d634106623d255166d3b544a51513bf73132627b71afb30776e`, CDR manifest
`sha256:5e70931345ebc3b7d003f568bbd351e2986d7f8036f8659404159df44a2ba7dd`, proof report
`sha256:e4df54a791145737fb4ea3fc72ab8f6948aed03faa6a5a0ce2a461094a44fe71` and recovery report
`sha256:e4d725bf14596cb49884ad97abe03bdd46df4bd0609bc3a1653a8059a4e5cfae`. Recovery reconciled four jobs, receipts and
items without blockers. This is development evidence, not production admission.

## Remaining Production Work

The code path and development recovery proof are complete. Production remains blocked until the deployed environment
provides independently verified runtime isolation, CDR and malware service HA/failover evidence, current signature and
engine provenance, signed image SBOM/provenance, malicious active-content neutralization fixtures, production network
policy, the separate hardened PDF.js origin and the real three-role DSSE approval ceremony.
