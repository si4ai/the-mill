/** Reader-facing labels for wake code-against-spec (card 925). */

export const title = "Wake code guards (0.8.5 / ce115f8)";

export const state = (v) => {
  const bits = [];
  if (v.leaseLive) bits.push("lease");
  if (v.retryArmed) bits.push("retry");
  if (v.pushPending) bits.push("push");
  if (v.unreadLeft) bits.push("unread");
  if (v.sitting) bits.push("sitting");
  if (v.lostUnread) bits.push("LOST");
  if (bits.length === 0) return "idle";
  return bits.join("+");
};

export const group = (v) => {
  if (v.lostUnread) return "lost";
  if (v.retryArmed) return "retry";
  if (v.leaseLive) return "lease";
  if (v.sitting) return "sit";
  if (v.pushPending || v.unreadLeft) return "work";
  return "idle";
};

export const colors = {
  idle: "blue",
  work: "tan",
  lease: "yellow",
  retry: "orange",
  sit: "teal",
  lost: "pink",
};

export const step = (action, from, to) => {
  const a = String(action);
  if (a === "ArrivePush") return "push row lands";
  if (a === "ArriveUnread") return "unread mail remains";
  if (a === "OpenMail") return "desk opens letter";
  if (a === "Sit") return "desk sits";
  if (a === "Leave") return "desk leaves";
  if (a === "DrainPush") return "connect drains push";
  if (a === "PostOk") return "post_desk sent";
  if (a === "PostFail") return "post_desk fail";
  if (a === "DrainStopsRetry") return "_queue_drained stops retry";
  if (a === "Trail") return "_send_trailing";
  if (a === "Ring") return "ring_waiting";
  if (a === "DoneOk") return "lease_done";
  if (a === "DoneSitting") return "lease_done sitting";
  if (a === "DoneStale") return "lease_done stale";
  if (a === "Term") return null;
  return a;
};
