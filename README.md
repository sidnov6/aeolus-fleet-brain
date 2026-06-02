# AEOLUS — Autonomous Operations Brain for a Renewable Energy Fleet

> A multi-agent system that runs a wind fleet the way a great operations director would:
> it **detects** a turbine degrading, **root-causes** it, **prices** the cost of acting now
> versus later against the live electricity market and weather, **schedules** the cheapest safe
> maintenance window with a real solver, **drafts** the work order, and routes it to a human for
> one-click approval — with a governance trail a regulated operator can actually deploy.

**The wedge:** everyone builds agents that *predict* failures. The hard, valuable problem is the
closed loop *after* the prediction — deciding **when to act** so you lose the least generation
revenue, under real constraints (crew, weather, grid commitments), with an immutable governance
trail. Prediction is commoditised; economically-optimal autonomous scheduling against a live
market is not.

Built end-to-end on **real, openly-licensed European wind-farm data** and **free APIs** — $0 to run.

**▶ Live demo: https://aeolus-fleet-brain.vercel.app** · See [DEPLOY.md](DEPLOY.md) for the full-stack (live backend) deploy.

---

## The money shot

A live counter — **value protected vs. naïve "fix-it-now" scheduling** — broken into two honest
components:

1. **Generation revenue protected** — lost generation avoided by scheduling downtime in the cheapest
   safe window instead of the first available slot (OR-Tools picks it).
2. **Unplanned-failure cost avoided** — the value of acting on the prognosis *at all*: a planned
   intervention now vs. an expected run-to-failure event later (`P(failure) × (unplanned − planned)`).

---

## Architecture (five layers)

```
DATA PLANE      SCADA telemetry · Grid & market · Weather
      │
LAKEHOUSE       Bronze → Silver (+ ISA-95 asset registry) → Gold feature store   (medallion / parquet)
      │
PERCEPTION      Normality models · anomaly + prognosis (health score + lead-time) ·
                power-curve + generation forecast · SHAP-style attribution
      │
COGNITION       LangGraph mesh:  Orchestrator → Diagnostician → Market →
                Scheduler/Optimizer → Work-order      (+ RAG over O&M manuals)
      │
GOVERNANCE      Policy gate (OPA-style) · digital-twin sim pre-check · human approval ·
& ACTION        immutable hash-chained audit log · fleet-wide kill switch
```

**Design principle (seniority signal):** the **LLM reasons and explains; OR-Tools does the
optimisation.** We never ask a language model to do the math it's bad at — the Scheduler agent reads
the solver's answer and narrates the rationale.

---

## The optimization core (the differentiator)

The Scheduler chooses a maintenance window start `t*` over a rolling hourly horizon to minimise:

```
minimise  C(t) = LostRevenue(t) + RiskCost(t)
   LostRevenue(t) = Σ over downtime hours h:  price(h) · E[power(weather, h)]
   RiskCost(t)    = P_failure(t) · CostOfUnplannedFailure
subject to
   (1) a skilled crew is available in window t
   (2) wind inside window t ≤ safe-climb envelope (12 m/s)
   (3) no firm grid dispatch commitment is breached during t
```

Implemented as a **CP-SAT model** (Google OR-Tools): multiple incidents compete for shared crews via
optional-interval no-overlap — not a hand-rolled argmin. A naïve "fix-now" baseline is solved too;
the difference is the revenue-protected figure.

> An insight the build surfaced honestly: the **safe-climb constraint excludes the windiest (highest-
> generation) windows**, so among *climbable* windows the lost-revenue spread is modest — which is
> exactly why the dominant value is catching the fault early enough for *planned vs. run-to-failure*
> maintenance. The headline counter reflects both levers.

---

## Data plane — all real, all free

| Plane | Source | Licence |
|---|---|---|
| SCADA telemetry | **Kelmarsh wind farm** — 6× Senvion MM92, 10-min SCADA + fault logbook, 2016 ([Zenodo](https://doi.org/10.5281/zenodo.7212475)). The fleet is expanded to **20 turbines** by adding 14 *derived* turbines (real power curves + live weather, labelled synthetic) so the ops centre runs at scale. | CC-BY-4.0 |
| Grid & market | **energy-charts.info** (Fraunhofer ISE) — German DE-LU day-ahead prices · *(ENTSO-E adapter optional)* | Free, no key |
| Weather | **Open-Meteo** — hub-height wind forecast at each turbine's coordinates | Free, no key |
| Knowledge (RAG) | O&M / failure-mode references + the real SCADA event logbook | authored corpus |

**Synthetic & clearly labelled** (not public data, fine for a portfolio build): the crew roster, parts
inventory, grid-commitment schedule, and an injected degradation scenario (a moderate, early-onset
bearing/generator overheating ramp on two turbines so the closed loop has something real to act on —
the normality models are trained only on the *clean* baseline, so the residuals, health score,
prognosis lead-time and attribution are all genuinely learned).

---

## Stack (every layer free)

Lakehouse: Delta-style parquet medallion · Orchestration: **LangGraph** · LLM: **LiteLLM**
(Gemini/Groq/Anthropic/Ollama) · Optimisation: **Google OR-Tools** · RAG: **Chroma** + MiniLM ·
Models: **scikit-learn** · API: **FastAPI** · Frontend: **React + Vite + Recharts**.

---

## Run it

```bash
cd aeolus
./run.sh                       # bootstraps venv, builds pipeline, starts API + dashboard
# -> http://localhost:5173
```

Or step by step:

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m aeolus.pipeline          # M0→M5: ingest → models → market → optimise → agents → governance
../.venv/bin/python -m uvicorn aeolus.api.main:app --port 8000   # API
# in another shell:
cd ../frontend && npm install && npm run dev     # dashboard on :5173
```

**LLM (optional):** `cp .env.example .env` and add one free key (Gemini/Groq). Without a key the
agents use a deterministic reasoning fallback so the whole loop still runs; with a key they switch to
the real model automatically. The dashboard badge shows which mode is live.

---

## What you see on the dashboard

- **Fleet map** — every turbine a node coloured by health; a degrading turbine pulses.
- **The counter** — value protected, ticking up as work orders are approved.
- **Incident drawer** (click a turbine) — root-cause + SHAP-style attribution, the cost-of-downtime
  curve with the chosen window vs. the naïve fix-now window, the prognosis trajectory, the drafted
  work order, and the full LangGraph agent reasoning trace.
- **Approval queue** — one-click approve / reject (rejection is logged as a training signal).
- **Audit trail** — the hash-chained reasoning log, with live chain verification.
- **Kill switch** — halts all agent action fleet-wide.

---

## Phased roadmap (as built)

| Phase | Deliverable | Status |
|---|---|---|
| M0 Foundation | Lakehouse + ISA-95 asset registry on real SCADA | ✅ |
| M1 Perception | Normality + anomaly/prognosis + power-curve + attribution | ✅ |
| M2 Economics | Live market + weather → cost-of-downtime curve | ✅ |
| M3 Optimizer | OR-Tools CP-SAT scheduler + revenue-protected metric | ✅ |
| M4 Agent mesh | LangGraph orchestrator + 5 agents + RAG → dossier | ✅ |
| M5 Governance + UI | Policy gate, sim, audit log, kill switch + live dashboard | ✅ |

## Repository layout

```
aeolus/
  backend/aeolus/
    config.py            paths, curated signal map, ISA-95 taxonomy, economics, thresholds
    pipeline.py          one-command M0→M5 build
    lakehouse/           ingest (medallion + asset registry), synthetic ops tables
    perception/          scenario, normality + power-curve models, anomaly/prognosis/attribution
    market/              Open-Meteo + energy-charts → cost-of-downtime curve
    optimizer/           OR-Tools CP-SAT scheduler
    agents/              llm (LiteLLM), knowledge corpus, rag (Chroma), graph (LangGraph), run
    governance/          policy gate, digital-twin sim, hash-chained audit, kill switch
    api/                 FastAPI
  frontend/              React + Vite + Recharts dashboard
  data/                  bronze / silver / gold / synthetic / knowledge / audit / chroma
```
