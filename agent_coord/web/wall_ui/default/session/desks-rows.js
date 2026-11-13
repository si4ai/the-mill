/* WALL_UI_DEFAULT_DESKS_ROWS - the DESKS tab rows (Wall redesign, first slice).
 * Marker: WALL_UI_DEFAULT_DESKS_ROWS
 * Pure: desksModel(ctx) -> model, desksHtml(model) -> HTML. boot.js gathers ctx from the reads it
 * already makes and paints #here; tests/wall/test_wall_desks_tab.py runs this file in Node.
 *
 * ctx {
 *   live:     [{ owner, state, seat }]  connected desks, state from hereGlance (the doing view wins)
 *   doing:    { owner: view } | null     GET /api/v1/doing?all=1 views (null = not read)
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

  function waitOf(view) {
    if (!view) return null;
    var w = view.waiting_on_it || {};
    var L = w.letters || {};
    var C = w.cards || {};
    return {
      letters: num(L.n) || 0,
      cards: num(C.n) || 0,
      /* Card 1192 fields. Absent on a server without it: null, and the row says nothing about age. */
      overDay: has(L, "n_over_day") ? (num(L.n_over_day) || 0) : null,
      oldestAt: has(L, "oldest_at") && String(L.oldest_at || "") ? String(L.oldest_at) : null
    };
  }

  function liveRow(a, ctx, byStation) {
    var owner = String(a.owner || "").trim();
    var view = ctx.doing ? (ctx.doing[owner] || null) : null;
    var cur = view ? String(view.doing || "").trim() : String(a.seat || "").trim();
    var last = view && view.last ? view.last : null;
    var st = byStation[owner] || null;
    var recent = st && st.recent_activity ? utc(st.recent_activity.at) : null;
    return {
      desk: owner,
      away: false,
      mine: !!(ctx.mine && owner === ctx.mine),
      state: String(a.state || (cur ? "working" : "idle")),
      doing: cur,
      lastDoing: !cur && last ? String(last.doing || "").trim() : "",
      on: view ? String((cur ? view.on : (last && last.on)) || "") : "",
      time: view ? String((cur ? view.age : view.idle) || "") : "",
      wait: waitOf(view),
      prios: ctx.prios ? (ctx.prios[owner] || []).slice(0, PRIO_TOP) : null,
      scores: scoresFor(ctx.kpis, owner),
      recentAt: recent != null ? recent : (st ? utc(st.last_connected) : null)
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
    var wa = a.wait || {}, wb = b.wait || {};
    var oa = wa.overDay || 0, ob = wb.overDay || 0;
    if (oa !== ob) return ob - oa;
    var fa = a.scores.some(function (s) { return s.off; }) ? 1 : 0;
    var fb = b.scores.some(function (s) { return s.off; }) ? 1 : 0;
    if (fa !== fb) return fb - fa;
    var na = (wa.letters || 0) + (wa.cards || 0), nb = (wb.letters || 0) + (wb.cards || 0);
    if (na !== nb) return nb - na;
    var ra = STATE_RANK[a.state] != null ? STATE_RANK[a.state] : 9;
    var rb = STATE_RANK[b.state] != null ? STATE_RANK[b.state] : 9;
    return (ra - rb) || byName(a, b);
  }
  function sortRows(rows, sort, away) {
    var cmp;
    if (sort === "az") cmp = byName;
    else if (sort === "za") cmp = function (a, b) { return byName(b, a); };
    else if (sort === "recent") cmp = byRecent;
    else cmp = away ? function (a, b) { return (b.lastSeenAt - a.lastSeenAt) || byName(a, b); } : urgency;
    return rows.slice().sort(cmp);
  }

  function attentionOf(rows) {
    var out = [];
    rows.forEach(function (r) {
      var w = r.wait;
      if (w && w.overDay) {
        out.push({ desk: r.desk, kind: "letter", text: w.overDay + " letter" + (w.overDay === 1 ? "" : "s") + " waiting over a day" +
          (w.oldestAt ? ", oldest since " + w.oldestAt.slice(5, 16) : "") });
      }
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
    (ctx.live || []).forEach(function (a) {
      var o = String((a && a.owner) || "").trim();
      if (!o || liveSet[o]) return;
      liveSet[o] = 1;
      live.push(liveRow(a, ctx, byStation));
    });
    var connected = sortRows(live, sort, false);
    var away = sortRows(awayRows(ctx, liveSet), sort, true);
    return {
      sort: sort,
      connected: connected,
      away: away,
      awayKnown: Array.isArray(ctx.stations) && ctx.awayScope !== false,
      attention: attentionOf(connected),
      attentionKnown: connected.some(function (r) { return r.wait && r.wait.overDay != null; }),
      selected: String(ctx.selected || "")
    };
  }

  function itemHtml(on) {
    var m = /^(mail|todo|hold|score)-(\d+)$/.exec(on);
    var tab = m ? { mail: "mail", todo: "jobs", score: "score" }[m[1]] : "";
    if (!tab) return '<span class="doing-on">' + h(on) + "</span>";
    return '<a class="doing-on" href="#' + tab + '" data-doing-go="' + h(on) + '">' + h(on) + "</a>";
  }
  function waitHtml(w) {
    if (!w) return "";
    var bits = [];
    if (w.letters) {
      var s = w.letters + " letter" + (w.letters === 1 ? "" : "s") + " waiting";
      if (w.overDay) s += " \u00b7 " + w.overDay + " over a day";
      bits.push(s);
    }
    if (w.cards) bits.push(w.cards + " card" + (w.cards === 1 ? "" : "s") + " waiting");
    if (!bits.length) return '<span class="desk-wait zero">nothing waiting</span>';
    var cls = "desk-wait" + (w.overDay ? " older" : "");
    var since = w.oldestAt ? ' <span class="desk-oldest" title="oldest waiting letter, office clock">oldest since ' + h(w.oldestAt.slice(5, 16)) + "</span>" : "";
    return '<span class="' + cls + '">' + h(bits.join(", ")) + since + "</span>";
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
        '<span class="desk-doing"><span class="desk-time" title="last connected">last seen ' + h(r.lastSeen) + "</span>" +
        (r.last ? '<span class="desk-text is-idle">last: ' + h(r.last) + "</span>" : "") + "</span></div>" +
        priosHtml(r.prios) + "</div>";
    }
    var text = r.doing ? '<span class="desk-text">' + h(r.doing) + "</span>"
      : '<span class="desk-text is-idle">idle' + (r.lastDoing ? '<span class="doing-last"> \u00b7 last: ' + h(r.lastDoing) + "</span>" : "") + "</span>";
    var time = r.time ? '<span class="desk-time" title="' + (r.doing ? "doing this for" : "idle for") + '">' + h(r.time) + "</span>" : "";
    return '<div class="here-line desk-line" data-here-owner="' + h(r.desk) + '">' +
      '<button type="button" class="here-row' + on + '" data-here-owner="' + h(r.desk) + '">' +
      '<span class="here-dot ' + h(r.state) + '"></span><span class="here-name">' + h(r.desk) + "</span>" +
      '<span class="here-state">' + h(r.state) + "</span>" +
      '<span class="desk-doing">' + time + text + "</span></button>" +
      '<div class="desk-meta">' + (r.on ? itemHtml(r.on) : "") + waitHtml(r.wait) + "</div>" +
      priosHtml(r.prios) + scoresHtml(r.scores) + "</div>";
  }
  function attentionHtml(m) {
    /* TODO(card 1192): with no n_over_day on the doing view, letter age is unknown; the block lists only scores and overdue cards. */
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
