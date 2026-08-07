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
