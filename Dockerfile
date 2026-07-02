# syntax=docker/dockerfile:1.7
# ---- builder ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml ./
COPY src ./src

RUN pip install --prefix=/install .

# ---- runtime ----
FROM python:3.12-slim AS runtime

ENV PATH="/install/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN groupadd --system app && useradd --system --gid app --uid 1001 app

WORKDIR /app

COPY --from=builder /install /install
COPY --chown=app:app src /app/src

USER app

CMD ["python", "-m", "forex_signal.main"]
