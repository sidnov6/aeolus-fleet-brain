"""Economics layer: live weather + live market -> per-asset cost-of-downtime curve.

Real, free, no-key sources:
  - Open-Meteo            hub-height wind forecast at each turbine's coordinates
  - energy-charts.info    German (DE-LU) day-ahead electricity prices (Fraunhofer ISE)
  - ENTSO-E               optional, used instead of energy-charts if a token is set

The cost-of-downtime (opportunity-cost) curve answers: "if this turbine is offline
during hour h, how much generation revenue do we lose?"

    opportunity_cost(h) = price(h) [EUR/MWh] * E[power(wind(h))] [MWh]

with E[power] from the turbine's fitted power curve. This hourly curve is what the
Scheduler trades off against rising failure risk.

Temporal bridge (stated honestly): asset health comes from the historical SCADA
record, while price and weather are pulled *live* for the scheduling horizon —
i.e. we value the maintenance decision against today's real German market and
today's real wind forecast.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import requests

from aeolus import config as C
from aeolus.perception import models as M

HORIZON_DAYS = 5
_TIMEOUT = 25


def get_horizon() -> tuple[pd.Timestamp, int]:
    start = pd.Timestamp.now(tz="UTC").floor("h")
    return start, HORIZON_DAYS * 24


# ---------------------------------------------------------------------------
# Weather (Open-Meteo) — real, no key
# ---------------------------------------------------------------------------
def fetch_weather(start: pd.Timestamp, hours: int) -> pd.DataFrame:
    turbines = pd.read_parquet(C.SILVER_DIR / "turbines.parquet")
    grid = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    frames = []
    for _, t in turbines.iterrows():
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": t["latitude"], "longitude": t["longitude"],
                "hourly": "wind_speed_80m,wind_direction_80m,temperature_2m",
                "wind_speed_unit": "ms", "forecast_days": 7, "timezone": "UTC",
            }, timeout=_TIMEOUT).json()["hourly"]
            w = pd.DataFrame({
                "timestamp": pd.to_datetime(r["time"], utc=True),
                "wind_ms": r["wind_speed_80m"],
                "wind_dir": r["wind_direction_80m"],
                "ambient_temp": r["temperature_2m"],
            })
            source = "Open-Meteo"
        except Exception as e:                                   # offline fallback
            print(f"  [warn] Open-Meteo failed for {t['turbine_id']}: {e}; synthesizing")
            rng = np.random.default_rng(hash(t["turbine_id"]) % 2**32)
            w = pd.DataFrame({"timestamp": grid,
                              "wind_ms": np.clip(7 + 3*np.sin(np.arange(hours)/6) + rng.normal(0,1.5,hours), 0, 25),
                              "wind_dir": rng.uniform(0,360,hours),
                              "ambient_temp": 12 + 4*np.sin(np.arange(hours)/12)})
            source = "SYNTHETIC-fallback"
        w = w[w["timestamp"].isin(grid)].copy()
        w["turbine_id"] = t["turbine_id"]
        w["source"] = source
        frames.append(w)
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(C.GOLD_DIR / "weather_forecast.parquet")
    return out


# ---------------------------------------------------------------------------
# Prices (energy-charts.info / ENTSO-E) — real, free
# ---------------------------------------------------------------------------
def _entsoe_prices(start: pd.Timestamp, hours: int, token: str) -> pd.DataFrame | None:
    try:
        from entsoe import EntsoePandasClient  # optional dep
        client = EntsoePandasClient(api_key=token)
        s = start.tz_convert("Europe/Berlin")
        e = s + pd.Timedelta(hours=hours)
        ser = client.query_day_ahead_prices("DE_LU", start=s, end=e)
        df = ser.rename("price_eur_mwh").reset_index()
        df.columns = ["timestamp", "price_eur_mwh"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["source"] = "ENTSO-E"
        return df
    except Exception as e:
        print(f"  [warn] ENTSO-E failed ({e}); falling back to energy-charts")
        return None


def fetch_prices(start: pd.Timestamp, hours: int) -> pd.DataFrame:
    grid = pd.date_range(start, periods=hours, freq="h", tz="UTC")

    token = os.environ.get("ENTSOE_API_TOKEN")
    if token:
        df = _entsoe_prices(start, hours, token)
        if df is not None and len(df):
            return _fit_price_to_grid(df, grid)

    # energy-charts day-ahead (real DE-LU), no key
    try:
        r = requests.get("https://api.energy-charts.info/price",
                         params={"bzn": "DE-LU"}, timeout=_TIMEOUT).json()
        raw = pd.DataFrame({
            "timestamp": pd.to_datetime(np.array(r["unix_seconds"]) * 1_000_000_000),
            "price_eur_mwh": r["price"],
        })
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
        raw["source"] = "energy-charts.info (DE-LU day-ahead)"
        return _fit_price_to_grid(raw, grid)
    except Exception as e:
        print(f"  [warn] energy-charts failed ({e}); synthesizing price curve")
        hour = grid.hour.to_numpy()
        # typical German day-ahead shape: morning + evening peaks
        base = 70 + 45*np.exp(-((hour-8)**2)/8) + 60*np.exp(-((hour-19)**2)/6) - 20*np.exp(-((hour-3)**2)/6)
        df = pd.DataFrame({"timestamp": grid, "price_eur_mwh": base,
                           "source": "SYNTHETIC-fallback"})
        return df


def _fit_price_to_grid(raw: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Resample real prices to hourly, then tile the daily shape to fill horizon.

    Day-ahead data usually covers ~1-2 days; we extend it as a forward curve by
    repeating the hour-of-day profile. Labelled so it's clear which hours are
    measured vs. modelled-forward.
    """
    raw = raw.set_index("timestamp").sort_index()
    hourly = raw["price_eur_mwh"].resample("1h").mean().dropna()
    source = raw["source"].iloc[0]

    # hour-of-day profile from the real data, to extend forward
    by_hour = hourly.groupby(hourly.index.hour).mean()
    global_mean = float(hourly.mean())

    rows = []
    for ts in grid:
        if ts in hourly.index:
            price, kind = float(hourly.loc[ts]), "measured"
        else:
            price = float(by_hour.get(ts.hour, global_mean))
            kind = "modelled-forward"
        rows.append({"timestamp": ts, "price_eur_mwh": round(price, 2),
                     "source": source, "kind": kind})
    df = pd.DataFrame(rows)
    df.to_parquet(C.GOLD_DIR / "market_prices.parquet")
    return df


# ---------------------------------------------------------------------------
# Cost-of-downtime curve
# ---------------------------------------------------------------------------
def build_cost_curves() -> pd.DataFrame:
    start, hours = get_horizon()
    weather = fetch_weather(start, hours)
    prices = fetch_prices(start, hours)

    price_by_ts = prices.set_index("timestamp")["price_eur_mwh"]
    rows = []
    for tid, w in weather.groupby("turbine_id"):
        w = w.sort_values("timestamp")
        exp_kw = M.expected_power_kw(tid, w["wind_ms"].to_numpy())
        for ts, wind, ekw in zip(w["timestamp"], w["wind_ms"], exp_kw):
            price = float(price_by_ts.get(ts, np.nan))
            if np.isnan(price):
                continue
            opp = price * (ekw / 1000.0)        # EUR lost for 1h of downtime
            rows.append({
                "turbine_id": tid, "timestamp": ts,
                "wind_ms": round(float(wind), 2),
                "expected_power_kw": round(float(ekw), 1),
                "price_eur_mwh": round(price, 2),
                "opportunity_cost_eur": round(float(opp), 2),
            })
    df = pd.DataFrame(rows)
    df.to_parquet(C.GOLD_DIR / "cost_of_downtime.parquet")
    psrc = prices["source"].iloc[0]
    wsrc = weather["source"].iloc[0]
    print(f"  market: prices[{psrc}] weather[{wsrc}] | horizon {start:%Y-%m-%d %Hh} +{hours}h")
    print(f"  cost-of-downtime curve: {len(df):,} turbine-hours; "
          f"mean opp.cost {df['opportunity_cost_eur'].mean():.1f} EUR/h, "
          f"peak {df['opportunity_cost_eur'].max():.1f} EUR/h")
    return df


def run() -> None:
    build_cost_curves()


if __name__ == "__main__":
    run()
