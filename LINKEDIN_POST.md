# LinkedIn launch post

---

Everyone is building AI agents that *predict* wind-turbine failures.

The hard, valuable problem is the closed loop *after* the prediction: deciding **when to act** so you lose the least generation revenue — under real crew, weather, and grid constraints, with a governance trail a regulated operator can actually deploy.

So I built **AEOLUS** — an autonomous operations brain that runs a wind fleet the way a great operations director would. 🌬️

🔗 Live demo: https://aeolus-fleet-brain.vercel.app
💻 Code: https://github.com/sidnov6/aeolus-fleet-brain

**What it does — the full closed loop:**

1️⃣ **Detects** a turbine degrading from real SCADA telemetry (a main bearing running hotter than operating conditions justify).
2️⃣ **Root-causes** it — names the component and confidence, grounded in O&M manuals via RAG.
3️⃣ **Prices** the cost of acting now vs. later against the **live German day-ahead market** and the **live wind forecast**.
4️⃣ **Schedules** the cheapest *safe* maintenance window with a real solver — under crew availability, the safe-climb wind envelope, and firm grid commitments.
5️⃣ **Drafts** the work order and routes it to a human for one-click approval.

Every action passes a policy gate, a digital-twin simulation, and a human approval gate — logged to an immutable, hash-chained audit trail. There's a fleet-wide kill switch. This is what the EU AI Act's high-risk obligations (live Aug 2026) actually require.

**The design principle I'm most proud of:** the LLM *reasons and explains*; **Google OR-Tools does the optimisation.** I never ask a language model to do the math it's bad at. The objective is explicit — minimise `LostRevenue(t) + RiskCost(t)` — and the headline metric is **value protected vs. naïve "fix-it-now" scheduling**, broken into generation revenue saved + unplanned-failure cost avoided (planned vs. run-to-failure).

**The stack — every layer free / open:**
🔹 Data: real **Kelmarsh** wind-farm SCADA (Zenodo, CC-BY) · German **DE-LU day-ahead prices** (energy-charts.info) · **Open-Meteo** hub-height wind
🔹 Lakehouse: Delta-style medallion (Bronze → Silver + an **ISA-95 unified namespace** asset registry → Gold feature store)
🔹 Perception: **scikit-learn** normality models + anomaly/prognosis (health score, lead-time, failure-probability curve) + SHAP-style attribution
🔹 Optimisation: **Google OR-Tools** CP-SAT
🔹 Agents: **LangGraph** orchestrator + 4 specialists, **Groq** (Llama-3.3-70B) via **LiteLLM**, **Chroma** RAG
🔹 Governance: OPA-style policy engine, digital-twin sim, hash-chained audit log, kill switch
🔹 App: **FastAPI** + **React/Vite** — a live ops dashboard with an animated wind farm, dark/light themes, and a revenue-protected counter that ticks up as you approve work orders

Prediction is commoditised. Economically-optimal, governed, autonomous scheduling against a live market is not. That gap is where the value is.

Built end-to-end on real European wind data for $0. Demo + code linked above — feedback very welcome. 👇

#AgenticAI #RenewableEnergy #WindEnergy #LangGraph #MLOps #Energiewende #PredictiveMaintenance #AI #OperationsResearch #EUAIAct

---

## Shorter variant (if you want punchier)

Everyone builds agents that *predict* turbine failures. The hard part is the closed loop *after*: deciding **when to act** to lose the least revenue, under crew/weather/grid constraints, with a governance trail you can actually deploy.

I built **AEOLUS** — an autonomous operations brain for a wind fleet. It detects a degrading turbine, root-causes it (RAG over O&M manuals), prices acting-now-vs-later against the **live German power market + wind forecast**, schedules the cheapest *safe* window with **OR-Tools**, drafts the work order, and gates every action behind a policy engine + digital-twin sim + human approval + an immutable audit log.

Key principle: the **LLM reasons; the solver optimises.** Real Kelmarsh SCADA + live market data. LangGraph · Groq · OR-Tools · scikit-learn · FastAPI · React.

🔗 https://aeolus-fleet-brain.vercel.app  ·  💻 https://github.com/sidnov6/aeolus-fleet-brain

#AgenticAI #RenewableEnergy #LangGraph #Energiewende #AI
