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
COPY --chown=10001:10001 docs/operations/productivity_pilot_policy.json ./docs/operations/productivity_pilot_policy.json

ENV PYTHONPATH=/workspace/app

EXPOSE 8000

USER 10001:10001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS preview-renderer

ARG LIBREOFFICE_VERSION=25.8.7.3-r0
ARG QPDF_VERSION=12.3.2-r0
ARG POPPLER_UTILS_VERSION=25.12.0-r1
ARG FONTCONFIG_VERSION=2.17.1-r1
ARG PY3_PILLOW_VERSION=11.3.0-r2
ARG DEJAVU_FONT_VERSION=2.37-r6
ARG LIBERATION_FONT_VERSION=2.1.5-r2

RUN apk add --no-cache \
        "libreoffice-common=${LIBREOFFICE_VERSION}" \
        "libreoffice-writer=${LIBREOFFICE_VERSION}" \
        "libreoffice-calc=${LIBREOFFICE_VERSION}" \
        "libreoffice-impress=${LIBREOFFICE_VERSION}" \
        "qpdf=${QPDF_VERSION}" \
        "poppler-utils=${POPPLER_UTILS_VERSION}" \
        "py3-pillow=${PY3_PILLOW_VERSION}" \
        "fontconfig=${FONTCONFIG_VERSION}" \
        "font-dejavu=${DEJAVU_FONT_VERSION}" \
        "ttf-liberation=${LIBERATION_FONT_VERSION}" \
    && addgroup -S -g 10002 preview \
    && adduser -S -D -H -u 10002 -G preview preview \
    && mkdir --parents /job/control /job/input /job/cdr /job/output /job/tmp \
    && chown -R 10002:10002 /job

COPY --chown=10002:10002 app ./app

ENV PYTHONPATH=/usr/lib/python3.12/site-packages:/workspace/app
ENV HOME=/job/tmp/home
ENV TMPDIR=/job/tmp

WORKDIR /job
USER 10002:10002

ENTRYPOINT ["python", "-m", "suite.platform.source_object_preview_conversion_worker"]
