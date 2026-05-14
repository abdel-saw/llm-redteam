# syntax=docker/dockerfile:1.7
# InternalLegalBot — demo vulnerable LLM target.
# Multi-stage, non-root, exposes 8765.

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 user \
 && useradd  -u 1000 -g user -m -s /bin/bash user

COPY --from=builder --chown=user:user /root/.local /home/user/.local

WORKDIR /app

# We package the demo as a self-contained module: the path inside the
# container mirrors the project layout (scripts/demo_target/) so the
# existing `python -m scripts.demo_target.run` entrypoint still works.
COPY --chown=user:user app.py    /app/scripts/demo_target/app.py
COPY --chown=user:user run.py    /app/scripts/demo_target/run.py
RUN touch /app/scripts/__init__.py /app/scripts/demo_target/__init__.py \
 && chown -R user:user /app/scripts

USER user

ENV PATH="/home/user/.local/bin:${PATH}" \
    DEMO_TARGET_PORT=8765 \
    PYTHONPATH=/app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/healthz || exit 1

CMD ["python", "-m", "scripts.demo_target.run"]
