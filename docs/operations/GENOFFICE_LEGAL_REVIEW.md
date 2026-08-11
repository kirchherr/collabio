# GenOffice Legal Review Dossier

## Purpose

This gate prepares reproducible evidence for a qualified human legal review of the pinned GenOffice DOCX candidate.
It does not provide legal advice and cannot approve source import, a worker build, product branding, distribution, or
production use.

The review scope is deliberately narrow:

- exact upstream commit `fd33934dab1fdf8666af3f88b9794e7b4e19474a`;
- future candidate scope `packages/docx-engine/**` only;
- `ee/**`, `apps/shell/**`, `packages/ai-provider/**`, and `packages/ai-search/**` remain prohibited;
- Collabio branding only; the GenOffice and Genspark names and logos are not product identity;
- 21 exact runtime dependency archives plus the separately proven vendored `emf-converter@2.0.2`.

## Trust Zones

`genoffice-license-material-collector` is the only networked step. It reads the reviewed source report, contacts only
`https://registry.npmjs.org`, downloads each exact lockfile URL without credentials, and rejects every package whose
bytes do not match its pinned npm `sha512` integrity. It neither installs packages nor executes lifecycle scripts,
Node, npm, or upstream code. The package archives and collection report are retained under the Collabio supply-chain
evidence directory.

`genoffice-legal-review-dossier` has `network_mode: none`, a read-only root, no capabilities, bounded resources, and
read-only source inputs. It never extracts an archive to the filesystem. It selectively reads and hashes:

- upstream root `LICENSE`, `NOTICE`, and the README trademark statement;
- the separate `ee/LICENSE`, while keeping the complete enterprise tree outside every selected source manifest;
- the vendored EMF converter license;
- license, notice, copyright, and supporting README files in each integrity-verified runtime package archive.

The offline gate recognizes only the license expressions already pinned by the reviewed lockfile: `MIT`, `ISC`,
`MIT OR GPL-3.0-or-later`, and `MIT AND Zlib`. Unknown expressions fail closed. Text markers are evidence-navigation
helpers, not automatic legal conclusions.

## Runbook

On `dev001`, after the required project/container/port preflight and coordination locks:

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-license-material-collector

docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-legal-review-dossier
```

The default retained outputs are:

- `backups/genoffice-supply-chain/license-materials/*.tgz`;
- `backups/genoffice-supply-chain/genoffice-license-material-collection-report.json`;
- `backups/genoffice-supply-chain/genoffice-legal-review-dossier-report.json`;
- `backups/genoffice-supply-chain/genoffice-legal-decision-record.schema.json`.

The collection output is deterministic for unchanged registry bytes. The legal dossier and decision schema are
deterministic for unchanged input evidence. Exit code `0` from the dossier means that the automated materials are ready
for human review. It does not mean that the review has been approved. Exit code `2` is fail-closed.

## Human Decision Boundary

The generated `genoffice_legal_decision_record.v1` schema requires a separate record with:

- dossier hash, reviewer identity, professional role, review time, legal-opinion reference, and change-control reference;
- explicit approved and prohibited source scopes;
- Collabio-only trademark policy;
- hash of the approved distributable third-party notice artifact;
- a resolution for every dossier question and every dependency license expression;
- detached-signature verification evidence and the canonical decision-record hash.

No service in this gate creates that record. A future admission step must verify the signed decision through the Suite
KMS/trust-provider boundary and bind it to the exact dossier before changing `legal_review_complete`. Even an approved
legal record does not by itself permit source import or build: reproducible build, image-derived SBOM, vulnerability,
malicious-file, fidelity, sandbox, and recovery gates remain independent.

The mandatory human questions cover Apache-2.0 distribution and patent terms, NOTICE preservation, upstream trademark
exclusion, enterprise-tree exclusion, the `jszip` OR choice, cumulative `pako` MIT and Zlib duties, and the vendored
EMF converter license/provenance chain.

## Primary References

- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- [Apache licensing and NOTICE guidance](https://www.apache.org/legal/apply-license.html)
- [SPDX 3.0.1 license expressions](https://spdx.github.io/spdx-spec/v3.0.1/annexes/spdx-license-expressions/)
- [Pinned GenOffice repository state](https://github.com/genspark-ai/genoffice/tree/fd33934dab1fdf8666af3f88b9794e7b4e19474a)

The pinned upstream README explicitly states that `ee/` has separate terms and that the GenOffice and Genspark names
and logos are Mainfunc, Inc. trademarks not granted by Apache-2.0. Those statements are treated as mandatory review
evidence, not inferred permissions.
