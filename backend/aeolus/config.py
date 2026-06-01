"""AEOLUS — central configuration, paths, and the curated signal registry.

This module is the single source of truth for filesystem layout, the curated
SCADA signal set we lift out of the raw 464-column Kelmarsh export, and the
ISA-95 component taxonomy that the asset registry is built on.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
PROJECT_DIR = BACKEND_DIR.parent                              # .../aeolus
DATA_DIR = PROJECT_DIR / "data"

RAW_DIR = DATA_DIR / "raw"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
ARTIFACT_DIR = DATA_DIR / "artifacts"           # trained models
AUDIT_DIR = DATA_DIR / "audit"                  # immutable audit log
CHROMA_DIR = DATA_DIR / "chroma"                # RAG vector store

for _p in (BRONZE_DIR, SILVER_DIR, GOLD_DIR, SYNTHETIC_DIR, KNOWLEDGE_DIR,
           ARTIFACT_DIR, AUDIT_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Fleet metadata (real Kelmarsh wind farm — Senvion MM92, 2.05 MW each)
# ---------------------------------------------------------------------------
SITE = "Kelmarsh"
RATED_POWER_KW = 2050.0
# Bidding zone for the German market (the deployment geography in the blueprint).
# energy-charts.info uses "DE-LU"; Open-Meteo is queried at the turbine coords.
BIDDING_ZONE = "DE-LU"

# ---------------------------------------------------------------------------
# Curated SCADA signals — the subset we lift from the 464-column raw export.
# Each maps to: canonical_name -> (raw_column, isa95_component, unit)
# This is the "data contract": every signal is anchored to a component.
# ---------------------------------------------------------------------------
# ISA-95 component taxonomy (site -> turbine -> component -> signal)
COMPONENTS = [
    "rotor",
    "main_bearing",
    "gearbox",
    "generator",
    "pitch_system",
    "nacelle",
    "power_train",
]

SIGNAL_MAP: dict[str, tuple[str, str, str]] = {
    # canonical                 raw column                                       component        unit
    "timestamp":               ("Date and time",                                 "_index",        "datetime"),
    "wind_speed":              ("Wind speed (m/s)",                              "nacelle",       "m/s"),
    "power":                   ("Power (kW)",                                    "power_train",   "kW"),
    "reactive_power":          ("Reactive power (kvar)",                         "power_train",   "kvar"),
    "rotor_speed":             ("Rotor speed (RPM)",                             "rotor",         "rpm"),
    "gearbox_speed":           ("Gearbox speed (RPM)",                           "gearbox",       "rpm"),
    "nacelle_temp":            ("Nacelle ambient temperature (°C)",              "nacelle",       "degC"),
    "front_bearing_temp":      ("Front bearing temperature (°C)",                "main_bearing",  "degC"),
    "rear_bearing_temp":       ("Rear bearing temperature (°C)",                 "main_bearing",  "degC"),
    "rotor_bearing_temp":      ("Rotor bearing temp (°C)",                       "main_bearing",  "degC"),
    "gen_bearing_front_temp":  ("Generator bearing front temperature (°C)",      "generator",     "degC"),
    "gen_bearing_rear_temp":   ("Generator bearing rear temperature (°C)",       "generator",     "degC"),
    "gen_motor_temp_1":        ("Temperature motor axis 1 (°C)",                 "generator",     "degC"),
    "gen_motor_temp_2":        ("Temperature motor axis 2 (°C)",                 "generator",     "degC"),
    "gen_motor_temp_3":        ("Temperature motor axis 3 (°C)",                 "generator",     "degC"),
    "nacelle_position":        ("Nacelle position (°)",                          "nacelle",       "deg"),
    "pitch_angle":             ("Blade angle (pitch position) A (°)",            "pitch_system",  "deg"),
}

# Temperature signals that get a per-component normality (expected-value) model.
# canonical_temp -> component
TEMP_TARGETS: dict[str, str] = {
    "front_bearing_temp": "main_bearing",
    "rear_bearing_temp": "main_bearing",
    "rotor_bearing_temp": "main_bearing",
    "gen_bearing_front_temp": "generator",
    "gen_bearing_rear_temp": "generator",
    "gen_motor_temp_1": "generator",
    "gen_motor_temp_2": "generator",
    "gen_motor_temp_3": "generator",
}

# Drivers used to predict the expected temperature under current conditions.
NORMALITY_DRIVERS = ["power", "rotor_speed", "wind_speed", "nacelle_temp"]

# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------
# Cost of an UNPLANNED failure per component (EUR) — replacement + collateral
# damage + emergency crew + extended downtime. Synthetic but order-of-magnitude
# realistic for a 2 MW onshore turbine. Labelled synthetic in the data dict.
UNPLANNED_FAILURE_COST: dict[str, float] = {
    "main_bearing": 230_000.0,
    "gearbox": 290_000.0,
    "generator": 195_000.0,
    "pitch_system": 85_000.0,
    "rotor": 160_000.0,
    "nacelle": 60_000.0,
    "power_train": 120_000.0,
}
# A planned intervention costs a fraction of the unplanned figure.
PLANNED_COST_FRACTION = 0.28

# Maintenance job duration per component (hours) — drives downtime window length.
MAINTENANCE_HOURS: dict[str, int] = {
    "main_bearing": 10,
    "gearbox": 14,
    "generator": 12,
    "pitch_system": 6,
    "rotor": 8,
    "nacelle": 5,
    "power_train": 7,
}

# Safe-climb envelope: technicians cannot climb / lift above this wind speed.
SAFE_CLIMB_MAX_WIND_MS = 12.0

# ---------------------------------------------------------------------------
# Governance / policy thresholds (OPA-style autonomy boundaries)
# ---------------------------------------------------------------------------
AUTO_APPROVE_MAX_COST_EUR = 25_000.0     # actions costlier than this -> human
AUTO_APPROVE_MAX_RISK = 0.35             # P(failure) above this -> human
KILL_SWITCH_FILE = DATA_DIR / "KILL_SWITCH"

# ---------------------------------------------------------------------------
# LLM (wired via LiteLLM; provider/key resolved from env / .env)
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# Model is chosen by which key is present; AEOLUS_LLM_MODEL overrides.
LLM_MODEL = os.environ.get("AEOLUS_LLM_MODEL", "")
if not LLM_MODEL:
    if os.environ.get("GEMINI_API_KEY"):
        LLM_MODEL = "gemini/gemini-2.0-flash"
    elif os.environ.get("GROQ_API_KEY"):
        LLM_MODEL = "groq/llama-3.3-70b-versatile"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        LLM_MODEL = "anthropic/claude-haiku-4-5-20251001"
    elif os.environ.get("OPENAI_API_KEY"):
        LLM_MODEL = "gpt-4o-mini"

LLM_AVAILABLE = bool(
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GROQ_API_KEY")
    or os.environ.get("ANTHROPIC_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)
