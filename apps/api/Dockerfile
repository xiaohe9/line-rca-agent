# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------- #
#  builder — resolves the uv workspace once, so the runtime image carries only
#  the virtual environment and no package manager.
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

# A build arg, not a hard-coded mirror: the same Dockerfile works everywhere and a
# fast local index can be injected without editing the file. Note that mirrors lag
# new releases, so a pinned UV_VERSION may need relaxing when PIP_INDEX_URL is a mirror.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_VERSION=0.13.1

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --index-url "$PIP_INDEX_URL" "uv==${UV_VERSION}"

WORKDIR /app

# Manifests first: this layer is cached until a dependency actually changes.
# The READMEs come along because each project declares one in its package metadata,
# and uv reads that metadata even with --no-install-project.
COPY pyproject.toml uv.lock README.md ./
COPY packages/agent-core/pyproject.toml packages/agent-core/README.md packages/agent-core/
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
RUN uv sync --frozen --no-dev --no-editable --no-install-project --index-url "$PIP_INDEX_URL"

# Then the sources, so editing code does not re-resolve dependencies.
COPY packages/agent-core/src packages/agent-core/src
COPY apps/api/src apps/api/src
RUN uv sync --frozen --no-dev --no-editable --index-url "$PIP_INDEX_URL"

# --------------------------------------------------------------------------- #
#  runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Never run the API as root.
RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app
EXPOSE 8000

# Dependency-free health check: the image has no curl, and urllib is enough.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "line_rca_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
