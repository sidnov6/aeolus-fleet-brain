"""Synthetic operational tables — crew roster, parts inventory, grid commitments.

These three tables are NOT public data. Per the blueprint, a realistic generated
table is fine for a portfolio build *as long as it is labelled honestly as
synthetic*. Every row carries source='SYNTHETIC' so nothing downstream can
mistake them for measured data.

Determinism: seeded RNG, no wall-clock — the same fleet + horizon always yields
the same tables, so the demo is reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aeolus import config as C

SEED = 42


def build_crew_roster(horizon_start: pd.Timestamp, days: int = 5) -> pd.DataFrame:
    """Two maintenance crews with daily shift availability over the horizon.

    A crew is climbable only during daylight working hours; the optimizer also
    checks the weather safe-climb envelope on top of this.
    """
    rng = np.random.default_rng(SEED)
    crews = [
        {"crew_id": "CREW-A", "skills": "main_bearing,gearbox,power_train", "base_km": 8},
        {"crew_id": "CREW-B", "skills": "generator,pitch_system,rotor,nacelle", "base_km": 22},
    ]
    rows = []
    for d in range(days):
        day = (horizon_start + pd.Timedelta(days=d)).normalize()
        for crew in crews:
            # most days available 07:00-17:00; ~15% of crew-days are booked out
            available = rng.random() > 0.15
            shift_start = day + pd.Timedelta(hours=7)
            shift_end = day + pd.Timedelta(hours=17)
            rows.append({
                "crew_id": crew["crew_id"],
                "skills": crew["skills"],
                "date": day,
                "available": bool(available),
                "shift_start": shift_start,
                "shift_end": shift_end,
                "travel_km": crew["base_km"],
                "source": "SYNTHETIC",
            })
    df = pd.DataFrame(rows)
    df.to_parquet(C.SYNTHETIC_DIR / "crew_roster.parquet")
    return df


def build_parts_inventory() -> pd.DataFrame:
    """Spare-parts stock per component, with lead time when out of stock."""
    rng = np.random.default_rng(SEED + 1)
    rows = []
    for comp in C.COMPONENTS:
        in_stock = int(rng.integers(0, 3))
        rows.append({
            "component": comp,
            "part_name": f"{comp.replace('_', ' ').title()} service kit",
            "in_stock": in_stock,
            "reorder_lead_days": int(rng.integers(2, 10)) if in_stock == 0 else 0,
            "unit_cost_eur": round(float(C.UNPLANNED_FAILURE_COST[comp]) * C.PLANNED_COST_FRACTION * 0.4, 0),
            "source": "SYNTHETIC",
        })
    df = pd.DataFrame(rows)
    df.to_parquet(C.SYNTHETIC_DIR / "parts_inventory.parquet")
    return df


def build_grid_commitments(horizon_start: pd.Timestamp, days: int = 5) -> pd.DataFrame:
    """Firm grid dispatch commitments the fleet must honour.

    During a committed block the fleet has promised a minimum aggregate output,
    so taking a turbine down then risks breaching the commitment. The optimizer
    treats these blocks as hard constraints (checked via the digital-twin sim).
    """
    rng = np.random.default_rng(SEED + 2)
    rows = []
    for d in range(days):
        day = (horizon_start + pd.Timedelta(days=d)).normalize()
        # a short evening-peak commitment block on ~40% of days (a real but
        # occasional constraint, not an everyday blanket)
        if rng.random() < 0.40:
            start = day + pd.Timedelta(hours=18)
            end = day + pd.Timedelta(hours=20)
            rows.append({
                "commitment_id": f"GRID-{day.date()}-PEAK",
                "start": start,
                "end": end,
                "min_aggregate_mw": round(float(rng.uniform(4.0, 7.0)), 2),
                "penalty_eur_per_mwh": 180.0,
                "source": "SYNTHETIC",
            })
    df = pd.DataFrame(rows)
    df.to_parquet(C.SYNTHETIC_DIR / "grid_commitments.parquet")
    return df


def run(horizon_start: pd.Timestamp | None = None, days: int = 5) -> None:
    if horizon_start is None:
        # anchor to the end of the real SCADA so the horizon sits "now" in-sim
        scada = pd.read_parquet(C.SILVER_DIR / "scada.parquet", columns=["timestamp"])
        horizon_start = pd.Timestamp(scada["timestamp"].max()).ceil("D")
    crew = build_crew_roster(horizon_start, days)
    parts = build_parts_inventory()
    grid = build_grid_commitments(horizon_start, days)
    print(f"  synthetic crew roster: {len(crew)} crew-days (labelled SYNTHETIC)")
    print(f"  synthetic parts inventory: {len(parts)} components")
    print(f"  synthetic grid commitments: {len(grid)} firm blocks")


if __name__ == "__main__":
    run()
