"""Run the agent mesh over every open incident -> Gold dossiers."""
from __future__ import annotations

import json

from aeolus import config as C
from aeolus.agents import graph, rag


def run() -> list[dict]:
    rag.build_index(rebuild=True)
    incidents = json.loads((C.GOLD_DIR / "incidents.json").read_text())
    dossiers = []
    for inc in incidents:
        d = graph.run_incident(inc)
        dossiers.append(d)
        print(f"  dossier: {d['turbine_id']} {d['component']} | "
              f"diag conf {d['diagnosis'].get('confidence')} | "
              f"scheduled {d['schedule'].get('scheduled', False)} | "
              f"WO '{d['work_order'].get('title','-')[:40]}'")
    (C.GOLD_DIR / "dossiers.json").write_text(json.dumps(dossiers, indent=2, default=str))
    print(f"  {len(dossiers)} dossier(s) -> dossiers.json (LLM mode: {__import__('aeolus.agents.llm', fromlist=['mode']).mode()})")
    return dossiers


if __name__ == "__main__":
    run()
