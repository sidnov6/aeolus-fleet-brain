import React, { useEffect, useRef, useState } from "react";
import { eur } from "../util.js";

// Smoothly tick the displayed value toward the target (the money shot).
// Timer-driven (not requestAnimationFrame) so it still reaches the target when
// the tab is backgrounded/hidden — rAF is paused while hidden, timers are not.
function useTicker(rawTarget) {
  const target = Number(rawTarget) || 0;        // guard against null/undefined -> NaN
  const [val, setVal] = useState(0);
  const valRef = useRef(0);
  useEffect(() => {
    const start = Number.isFinite(valRef.current) ? valRef.current : 0;
    if (start === target) return;
    const t0 = Date.now();
    const dur = 900;
    const tick = () => {
      const p = Math.min(1, (Date.now() - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      const next = start + (target - start) * eased;
      valRef.current = next;
      setVal(next);
      if (p >= 1) { clearInterval(id); valRef.current = target; setVal(target); }
    };
    const id = setInterval(tick, 16);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);
  return val;
}

export default function Counter({ fleet }) {
  const realized = useTicker(fleet?.realized_value_protected_eur || 0);
  const potential = fleet?.potential_value_protected_eur || 0;
  return (
    <div className="counter-overlay counter">
      <div className="label">Value protected · vs. naïve fix-now</div>
      <div className="big">{eur(realized)}</div>
      <div className="row">
        <div className="stat">
          <div className="v" style={{ color: "var(--good)" }}>{eur(realized)}</div>
          <div className="k">REALIZED (approved)</div>
        </div>
        <div className="stat">
          <div className="v">{eur(potential)}</div>
          <div className="k">IN QUEUE (pending approval)</div>
        </div>
      </div>
      <div className="breakdown">
        Generation revenue protected by optimal scheduling <b>+</b> expected
        unplanned-failure cost avoided (planned vs. run-to-failure).
      </div>
    </div>
  );
}
