import React from "react";
import { eur } from "../util.js";

export default function ApprovalQueue({ approvals, onDecide, onOpen }) {
  const queue = approvals?.queue || [];
  return (
    <div className="panel">
      <h2>Approval queue · human gate</h2>
      {queue.length === 0 && <div className="muted">No pending actions.</div>}
      {queue.map((q) => {
        const decided = q.status === "approved" || q.status === "rejected";
        const blocked = q.status.startsWith("blocked");
        return (
          <div className="queue-item" key={q.id}>
            <div className="hdr">
              <span className="qid">{q.id}</span>
              <span className={`pill ${q.status}`}>{q.status.replace(/_/g, " ")}</span>
              <span style={{ flex: 1 }} />
              <span className="val">{eur(q.value_protected_eur)}</span>
            </div>
            <div className="title">{q.work_order_title}</div>
            <div className="meta">
              {q.turbine_id} · {q.component.replace(/_/g, " ")} · crew {q.crew || "—"} ·
              diag confidence {q.diagnosis_confidence ?? "—"}
            </div>
            <div className="meta" style={{ marginTop: 4 }}>
              {q.sim?.passed
                ? "✓ digital-twin sim passed"
                : "✗ sim: " + (q.sim?.reason || "blocked")}
            </div>
            <div className="qbtns">
              <button className="btn approve" disabled={decided || blocked}
                onClick={() => onDecide(q.id, true)}>Approve</button>
              <button className="btn reject" disabled={decided}
                onClick={() => onDecide(q.id, false)}>Reject</button>
              <button className="btn" onClick={() => onOpen(q.turbine_id)}>Open dossier</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
