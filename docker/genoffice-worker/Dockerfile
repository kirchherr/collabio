FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS dependencies

ARG SOURCE_DATE_EPOCH=0
ARG GENOFFICE_CONTEXT_SHA256
ARG GENOFFICE_CONTEXT_REPORT_SHA256
ARG GENOFFICE_AUTHORIZATION_REPORT_SHA256

ENV HOME=/tmp/home \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_IGNORE_SCRIPTS=true \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_USERCONFIG=/dev/null

WORKDIR /opt/genoffice

COPY --from=genoffice_context /genoffice-development-build-context.tar /tmp/genoffice-context.tar
COPY --from=genoffice_dependencies /license-materials/ /tmp/npm-artifacts/
COPY --from=genoffice_dependencies /genoffice-license-material-collection-report.json /tmp/dependency-report.json
COPY docker/genoffice-worker/verify-dependency-artifacts.mjs /opt/collabio/verify-dependency-artifacts.mjs
COPY docker/genoffice-worker/prepare-runtime-manifest.mjs /opt/collabio/prepare-runtime-manifest.mjs
COPY docker/genoffice-worker/verify-runtime-inventory.mjs /opt/collabio/verify-runtime-inventory.mjs

RUN test -n "${GENOFFICE_CONTEXT_SHA256}" \
    && test -n "${GENOFFICE_CONTEXT_REPORT_SHA256}" \
    && test -n "${GENOFFICE_AUTHORIZATION_REPORT_SHA256}" \
    && printf '%s  %s\n' "${GENOFFICE_CONTEXT_SHA256#sha256:}" /tmp/genoffice-context.tar | sha256sum --check --strict - \
    && node /opt/collabio/verify-dependency-artifacts.mjs \
    && tar --extract --file /tmp/genoffice-context.tar --directory /opt/genoffice \
    && rm /tmp/genoffice-context.tar \
    && node /opt/collabio/prepare-runtime-manifest.mjs \
    && cd /opt/genoffice/packages/docx-engine \
    && npm install --offline --ignore-scripts --omit=dev --no-audit --no-fund --no-save \
         --package-lock=false --cache /tmp/npm-cache /tmp/npm-artifacts/*.tgz \
    && node /opt/collabio/verify-runtime-inventory.mjs \
    && rm -rf /tmp/npm-artifacts /tmp/npm-cache /tmp/home /tmp/dependency-report.json \
    && rm -rf /opt/genoffice/packages/docx-engine/scripts \
              /opt/genoffice/packages/docx-engine/tests \
              /opt/genoffice/packages/docx-engine/tsconfig.json \
              /opt/genoffice/packages/docx-engine/vitest.config.ts \
              /opt/genoffice/.collabio/upstream \
    && find /opt/genoffice /opt/collabio -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} + \
    && tar --create --file /opt/collabio/genoffice-runtime.tar --format=posix \
         --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=10003 --group=10003 \
         --numeric-owner --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime -C / \
         opt/genoffice opt/collabio/runtime-inventory.json \
    && touch -h -d "@${SOURCE_DATE_EPOCH}" /opt/collabio/genoffice-runtime.tar

FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS runtime

ARG SOURCE_DATE_EPOCH=0
ARG GENOFFICE_CONTEXT_SHA256
ARG GENOFFICE_CONTEXT_REPORT_SHA256
ARG GENOFFICE_AUTHORIZATION_REPORT_SHA256

RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
    && touch -h -d "@${SOURCE_DATE_EPOCH}" /usr/local/lib/node_modules /usr/local/bin

COPY --from=dependencies /opt/collabio/genoffice-runtime.tar /tmp/genoffice-runtime.tar
RUN tar --extract --file /tmp/genoffice-runtime.tar --directory / --numeric-owner \
    && rm /tmp/genoffice-runtime.tar
COPY --chown=10003:10003 docker/genoffice-worker/worker-entrypoint.mjs /opt/collabio/worker-entrypoint.mjs

LABEL org.opencontainers.image.title="Collabio GenOffice DOCX development worker candidate" \
      org.opencontainers.image.description="Non-runtime development candidate for the admitted GenOffice DOCX engine scope" \
      org.opencontainers.image.source="https://github.com/kirchherr/collabio" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.collabio.genoffice.build-context-sha256="${GENOFFICE_CONTEXT_SHA256}" \
      io.collabio.genoffice.build-context-report-sha256="${GENOFFICE_CONTEXT_REPORT_SHA256}" \
      io.collabio.genoffice.authorization-report-sha256="${GENOFFICE_AUTHORIZATION_REPORT_SHA256}" \
      io.collabio.genoffice.scope="development_evaluation" \
      io.collabio.genoffice.execution-state="blocked" \
      io.collabio.genoffice.source-import-allowed="false" \
      io.collabio.genoffice.tenant-content-allowed="false" \
      io.collabio.genoffice.production-use-allowed="false"

ENV HOME=/nonexistent \
    NODE_ENV=production \
    NODE_OPTIONS=--disable-proto=throw

WORKDIR /opt/genoffice/packages/docx-engine
USER 10003:10003

ENTRYPOINT ["node", "/opt/collabio/worker-entrypoint.mjs"]
CMD ["--status"]
