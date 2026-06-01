import React, { useState } from "react";
import { STATUS_COLOR } from "../util.js";

// Composition slots (x, ground-y, scale) — front row big, back row small for depth.
const SLOTS = [
  { x: 200, y: 396, s: 1.12 },
  { x: 565, y: 410, s: 1.20 },
  { x: 950, y: 392, s: 1.06 },
  { x: 370, y: 352, s: 0.70 },
  { x: 770, y: 350, s: 0.68 },
  { x: 1110, y: 366, s: 0.82 },
];

const H = 150;        // tower height (local)
const R = 56;         // rotor radius (local)

// blade spin duration: stronger wind -> faster spin (shorter duration)
const spinDur = (wind) => `${Math.min(9, Math.max(1.1, 24 / (Number(wind) + 2))).toFixed(2)}s`;

function Blade({ angle }) {
  return (
    <path className="blade" transform={`rotate(${angle})`}
      d={`M 0,-5 Q 4,-${R * 0.5} 2,-${R} Q 0,-${R + 4} -2,-${R} Q -4,-${R * 0.5} 0,-5 Z`} />
  );
}

function Turbine({ t, slot, onSelect, onHover, hovered }) {
  const color = STATUS_COLOR[t.status] || STATUS_COLOR.healthy;
  const degraded = t.status === "degrading" || t.status === "critical";
  const dur = spinDur(t.wind_ms);
  return (
    <g className="turbine" transform={`translate(${slot.x},${slot.y}) scale(${slot.s})`}
       onClick={() => onSelect(t)}
       onMouseEnter={() => onHover(t.turbine_id)} onMouseLeave={() => onHover(null)}>
      {/* ground shadow */}
      <ellipse cx="0" cy="2" rx="26" ry="6" fill="rgba(0,0,0,0.22)" />
      {/* tower */}
      <polygon className="tower-poly" points={`-5,0 5,0 2,${-H} -2,${-H}`} />
      {/* nacelle + health ring at hub */}
      <g transform={`translate(0,${-H})`}>
        <circle className="health-ring" r="13" style={{ stroke: color }} />
        {degraded && <circle className="pulse-ring" cx="0" cy="0" fill="none"
          stroke={color} strokeWidth="2.5" />}
        <rect className="nacelle" x="-6" y="-6" width="20" height="11" rx="4" />
        {/* spinning rotor */}
        <g className="rotor" style={{ animationDuration: dur }}>
          <Blade angle={0} /><Blade angle={120} /><Blade angle={240} />
          <circle className="hub" r="4.5" />
        </g>
      </g>
      {/* label */}
      <text x="0" y="20" textAnchor="middle" fontSize="11" fontWeight="700" fill={color}>
        {t.turbine_id}
      </text>
      <text x="0" y="32" textAnchor="middle" fontSize="9" fill="var(--muted)">
        {Math.round(t.health_score)} · {Math.round(t.wind_ms)} m/s
      </text>
      {hovered && (
        <g transform={`translate(0,${-H - 78})`} style={{ pointerEvents: "none" }}>
          <rect x="-66" y="-30" width="132" height="52" rx="9"
            fill="var(--panel-solid)" stroke={color} strokeWidth="1.2" opacity="0.96" />
          <text x="0" y="-12" textAnchor="middle" fontSize="11" fontWeight="800" fill="var(--text)">
            {t.turbine_id} · {t.status}
          </text>
          <text x="0" y="2" textAnchor="middle" fontSize="9.5" fill="var(--muted)">
            health {Math.round(t.health_score)} · wind {t.wind_ms} m/s
          </text>
          <text x="0" y="15" textAnchor="middle" fontSize="9.5" fill="var(--muted)">
            output ~{Math.round(t.expected_power_kw || 0)} kW
          </text>
        </g>
      )}
    </g>
  );
}

function WindLines() {
  const lines = Array.from({ length: 16 }, (_, i) => {
    const y = 40 + ((i * 53) % 300);
    const len = 26 + (i % 5) * 14;
    const dur = (5 + (i % 6)) + "s";
    const delay = -((i * 0.7) % 6) + "s";
    return (
      <line key={i} className="wind-line" x1={0} y1={y} x2={len} y2={y}
        style={{ animationDuration: dur, animationDelay: delay }} />
    );
  });
  return <g>{lines}</g>;
}

export default function WindFarm({ turbines = [], onSelect }) {
  const [hovered, setHovered] = useState(null);
  const W = 1200, Ht = 520;
  return (
    <svg className="scene" viewBox={`0 0 ${W} ${Ht}`} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--sky-top)" />
          <stop offset="55%" stopColor="var(--sky-mid)" />
          <stop offset="100%" stopColor="var(--sky-bot)" />
        </linearGradient>
        <linearGradient id="towerGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--tower2)" />
          <stop offset="50%" stopColor="var(--tower)" />
          <stop offset="100%" stopColor="var(--tower2)" />
        </linearGradient>
        <radialGradient id="orbGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--orb)" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
      </defs>

      <rect width={W} height={Ht} fill="url(#sky)" />

      {/* sun / moon */}
      <circle className="orb-glow" cx="1010" cy="118" r="110" fill="url(#orbGrad)" />
      <circle className="orb" cx="1010" cy="118" r="44" />

      {/* stars (dark) */}
      <g>
        {Array.from({ length: 46 }, (_, i) => (
          <circle key={i} className="star"
            cx={(i * 137) % W} cy={(i * 71) % 230} r={(i % 3) * 0.5 + 0.6}
            style={{ animationDelay: `${(i % 7) * 0.5}s` }} />
        ))}
      </g>
      {/* clouds (light) */}
      <g className="cloud c1">
        <ellipse cx="260" cy="90" rx="60" ry="20" /><ellipse cx="310" cy="80" rx="44" ry="18" />
        <ellipse cx="210" cy="82" rx="40" ry="16" />
      </g>
      <g className="cloud c2">
        <ellipse cx="620" cy="140" rx="52" ry="17" /><ellipse cx="660" cy="132" rx="38" ry="15" />
      </g>

      <WindLines />

      {/* hills (parallax) */}
      <path d="M0,330 Q300,280 600,318 T1200,300 L1200,520 L0,520 Z" fill="var(--hill-back)" />
      <path d="M0,372 Q360,330 720,366 T1200,356 L1200,520 L0,520 Z" fill="var(--hill-mid)" />
      <path d="M0,420 Q420,392 840,420 T1200,410 L1200,520 L0,520 Z" fill="var(--hill-front)" />

      {turbines.map((t, i) => (
        <Turbine key={t.turbine_id} t={t} slot={SLOTS[i % SLOTS.length]}
          onSelect={onSelect} onHover={setHovered} hovered={hovered === t.turbine_id} />
      ))}
    </svg>
  );
}
