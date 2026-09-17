ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27
FROM ${PLAYWRIGHT_IMAGE}

LABEL org.opencontainers.image.source="https://github.com/kirchherr/collabio"
LABEL org.opencontainers.image.title="Collabio Work E2E Runner"

ENV CI=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /work-e2e

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force

COPY --chown=pwuser:pwuser playwright.config.mjs ./
COPY --chown=pwuser:pwuser tests ./tests

USER pwuser

ENTRYPOINT ["npx", "--no-install", "playwright", "test"]
