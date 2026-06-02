import React, { useMemo, useState } from "react";
import { STATUS_COLOR } from "../util.js";

const SCENE_W = 1600;
const SCENE_H = 760;
const HORIZON = 470;

// Scatter turbines across a deep field with atmospheric perspective: far turbines
// sit near the horizon (small, hazy), near ones are large and crisp. A golden-ratio
// depth sequence keeps neighbours at different depths so nothing crowds.
function layout(n) {
  const marginX = 90;
  const slots = [];
  for (let i = 0; i < n; i++) {
    const depth = (i * 0.61803398875) % 1;            // 0 = far, 1 = near
    const jitter = (((i * 2654435761) % 1000) / 1000 - 0.5) * 0.5;
    const x = marginX + ((i + 0.5 + jitter) / n) * (SCENE_W - 2 * marginX);
    const y = HORIZON - 150 + depth * 215;            // higher = farther
    const s = 0.34 + depth * 0.92;                    // small (far) .. large (near)
    const opacity = 0.42 + depth * 0.58;              // atmospheric haze
    slots.push({ x, y, s, opacity, depth });
  }
  return slots;
}

const isDegraded = (t) => t.status === "degrading" || t.status === "critical";

// majestic, slower spin; stronger wind turns faster
const spinDur = (wind) => `${Math.min(12, Math.max(2.2, 42 / (Number(wind) + 3))).toFixed(2)}s`;

const H = 150;   // tower height (local)
const L = 74;    // blade length (local)

// slender, gently-curved aerofoil blade rooted at the hub (points up)
const BLADE_D =
  "M -1.5,0 C -2.8,-16 -2.3,-42 -1.0,-66 C -0.6,-72 0.1,-74.5 0.6,-74.5 " +
  "C 1.3,-72 2.1,-58 1.9,-40 C 1.7,-22 1.4,-7 1.2,0 Z";

function Turbine({ t, slot, onSelect, onHover, hovered }) {
  const color = STATUS_COLOR[t.status] || STATUS_COLOR.healthy;
  const degraded = isDegraded(t);
  const dur = spinDur(t.wind_ms);
  return (
    <g className="turbine" opacity={slot.opacity}
       transform={`translate(${slot.x},${slot.y}) scale(${slot.s})`}
       onClick={() => onSelect(t)}
       onMouseEnter={() => onHover(t.turbine_id)} onMouseLeave={() => onHover(null)}>
      <ellipse cx="0" cy="3" rx="20" ry="5" fill="rgba(0,0,0,0.18)" />
      <polygon className="tower-poly" points={`-4,0 4,0 1.7,${-H} -1.7,${-H}`} />
      <g transform={`translate(0,${-H})`}>
        {/* soft health glow (refined — not a hard ring) */}
        <circle r="20" fill={color} className={degraded ? "health-glow pulse" : "health-glow"} />
        {/* swept-area disc — subtle motion cue */}
        <circle r={L} className="swept-disc" />
        {/* nacelle */}
        <rect className="nacelle" x="-7" y="-4.5" width="18" height="9" rx="4.5" />
        <circle className="nacelle" cx="11" cy="0" r="4.8" />
        {/* spinning rotor */}
        <g className="rotor" style={{ animationDuration: dur }}>
          <path className="blade" d={BLADE_D} transform="rotate(0)" />
          <path className="blade" d={BLADE_D} transform="rotate(120)" />
          <path className="blade" d={BLADE_D} transform="rotate(240)" />
          <circle className="hub" r="3.6" />
        </g>
      </g>
      <text x="0" y="20" textAnchor="middle" fontSize="10" fontWeight="600"
        fill={degraded ? color : "var(--muted)"} opacity="0.9">{t.turbine_id}</text>
      {hovered && (
        <g transform={`translate(0,${-H - 70})`} style={{ pointerEvents: "none" }}>
          <rect x="-64" y="-30" width="128" height="50" rx="10"
            fill="var(--panel-solid)" stroke={color} strokeWidth="1" opacity="0.97" />
          <text x="0" y="-12" textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--text)">
            {t.turbine_id} · {t.status}</text>
          <text x="0" y="2" textAnchor="middle" fontSize="9.5" fill="var(--muted)">
            health {Math.round(t.health_score)} · wind {t.wind_ms} m/s</text>
          <text x="0" y="14" textAnchor="middle" fontSize="9.5" fill="var(--muted)">
            output ~{Math.round(t.expected_power_kw || 0)} kW</text>
        </g>
      )}
    </g>
  );
}

function WindStreaks() {
  return (
    <g>
      {Array.from({ length: 11 }, (_, i) => {
        const y = 60 + ((i * 67) % 360);
        const len = 60 + (i % 4) * 40;
        const dur = (9 + (i % 5) * 2) + "s";
        const delay = -((i * 1.3) % 9) + "s";
        return <line key={i} className="wind-line" x1={0} y1={y} x2={len} y2={y}
          style={{ animationDuration: dur, animationDelay: delay }} />;
      })}
    </g>
  );
}

export default function WindFarm({ turbines = [], onSelect }) {
  const [hovered, setHovered] = useState(null);
  const slots = useMemo(() => layout(turbines.length), [turbines.length]);
  // draw far→near so depth ordering is correct; degraded last so they stay visible
  const order = useMemo(
    () => turbines.map((t, i) => ({ t, i, slot: slots[i] }))
      .sort((a, b) => (a.slot.depth - b.slot.depth) || (isDegraded(a.t) - isDegraded(b.t))),
    [turbines, slots]);

  return (
    <svg className="scene" viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--sky-top)" />
          <stop offset="50%" stopColor="var(--sky-mid)" />
          <stop offset="100%" stopColor="var(--sky-bot)" />
        </linearGradient>
        <linearGradient id="towerGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--tower2)" />
          <stop offset="45%" stopColor="var(--tower)" />
          <stop offset="100%" stopColor="var(--tower2)" />
        </linearGradient>
        <radialGradient id="orbGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--orb)" /><stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <radialGradient id="haze" cx="50%" cy="100%" r="80%">
          <stop offset="0%" stopColor="var(--haze)" /><stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--hill-mid)" /><stop offset="100%" stopColor="var(--hill-front)" />
        </linearGradient>
      </defs>

      <rect width={SCENE_W} height={SCENE_H} fill="url(#sky)" />
      <circle className="orb-glow" cx="1300" cy="150" r="150" fill="url(#orbGrad)" />
      <circle className="orb" cx="1300" cy="150" r="52" />

      <g>{Array.from({ length: 60 }, (_, i) => (
        <circle key={i} className="star" cx={(i * 211) % SCENE_W} cy={(i * 89) % 300}
          r={(i % 3) * 0.5 + 0.5} style={{ animationDelay: `${(i % 7) * 0.6}s` }} />))}</g>
      <g className="cloud c1"><ellipse cx="300" cy="110" rx="80" ry="22" />
        <ellipse cx="370" cy="98" rx="56" ry="18" /><ellipse cx="240" cy="100" rx="50" ry="16" /></g>
      <g className="cloud c2"><ellipse cx="820" cy="160" rx="66" ry="18" />
        <ellipse cx="880" cy="150" rx="46" ry="15" /></g>

      <WindStreaks />

      {/* layered hills + atmospheric haze band at the horizon */}
      <path d="M0,430 Q400,392 800,424 T1600,408 L1600,760 L0,760 Z" fill="var(--hill-back)" opacity="0.8" />
      <rect x="0" y={HORIZON - 70} width={SCENE_W} height="120" fill="url(#haze)" opacity="0.7" />
      <path d={`M0,${HORIZON} Q500,${HORIZON-30} 1000,${HORIZON+8} T1600,${HORIZON-6} L1600,760 L0,760 Z`} fill="url(#ground)" />

      {order.map(({ t, i, slot }) => (
        <Turbine key={t.turbine_id} t={t} slot={slot}
          onSelect={onSelect} onHover={setHovered} hovered={hovered === t.turbine_id} />
      ))}
    </svg>
  );
}
