# GenOffice Development Build Context

## Purpose

This boundary converts the exact reviewed GenOffice archive into one deterministic development build-context TAR. It
does not install dependencies, run upstream code, build an image or permit document processing.

## Required Evidence

- pinned `genoffice_docx_source_admission_report.v1` and exact source archive;
- green `genoffice_docx_supply_chain_admission_report.v1`;
- green `genoffice_npm_provenance_admission_report.v1`;
- exactly one explicit development authorization: either a real `genoffice_internal_oss_admission_report.v1` produced
  by the two-person ceremony or an active signed `genoffice_solo_founder_exception_report.v1`;
- exact `GENOFFICE_THIRD_PARTY_NOTICES.txt`.

Missing, stale, malformed or hash-inconsistent evidence exits with code `2` before an output is persisted.

## Output

The service writes:

- `genoffice-development-build-context.tar`;
- `genoffice-development-build-context-report.json`.

The TAR contains the 93 individually admitted source files, `THIRD_PARTY_NOTICES.txt` and
`.collabio/build-context-manifest.json`. Entries are ordered and normalized to UID/GID 0, mode `0644`, empty owner names
and `SOURCE_DATE_EPOCH`. Root `package.json` and `package-lock.json` are quarantined under `.collabio/upstream/`, so the
known root `postinstall` hook is evidence but not an implicit build entry point. The report binds the TAR, embedded
manifest, source archive, source manifest, pre-build supply-chain report, npm provenance, authorization mode, exact
authorization report, signer policy, authorization record and NOTICE. Report and manifest schema v2 reject mixed or
ambiguous authorization evidence.

## Runbook

After the standard `dev001` preflight, create an output directory owned by the configured unprivileged runtime UID. Set
`SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_HOST_DIR` to that directory. With `build.lock` acquired before `docker.lock`:

Select exactly one mode with `SUITE_GENOFFICE_DEVELOPMENT_AUTHORIZATION_MODE`:

- `two_person_internal_oss_admission`; or
- `solo_founder_development_exception`.

```bash
docker compose -p collabio --profile office-supply-chain run --rm --no-deps \
  genoffice-development-build-context
```

The default `SOURCE_DATE_EPOCH` is `0`. Changing it changes the context bytes and must be recorded as a build input.

## Closed Boundaries

A green report means only that a later no-network worker image build may consume the exact TAR. It leaves dependency
installation, worker-image creation, engine execution, source import, tenant content, Hosted Service, On-Prem and
production false. The real service fails closed until the selected mode's accountable signer policy, external
signature and authorization report exist. A solo-founder report is checked for expiration on every materialization.

## Recovery

Back up the TAR and report with all referenced supply-chain evidence. On restore, verify the report hash, TAR hash,
embedded manifest hash and every referenced input hash before presenting the context to a builder. Do not retain build
caches, scratch workspaces or signing keys with this artifact.
