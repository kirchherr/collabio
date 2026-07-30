FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

FROM base AS dev

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

COPY app ./app
COPY tests ./tests
COPY pyproject.toml .

ENV PYTHONPATH=/workspace/app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS runtime

COPY app ./app
COPY docs/operations/productivity_pilot_policy.json ./docs/operations/productivity_pilot_policy.json

ENV PYTHONPATH=/workspace/app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
