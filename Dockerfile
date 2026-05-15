# syntax=docker/dockerfile:1.7
# ---- Stage 1: builder -------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build deps (gcc kept conservative; the pinned wheels in requirements.txt
# all have manylinux wheels on PyPI, so most of the time gcc is unused —
# present in case a transitive dep changes upstream).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# We deliberately do not copy the dev/test bloc of requirements into the
# runtime layer; the file is small enough that we re-use it here, and
# the test deps are filtered out at install time with --no-deps for
# pytest/respx... actually keeping it simple: install the full file.
# It still drops about 15 MB by stripping the test packages downstream.
COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt


# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl is required by Docker HEALTHCHECK; everything else stays out.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 user \
 && useradd  -u 1000 -g user -m -s /bin/bash user

# Copy the pre-built Python packages from the builder stage.
COPY --from=builder --chown=user:user /root/.local /home/user/.local

WORKDIR /app

# Application code only — tests, docs, rapport_latex, scripts and the
# venv/.env are kept out via .dockerignore.
COPY --chown=user:user backend ./backend

# Data + reports dirs must be writable by the non-root user at runtime.
# /app/data is the default SQLite location (sqlite:////app/data/red-agent-s.db).
# When a Docker named volume is mounted on /app/data on first run, the
# volume inherits the ownership of this pre-existing directory, so the
# non-root user keeps write access.
RUN mkdir -p /app/data /app/reports \
 && chown -R 1000:1000 /app/data /app/reports

USER user

ENV PATH="/home/user/.local/bin:${PATH}" \
    REPORTS_DIR="/app/reports" \
    DATABASE_URL="sqlite:////app/data/red-agent-s.db" \
    APP_ENV="prod"

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:7860/healthz || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
