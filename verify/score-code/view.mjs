export const title = "Score liveness truth (0.8.5 / ce115f8)";
export const state = (v) => {
  const bits = [];
  if (v.wsMissEvents) bits.push(`miss=${v.wsMissCount}/${v.wsMissEvents}`);
  if (v.holdEvents) bits.push(`hold=${v.holdCount}/${v.holdEvents}`);
  if (v.published && v.published !== "none") bits.push(`pub=${v.published}`);
  if (v.truncated) bits.push(v.labelled ? "trunc+label" : "TRUNC");
  if (!bits.length) return "idle";
  return bits.join(",");
};
export const group = (v) => {
  if ((v.wsMissCount !== v.wsMissEvents) || (v.holdCount !== v.holdEvents)) return "bad";
  if (v.truncated && !v.labelled) return "bad";
  if (v.published === "zero") return "bad";
  if (v.published === "value" || v.published === "missing") return "active";
  return "idle";
};
export const colors = { idle: "blue", active: "yellow", bad: "pink" };
export const step = (a) => {
  const s = String(a);
  if (s.startsWith("WsMiss")) return "fanout miss counted";
  if (s.startsWith("Hold")) return "hold.blocked ms";
  if (s.startsWith("Sample")) return "sample arrives";
  if (s.startsWith("Publish")) return "score tick publish";
  if (s.startsWith("Shape")) return "series shape truncate";
  return null;
};
