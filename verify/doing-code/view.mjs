/** Reader-facing labels for doing code-against-spec (card 925).
 *  Current: MaxTasks=1. 0.8.6 target: MaxTasks=2 concurrent tw tasks. */

export const title = "Doing tw tasks (0.8.5 current / 0.8.6 target)";

export const state = (v) => {
  const bits = [];
  const slot = (d, t, st, live, age) => {
    if (!st) return;
    const tag = !live ? "STALE" : st === 2 ? "wait" : "active";
    bits.push(`${d}.${t}:${tag}${!live && age >= 3 ? "*" : ""}`);
  };
  slot(1, 1, v.st11, v.live1, v.age11);
  slot(1, 2, v.st12, v.live1, v.age12);
  slot(2, 1, v.st21, v.live2, v.age21);
  slot(2, 2, v.st22, v.live2, v.age22);
  const cycle =
    ((v.w11 === 2 || v.w12 === 2) && (v.w21 === 1 || v.w22 === 1));
  if (cycle) bits.push("CYCLE");
  if (!bits.length) return "idle";
  return bits.join(",");
};

export const group = (v) => {
  const cycle =
    ((v.w11 === 2 || v.w12 === 2) && (v.w21 === 1 || v.w22 === 1));
  const stale =
    (v.age11 >= 3 && v.st11 && !v.live1) ||
    (v.age12 >= 3 && v.st12 && !v.live1) ||
    (v.age21 >= 3 && v.st21 && !v.live2) ||
    (v.age22 >= 3 && v.st22 && !v.live2);
  if (cycle || stale) return "bad";
  if (v.st11 || v.st12 || v.st21 || v.st22) return "active";
  return "idle";
};

export const colors = { idle: "blue", active: "yellow", bad: "pink" };

export const step = (a) => {
  const s = String(a);
  if (s.startsWith("Focus")) return "tw start / focus";
  if (s.startsWith("Wait")) return "task waiting-on";
  if (s.startsWith("End")) return "tw end (finished)";
  if (s.startsWith("Crash")) return "desk/tw crash";
  if (s.startsWith("Clear")) return "reset/retire clears tasks";
  if (s === "Tick") return "time passes (stale age)";
  return null;
};
