/** Reader-facing labels for mail recovery guards (card 925). */

export const title = "Mail delivery and recovery (0.8.5 / ce115f8)";

export const state = (v) => {
  const bits = [];
  if (v.silentTrunc) bits.push("TRUNC");
  if (v.orphaned) bits.push("ORPHAN");
  if (v.letterLive) bits.push("letter");
  if (v.recipient) bits.push("to");
  if (v.opened === 0 && v.recipient) bits.push("unread");
  if (v.opened === 1) bits.push("handled");
  if (v.opened === 2) bits.push("rewritten");
  if (v.receipts > 0) bits.push("rcpt=" + v.receipts);
  if (bits.length === 0) return "idle";
  return bits.join("+");
};

export const group = (v) => {
  if (v.silentTrunc || v.orphaned) return "bad";
  if (v.opened >= 1) return "handled";
  if (v.letterLive) return "live";
  return "idle";
};

export const colors = {
  idle: "blue",
  live: "tan",
  handled: "teal",
  bad: "pink",
};

export const step = (action) => {
  const a = String(action);
  if (a.startsWith("PickBody")) return "pick body length";
  if (a === "SendOrReply") return "send or reply";
  if (a === "SendNoRecipient") return "send with no live recipient";
  if (a === "OpenUnlockedRace") return "open without row lock [mutant]";
  if (a === "Open") return "mill_mail_open";
  if (a === "Term") return null;
  return a;
};
