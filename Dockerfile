FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore

WORKDIR /workspace

COPY requirements.lock .
RUN python -m pip install --require-hashes --requirement requirements.lock

FROM base AS dev

COPY requirements-dev.lock .
COPY requirements-preview.lock .
RUN python -m pip install --require-hashes --requirement requirements-dev.lock

COPY app ./app
COPY tests ./tests
COPY pyproject.toml .

ENV PYTHONPATH=/workspace/app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS runtime

RUN addgroup -S -g 10001 collabio \
    && adduser -S -D -H -u 10001 -G collabio collabio \
    && mkdir --parents /workspace/data \
    && chown 10001:10001 /workspace/data

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 docs/operations/genoffice_evaluation_policy.json ./docs/operations/genoffice_evaluation_policy.json
COPY --chown=10001:10001 docs/operations/productivity_pilot_policy.json ./docs/operations/productivity_pilot_policy.json
COPY --chown=10001:10001 infra/self-hosted/provider-stack-policy.json ./infra/self-hosted/provider-stack-policy.json

ENV PYTHONPATH=/workspace/app

EXPOSE 8000

USER 10001:10001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS preview-renderer

COPY requirements-preview.lock .
RUN python -m pip install --require-hashes --requirement requirements-preview.lock

ARG LIBREOFFICE_VERSION=25.8.7.3-r0
ARG QPDF_VERSION=12.3.2-r0
ARG POPPLER_UTILS_VERSION=25.12.0-r1
ARG FONTCONFIG_VERSION=2.17.1-r1
ARG DEJAVU_FONT_VERSION=2.37-r6
ARG LIBERATION_FONT_VERSION=2.1.5-r2

RUN apk add --no-cache \
        "libreoffice-common=${LIBREOFFICE_VERSION}" \
        "libreoffice-writer=${LIBREOFFICE_VERSION}" \
        "libreoffice-calc=${LIBREOFFICE_VERSION}" \
        "libreoffice-impress=${LIBREOFFICE_VERSION}" \
        "qpdf=${QPDF_VERSION}" \
        "poppler-utils=${POPPLER_UTILS_VERSION}" \
        "fontconfig=${FONTCONFIG_VERSION}" \
        "font-dejavu=${DEJAVU_FONT_VERSION}" \
        "ttf-liberation=${LIBERATION_FONT_VERSION}" \
    && addgroup -S -g 10002 preview \
    && adduser -S -D -H -u 10002 -G preview preview \
    && mkdir --parents /job/control /job/input /job/cdr /job/output /job/tmp \
    && chown -R 10002:10002 /job

COPY --chown=10002:10002 app ./app

ENV PYTHONPATH=/workspace/app
ENV HOME=/job/tmp/home
ENV TMPDIR=/job/tmp

WORKDIR /job
USER 10002:10002

ENTRYPOINT ["python", "-m", "suite.platform.source_object_preview_conversion_worker"]

FROM base AS openxml-validator-build

ARG DOTNET8_SDK_VERSION=8.0.129-r0

RUN apk add --no-cache "dotnet8-sdk=${DOTNET8_SDK_VERSION}"

WORKDIR /src/openxml-validator
COPY tools/openxml-validator/Collabio.OpenXmlValidator.csproj .
COPY tools/openxml-validator/packages.lock.json .
RUN dotnet restore --locked-mode
COPY tools/openxml-validator/Program.cs .
RUN dotnet publish --configuration Release --no-restore --output /opt/collabio-openxml-validator \
    && find /opt/collabio-openxml-validator -type f -exec chmod 0444 {} +

FROM base AS libreoffice-fidelity-runner

ARG LIBREOFFICE_VERSION=25.8.7.3-r0
ARG POPPLER_UTILS_VERSION=25.12.0-r1
ARG FONTCONFIG_VERSION=2.17.1-r1
ARG DEJAVU_FONT_VERSION=2.37-r6
ARG LIBERATION_FONT_VERSION=2.1.5-r2
ARG DOTNET8_RUNTIME_VERSION=8.0.29-r0

RUN apk add --no-cache \
        "libreoffice-common=${LIBREOFFICE_VERSION}" \
        "libreoffice-writer=${LIBREOFFICE_VERSION}" \
        "poppler-utils=${POPPLER_UTILS_VERSION}" \
        "fontconfig=${FONTCONFIG_VERSION}" \
        "font-dejavu=${DEJAVU_FONT_VERSION}" \
        "ttf-liberation=${LIBERATION_FONT_VERSION}" \
        "dotnet8-runtime=${DOTNET8_RUNTIME_VERSION}" \
    && addgroup -S -g 10004 fidelity \
    && adduser -S -D -H -u 10004 -G fidelity fidelity \
    && mkdir --parents /job/input /job/output /job/tmp/home \
    && chown -R 10004:10004 /job

COPY --from=openxml-validator-build /opt/collabio-openxml-validator /opt/collabio-openxml-validator
COPY --chown=10004:10004 app ./app

ENV PYTHONPATH=/workspace/app \
    HOME=/job/tmp/home \
    TMPDIR=/job/tmp \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1

WORKDIR /job
USER 10004:10004

ENTRYPOINT ["python", "-m", "suite.operations.genoffice_docx_libreoffice_runner"]

FROM base AS word-fidelity-collector

ARG POPPLER_UTILS_VERSION=25.12.0-r1
ARG DOTNET8_RUNTIME_VERSION=8.0.29-r0

RUN apk add --no-cache \
        "poppler-utils=${POPPLER_UTILS_VERSION}" \
        "dotnet8-runtime=${DOTNET8_RUNTIME_VERSION}" \
    && addgroup -S -g 10005 wordcollector \
    && adduser -S -D -H -u 10005 -G wordcollector wordcollector \
    && mkdir --parents /job/input /job/handoff /job/output /job/tmp/home \
    && chown -R 10005:10005 /job

COPY --from=openxml-validator-build /opt/collabio-openxml-validator /opt/collabio-openxml-validator
COPY --chown=10005:10005 app ./app

ENV PYTHONPATH=/workspace/app \
    HOME=/job/tmp/home \
    TMPDIR=/job/tmp \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1

WORKDIR /job
USER 10005:10005

ENTRYPOINT ["python", "-m", "suite.operations.genoffice_docx_word_runner"]
