/** Reader-facing labels for todo who-may (card 925). */

const statusLabel = {
  none: "Not created",
  parked: "Parked",
  open: "Open",
  claimed: "Claimed",
  shipped: "Shipped",
  done: "Done",
};

export const title = "Todo T1-T14 who-may (0.8.0 code)";

export const state = (v) => {
  if (v.status === "none") return "Not created";
  if (v.retired) return `Retired (${statusLabel[v.status] ?? v.status})`;
  const who = v.vol && v.vol !== "none" ? ` by ${v.vol}` : "";
  if (v.status === "claimed") return `Claimed${who}`;
  return statusLabel[v.status] ?? v.status;
};

export const group = (v) => {
  if (v.status === "none") return "start";
  if (v.retired) return "retired";
  if (v.status === "done") return "done";
  if (v.status === "shipped") return "ship";
  if (v.status === "claimed") return "work";
  return "live";
};

export const colors = {
  start: "blue",
  live: "tan",
  work: "yellow",
  ship: "orange",
  done: "teal",
  retired: "pink",
};

export const step = (action, from, to) => {
  const a = String(action);
  if (a.startsWith("T1_")) return "create todo";
  if (a.startsWith("T2_")) return "create todo --status parked";
  if (a.startsWith("T3_")) return "unpark";
  if (a.startsWith("T4_ClaimRetired")) return "claim on retired [mutant]";
  if (a.startsWith("T4_")) return "claim";
  if (a.startsWith("T5_")) return "assign";
  if (a.startsWith("T6_Steal")) return "claim without --take-over [mutant]";
  if (a.startsWith("T6_")) return "claim --take-over";
  if (a.startsWith("T7_")) return "unclaim";
  if (a.startsWith("T8_")) return "pass (ship)";
  if (a.startsWith("T9_")) return "pass --done";
  if (a.startsWith("T10_")) return "pass --back (from done)";
  if (a.startsWith("T11_")) return "pass --back (from shipped)";
  if (a.startsWith("T12_")) return "retire todo";
  if (a.startsWith("T13_")) return "reclaim todo";
  if (a.startsWith("T14_")) return null;
  if (a === "Term") return null;
  return a;
};
