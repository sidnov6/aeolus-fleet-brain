export const STATUS_COLOR = {
  healthy: "#2dd4a7",
  watch: "#fbbf24",
  degrading: "#fb923c",
  critical: "#f43f5e",
};

export const eur = (n) =>
  "€" + Math.round(Number(n) || 0).toLocaleString("en-US");

export const eur2 = (n) =>
  "€" + (Number(n) || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

export const ago = (iso) => {
  if (!iso) return "just now";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
};

export const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    weekday: "short", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }) + " UTC";
};
