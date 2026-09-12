# ---- stage 1: build the React frontend ---------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: the Python app -------------------------------------------------
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    NLTK_DATA=/opt/nltk_data

# libgomp1: OpenMP runtime needed by onnxruntime (Silero VAD, Smart Turn).
# daily-python ships manylinux_2_28 wheels, so glibc-based Debian is required; Alpine will not work.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create the runtime user first so the virtualenv is owned by it from the start.
# Re-owning it afterwards with chown -R would duplicate the whole layer.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app /opt/nltk_data \
 && chown app:app /app /opt/nltk_data
USER app
WORKDIR /app

# Dependencies first so this layer is cached across code changes.
# The uv download cache lives in a BuildKit cache mount, not in the image.
COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked --no-dev --no-install-project

# Pipecat lazily downloads the NLTK punkt_tab tokenizer on the bot's first sentence.
# Prebake it so the first spoken turn is not delayed by a download.
RUN uv run --no-sync python -c "import nltk; nltk.download('punkt_tab', download_dir='/opt/nltk_data', quiet=True)"

COPY --chown=app:app ledgerline/ ./ledgerline/
COPY --from=web --chown=app:app /web/dist ./frontend/dist

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=2).status == 200 else 1)"

CMD ["uv", "run", "--no-sync", "uvicorn", "ledgerline.main:app", "--host", "0.0.0.0", "--port", "7860"]
