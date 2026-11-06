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
    "mill-office.activities": "activities/h",
    "doing.task.dwell_idle_ms": "task idle ms",
    "doing.task.dwell_active_ms": "task active ms",
    "doing.task.dwell_waiting_ms": "task waiting ms",
    "doing.task.wait_by_cause": "task waits",
    "doing.task.end_reason": "task end",
    "doing.task.buffer_overflow_n": "task overflow",
    "doing.task.retry_give_up_n": "task give-up"
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
    /* 0.8.0: Admin / roster scores may have desk_id NULL; show under the roster. */
    var s = String((k && (k.owner || k.desk_id || k.desk)) || "").trim();
    if (s) return s;
    var roster = String((k && (k.roster_id || k.roster)) || "").trim();
    return roster || "(unknown)";
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

  /* wall-scores Phase A (letters 4805/4808/4853): doing.task.* leaves + derived rollups.
   * Missing != 0: omit unwritten KPIs. Never invent stale_n / wait_cycle_n. */
  var DOING_TASK_PREFIX = "doing.task.";
  var DOING_TASK_SUM_KEYS = [
    "dwell_idle_ms", "dwell_active_ms", "dwell_waiting_ms",
    "buffer_overflow_n", "retry_give_up_n"
  ];
  var DOING_TASK_LEAF_KEYS = DOING_TASK_SUM_KEYS.concat(["wait_by_cause", "end_reason"]);
  var DOING_TASK_TERMINAL = { finished: 1, failed: 1 };
  var DOING_TASK_PRIVACY = {
    title: 1, argv: 1, pattern: 1, stdout: 1, stderr: 1, log: 1, sample: 1, pid: 1
  };

  function scoreDoingTaskSuffix(name) {
    var n = String(name || "").trim();
    if (n.indexOf(DOING_TASK_PREFIX) !== 0) return "";
    return n.slice(DOING_TASK_PREFIX.length);
  }
  function scoreDoingTaskIsLeaf(name) {
    var suf = scoreDoingTaskSuffix(name);
    return !!suf && DOING_TASK_LEAF_KEYS.indexOf(suf) >= 0;
  }
  function scoreDoingTaskParseCause(raw) {
    /* wait_by_cause value is JSON cause->count. Keys are cause names (e.g. "pattern"), never a watch pattern string. */
    if (raw == null || raw === "") return null;
    if (typeof raw === "object" && !Array.isArray(raw)) return raw;
    try {
      var o = JSON.parse(String(raw));
      if (o && typeof o === "object" && !Array.isArray(o)) return o;
    } catch (eParse) {}
    return null;
  }
  function scoreDoingTaskLeavesByDesk(kpis) {
    var by = {};
    (kpis || []).forEach(function (k) {
      var name = scoreKpiName(k);
      var suf = scoreDoingTaskSuffix(name);
      if (!suf || DOING_TASK_LEAF_KEYS.indexOf(suf) < 0) return;
      var val = k && k.value;
      if (val == null || val === "") return; /* omit missing; never treat as 0 */
      var desk = scoreDeskSlug(k);
      if (!by[desk]) by[desk] = { desk: desk, leaves: {} };
      by[desk].leaves[suf] = String(val);
    });
    return by;
  }
  function scoreDoingTaskDeskRollup(leaves) {
    /* Per-desk rollup = that desk's current leaves grouped together (latest upsert). */
    var out = {};
    var src = (leaves && leaves.leaves) ? leaves.leaves : (leaves || {});
    DOING_TASK_LEAF_KEYS.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(src, key) && src[key] != null && src[key] !== "") {
        out[key] = src[key];
      }
    });
    return out;
  }
  function scoreDoingTaskOfficeRollup(byDesk) {
    /* Sums / merges / tallies of each desk's latest upsert. Omit missing; never treat as 0. */
    var sum = {};
    var causes = {};
    var endTally = {};
    var desks = 0;
    Object.keys(byDesk || {}).forEach(function (desk) {
      var row = byDesk[desk] || {};
      var leaves = scoreDoingTaskDeskRollup(row);
      if (!Object.keys(leaves).length) return;
      desks += 1;
      DOING_TASK_SUM_KEYS.forEach(function (key) {
        if (!Object.prototype.hasOwnProperty.call(leaves, key)) return;
        var n = numish(leaves[key]);
        if (n == null) return;
        sum[key] = (sum[key] == null ? 0 : sum[key]) + n;
      });
      var causeMap = scoreDoingTaskParseCause(leaves.wait_by_cause);
      if (causeMap) {
        Object.keys(causeMap).forEach(function (cause) {
          var n = Number(causeMap[cause]);
          if (!Number.isFinite(n)) return;
          causes[cause] = (causes[cause] || 0) + n;
        });
      }
      var er = leaves.end_reason != null ? String(leaves.end_reason).trim() : "";
      if (er) endTally[er] = (endTally[er] || 0) + 1;
    });
    var out = { desks: desks, sum: sum, wait_by_cause: causes, end_reason: endTally };
    return out;
  }
  function scoreDoingTaskFormatLeaf(key, raw) {
    if (raw == null || raw === "") return "";
    if (key === "wait_by_cause") {
      var m = scoreDoingTaskParseCause(raw);
      if (!m) return "";
      return Object.keys(m).sort().map(function (cause) {
        return cause + ":" + String(m[cause]);
      }).join(" ");
    }
    return String(raw);
  }
  function scoreDoingTaskRowVisible(row) {
    var st = String((row && row.state) || "").trim().toLowerCase();
    if (!st) return true;
    return !DOING_TASK_TERMINAL[st];
  }
  function scoreDoingTaskSanitizeRow(row) {
    /* Show only contracted fields; drop privacy keys even if a feed leaks them. */
    if (!row || typeof row !== "object") return null;
    var out = {
      act: "task",
      state: String(row.state || "").trim(),
      join_key: String(row.join_key || "").trim(),
      waiting_on: "",
      card: ""
    };
    if (row.waiting_on != null && String(row.waiting_on).trim()) {
      out.waiting_on = typeof row.waiting_on === "object"
        ? String((row.waiting_on.on || row.waiting_on.why || "")).trim()
        : String(row.waiting_on).trim();
    } else if (row.cause != null && String(row.cause).trim()) {
      /* cause name only (e.g. pattern), never a watch pattern string */
      out.waiting_on = String(row.cause).trim();
    }
    if (row.card != null && String(row.card).trim()) out.card = String(row.card).trim();
    else if (row.on != null && String(row.on).trim()) out.card = String(row.on).trim();
    return out;
  }
  function scoreDoingTaskLiveRows(list) {
    var out = [];
    (list || []).forEach(function (raw) {
      var row = scoreDoingTaskSanitizeRow(raw);
      if (!row || !scoreDoingTaskRowVisible(row)) return;
      out.push(row);
    });
    return out.slice(0, 8);
  }
  var DOING_TASK_LAST_DONE_KEYS = ["end_reason", "dwell_active_ms", "dwell_idle_ms"];
  /* Per-score timestamps only. Never treat dwell_idle_ms (or other leaf values) as a clock. */
  var DOING_TASK_TS_KEYS = {
    finished_at: 1, written_at: 1, updated_at: 1, created_at: 1,
    scored_at: 1, upserted_at: 1, timestamp: 1, ts: 1, when: 1
  };
  function scoreDoingTaskParseTimestamp(raw) {
    if (raw == null || raw === "") return null;
    if (typeof raw === "number" && Number.isFinite(raw)) {
      if (raw > 1e12) return raw;
      if (raw > 1e9) return raw * 1000;
      return null;
    }
    if (typeof raw === "string" && /^-?\d+(?:\.\d+)?$/.test(raw.trim())) {
      var n = Number(raw.trim());
      if (Number.isFinite(n)) {
        if (n > 1e12) return n;
        if (n > 1e9) return n * 1000;
        return null;
      }
    }
    return scoreParseAt(raw);
  }
  function scoreDoingTaskPickTimestamp(obj) {
    if (!obj || typeof obj !== "object") return null;
    var best = null;
    Object.keys(DOING_TASK_TS_KEYS).forEach(function (key) {
      if (obj[key] == null || obj[key] === "") return;
      var t = scoreDoingTaskParseTimestamp(obj[key]);
      if (t != null && (best == null || t > best)) best = t;
    });
    return best;
  }
  function scoreDoingTaskFormatAgo(tsMs, nowMs) {
    if (tsMs == null || !Number.isFinite(Number(tsMs))) return "";
    var now = nowMs != null ? nowMs : Date.now();
    var delta = now - Number(tsMs);
    if (!Number.isFinite(delta)) return "";
    if (delta < 0) delta = 0;
    var sec = Math.floor(delta / 1000);
    if (sec < 60) return (sec <= 1 ? "1 second ago" : (sec + " seconds ago"));
    var min = Math.floor(sec / 60);
    if (min < 60) return (min === 1 ? "1 minute ago" : (min + " minutes ago"));
    var hr = Math.floor(min / 60);
    if (hr < 24) return (hr === 1 ? "1 hour ago" : (hr + " hours ago"));
    var day = Math.floor(hr / 24);
    return (day === 1 ? "1 day ago" : (day + " days ago"));
  }
  function scoreDoingTaskLastDoneFromScores(kpis, desk, nowMs) {
    /* Last wrapper from that desk's doing.task.* leaves. No invented fields. */
    var want = String(desk || "").trim();
    if (!want) return null;
    var by = scoreDoingTaskLeavesByDesk(kpis);
    var packed = by[want];
    if (!packed) return null;
    var leaves = scoreDoingTaskDeskRollup(packed);
    var out = { kind: "last_done", live: false };
    var any = false;
    DOING_TASK_LAST_DONE_KEYS.forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(leaves, key)) return;
      if (leaves[key] == null || leaves[key] === "") return;
      out[key] = leaves[key];
      any = true;
    });
    if (!any) return null;
    var ts = null;
    (kpis || []).forEach(function (k) {
      if (scoreDeskSlug(k) !== want) return;
      var suffix = scoreDoingTaskSuffix(scoreKpiName(k));
      if (!suffix) return;
      var picked = scoreDoingTaskPickTimestamp(k);
      if (picked != null && (ts == null || picked > ts)) ts = picked;
      if (DOING_TASK_TS_KEYS[suffix]) {
        var fromVal = scoreDoingTaskParseTimestamp(k.value);
        if (fromVal != null && (ts == null || fromVal > ts)) ts = fromVal;
      }
    });
    if (ts != null) {
      var ago = scoreDoingTaskFormatAgo(ts, nowMs);
      if (ago) out.ago = ago;
    }
    return out;
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
    scoreEnsurePaintContract: scoreEnsurePaintContract,
    DOING_TASK_PREFIX: DOING_TASK_PREFIX,
    DOING_TASK_LEAF_KEYS: DOING_TASK_LEAF_KEYS,
    DOING_TASK_SUM_KEYS: DOING_TASK_SUM_KEYS,
    scoreDoingTaskSuffix: scoreDoingTaskSuffix,
    scoreDoingTaskIsLeaf: scoreDoingTaskIsLeaf,
    scoreDoingTaskParseCause: scoreDoingTaskParseCause,
    scoreDoingTaskLeavesByDesk: scoreDoingTaskLeavesByDesk,
    scoreDoingTaskDeskRollup: scoreDoingTaskDeskRollup,
    scoreDoingTaskOfficeRollup: scoreDoingTaskOfficeRollup,
    scoreDoingTaskFormatLeaf: scoreDoingTaskFormatLeaf,
    scoreDoingTaskRowVisible: scoreDoingTaskRowVisible,
    scoreDoingTaskSanitizeRow: scoreDoingTaskSanitizeRow,
    scoreDoingTaskLiveRows: scoreDoingTaskLiveRows,
    DOING_TASK_LAST_DONE_KEYS: DOING_TASK_LAST_DONE_KEYS,
    scoreDoingTaskParseTimestamp: scoreDoingTaskParseTimestamp,
    scoreDoingTaskFormatAgo: scoreDoingTaskFormatAgo,
    scoreDoingTaskLastDoneFromScores: scoreDoingTaskLastDoneFromScores
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallScore = api;
  global.WALL_UI_DEFAULT_SCORE = "WALL_UI_DEFAULT_SCORE";
})(typeof window !== "undefined" ? window : globalThis);
