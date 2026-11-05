/** Reader-facing labels for hold recovery guards (card 925). */

export const title = "Hold mutex and release-other (0.8.5 / ce115f8)";

export const state = (v) => {
  if (v.twoHolders) return "TWO_HOLDERS";
  if (v.holder === 0) return "free";
  const who = v.holder === 1 ? "A" : "B";
  return `held-by-${who}` + (v.age >= 3 ? "+STUCK" : "");
};

export const group = (v) => {
  if (v.twoHolders || (v.age >= 3 && v.holder !== 0)) return "bad";
  if (v.holder === 0) return "free";
  return "held";
};

export const colors = { free: "blue", held: "yellow", bad: "pink" };

export const step = (action) => {
  const a = String(action);
  if (a.startsWith("Take")) return "mill hold";
  if (a.startsWith("DropOwn")) return "mill drop (own)";
  if (a.startsWith("ReleaseOther")) return "mill drop (other)";
  if (a === "Tick") return "time passes";
  if (a === "Expire") return "auto-expire [proposed]";
  if (a === "Term") return null;
  return a;
};
