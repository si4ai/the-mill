/* WALL_UI_LIB_TABS - hash / showTab / ensure*Paint hook registry (Path A).
 * Mirrors wall_logic.tabs contracts for packs; board may thin-wrap.
 * SoR: wall-contract; tests/wall + lib/tabs.js
 * Marker: WALL_UI_LIB_TABS
 */
(function (global) {
  "use strict";

  var PLAN_ALIASES = { plan: 1, backlog: 1, board: 1, issues: 1 };
  var SCORE_ALIASES = { score: 1, scorecards: 1 };
  var ENSURE_PAINT = {
    floor: "ensureFloorPaint",
    mail: "ensureMailPaint",
    score: "ensureScorePaint",
    scorecards: "ensureScorePaint"
  };
  var DEFAULT_MAIN_TABS = ["session", "floor", "jobs", "score", "mail"];

  function normalizeTab(name) {
    var raw = String(name || "").trim().toLowerCase();
    if (raw === "stations" || raw === "leases") {
      return { raw: raw, pane: "session", nav: "session", jobs_view: null, session_mode: "leases", plan_alias: null, hash: "leases" };
    }
    if (PLAN_ALIASES[raw]) {
      return {
        raw: raw,
        pane: "todo",
        nav: "jobs",
        jobs_view: "needs",
        plan_alias: raw,
        hash: "jobs"
      };
    }
    if (raw === "scorecards") {
      return { raw: raw, pane: "score", nav: "score", jobs_view: null, plan_alias: null, hash: "scorecards" };
    }
    return {
      raw: raw,
      pane: raw === "jobs" ? "todo" : raw,
      nav: raw === "jobs" ? "jobs" : raw,
      jobs_view: raw === "jobs" ? "needs" : null,
      plan_alias: null,
      hash: raw
    };
  }

  function ensurePaintForTab(name) {
    var info = normalizeTab(name);
    return ENSURE_PAINT[info.raw] || ENSURE_PAINT[info.pane] || null;
  }

  function runEnsurePaint(name, hooks) {
    var fnName = ensurePaintForTab(name);
    if (!fnName) return null;
    hooks = hooks || global;
    var fn = hooks[fnName];
    if (typeof fn === "function") {
      try { fn(); } catch (e) {}
      return fnName;
    }
    return fnName;
  }

  function hashFromLocation(loc) {
    loc = loc || (typeof location !== "undefined" ? location : { hash: "" });
    return String(loc.hash || "").replace(/^#/, "").trim().toLowerCase();
  }

  global.wallNormalizeTab = normalizeTab;
  global.wallEnsurePaintForTab = ensurePaintForTab;
  global.wallRunEnsurePaint = runEnsurePaint;
  global.wallHashFromLocation = hashFromLocation;
  global.WALL_UI_LIB_TABS = "WALL_UI_LIB_TABS";
  global.WALL_UI_LIB_DEFAULT_MAIN_TABS = DEFAULT_MAIN_TABS.slice();
})(typeof window !== "undefined" ? window : globalThis);
