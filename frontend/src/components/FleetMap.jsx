import React from "react";
import { STATUS_COLOR } from "../util.js";

// Project lat/lon into the SVG viewbox with padding.
function project(turbines, W, H, pad) {
  const lats = turbines.map((t) => t.latitude);
  const lons = turbines.map((t) => t.longitude);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const sx = (lon) => pad + ((lon - minLon) / (maxLon - minLon || 1)) * (W - 2 * pad);
  const sy = (lat) => H - pad - ((lat - minLat) / (maxLat - minLat || 1)) * (H - 2 * pad);
  return { sx, sy };
}

export default function FleetMap({ turbines, onSelect }) {
  const W = 720, H = 450, pad = 70;
  if (!turbines?.length) return <div className="panel"><h2>Fleet map</h2></div>;
  const { sx, sy } = project(turbines, W, H, pad);

  return (
    <div className="panel">
      <h2>Fleet map · {turbines[0]?.site}</h2>
      <div className="map-wrap">
        <svg className="map-svg" viewBox={`0 0 ${W} ${H}`}>
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#13202e" strokeWidth="1" />
            </pattern>
            <radialGradient id="glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#1b2c3e" />
              <stop offset="100%" stopColor="transparent" />
            </radialGradient>
          </defs>
          <rect width={W} height={H} fill="url(#grid)" />
          <ellipse cx={W / 2} cy={H / 2} rx={W / 2.4} ry={H / 2.6} fill="url(#glow)" />

          {turbines.map((t) => {
            const x = sx(t.longitude), y = sy(t.latitude);
            const color = STATUS_COLOR[t.status] || STATUS_COLOR.healthy;
            const degraded = t.status === "degrading" || t.status === "critical";
            return (
              <g key={t.turbine_id} className="node" onClick={() => onSelect(t)}>
                {degraded && (
                  <circle cx={x} cy={y} r="10" fill={color} opacity="0.5">
                    <animate attributeName="r" values="10;26;10" dur="2.2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.5;0;0.5" dur="2.2s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle cx={x} cy={y} r="9" fill={color} stroke="#0a0e14" strokeWidth="2" />
                <text className="node-label" x={x + 13} y={y - 8}>{t.turbine_id}</text>
                <text className="node-label" x={x + 13} y={y + 6} fill={color}>
                  {Math.round(t.health_score)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        {Object.entries(STATUS_COLOR).map(([k, c]) => (
          <span key={k}><span className="dot" style={{ background: c }} />{k}</span>
        ))}
        <span style={{ marginLeft: "auto" }}>click a turbine for the incident dossier</span>
      </div>
    </div>
  );
}
