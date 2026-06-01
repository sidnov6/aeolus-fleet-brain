# Deploying AEOLUS

## Live demo (frontend, static) — already deployed
**https://aeolus-fleet-brain.vercel.app**

The dashboard ships with baked JSON snapshots (`frontend/public/api-static/`) and a
client-side fallback in `src/api.js`. When no backend is reachable it serves those
snapshots and handles approve / reject / kill-switch / the value counter entirely
client-side — so the static Vercel deploy is fully interactive.

Re-deploy the frontend:
```bash
cd frontend && npm run build && vercel --prod
# refresh the snapshots first (with the API running): see scripts below
```

Refresh the baked snapshots from a running backend:
```bash
OUT=frontend/public/api-static; mkdir -p $OUT/incident
for ep in health fleet approvals audit; do curl -s localhost:8000/api/$ep -o $OUT/$ep.json; done
for t in KWF3 KWF5; do curl -s localhost:8000/api/incident/$t -o $OUT/incident/$t.json; done
```

## Full stack (live backend) — one container
The FastAPI app serves both the API and the built dashboard. Deploy the included
`Dockerfile` anywhere that runs containers:

- **Render** — New › Blueprint › pick this repo (`render.yaml`), add `GROQ_API_KEY`.
- **Railway / Fly.io / HF Spaces (Docker)** — point at the `Dockerfile`, set `GROQ_API_KEY`.

```bash
docker build -t aeolus .
docker run -p 8000:8000 -e GROQ_API_KEY=... aeolus
# -> http://localhost:8000
```
The image runs the full pipeline at build (downloads the real Kelmarsh SCADA from
Zenodo, trains the models, pulls live prices/weather, solves the schedule, runs the
agents, builds the governance queue), then serves everything.
```
