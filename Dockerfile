# syntax=docker/dockerfile:1

# ── stage 1: build the frontend ───────────────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build          # -> /web/dist

# ── stage 2: python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# native libs for ifcopenshell / trimesh
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ifcbox/ ifcbox/
COPY api/ api/
COPY --from=web /web/dist api/static/

ENV IFCBOX_STORAGE=cloud \
    IFCBOX_CACHE_DIR=/tmp/ifcbox \
    PYTHONUNBUFFERED=1

EXPOSE 10000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
