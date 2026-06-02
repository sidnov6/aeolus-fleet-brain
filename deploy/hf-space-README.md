---
title: AEOLUS Fleet Brain
emoji: 🌬️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Autonomous operations brain for a renewable wind fleet
---

# AEOLUS — Autonomous Operations Brain for a Renewable Energy Fleet

Live full-stack deployment (FastAPI + dashboard, single service). Detects a
degrading turbine, root-causes it, prices acting now vs. later against the live
German market + wind forecast, schedules the cheapest safe window with OR-Tools,
drafts the work order, and gates every action through human approval with an
immutable audit trail. A background scheduler re-optimises against the moving
market on an interval.

Code & docs: https://github.com/sidnov6/aeolus-fleet-brain

Real data: Kelmarsh SCADA (Zenodo, CC-BY-4.0) · DE-LU day-ahead prices
(energy-charts.info) · Open-Meteo wind. LLM via Groq (set `GROQ_API_KEY` as a
Space secret).
