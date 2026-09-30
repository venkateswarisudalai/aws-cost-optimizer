# syntax=docker/dockerfile:1
#
# aws-cost-optimizer — single image, dashboard + API on one origin.
#
# Stage 1 builds the Next.js static export; stage 2 bakes it into the Python
# package at awsco/static/ so FastAPI serves it directly. Nothing in this image
# needs AWS credentials at build time — they are mounted read-only at run time.

# ---------- stage 1: build the dashboard ----------
FROM node:20-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Unset so the client uses relative URLs — same origin as the API in this image.
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# ---------- stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# Keep Python lean and unbuffered so `docker logs` streams scan progress live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AWSCO_DATA_DIR=/data

WORKDIR /app

COPY backend/pyproject.toml backend/MANIFEST.in backend/README.md ./
COPY backend/awsco ./awsco

# Take the dashboard from stage 1 rather than any stale committed build.
COPY --from=frontend /build/out ./awsco/static

RUN pip install .

# Scans are read-only against AWS, but the image should still not run as root.
RUN useradd --create-home --uid 10001 awsco \
    && mkdir -p /data \
    && chown -R awsco:awsco /data
USER awsco

# Scan history persists here; mount a volume to keep it across runs.
VOLUME ["/data"]

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz').read()"

ENTRYPOINT ["awsco"]
CMD ["serve", "--host", "0.0.0.0", "--port", "3000"]
