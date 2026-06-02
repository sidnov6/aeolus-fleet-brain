"""End-to-end data + model pipeline (M0 -> M3), with one aligned horizon.

Run this once to (re)build the lakehouse, perception models, market curves and
the optimal schedule. The LangGraph agent mesh (M4) and the API (M5) read the
Gold artefacts this produces.

    python -m aeolus.pipeline            # full rebuild
    python -m aeolus.pipeline --fast     # skip raw re-ingest + model retrain
"""
from __future__ import annotations

import sys

from aeolus.agents import run as agents_run
from aeolus.governance import gate
from aeolus.lakehouse import expand, ingest, synthetic
from aeolus.market import market
from aeolus.optimizer import scheduler
from aeolus.perception import detect, models, scenario


def run(fast: bool = False) -> None:
    if not fast:
        print("== M0: lakehouse ==")
        ingest.run()
        print("== M0: fleet expansion (6 real + derived) ==")
        expand.run()
        print("== M1: scenario + perception models ==")
        scenario.inject()
        models.run()
    print("== M1: anomaly + prognosis ==")
    detect.assess()

    print("== M2: market + cost-of-downtime ==")
    market.run()
    # align synthetic crew/grid to the live market horizon (+buffer)
    start, hours = market.get_horizon()
    synthetic.run(horizon_start=start.normalize(), days=hours // 24 + 3)

    print("== M3: optimiser ==")
    scheduler.optimise()

    print("== M4: agent mesh -> dossiers ==")
    agents_run.run()

    print("== M5: governance gate -> approval queue + audit ==")
    gate.build_approval_queue()
    print("== pipeline complete ==")


if __name__ == "__main__":
    run(fast="--fast" in sys.argv)
