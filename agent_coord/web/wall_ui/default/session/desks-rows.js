/* WALL_UI_DEFAULT_DESKS_ROWS - the DESKS tab rows (Wall redesign, first slice).
 * Marker: WALL_UI_DEFAULT_DESKS_ROWS
 * Pure: desksModel(ctx) -> model, desksHtml(model) -> HTML. boot.js gathers ctx from the reads it
 * already makes and paints #here; tests/wall/test_wall_desks_tab.py runs this file in Node.
 *
 * ctx {
 *   live:     [{ owner, state, seatAlive }]  connected desks, state from hereGlance (the doing
 *                                        view wins); seatAlive false: the seat row itself is not alive
 *   doing:    { owner: view } | null     GET /api/v1/doing?all=1 views (null = not read); card 1207:
 *                                        n live doings (tw runs) and doings [{ id, created, text, state,
 *                                        state_at, card }], newest first (at most 20)
 *   stations: [pov desks row] | null     GET /api/pov?part=desks rows (card 1191): name, connected,
 *                                        last_connected (UTC ISO), recent_activity { at, type, thing }
 *   prios:    { desk: [{ pos, id, ord, title, overdue }] } | null   labels read (null = not read)
 *   kpis:     [score row]                Office scores (doing.task.* leaves per desk)
 *   awayScope: true | false              false: the rail scope cannot say which away desks belong
 *   sort, mine, now
 * }
 * Every field shown is a field the server sent. A field it does not send hides its element. */
(function (global) {
  "use strict";
  var SORTS = ["urgency", "az", "za", "recent"];
  var SORT_LABEL = { urgency: "Urgency", az: "A\u2013Z", za: "Z\u2013A", recent: "Recent" };
  var PRIO_TOP = 3;
  var DAY_MS = 86400000;
  /* TODO(card 1193): the rail time range (?window=1d|7d|30d) replaces this fixed 7 days. */
  var AWAY_WINDOW_MS = 7 * DAY_MS;
  var STATE_RANK = { working: 0, waiting: 1, blocked: 2, here: 3, idle: 4, gone: 5 };

  function h(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v) {
    if (v == null || v === "") return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function has(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }
  function ago(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    var m = Math.max(0, Math.floor(ms / 60000));
    if (m < 1) return "now";
    if (m < 60) return m + "m ago";
    var hr = Math.floor(m / 60);
    if (hr < 48) return hr + "h ago";
    return Math.floor(ms / DAY_MS) + "d ago";
  }
  function utc(raw) {
    var t = Date.parse(String(raw || ""));
    return Number.isFinite(t) ? t : null;
  }
  function deskOf(k) { return String((k && (k.owner || k.desk_id || k.desk)) || "").trim(); }
  function kpiOf(k) { return String((k && (k.kpi || k.name)) || "").trim(); }

  /* Score labels a human reads. Only doing.task.* leaves the server wrote for this desk. */
  function scoresFor(kpis, desk) {
    var out = [];
    var want = { "doing.task.last_run": "Last run", "doing.task.end_reason": "Last run ended" };
    var seen = {};
    (kpis || []).forEach(function (k) {
      var name = kpiOf(k);
      if (!want[name] || seen[name] || deskOf(k) !== desk) return;
      var v = k.value;
      if (v == null || v === "") return;
      seen[name] = 1;
      var val = String(v);
      out.push({ key: name, label: want[name], value: val, off: val === "failed" });
    });
    /* TODO(card 1194): window-scoped doing time ("Doing time today") is not served yet, so no row. */
    return out;
  }

  /* The server's own flags on the doing view. Its doing text on a desk that is not alive (or is
   * stale) is a leftover, never "working". No time threshold here. */
  function viewStale(view) { return !!view && (view.alive === false || view.stale === true); }
  /* Card 1207: a desk's doing is its live tw runs: the newest run's text, or "N doings", or idle. */
  function newest(view) {
    return (view && Array.isArray(view.doings) && view.doings[0]) || null;
  }
  function doingText(view) {
    var n = (view && num(view.n)) || 0;
    if (!n) return "";
    var top = newest(view);
    var text = top ? String(top.text || "").trim() : "";
    return text || (n + " doing" + (n === 1 ? "" : "s"));
  }

  function liveRow(a, ctx, byStation) {
    var owner = String(a.owner || "").trim();
    var view = ctx.doing ? (ctx.doing[owner] || null) : null;
    var st = byStation[owner] || null;
    var recent = st && st.recent_activity ? utc(st.recent_activity.at) : null;
    if (viewStale(view) && a.seatAlive === false) return staleAwayRow(owner, view, ctx, st, recent);
    var stale = viewStale(view);
    var cur = stale ? "" : doingText(view);
    return {
      desk: owner,
      away: false,
      stale: stale,
      mine: !!(ctx.mine && owner === ctx.mine),
      /* A connected seat with a stale doing view is idle, whatever the glance said. */
      state: stale ? "idle" : String(a.state || (cur ? "working" : "idle")),
      doing: cur,
      on: cur && newest(view) && newest(view).card != null ? "todo-" + newest(view).card : "",
      time: cur && newest(view) && utc(newest(view).created) != null ? ago(ctx.now - utc(newest(view).created)) : "",
      prios: ctx.prios ? (ctx.prios[owner] || []).slice(0, PRIO_TOP) : null,
      scores: scoresFor(ctx.kpis, owner),
      recentAt: recent != null ? recent : (st ? utc(st.last_connected) : null)
    };
  }

  /* A seat that is not alive and a stale doing view: away (dimmed), last seen from the station. */
  function staleAwayRow(owner, view, ctx, st, recent) {
    var lc = st ? utc(st.last_connected) : null;
    return {
      desk: owner,
      away: true,
      state: "disconnected",
      lastSeenAt: lc,
      lastSeen: lc != null ? ago(ctx.now - lc) : "",
      last: "",
      lastKind: "",
      recentAt: recent != null ? recent : lc,
      prios: ctx.prios ? (ctx.prios[owner] || []).slice(0, PRIO_TOP) : null
    };
  }

  function awayRows(ctx, liveSet) {
    if (!Array.isArray(ctx.stations) || ctx.awayScope === false) return [];
    var now = ctx.now;
    var seen = {};
    var out = [];
    ctx.stations.forEach(function (s) {
      var name = String((s && s.name) || "").trim();
      if (!name || s.connected || liveSet[name] || seen[name]) return;
      var lc = utc(s.last_connected);
      if (lc == null || now - lc > AWAY_WINDOW_MS) return;
      seen[name] = 1;
      var ra = s.recent_activity || null;
      out.push({
        desk: name,
        away: true,
        state: "disconnected",
        lastSeenAt: lc,
        lastSeen: ago(now - lc),
        last: ra ? String(ra.thing || "").trim() : "",
        lastKind: ra ? String(ra.type || "") : "",
        recentAt: ra && utc(ra.at) != null ? utc(ra.at) : lc,
        prios: ctx.prios ? (ctx.prios[name] || []).slice(0, PRIO_TOP) : null
      });
    });
    return out;
  }

  function byName(a, b) { return a.desk.localeCompare(b.desk); }
  function byRecent(a, b) {
    var ta = a.recentAt == null ? -Infinity : a.recentAt;
    var tb = b.recentAt == null ? -Infinity : b.recentAt;
    return (tb - ta) || byName(a, b);
  }
  function urgency(a, b) {
    if (a.mine !== b.mine) return a.mine ? -1 : 1;
    var ra = STATE_RANK[a.state], rb = STATE_RANK[b.state];
    if (ra !== rb) return (ra == null ? 9 : ra) - (rb == null ? 9 : rb);
    var fa = a.scores.some(function (s) { return s.off; }) ? 1 : 0;
    var fb = b.scores.some(function (s) { return s.off; }) ? 1 : 0;
    if (fa !== fb) return fb - fa;
    return byName(a, b);
  }
  function sortRows(rows, sort, away) {
    var cmp;
    if (sort === "az") cmp = byName;
    else if (sort === "za") cmp = function (a, b) { return byName(b, a); };
    else if (sort === "recent") cmp = byRecent;
    else cmp = away ? function (a, b) {
      var ta = a.lastSeenAt == null ? -Infinity : a.lastSeenAt, tb = b.lastSeenAt == null ? -Infinity : b.lastSeenAt;
      return (tb - ta) || byName(a, b);
    } : urgency;
    return rows.slice().sort(cmp);
  }

  function attentionOf(rows) {
    var out = [];
    rows.forEach(function (r) {
      r.scores.forEach(function (s) {
        if (s.off) out.push({ desk: r.desk, kind: "score", text: s.label + " " + s.value });
      });
      (r.prios || []).forEach(function (p) {
        if (p.overdue) out.push({ desk: r.desk, kind: "prio", text: "#" + p.pos + " todo-" + p.id + " overdue " + p.overdue });
      });
    });
    return out;
  }

  function desksModel(ctx) {
    ctx = Object.assign({}, ctx || {});
    if (ctx.now == null) ctx.now = Date.now();
    var sort = SORTS.indexOf(ctx.sort) >= 0 ? ctx.sort : "urgency";
    var byStation = {};
    (Array.isArray(ctx.stations) ? ctx.stations : []).forEach(function (s) {
      var n = String((s && s.name) || "").trim();
      if (n && !byStation[n]) byStation[n] = s;
    });
    var liveSet = {};
    var live = [];
    var goneSeats = [];
    (ctx.live || []).forEach(function (a) {
      var o = String((a && a.owner) || "").trim();
      if (!o || liveSet[o]) return;
      liveSet[o] = 1;
      var row = liveRow(a, ctx, byStation);
      (row.away ? goneSeats : live).push(row);
    });
    var connected = sortRows(live, sort, false);
    var away = sortRows(goneSeats.concat(awayRows(ctx, liveSet)), sort, true);
    return {
      sort: sort,
      connected: connected,
      away: away,
      awayKnown: Array.isArray(ctx.stations) && ctx.awayScope !== false,
      attention: attentionOf(connected),
      selected: String(ctx.selected || "")
    };
  }

  function itemHtml(on) {
    var m = /^(mail|todo|hold|score)-(\d+)$/.exec(on);
    var tab = m ? { mail: "mail", todo: "jobs", score: "score" }[m[1]] : "";
    if (!tab) return '<span class="doing-on">' + h(on) + "</span>";
    return '<a class="doing-on" href="#' + tab + '" data-doing-go="' + h(on) + '">' + h(on) + "</a>";
  }
  function priosHtml(p) {
    /* null: the labels read has not landed (or the route is missing), so the line is left out. */
    if (p == null) return "";
    if (!p.length) return '<div class="desk-prios empty">no priorities set</div>';
    return '<div class="desk-prios">' + p.map(function (r) {
      return '<span class="desk-prio"><span class="rank" title="ord ' + h(r.ord) + '">#' + h(r.pos) + "</span> " +
        '<span class="item-id">todo-' + h(r.id) + "</span> " + h(r.title || "") + "</span>";
    }).join('<span class="sep"> \u00b7 </span>') + "</div>";
  }
  function scoresHtml(s) {
    if (!s || !s.length) return "";
    return '<div class="desk-scores">' + s.map(function (x) {
      return '<span class="desk-score' + (x.off ? " off" : "") + '" title="' + h(x.key) + '">' + h(x.label) + " <b>" + h(x.value) + "</b></span>";
    }).join("") + "</div>";
  }
  function rowHtml(r, selected) {
    var on = r.desk === selected ? " on" : "";
    if (r.away) {
      return '<div class="here-line desk-line away" data-here-owner="' + h(r.desk) + '">' +
        '<div class="here-row desk-away"><span class="here-dot gone"></span>' +
        '<span class="here-name">' + h(r.desk) + '</span><span class="here-state">disconnected</span>' +
        '<span class="desk-doing">' + (r.lastSeen ? '<span class="desk-time" title="last connected">last seen ' + h(r.lastSeen) + "</span>" : "") +
        (r.last ? '<span class="desk-text is-idle">last: ' + h(r.last) + "</span>" : "") + "</span></div>" +
        priosHtml(r.prios) + "</div>";
    }
    var text = r.doing ? '<span class="desk-text">' + h(r.doing) + "</span>"
      : '<span class="desk-text is-idle">idle</span>';
    var time = r.time ? '<span class="desk-time" title="' + "newest doing" + '">' + h(r.time) + "</span>" : "";
    return '<div class="here-line desk-line' + (r.stale ? " stale" : "") + '" data-here-owner="' + h(r.desk) + '">' +
      '<button type="button" class="here-row' + on + '" data-here-owner="' + h(r.desk) + '">' +
      '<span class="here-dot ' + h(r.state) + '"></span><span class="here-name">' + h(r.desk) + "</span>" +
      '<span class="here-state">' + h(r.state) + "</span>" +
      '<span class="desk-doing">' + time + text + "</span></button>" +
      '<div class="desk-meta">' + (r.on ? itemHtml(r.on) : "") + "</div>" +
      priosHtml(r.prios) + scoresHtml(r.scores) + "</div>";
  }
  function attentionHtml(m) {
    var items = m.attention;
    var body = items.length
      ? items.map(function (a) {
          return '<div class="attn-row" data-attn="' + h(a.kind) + '"><span class="desk-chip">' + h(a.desk) + '</span><span class="attn-text">' + h(a.text) + "</span></div>";
        }).join("")
      : '<div class="attn-row empty">Nothing needs attention.</div>';
    return '<div class="desks-attention" role="region" aria-label="Needs attention"><h3>NEEDS ATTENTION <span class="sub">' + items.length + "</span></h3>" + body + "</div>";
  }
  function sortHtml(sort) {
    return '<span class="desks-sort" role="group" aria-label="Sort desks"><span class="lbl">SORT</span>' + SORTS.map(function (k) {
      return '<button type="button" data-desks-sort="' + k + '"' + (k === sort ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + SORT_LABEL[k] + "</button>";
    }).join("") + "</span>";
  }
  function desksHtml(m) {
    var html = '<div class="desks-tools">' + sortHtml(m.sort) + "</div>" + attentionHtml(m) +
      '<div class="here-section">Connected \u00b7 ' + m.connected.length + "</div>" +
      (m.connected.length ? m.connected.map(function (r) { return rowHtml(r, m.selected); }).join("")
        : '<div class="empty-session"><b>No desks are here.</b> Ask your agent to join.</div>');
    if (m.away.length) {
      html += '<div class="here-section away">Disconnected \u00b7 ' + m.away.length + "</div>" +
        m.away.map(function (r) { return rowHtml(r, m.selected); }).join("");
    }
    return html;
  }

  global.desksModel = desksModel;
  global.desksHtml = desksHtml;
  global.WALL_DESKS_SORTS = SORTS.slice();
  global.WALL_UI_DEFAULT_DESKS_ROWS = "WALL_UI_DEFAULT_DESKS_ROWS";
})(typeof window !== "undefined" ? window : globalThis);
