/* SCORE redesign (review letters 5445-5471): Scores in impact groups, Spend as tw doing time.
 * Every score row is listed; nothing is collapsed or hidden. Legend, never 0 for a gap:
 *   "-" (em dash) not fetched | "omitted" leaf not stored | "not filed" kpi key, nothing stored
 *   "no kpi" no key | "not sent" score.updated not in the payload.
 * Time comes only from doing.task.dwell_*_ms. Activity counts and transitions are context. */
(function (global) {
  "use strict";
  var DASH = "\u2014";
  var DAY_MS = 86400000;
  function W() { return global.WallScore || {}; }
  function kname(k) { return W().scoreKpiName ? W().scoreKpiName(k) : String((k && (k.kpi || k.name)) || "").trim(); }
  function kdesk(k) { return W().scoreDeskSlug ? W().scoreDeskSlug(k) : String((k && k.owner) || "").trim(); }
  function num(v) {
    if (v == null || v === "") return null;
    var n = Number(String(v).trim());
    return Number.isFinite(n) ? n : null;
  }
  function h(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Groups in impact order. keys = defined in code (server/*_activity.py, wasted_wake.py,
   * wake_first.py); a key with no row paints "not filed". nokpi = asked for, no key yet. */
  var GROUPS = [
    { id: "wakes", title: "Wakes", type: "wake",
      why: "A wasted or colliding wake burns a sit and hides real work.",
      keys: ["mill-office.wasted_wake_share", "mill-office.wasted_wake_n", "wake.wasted_n", "wake.wakes_n",
        "mill-office.wake_first_ms", "mill-office.wake_first_rpc", "mill-office.wrong_verb_n", "mill-office.retry_before_ok"],
      prefixes: ["wake."], nokpi: ["stale wake-done", "seat collisions"] },
    { id: "doing", title: "Doing (tw)", type: "doing", prefixes: ["doing."],
      why: "Measured doing, the same leaves as Spend. Durations carry no rate column. Doing items are context, not a second clock." },
    { id: "mail", title: "Mail", type: "mail", why: "Answer latency.", prefixes: ["mail."],
      keys: ["mail.send_to_wake_ms", "mail.wake_to_answer_ms", "mail.re_rings_n", "mail.never_answered_n"] },
    { id: "todo", title: "Todo", type: "todo", why: "Card cycle.", prefixes: ["todo."],
      keys: ["todo.open_to_claim_ms", "todo.claim_to_ship_ms", "todo.ship_to_done_ms", "todo.open_age_ms",
        "todo.claimed_age_ms", "todo.open_n", "todo.claimed_n"] },
    { id: "hold", title: "Hold", type: "hold", why: "Contention.", prefixes: ["hold."],
      keys: ["hold.wait_ms", "hold.held_ms", "hold.contention_n", "hold.force_taken_n", "hold.expired_n"] },
    { id: "connect", title: "Connect", type: "", why: "Seat health. No activity type of its own yet, so no rate.", prefixes: ["connect."],
      keys: ["connect.startup_ms", "connect.session_ms", "connect.drop_n", "connect.reconnect_n"] },
    { id: "platform", title: "Platform", type: "", why: "Host health. Office rows first, then every per-desk row.",
      prefixes: ["mill-wall.", "mill-desk.", "mill-office."], exact: ["wall"] },
    { id: "system", title: "System commands", type: "", why: "Command counts, not doing time. Hour and day charts for one desk sit under this table.",
      exact: ["system"] },
    { id: "other", title: "Other", type: "", why: "Filed scores outside the groups above. Listed so nothing is hidden.", catchAll: true }
  ];

  function groupOf(name) {
    var n = String(name || "");
    for (var i = 0; i < GROUPS.length; i++) {
      var g = GROUPS[i];
      if (g.keys && g.keys.indexOf(n) >= 0) return g.id;
      if (g.exact && g.exact.indexOf(n) >= 0) return g.id;
    }
    for (var j = 0; j < GROUPS.length; j++) {
      var p = GROUPS[j].prefixes || [];
      for (var q = 0; q < p.length; q++) if (n.indexOf(p[q]) === 0) return GROUPS[j].id;
    }
    return "other";
  }

  function written(k) {
    /* score.updated (Builder, after card 1133). Absent => "not sent", never an invented clock. */
    var raw = k && (k.updated != null ? k.updated : k.updated_at);
    if (raw == null || raw === "") return null;
    var t = (typeof raw === "number") ? (raw > 1e12 ? raw : raw * 1000) : Date.parse(String(raw).replace(" ", "T"));
    return Number.isFinite(t) ? t : null;
  }
  function writtenText(ts) {
    if (ts == null) return "not sent";
    var d = new Date(ts);
    var mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
    return mon + " " + d.getDate() + " " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function fmtMs(v) {
    var n = num(v);
    if (n == null) return String(v);
    if (n < 1000) return (Math.round(n * 10) / 10) + " ms";
    if (n < 60000) return (Math.round(n / 100) / 10) + "s";
    var s = Math.floor(n / 1000), d = Math.floor(s / 86400), hr = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return d + "d " + hr + "h " + m + "m";
    if (hr) return hr + "h " + m + "m";
    return m + "m " + (s % 60) + "s";
  }

  /* Activity context (mill_activity_bucket hour by type, Builder payload pending):
   * ctx.activity[type] = { hours: [24 counts, local hour 0..23 today], byDesk: { desk: [24] } }.
   * Missing => em dash (not fetched). Rate = today's items / hours elapsed today. */
  function activityFor(ctx, type, desk, nowMs) {
    var a = ctx && ctx.activity && type ? ctx.activity[type] : null;
    if (!a) return null;
    var office = !desk || desk === "Office" || (W().scoreIsHostDesk && W().scoreIsHostDesk(desk));
    var hours = office ? a.hours : (a.byDesk && a.byDesk[desk]);
    if (!Array.isArray(hours)) return office ? null : { today: 0, rate: 0, hours: [] };
    var now = new Date(nowMs == null ? Date.now() : nowMs);
    var upto = now.getHours() + 1;
    var today = 0;
    for (var i = 0; i < Math.min(upto, hours.length); i++) today += Number(hours[i]) || 0;
    var elapsed = now.getHours() + now.getMinutes() / 60;
    return { today: today, rate: elapsed > 0 ? today / elapsed : null, hours: hours.slice(0, upto) };
  }
  function sparkHtml(hours) {
    if (!hours || !hours.length) return '<span class="si-gap">' + DASH + "</span>";
    var max = Math.max.apply(null, hours.map(function (x) { return Number(x) || 0; })) || 1;
    return '<span class="si-spark" aria-hidden="true">' + hours.map(function (x) {
      return '<i class="s' + Math.max(0, Math.round(((Number(x) || 0) / max) * 8)) + '"></i>';
    }).join("") + "</span>";
  }

  /* Doing (tw) leaves per desk, keyed by suffix. last_run drives open/finished tags. */
  function doingByDesk(kpis) {
    var by = {};
    (kpis || []).forEach(function (k) {
      var n = kname(k);
      if (n.indexOf("doing.task.") !== 0) return;
      var desk = kdesk(k);
      var suf = n.slice(11);
      if (!by[desk]) by[desk] = { desk: desk, leaves: {}, rows: {} };
      by[desk].rows[suf] = k;
      if (k.value != null && k.value !== "") by[desk].leaves[suf] = String(k.value);
    });
    return by;
  }
  function lastRunTally(by) {
    var t = { finished: 0, active: 0, failed: 0, desks: 0 };
    Object.keys(by).forEach(function (d) {
      var lr = String(by[d].leaves.last_run || "").trim();
      if (!lr) return;
      t.desks += 1;
      if (t[lr] != null) t[lr] += 1;
    });
    return t;
  }

  /* Model: every row, grouped. Pure; no DOM. */
  function scoreImpactModel(kpis, ctx, nowMs) {
    var groups = {};
    GROUPS.forEach(function (g) { groups[g.id] = { def: g, rows: [] }; });
    var seenName = {};
    (kpis || []).forEach(function (k) {
      var name = kname(k);
      if (!name) return;
      seenName[name] = 1;
      groups[groupOf(name)].rows.push({ kpi: name, desk: kdesk(k), k: k, state: (k.value == null || k.value === "") ? "omitted" : "ok" });
    });
    GROUPS.forEach(function (g) {
      (g.keys || []).forEach(function (key) {
        if (!seenName[key]) groups[g.id].rows.push({ kpi: key, desk: "Office", k: null, state: "not filed" });
      });
      (g.nokpi || []).forEach(function (label) {
        groups[g.id].rows.push({ kpi: label, desk: DASH, k: null, state: "no kpi" });
      });
      var order = g.keys || [];
      groups[g.id].rows.sort(function (a, b) {
        var ia = order.indexOf(a.kpi), ib = order.indexOf(b.kpi);
        if (a.state === "no kpi" || b.state === "no kpi") return (a.state === "no kpi") - (b.state === "no kpi");
        if (ia >= 0 || ib >= 0) {
          if (ia < 0) return 1;
          if (ib < 0) return -1;
          if (ia !== ib) return ia - ib;
        }
        var ao = a.desk === "Office" ? 0 : 1, bo = b.desk === "Office" ? 0 : 1;
        if (g.id === "platform" && ao !== bo) return ao - bo;
        return a.kpi.localeCompare(b.kpi) || String(a.desk).localeCompare(String(b.desk));
      });
    });
    var doing = doingByDesk(kpis);
    return {
      groups: GROUPS.map(function (g) { return groups[g.id]; }).filter(function (gr) {
        return !gr.def.catchAll || gr.rows.length;
      }),
      doing: doing,
      tally: lastRunTally(doing),
      ctx: ctx || {},
      nowMs: nowMs,
      total: (kpis || []).length
    };
  }

  function lastCell(row) {
    if (row.state !== "ok") return '<td class="num si-gap">' + h(row.state) + "</td>";
    var v = String(row.k.value), t = row.k.target;
    var miss = typeof global.kpiMiss === "function" && global.kpiMiss(v, t);
    return '<td class="num' + (miss ? " si-miss" : "") + '">' + h(v) +
      (t != null && t !== "" ? '<span class="si-tgt"> / ' + h(t) + "</span>" : "") + "</td>";
  }
  function writtenCell(row) {
    if (!row.k) return '<td class="si-gap">' + DASH + "</td>";
    var ts = written(row.k);
    return '<td class="' + (ts == null ? "si-gap" : "") + '">' + h(writtenText(ts)) + "</td>";
  }
  function deskName(desk) {
    return (typeof global.millName === "function" && desk && desk !== DASH && desk !== "Office") ? global.millName("desk", desk) : desk;
  }

  function doingLeafCell(row, by) {
    if (row.state !== "ok") return '<td class="num si-gap">' + h(row.state) + "</td>";
    var suf = row.kpi.slice(11);
    var lr = String(((by[row.desk] || {}).leaves || {}).last_run || "");
    var v = String(row.k.value);
    var tags = [];
    if (/_ms$/.test(suf)) {
      var n = num(v);
      var shown = fmtMs(v) + (n != null && n >= 1000 ? ' <span class="si-tag">' + h(v) + " ms</span>" : "");
      if (lr === "active" && suf === "dwell_active_ms") tags.push("partial, run open");
      if (n != null && n > DAY_MS) tags.push("outlier: multi-day, shown as stored");
      return '<td class="num si-wrap' + (n != null && n > DAY_MS ? " si-hot" : "") + '">' + shown +
        tags.map(function (t) { return ' <span class="si-tag">' + h(t) + "</span>"; }).join("") + "</td>";
    }
    if (suf === "wait_by_cause") {
      var m = W().scoreDoingTaskParseCause ? W().scoreDoingTaskParseCause(v) : null;
      return '<td class="num">' + h(m ? Object.keys(m).sort().map(function (c) { return c + ":" + m[c]; }).join(" ") : v) + "</td>";
    }
    if (suf === "end_reason" && lr === "active") tags.push("previous run");
    var cls = (v === "finished" || v === "tw_finished") ? " si-ok" : ((v === "failed" || v === "tw_failed") ? " si-warn" : (v === "active" ? " si-warn" : ""));
    return '<td class="num' + cls + '">' + h(v) + tags.map(function (t) { return ' <span class="si-tag">' + h(t) + "</span>"; }).join("") + "</td>";
  }

  function ctxCells(model, type, desk, withRate) {
    var a = activityFor(model.ctx, type, desk === DASH ? "" : desk, model.nowMs);
    var out = '<td class="num si-ctx' + (a ? "" : " si-gap") + '">' + (a ? h(String(a.today)) : DASH) + "</td>";
    if (withRate) {
      out += '<td class="num si-ctx' + (a && a.rate != null ? "" : " si-gap") + '">' + (a && a.rate != null ? "~" + h(a.rate.toFixed(1)) + "/hr" : DASH) + "</td>";
      out += '<td class="si-ctx">' + sparkHtml(a && a.hours) + "</td>";
    }
    return out;
  }

  function groupHtml(model, gr) {
    var g = gr.def;
    var filed = gr.rows.filter(function (r) { return r.state === "ok" || r.state === "omitted"; }).length;
    var head = '<h3><span>' + h(g.title) + '</span><span class="si-count">' + h(String(gr.rows.length)) + " rows" +
      (g.keys ? " \u00b7 " + h(String(filed)) + " filed" : "") + "</span></h3>";
    var why = '<p class="si-why">' + h(g.why) + "</p>";
    if (g.id === "wakes" && !filed) why += '<p class="si-why"><b>Nothing filed yet on this Office.</b> Every wake row below is empty.</p>';
    var body;
    if (g.id === "doing") {
      var t = model.tally;
      var rows = gr.rows.map(function (r) {
        return '<tr data-kpi="' + h(r.kpi) + '"><td>' + h(r.kpi.replace(/^doing\.task\./, "")) + "</td><td>" + h(deskName(r.desk)) + "</td>" +
          doingLeafCell(r, model.doing) + writtenCell(r) + ctxCells(model, "doing", r.desk, false) + "</tr>";
      }).join("");
      var roll = t.desks
        ? '<tr class="si-roll"><td>last_run rollup</td><td>' + h(String(t.desks)) + ' desks</td><td class="num">' +
          h(t.finished + " finished \u00b7 " + t.active + " active \u00b7 " + t.failed + " failed") + '</td><td class="si-gap">' + DASH + '</td><td class="num si-gap">' + DASH + "</td></tr>"
        : "";
      body = '<table data-table="score-impact-doing"><thead><tr><th>score</th><th>desk</th><th class="num">last run</th><th>written</th><th class="num si-ctx">doing items today</th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="5" class="si-gap">No doing.task.* scores yet.</td></tr>') + roll + "</tbody></table>";
    } else {
      var withRate = !!g.type;
      var rowsHtml = gr.rows.map(function (r) {
        var cls = r.state === "ok" ? "" : ' class="si-missrow"';
        return "<tr" + cls + ' data-kpi="' + h(r.kpi) + '"><td>' + h(r.kpi) + "</td><td>" + h(deskName(r.desk)) + "</td>" + lastCell(r) + writtenCell(r) +
          (r.state === "no kpi" ? '<td class="num si-gap">' + DASH + "</td>" + (withRate ? '<td class="num si-gap">' + DASH + '</td><td class="si-gap">' + DASH + "</td>" : "") : ctxCells(model, g.type, r.desk, withRate)) + "</tr>";
      }).join("");
      body = '<table data-table="score-impact-' + h(g.id) + '"><thead><tr><th>score</th><th>desk</th><th class="num">last / target</th><th>written</th><th class="num si-ctx">activity today</th>' +
        (withRate ? '<th class="num si-ctx">rate</th><th class="si-ctx">today by hour</th>' : "") + "</tr></thead><tbody>" +
        (rowsHtml || '<tr><td colspan="' + (withRate ? 7 : 5) + '" class="si-gap">No rows.</td></tr>') + "</tbody></table>";
      if (!g.type) body += '<p class="si-why">Activity source: ' + (g.id === "connect" ? "no dedicated activity type (gap)." : "none; these are not family volume.") + "</p>";
    }
    var slot = g.id === "system" ? '<div class="si-slot" id="score-impact-charts"></div>' : "";
    return '<section class="si-group" id="si-g-' + h(g.id) + '" data-group="' + h(g.id) + '">' + head + why + body + slot + "</section>";
  }

  var LEGEND = "<b>" + DASH + "</b> = not fetched \u00b7 <b>omitted</b> = leaf not stored, never 0 \u00b7 <b>not filed</b> = key in code, nothing stored \u00b7 <b>no kpi</b> = no key \u00b7 <b>not sent</b> = score.updated not in the payload yet";

  function scoreImpactHtml(model) {
    var jump = model.groups.map(function (gr) {
      return '<a href="#si-g-' + h(gr.def.id) + '" data-si-jump="' + h(gr.def.id) + '">' + h(gr.def.title) + "</a>";
    }).join(" \u00b7 ");
    var sample = model.ctx && model.ctx.sample ? '<p class="si-sample"><b>SAMPLE</b> ' + h(model.ctx.sample) + "</p>" : "";
    return sample + '<nav class="si-jump" aria-label="Score groups">Jump: ' + jump + "</nav>" +
      '<p class="si-legend">' + LEGEND + "</p>" +
      model.groups.map(function (gr) { return groupHtml(model, gr); }).join("") +
      '<p class="si-foot">' + h(String(model.total)) + " score rows loaded. Rate uses activity buckets, never tw time.</p>";
  }

  /* Spend = tw doing time. ctx.runs (Builder: last_run transition meta, phase=finished):
   * [{ desk, phase, dwell_active_ms, dwell_idle_ms, dwell_waiting_ms }]. Absent => no sum. */
  function scoreSpendModel(kpis, ctx) {
    var by = doingByDesk(kpis);
    var runs = ctx && Array.isArray(ctx.runs) ? ctx.runs : null;
    var sums = null;
    if (runs) {
      sums = {};
      runs.forEach(function (r) {
        if (!r || r.phase !== "finished") return;
        var d = String(r.desk || "");
        var s = sums[d] || (sums[d] = { n: 0, dwell_active_ms: null, dwell_idle_ms: null, dwell_waiting_ms: null });
        s.n += 1;
        ["dwell_active_ms", "dwell_idle_ms", "dwell_waiting_ms"].forEach(function (key) {
          var v = num(r[key]);
          if (v != null) s[key] = (s[key] || 0) + v;
        });
      });
    }
    var desks = Object.keys(by).filter(function (d) {
      var l = by[d].leaves;
      return l.dwell_active_ms != null || l.dwell_idle_ms != null || l.dwell_waiting_ms != null || l.last_run != null;
    }).sort();
    var office = null;
    if (sums) {
      office = { n: 0, dwell_active_ms: 0 };
      Object.keys(sums).forEach(function (d) {
        office.n += sums[d].n;
        office.dwell_active_ms += sums[d].dwell_active_ms || 0;
      });
    }
    var waitDesks = desks.filter(function (d) { return by[d].leaves.dwell_waiting_ms != null; });
    return { by: by, desks: desks, sums: sums, office: office, tally: lastRunTally(by), waitDesks: waitDesks, ctx: ctx || {} };
  }

  function msCell(v, extra) {
    if (v == null) return '<td class="num si-gap">omitted</td>';
    var n = num(v);
    var hot = n != null && n > DAY_MS;
    return '<td class="num si-wrap' + (hot ? " si-hot" : "") + '">' + h(fmtMs(v)) +
      (n != null && n >= 1000 ? ' <span class="si-tag">' + h(String(v)) + " ms</span>" : "") +
      (extra ? ' <span class="si-tag">' + h(extra) + "</span>" : "") +
      (hot ? ' <span class="si-tag">outlier: multi-day, shown as stored</span>' : "") + "</td>";
  }

  function scoreSpendHtml(sm, nowMs) {
    var t = sm.tally;
    var sample = sm.ctx.sample ? '<p class="si-sample"><b>SAMPLE</b> ' + h(sm.ctx.sample) + "</p>" : "";
    var kpis = '<div class="si-kpis">' +
      '<div class="si-kpi"><span class="l">Desks with a last tw run</span><b>' + h(String(t.desks)) + '</b><div class="s">by last_run: ' +
        h(t.finished + " finished \u00b7 " + t.active + " active \u00b7 " + t.failed + " failed") + "</div></div>" +
      '<div class="si-kpi"><span class="l">Last-run active</span><b>' + h(String(sm.desks.filter(function (d) { return sm.by[d].leaves.dwell_active_ms != null; }).length)) +
        ' values</b><div class="s">dwell_active_ms per desk \u00b7 not a sum</div></div>' +
      '<div class="si-kpi"><span class="l">Last-run waiting</span><b>' + h(String(sm.waitDesks.length)) + (sm.waitDesks.length === 1 ? " desk" : " desks") + '</b><div class="s">others omitted, not 0</div></div>' +
      '<div class="si-kpi"><span class="l">Finished-run total</span>' + (sm.office
        ? "<b>" + h(fmtMs(sm.office.dwell_active_ms)) + '</b><div class="s">active, sum of ' + h(String(sm.office.n)) + " finished runs</div>"
        : '<b class="si-gap">unavailable</b><div class="s">no finished-run history in the payload</div>') + "</div></div>";
    var rows = sm.desks.map(function (d) {
      var l = sm.by[d].leaves, rws = sm.by[d].rows;
      var lr = l.last_run || "";
      var lrCls = lr === "finished" ? "si-ok" : (lr ? "si-warn" : "si-gap");
      var er = l.end_reason;
      var a = activityFor(sm.ctx, "doing", d, nowMs);
      var s = sm.sums ? sm.sums[d] : undefined;
      var ts = null;
      ["dwell_active_ms", "dwell_idle_ms", "dwell_waiting_ms", "last_run", "end_reason"].forEach(function (key) {
        var w = rws[key] ? written(rws[key]) : null;
        if (w != null && (ts == null || w > ts)) ts = w;
      });
      return "<tr><td>" + h(deskName(d)) + "</td>" +
        msCell(l.dwell_active_ms, lr === "active" ? "partial, run open" : "") + msCell(l.dwell_idle_ms) + msCell(l.dwell_waiting_ms) +
        '<td class="' + lrCls + '">' + h(lr || "omitted") + "</td>" +
        "<td" + (er ? "" : ' class="si-gap"') + ">" + h(er || "omitted") + (er && lr === "active" ? ' <span class="si-tag">previous run</span>' : "") + "</td>" +
        '<td class="' + (ts == null ? "si-gap" : "") + '">' + h(writtenText(ts)) + "</td>" +
        (sm.sums ? (s ? msCell(s.dwell_active_ms, s.n + (s.n === 1 ? " run" : " runs")) : '<td class="num si-gap">none finished</td>') : '<td class="num si-gap">' + DASH + "</td>") +
        '<td class="num si-ctx' + (a ? "" : " si-gap") + '">' + (a ? h(String(a.today)) : DASH) + "</td></tr>";
    }).join("");
    var table = '<table data-table="score-spend-time"><thead><tr><th>desk</th><th class="num">last run active</th><th class="num">last run idle</th>' +
      '<th class="num">last run waiting</th><th>last_run</th><th>end_reason</th><th>written</th><th class="num">finished runs active (sum)</th>' +
      '<th class="num si-ctx">doing items today (ctx)</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="9" class="si-gap">No doing.task.* scores yet.</td></tr>') + "</tbody></table>";
    var legend = '<p class="si-legend"><b>' + DASH + "</b> = not fetched \u00b7 <b>omitted</b> = leaf not stored, never 0 \u00b7 <b>not sent</b> = score.updated not in the payload yet \u00b7 <b>previous run</b> = end_reason left from the run before, while last_run is active \u00b7 <b>partial</b> = dwell of a run still open</p>";
    var counts = sm.desks.map(function (d) {
      var a = activityFor(sm.ctx, "doing", d, nowMs);
      return "<tr><td>" + h(deskName(d)) + '</td><td class="num si-ctx' + (a ? "" : " si-gap") + '">' + (a ? h(String(a.today)) : DASH) +
        '</td><td class="num si-ctx' + (a && a.rate != null ? "" : " si-gap") + '">' + (a && a.rate != null ? h(a.rate.toFixed(1)) : DASH) + "</td><td class=\"si-ctx\">" + sparkHtml(a && a.hours) + "</td></tr>";
    }).join("");
    var tr = sm.ctx.transitions;
    var pairs = tr && Array.isArray(tr.by_pair) ? tr.by_pair : null;
    var doingPairs = pairs ? pairs.filter(function (p) { return p && p.activity_type === "doing"; }) : null;
    var shownPairs = doingPairs && doingPairs.length ? doingPairs : pairs;
    var pairRows = shownPairs ? shownPairs.map(function (p) {
      return "<tr><td><code>" + h(p.activity_type) + "</code></td><td>" + h(p.from_state) + " \u2192 " + h(p.to_state) + '</td><td class="num">' +
        h(p.rows == null ? DASH : p.rows) + '</td><td class="num">' + h(p.events == null ? DASH : p.events) + '</td><td class="num">' + h(p.saved_rows == null ? DASH : p.saved_rows) + "</td></tr>";
    }).join("") : '<tr><td colspan="5" class="si-gap">' + DASH + " not fetched</td></tr>";
    var panels = '<div class="si-grid2">' +
      '<div class="si-panel"><h3>Doing counts \u00b7 context only</h3><p class="si-why">Item counts from activity buckets (type doing, act task). Not duration.</p>' +
        '<table data-table="score-spend-counts"><thead><tr><th>desk</th><th class="num si-ctx">items today</th><th class="num si-ctx">items / hour</th><th class="si-ctx">today by hour</th></tr></thead><tbody>' + counts + "</tbody></table></div>" +
      '<div class="si-panel"><h3>Transitions \u00b7 context only</h3><p class="si-why">Card 1098 transition pairs' + (tr && tr.window ? " (" + h(tr.window) + ")" : "") +
        (doingPairs && doingPairs.length ? ", doing pairs." : (pairs ? ", all types (no doing pairs)." : ".")) + "</p>" +
        '<table data-table="score-spend-transitions"><thead><tr><th>type</th><th>from \u2192 to</th><th class="num">rows</th><th class="num">events</th><th class="num">saved</th></tr></thead><tbody>' + pairRows + "</tbody></table></div></div>";
    return sample + '<p class="si-note">Spend is doing (tw) time only: doing.task.dwell_active_ms, dwell_idle_ms, dwell_waiting_ms. Each cell is that desk\'s latest run, not a sum, unless the finished-runs column is filled. Counts and transitions sit beside the times and are never turned into minutes.</p>' +
      kpis + table + legend + panels;
  }

  function scoreImpactKpis() {
    var books = [];
    if (global._officeScores && Array.isArray(global._officeScores.kpis)) books = books.concat(global._officeScores.kpis);
    var f = global._floor;
    if (f && Array.isArray(f.kpis)) books = books.concat(f.kpis);
    var seen = {};
    return books.filter(function (k) {
      var key = kdesk(k) + "|" + kname(k) + "|" + String((k && k.roster_id) || "");
      if (seen[key]) return false;
      seen[key] = 1;
      return true;
    });
  }

  /* DOM paint. #score-product (desk/command charts) moves into the System commands slot. */
  function paintScoreImpact() {
    var doc = global.document;
    if (!doc) return;
    var kpis = scoreImpactKpis();
    var ctx = global._scoreImpactCtx || {};
    var box = doc.getElementById("score-impact");
    if (box) {
      var product = doc.getElementById("score-product");
      var scroll = box.scrollTop;
      if (product && product.parentNode) product.parentNode.removeChild(product);
      box.innerHTML = scoreImpactHtml(scoreImpactModel(kpis, ctx));
      var slot = doc.getElementById("score-impact-charts");
      if (product && slot) { product.hidden = false; slot.appendChild(product); }
      box.scrollTop = scroll;
      ["score-human", "score-task-wrap", "score-show", "score-show-toggle"].forEach(function (id) {
        var el = doc.getElementById(id);
        if (el) el.hidden = true;
      });
    }
    var spend = doc.getElementById("score-spend-view");
    if (spend) spend.innerHTML = scoreSpendHtml(scoreSpendModel(kpis, ctx));
  }

  var api = {
    SCORE_IMPACT_GROUPS: GROUPS,
    scoreImpactGroupOf: groupOf,
    scoreImpactModel: scoreImpactModel,
    scoreImpactHtml: scoreImpactHtml,
    scoreSpendModel: scoreSpendModel,
    scoreSpendHtml: scoreSpendHtml,
    scoreImpactActivity: activityFor,
    scoreImpactFmtMs: fmtMs,
    paintScoreImpact: paintScoreImpact
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallScoreImpact = api;
  global.WALL_UI_DEFAULT_SCORE_IMPACT = "WALL_UI_DEFAULT_SCORE_IMPACT";
  if (global.document && global._floor) { try { paintScoreImpact(); } catch (eFirst) {} }
})(typeof window !== "undefined" ? window : globalThis);
