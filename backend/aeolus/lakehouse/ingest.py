"""Medallion ingestion: raw Kelmarsh export -> Bronze -> Silver + asset registry.

Real data source: Kelmarsh wind farm (Zenodo 10.5281/zenodo.7212475, CC-BY-4.0).
6x Senvion MM92 turbines, 10-min SCADA, full-year 2016, plus a real status/fault
logbook per turbine.

We lift a curated, component-anchored subset of the 464-column raw export
(see config.SIGNAL_MAP) and resample onto a regular 10-min grid. The unglamorous
artefact this produces — the ISA-95 asset registry — is the data contract that
lets every downstream agent share one clean view of the fleet.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

from aeolus import config as C

_SCADA_ZIP = C.RAW_DIR / "Kelmarsh_SCADA_2016_3082.zip"
_STATIC_CSV = C.RAW_DIR / "Kelmarsh_WT_static.csv"

# Real Kelmarsh wind farm dataset (Zenodo 10.5281/zenodo.7212475, CC-BY-4.0).
_ZENODO = "https://zenodo.org/api/records/7212475/files"
_RAW_FILES = [
    "Kelmarsh_WT_static.csv",
    "Kelmarsh_WT_dataSignalMapping.csv",
    "Kelmarsh_Grid_3088.zip",
    "Kelmarsh_SCADA_2016_3082.zip",   # ~95 MB
]


def ensure_raw() -> None:
    """Download the real Kelmarsh inputs from Zenodo if not already present."""
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for fname in _RAW_FILES:
        dest = C.RAW_DIR / fname
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"{_ZENODO}/{fname}/content"
        print(f"  downloading {fname} from Zenodo ...")
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)

# raw column names we want (values of SIGNAL_MAP, position 0)
_WANTED_RAW = {raw: canon for canon, (raw, _comp, _unit) in C.SIGNAL_MAP.items()}


def _strip_hash(col: str) -> str:
    """The header's first cell is '# Date and time'; normalise it."""
    return col.lstrip("#").strip()


def _read_turbine_csv(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one Greenbyte turbine CSV: 9 comment lines, header on line 10."""
    text = raw_bytes.decode("utf-8", errors="replace")

    def _usecols(col: str) -> bool:
        return _strip_hash(col) in _WANTED_RAW

    df = pd.read_csv(
        io.StringIO(text),
        skiprows=9,            # drop the 9-line '#' preamble; line 10 is the header
        usecols=_usecols,
        na_values=["NaN"],
        low_memory=False,
    )
    df.columns = [_strip_hash(c) for c in df.columns]
    # raw -> canonical
    df = df.rename(columns={raw: canon for raw, canon in _WANTED_RAW.items()})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    # numeric coercion for everything else
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _read_status_csv(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one status/fault logbook CSV: header on line 10."""
    text = raw_bytes.decode("utf-8", errors="replace")
    df = pd.read_csv(io.StringIO(text), skiprows=9, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def _turbine_id(filename: str) -> str | None:
    m = re.search(r"Kelmarsh_(\d+)_", filename)
    return f"KWF{m.group(1)}" if m else None


def build_bronze() -> dict[str, Path]:
    """Extract curated SCADA + status from the raw zip into Bronze parquet.

    Bronze is immutable raw landing: curated columns, parsed types, nothing else.
    Returns {turbine_id: scada_parquet_path}.
    """
    if not _SCADA_ZIP.exists():
        raise FileNotFoundError(f"Missing raw SCADA zip: {_SCADA_ZIP}")

    scada_paths: dict[str, Path] = {}
    status_frames: list[pd.DataFrame] = []

    with zipfile.ZipFile(_SCADA_ZIP) as zf:
        for name in zf.namelist():
            tid = _turbine_id(name)
            if tid is None:
                continue
            raw = zf.read(name)
            if name.startswith("Turbine_Data_"):
                df = _read_turbine_csv(raw)
                df.insert(0, "turbine_id", tid)
                out = C.BRONZE_DIR / f"scada_{tid}.parquet"
                df.to_parquet(out)
                scada_paths[tid] = out
                print(f"  bronze SCADA {tid}: {len(df):,} rows x {df.shape[1]} cols -> {out.name}")
            elif name.startswith("Status_"):
                sdf = _read_status_csv(raw)
                sdf.insert(0, "turbine_id", tid)
                status_frames.append(sdf)

    if status_frames:
        status = pd.concat(status_frames, ignore_index=True)
        status.to_parquet(C.BRONZE_DIR / "status_events.parquet")
        print(f"  bronze status events: {len(status):,} rows")
    return scada_paths


def build_asset_registry() -> pd.DataFrame:
    """ISA-95 unified namespace: site -> turbine -> component -> signal.

    Every curated signal is anchored to a canonical path. This is the data
    contract shared by all agents.
    """
    static = pd.read_csv(_STATIC_CSV)
    static.columns = [c.strip() for c in static.columns]
    static = static.rename(columns={"Alternative Title": "turbine_id"})

    rows = []
    for _, t in static.iterrows():
        tid = str(t["turbine_id"]).strip()
        for canon, (raw, component, unit) in C.SIGNAL_MAP.items():
            if component == "_index":
                continue
            rows.append({
                "site": C.SITE,
                "turbine_id": tid,
                "turbine_name": str(t["Title"]).strip(),
                "component": component,
                "signal": canon,
                "raw_signal": raw,
                "unit": unit,
                "isa95_path": f"{C.SITE}/{tid}/{component}/{canon}",
                "rated_power_kw": float(t["Rated power (kW)"]),
                "rotor_diameter_m": float(t["Rotor Diameter (m)"]),
                "hub_height_m": float(t["Hub Height (m)"]),
                "latitude": float(t["Latitude"]),
                "longitude": float(t["Longitude"]),
            })
    reg = pd.DataFrame(rows)
    reg.to_parquet(C.SILVER_DIR / "asset_registry.parquet")

    # also a compact per-turbine table for the UI / market layer
    turbines = (reg.groupby("turbine_id")
                .agg(turbine_name=("turbine_name", "first"),
                     rated_power_kw=("rated_power_kw", "first"),
                     rotor_diameter_m=("rotor_diameter_m", "first"),
                     hub_height_m=("hub_height_m", "first"),
                     latitude=("latitude", "first"),
                     longitude=("longitude", "first"))
                .reset_index())
    turbines["site"] = C.SITE
    turbines.to_parquet(C.SILVER_DIR / "turbines.parquet")
    print(f"  asset registry: {len(reg)} signal mappings across {turbines.shape[0]} turbines")
    return reg


def build_silver(scada_paths: dict[str, Path]) -> Path:
    """Clean + resample to a regular 10-min grid; unified fleet SCADA table.

    - dedupe on (turbine, timestamp)
    - reindex onto a continuous 10-min grid, gaps left as NaN (honest)
    - light interpolation of short gaps (<= 30 min) for model stability
    """
    frames = []
    for tid, path in sorted(scada_paths.items()):
        df = pd.read_parquet(path)
        df = df[~df.index.duplicated(keep="first")]
        grid = pd.date_range(df.index.min(), df.index.max(), freq="10min", tz="UTC")
        df = df.reindex(grid)
        df["turbine_id"] = tid
        # short-gap interpolation only (don't fabricate long outages)
        num_cols = [c for c in df.columns if c != "turbine_id"]
        df[num_cols] = df[num_cols].interpolate(method="time", limit=3, limit_area="inside")
        df.index.name = "timestamp"
        frames.append(df.reset_index())
        print(f"  silver {tid}: {len(df):,} rows on regular 10-min grid")

    fleet = pd.concat(frames, ignore_index=True)
    out = C.SILVER_DIR / "scada.parquet"
    fleet.to_parquet(out)
    print(f"  silver fleet SCADA: {len(fleet):,} rows -> {out.name}")
    return out


def run() -> None:
    print("== M0: ensure raw data (Zenodo, CC-BY-4.0) ==")
    ensure_raw()
    print("== M0: Bronze ingestion ==")
    scada_paths = build_bronze()
    print("== M0: Asset registry (ISA-95) ==")
    build_asset_registry()
    print("== M0: Silver clean + resample ==")
    build_silver(scada_paths)
    print("== M0 complete ==")


if __name__ == "__main__":
    run()
