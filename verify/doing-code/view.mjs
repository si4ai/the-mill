export const title = "Doing focus and waiting (0.8.5 / ce115f8)";
export const state = (v) => {
  const bits = [];
  if (v.focus1) bits.push(v.live1 ? "1:active" : "1:STALE");
  if (v.focus2) bits.push(v.live2 ? "2:active" : "2:STALE");
  if (v.wait1 === 2 && v.wait2 === 1) bits.push("CYCLE");
  if (!bits.length) return "idle";
  return bits.join(",");
};
export const group = (v) => {
  if ((v.wait1 === 2 && v.wait2 === 1) || ((v.age1 >= 3 && v.focus1 && !v.live1) || (v.age2 >= 3 && v.focus2 && !v.live2))) return "bad";
  if (v.focus1 || v.focus2) return "active";
  return "idle";
};
export const colors = { idle: "blue", active: "yellow", bad: "pink" };
export const step = (a) => {
  const s = String(a);
  if (s.startsWith("Focus")) return "mill ... --doing";
  if (s.startsWith("Wait")) return "--waiting-on";
  if (s.startsWith("End")) return "pass/drop ends focus";
  if (s.startsWith("Crash")) return "desk crash";
  if (s.startsWith("Clear")) return "reset/retire";
  if (s === "Tick") return "time passes";
  return null;
};
