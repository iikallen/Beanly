FROM python:3.12-slim AS base

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
