"""O&M knowledge corpus builder.

Writes a small, realistic corpus of turbine O&M / failure-mode references that
grounds the Diagnostician and Work-order agents (so they cite procedure, not
hallucinate). Content reflects genuine wind-turbine failure physics for Senvion
MM92-class machines. Real event-log messages from the SCADA status files are also
folded in so retrieval can surface historically-observed faults.

These reference docs are authored for the portfolio build; in production they
would be the OEM's actual O&M manuals and the operator's maintenance history.
"""
from __future__ import annotations

import pandas as pd

from aeolus import config as C

DOCS: dict[str, str] = {
    "main_bearing.md": """# Main Bearing — Condition Monitoring & Maintenance (Senvion MM92 class)

## Failure modes
The main (rotor) bearing supports the low-speed shaft. The dominant degradation
mode is **grease degradation / loss of lubrication**, followed by raceway
spalling and micro-pitting. As lubrication fails, friction rises and the bearing
runs progressively **hotter than operating conditions justify** — the front and
rotor bearing temperatures climb above the value predicted by a normality model
for the current power and rotor speed. A sustained positive temperature residual
(2-8 °C and rising over weeks) is the classic early signature, typically 30-90
days before functional failure.

## Diagnostic signals
- Front bearing temperature residual rising vs. ambient and load.
- Rotor bearing temperature residual rising in step with the front bearing.
- Correlated low-frequency drive-train vibration (where available).

## Recommended action
Plan a re-greasing or bearing inspection during a low-generation window. If the
residual exceeds ~6 °C sustained, escalate to a bearing replacement work order.
An unplanned main-bearing seizure causes collateral damage to the shaft and
months of downtime, so acting on a confident prognosis is strongly preferred.

## Parts & crew
- Main bearing service kit (grease, seals, sensors).
- Replacement: low-speed-shaft bearing, 2 technicians + crane for full swap.
- Skill: main_bearing / drive-train certified crew.
- Typical planned downtime: 8-12 h (re-grease) ; 2-3 days (full replacement).
""",
    "gearbox.md": """# Gearbox — Condition Monitoring & Maintenance

## Failure modes
Gear-tooth pitting, bearing wear on intermediate/high-speed shafts, and oil
degradation. Symptoms: rising oil and bearing temperatures, increasing high-speed
vibration, particle counts in oil analysis. A persistent temperature residual on
gearbox bearings under normal load indicates progressing wear.

## Recommended action
Oil sampling + filtration first; schedule bearing/gear inspection in a planned
window. Unplanned gearbox failure is among the most expensive turbine events.

## Parts & crew
- Gearbox service kit, filtration unit, oil charge.
- Skill: gearbox / drive-train certified crew. Planned downtime 12-16 h.
""",
    "generator.md": """# Generator — Condition Monitoring & Maintenance

## Failure modes
Generator **bearing** wear (front/rear) and winding insulation degradation. The
leading early signature is a **generator bearing temperature residual** rising
above the normality-model prediction for the current power output — caused by
lubrication breakdown or bearing-current etching. Winding hot-spots show as motor
axis temperature residuals. Lead time to failure is typically 20-60 days from
first sustained residual.

## Diagnostic signals
- Generator bearing rear/front temperature residual rising under steady load.
- Motor-axis (winding) temperature residuals.

## Recommended action
Re-grease or replace the generator bearing in a planned window. Inspect slip
rings and winding insulation. Acting early converts a ~€195k unplanned failure
into a planned bearing service.

## Parts & crew
- Generator bearing kit, grease, insulation test gear.
- Skill: generator / electrical certified crew. Planned downtime 10-14 h.
""",
    "pitch_system.md": """# Pitch System — Condition Monitoring & Maintenance

## Failure modes
Pitch motor/gear wear, accumulator pressure loss, blade-angle sensor drift.
Symptoms: blade-angle tracking error between blades, pitch motor overtemperature,
hydraulic accumulator faults.

## Recommended action
Inspect pitch drives and accumulators; calibrate blade-angle sensors. Pitch
faults affect power regulation and safety (over-speed protection).

## Parts & crew
- Pitch motor/accumulator kit. Skill: pitch / hydraulics crew. Downtime 4-6 h.
""",
    "rotor.md": """# Rotor & Blades — Condition Monitoring

## Failure modes
Blade leading-edge erosion, imbalance, bolt loosening. Symptoms: rotor speed and
power-curve deviation, 1P vibration. Inspect during low-wind windows.

## Parts & crew
Blade repair kit, torque tooling. Skill: rotor / blade crew. Downtime 6-8 h.
""",
    "power_train.md": """# Power Train / Converter — Condition Monitoring

## Failure modes
Converter overtemperature, transformer fan overloads, reactive-power faults.
Symptoms: converter inlet-air overtemperature, apparent/reactive power anomalies,
breaker events in the status log.

## Parts & crew
Converter/fan spares. Skill: electrical crew. Downtime 5-7 h.
""",
    "scheduling_policy.md": """# Maintenance Scheduling Policy (economics & safety)

Choose the maintenance window that minimises total expected cost:
LostRevenue (price x expected generation during downtime) + RiskCost
(failure probability x unplanned-failure cost). Constraints: a skilled crew must
be available; wind inside the window must stay within the safe-climb envelope
(<= 12 m/s); no firm grid dispatch commitment may be breached.

Because SCADA prognosis can flag degradation weeks ahead, prefer a low-generation,
low-price, low-wind window over an immediate "fix-now" intervention. Always
prefer a planned intervention over running to an unplanned failure: a planned
job costs roughly a quarter of the unplanned event plus its extended downtime.
""",
    "eu_ai_act_governance.md": """# Governance & EU AI Act (high-risk obligations, Aug 2026)

Actions touching high-value physical assets require: a policy gate defining
autonomy boundaries (auto-approve vs. human escalation by cost/risk threshold), a
simulation pre-check, a technically-enforced human approval gate, and an immutable
audit log capturing the full reasoning chain (data considered, alternatives
weighed, confidence, decision, approver). A fleet-wide kill switch must be able to
halt agent action. This answers the regulator's three questions: what did the
system do, why, and should it have.
""",
}


def build_corpus() -> list[dict]:
    """Write the corpus to disk and return chunked documents for indexing."""
    chunks = []
    for fname, text in DOCS.items():
        path = C.KNOWLEDGE_DIR / fname
        path.write_text(text)
        component = fname.replace(".md", "")
        # chunk by markdown section (## ...)
        sections = text.split("\n## ")
        for i, sec in enumerate(sections):
            body = sec if i == 0 else "## " + sec
            chunks.append({
                "id": f"{component}-{i}",
                "text": body.strip(),
                "source": fname,
                "component": component,
                "kind": "om_manual",
            })

    # fold in real, distinct status/fault messages from the SCADA logbook
    try:
        status = pd.read_parquet(C.BRONZE_DIR / "status_events.parquet")
        faults = (status[status["Status"].isin(["Stop", "Warning"])]
                  .dropna(subset=["Message"]))
        top = (faults["Message"].value_counts().head(40).index.tolist())
        for j, msg in enumerate(top):
            chunks.append({
                "id": f"eventlog-{j}",
                "text": f"Historical SCADA event (observed on the Kelmarsh fleet): {msg}.",
                "source": "status_events.parquet",
                "component": "event_log",
                "kind": "event_log",
            })
    except Exception as e:
        print(f"  [warn] could not fold in event log: {e}")

    print(f"  knowledge corpus: {len(DOCS)} O&M docs -> {len(chunks)} chunks")
    return chunks


if __name__ == "__main__":
    build_corpus()
