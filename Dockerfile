# syntax=docker/dockerfile:1.4
# AEOLUS — single-service container: builds the frontend, runs the data pipeline,
# serves the API + dashboard. Suitable for Render / Railway / Fly / HF Spaces.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY data/ ./data/
COPY --from=web /web/dist ./frontend/dist

ENV PYTHONWARNINGS=ignore
# Build the lakehouse + models + market + schedule + dossiers + governance queue.
# (Downloads ~95MB real SCADA from Zenodo on first build.) The GROQ_API_KEY Space
# secret is mounted at build so the baked dossiers use the real LLM, not the
# deterministic fallback.
RUN --mount=type=secret,id=GROQ_API_KEY,mode=0444 \
    sh -c 'export GROQ_API_KEY="$(cat /run/secrets/GROQ_API_KEY 2>/dev/null || true)"; \
           cd backend && python -m aeolus.pipeline || echo "pipeline will run at startup"'

EXPOSE 8000
CMD ["sh", "-c", "cd backend && uvicorn aeolus.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
