ARG PYTHON_IMAGE=python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY beanly ./beanly
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install --no-cache-dir .

RUN addgroup --system beanly && adduser --system --ingroup beanly beanly
USER beanly

FROM base AS test
USER root
COPY tests ./tests
RUN pip install --no-cache-dir ".[test]"
USER beanly
CMD ["sh", "-c", "ruff check --no-cache . && pytest -ra -p no:cacheprovider"]

FROM base AS production
CMD ["uvicorn", "beanly.main:app", "--host", "0.0.0.0", "--port", "8000"]
