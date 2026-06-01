import React from "react";

export default function AuditViewer({ audit }) {
  const entries = audit?.entries || [];
  const v = audit?.verification || {};
  return (
    <div className="panel">
      <h2>Audit trail · immutable reasoning log</h2>
      <div style={{ fontSize: 12, marginBottom: 8 }}>
        Hash-chain:{" "}
        {v.valid ? <span className="chain-ok">✓ verified ({v.count} entries)</span>
          : <span className="chain-bad">✗ tampered</span>}
      </div>
      <div style={{ maxHeight: 260, overflowY: "auto" }}>
        {entries.slice().reverse().map((e, i) => (
          <div className="audit-row" key={i}>
            <span className="et">{e.event_type}</span>
            <span style={{ flex: 1 }}>
              {e.payload?.id || e.payload?.turbine_id || ""}
              {e.payload?.approver ? ` · by ${e.payload.approver}` : ""}
              {e.payload?.value_protected_eur ? ` · €${Math.round(e.payload.value_protected_eur).toLocaleString()}` : ""}
              <div className="hashline">{(e.hash || "").slice(0, 32)}…</div>
            </span>
            <span className="ts">{new Date(e.timestamp).toLocaleTimeString("en-GB")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
