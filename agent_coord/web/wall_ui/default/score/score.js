/* WALL_UI_DEFAULT_SCORE - thin pure-rule module for default pack (fungible cut 5).
 * Path A extract from board.html score helpers. Packs may override this file.
 * SoR Python: agent_coord.wall_logic.score (WALL_LOGIC_SCORE_SOR).
 * Marker: WALL_UI_DEFAULT_SCORE
 */
(function (global) {
  "use strict";

  function numish(s) {
    var t = String(s || "").replace(/\*/g, "").trim();
    if (/^(not run|leftover|pass|stay|shipped|none|-)$/i.test(t)) return null;
    var m = t.match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  }
  function kpiMiss(last, target) {
    var L = String(last || "").toLowerCase();
    if (!L || /not run|leftover|shipped|stay|none/.test(L)) return false;
    if (/\bfail\b|\bstarve\b|\bmiss\b/.test(L)) return true;
    /* Informational KPIs (empty/blank target, e.g. mill-office.activities): never red on numeric Last. */
    var T = String(target == null ? "" : target).trim();
    if (!T) return false;
    var ln = numish(last), tn = numish(target);
    if (ln == null || tn == null) return false;
    if (tn === 0) return ln !== 0;
    return ln < tn;
  }
  function scoreParseAt(at) {
    if (!at) return null;
    var s = String(at).replace(" ", "T");
    var t = Date.parse(s);
    return Number.isFinite(t) ? t : null;
  }
  function scoreWindowMs(span) {
    if (span === "7d") return 7 * 24 * 3600 * 1000;
    return 24 * 3600 * 1000;
  }
  function scoreInWindow(at, span, nowMs) {
    var t = scoreParseAt(at);
    if (t == null) return false;
    var now = nowMs != null ? nowMs : Date.now();
    return (now - t) <= scoreWindowMs(span);
  }
  function scoreSourceJob(note, kpi) {
    var m = String(note || "").match(/JOB[:\s]+([^\s;]+)/i);
    return m ? m[1] : String(kpi || "");
  }
  var SCORE_HOST_KPIS = ["mill-wall.ticks", "mill-desk.idle_verbs", "mill-desk.hint_drop"];
  /* Office book chips (any owner) shown on SCORE strip alongside host totals. */
  var SCORE_OFFICE_CHIPS = ["mill-office.activities"];
  /* Display labels for SCORE chips / detail (raw kpi name -> short chip label). */
  var SCORE_KPI_LABELS = {
    "mill-wall.ticks": "ticks",
    "mill-desk.idle_verbs": "idle",
    "mill-desk.hint_drop": "hint drop",
    "mill-office.activities": "activities/h"
  };
  function scoreKpiName(k) {
    return String((k && (k.kpi || k.name)) || "").trim();
  }
  function scoreKpiLabel(nameOrK) {
    var n = typeof nameOrK === "string" ? nameOrK : scoreKpiName(nameOrK);
    n = String(n || "").trim();
    return (SCORE_KPI_LABELS[n] != null && SCORE_KPI_LABELS[n] !== "") ? SCORE_KPI_LABELS[n] : n;
  }
  function scoreFindKpi(d, name) {
    var want = String(name || "").trim();
    if (!want) return null;
    var hit = null;
    ((d && d.kpis) || []).forEach(function (k) {
      if (scoreKpiName(k) === want) hit = k;
    });
    return hit;
  }
  function scoreDeskSlug(k) {
    var s = String((k && (k.owner || k.desk_id || k.desk)) || "").trim();
    return s || "(unknown)";
  }
  function scoreIsHostDesk(desk) {
    return String(desk || "").trim().toLowerCase() === "mill-host";
  }
  function scoreMintQuiet(last, target) {
    var L = String(last == null ? "" : last).trim();
    var tn = numish(target);
    return !L && tn === 0;
  }
  function scoreOfficeTotals(d) {
    var out = {};
    SCORE_HOST_KPIS.forEach(function (n) { out[n] = null; });
    ((d && d.kpis) || []).forEach(function (k) {
      if (!scoreIsHostDesk(scoreDeskSlug(k))) return;
      var name = scoreKpiName(k);
      if (Object.prototype.hasOwnProperty.call(out, name)) out[name] = k;
    });
    return out;
  }
  function scoreDeskRows(d, span, nowMs) {
    d = d || {};
    var by = {};
    (d.kpis || []).forEach(function (k) {
      var desk = scoreDeskSlug(k);
      if (!by[desk]) by[desk] = { desk: desk, kpis: [], byKpi: {}, miss: 0, missing: 0, stale: 0, latest: null, host: scoreIsHostDesk(desk) };
      by[desk].kpis.push(k);
      by[desk].byKpi[scoreKpiName(k)] = k;
      var last = k.value;
      var tgt = k.target;
      if (scoreMintQuiet(last, tgt)) { /* mill connect mint: empty Last, target 0 */ }
      else if (last == null || last === "") by[desk].missing++;
      else if (kpiMiss(last, tgt)) by[desk].miss++;
      var ut = scoreParseAt(k.updated_at);
      if (ut != null && (!by[desk].latest || ut > by[desk].latest)) by[desk].latest = ut;
    });
    var now = nowMs != null ? nowMs : Date.now();
    var useSpan = span || (typeof global.scoreSpan !== "undefined" ? global.scoreSpan : "24h");
    var staleCut = scoreWindowMs(useSpan);
    Object.keys(by).forEach(function (desk) {
      var row = by[desk];
      if (row.latest == null || (now - row.latest) > staleCut) row.stale++;
      row.hot = (row.miss > 0) || (row.missing > 0) || (row.stale > 0);
      row.reasons = [];
      if (row.miss) row.reasons.push(row.miss + " over Target");
      if (row.missing) row.reasons.push(row.missing + " missing Last");
      if (row.stale) row.reasons.push("stale publish");
      var primary = row.kpis.find(function (k) { return kpiMiss(k.value, k.target); }) || row.kpis[0] || {};
      row.last = primary.value == null ? "" : primary.value;
      row.target = primary.target == null ? "" : primary.target;
      row.kpi = primary.kpi || "";
      row.roster_id = primary.roster_id || "";
      row.note = primary.note || "";
      row.published = primary.updated_at || "";
      row.sourceJob = scoreSourceJob(primary.note, primary.kpi || "");
    });
    return Object.keys(by).sort().map(function (k) { return by[k]; });
  }
  function scoreHotList(rows, filterMode) {
    rows = rows || [];
    if (filterMode === "all") return rows.slice();
    return rows.filter(function (r) { return r && r.hot; });
  }
  function scoreDeskTableList(rows, filterMode) {
    rows = rows || [];
    if (filterMode === "all") return { rows: rows.slice(), fellBack: false };
    var hot = rows.filter(function (r) { return r && r.hot; });
    if (!hot.length && rows.length) return { rows: rows.slice(), fellBack: true };
    return { rows: hot, fellBack: false };
  }
  function scoreDelta(row) {
    if (!row) return "|";
    if (row.miss) return "-" + String(row.miss);
    if (row.missing) return "?";
    return "|";
  }
  function scorePreferDesk(rows, selected) {
    rows = rows || [];
    var sel = String(selected || "").trim();
    if (sel && rows.some(function (r) { return String(r.desk || "") === sel; })) return sel;
    if (!rows.length) return "";
    var prefer = rows.find(function (r) { return r.hot; }) || rows[0];
    return String(prefer.desk || "").trim();
  }
  function scoreWaiting(d) {
    var n = 0;
    ((d && (d.agents || d.live_agents)) || []).forEach(function (a) {
      if (a && String(a.waiting_on || "").trim()) n++;
    });
    return n;
  }
  function scoreEnsurePaintContract() {
    return {
      marker: "WALL_UI_DEFAULT_SCORE",
      calls_score: true,
      cold_load: true,
      tab_enter: true,
      rAF_second_paint: true
    };
  }

  var api = {
    SCORE_HOST_KPIS: SCORE_HOST_KPIS,
    SCORE_OFFICE_CHIPS: SCORE_OFFICE_CHIPS,
    SCORE_KPI_LABELS: SCORE_KPI_LABELS,
    scoreKpiName: scoreKpiName,
    scoreKpiLabel: scoreKpiLabel,
    scoreFindKpi: scoreFindKpi,
    scoreDeskSlug: scoreDeskSlug,
    scoreIsHostDesk: scoreIsHostDesk,
    scoreMintQuiet: scoreMintQuiet,
    scoreOfficeTotals: scoreOfficeTotals,
    numish: numish,
    kpiMiss: kpiMiss,
    scoreParseAt: scoreParseAt,
    scoreWindowMs: scoreWindowMs,
    scoreInWindow: scoreInWindow,
    scoreSourceJob: scoreSourceJob,
    scoreDeskRows: scoreDeskRows,
    scoreHotList: scoreHotList,
    scoreDeskTableList: scoreDeskTableList,
    scoreDelta: scoreDelta,
    scorePreferDesk: scorePreferDesk,
    scoreWaiting: scoreWaiting,
    scoreEnsurePaintContract: scoreEnsurePaintContract
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallScore = api;
  global.WALL_UI_DEFAULT_SCORE = "WALL_UI_DEFAULT_SCORE";
})(typeof window !== "undefined" ? window : globalThis);
