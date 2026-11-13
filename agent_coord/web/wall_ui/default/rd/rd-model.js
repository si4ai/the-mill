/* WALL_UI_DEFAULT_RD_MODEL - the Wall redesign: one scope, six roster-wide tabs.
 * Marker: WALL_UI_DEFAULT_RD_MODEL
 * Pure: WallRd.base(data, scope, now) folds the reads into desks; each tab has a model
 * (desks, todo, mail, priorities, score, collab) and rd-view.js turns a model into HTML.
 * rd-app.js gathers `data` from the read routes; tests/wall/test_wall_rd_*.py run this in Node.
 *
 * data {
 *   agents:  { roster: [seat rows] }            GET /api/v1/agents?project=R
 *   doing:   { owner: view } | null             GET /api/v1/doing?all=1
 *   stations:[pov desks rows] | null            GET /api/pov?part=desks (card 1191)
 *   names:   { roster: [catalog rows] }         GET /api/v1/names?project=R (deleted desks)
 *   todos:   { roster: { needs, issues } }      GET /api/v1/todos?project=R
 *   mail:    { roster: [letters] }              GET /api/v1/mailbox?project=R
 *   labels:  { roster: { rows, checks } }       GET /api/v1/labels?project=R
 *   scores:  { roster: [kpis] }                 GET /api/v1/scores?project=R
 *   holds:   { roster: [locks] }                GET /api/v1/holds?project=R
 *   rooms:   { roster: [trees] }                GET /api/v1/rooms?project=R
 *   events:  { roster: [events] }               GET /api/v1/events?project=R
 *   history: { desk: [doing history rows] }     GET /api/v1/doing/history?desk=D
 *   runs:    { roster: [score-runs rows] }      GET /api/v1/score-runs?project=R
 * }
 * A key that is missing (or null) has not been read: the spot it feeds is left out, never
 * filled in. Every number shown is one the server sent, or a count of rows it sent. */
(function (global) {
  "use strict";
  var MIN = 60000, HOUR = 3600000, DAY = 86400000;
  var RANGE_MS = { "7d": 7 * DAY, "30d": 30 * DAY };
  var RANGES = ["today", "7d", "30d"];
  var STATE_RANK = { working: 0, waiting: 1, idle: 2 };
  var STUCK_MS = 2 * DAY;

  function has(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }
  function str(v) { return String(v == null ? "" : v).trim(); }
  function num(v) {
    if (v == null || v === "") return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  /* Office clock: naive "YYYY-MM-DD HH:MM:SS" is UTC; ISO strings keep their zone. */
  function utc(raw) {
    var s = str(raw);
    if (!s) return null;
    if (/^\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(s)) s = s.replace(" ", "T") + "Z";
    var t = Date.parse(s);
    return Number.isFinite(t) ? t : null;
  }
  function dur(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    var m = Math.max(0, Math.floor(ms / MIN));
    if (m < 1) return "<1m";
    if (m < 60) return m + "m";
    var hr = Math.floor(m / 60);
    if (hr < 24) { var mm = m % 60; return hr + "h" + (mm ? " " + (mm < 10 ? "0" : "") + mm + "m" : ""); }
    var d = Math.floor(hr / 24), hh = hr % 24;
    return d + "d" + (hh ? " " + hh + "h" : "");
  }
  function ago(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    return ms < MIN ? "now" : dur(ms) + " ago";
  }
  /* A server dwell in milliseconds, as a person reads it. */
  function msText(v) {
    var n = num(v);
    if (n == null) return "";
    if (n < 1000) return "<1s";
    if (n < MIN) return Math.round(n / 1000) + "s";
    var s = Math.round(n / 1000), m = Math.floor(s / 60);
    if (m < 60) return m + "m " + (s % 60 < 10 ? "0" : "") + (s % 60) + "s";
    return dur(n);
  }
  function firstLine(text, n) {
    var lines = String(text == null ? "" : text).split(/\r?\n/);
    var line = "";
    for (var i = 0; i < lines.length; i++) { line = lines[i].trim(); if (line) break; }
    n = n || 120;
    return line.length > n ? line.slice(0, n - 1).trimEnd() + "\u2026" : line;
  }
  function itemOf(on) {
    var m = /^(mail|todo|hold|score)-(\d+)$/.exec(str(on));
    return m ? { kind: m[1], id: Number(m[2]), key: m[0] } : null;
  }
  function rangeStart(range, now) {
    if (range === "today") { var d = new Date(now); d.setHours(0, 0, 0, 0); return d.getTime(); }
    return now - (RANGE_MS[range] || RANGE_MS["7d"]);
  }
  function eachRoster(map, rosters, fn) {
    if (!map) return false;
    var any = false;
    rosters.forEach(function (r) {
      if (map[r] == null) return;
      any = true;
      fn(map[r], r);
    });
    return any;
  }
  function endWord(v) { return str(v).replace(/^tw_/, "").replace(/_/g, " "); }

  /* The platform's off-target rule (score.js kpiMiss), plus a failed run. */
  function numish(s) {
    var t = String(s || "").replace(/\*/g, "").trim();
    if (/^(not run|leftover|pass|stay|shipped|none|-)$/i.test(t)) return null;
    var m = t.match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  }
  function kpiMiss(last, target) {
    var L = String(last || "").toLowerCase();
    if (!L || /not run|leftover|shipped|stay|none/.test(L)) return false;
    if (/\bfail(ed)?\b|\bstarve\b|\bmiss\b|_failed$/.test(L)) return true;
    var T = String(target == null ? "" : target).trim();
    if (!T) return false;
    var ln = numish(last), tn = numish(target);
    if (ln == null || tn == null) return false;
    if (tn === 0) return ln !== 0;
    return ln < tn;
  }

  var KPI_LABELS = {
    "doing.task.dwell_active_ms": "Active time",
    "doing.task.dwell_idle_ms": "Idle time",
    "doing.task.dwell_waiting_ms": "Waiting time",
    "doing.task.last_run": "Last run",
    "doing.task.end_reason": "Last run ended",
    "doing.task.retry_give_up_n": "Give-ups",
    "doing.task.buffer_overflow_n": "Buffer overflows",
    "doing.task.wait_by_cause": "Wait by cause",
    "mill-office.wasted_wake_share": "Wasted wakes",
    "mill-office.wasted_wake_n": "Wasted wake count",
    "mill-office.activities": "Activities",
    "mill-desk.hint_drop": "Dropped hints",
    "mill-desk.idle_verbs": "Idle commands",
    "mill-wall.ticks": "Extra heartbeats",
    "mill-wall.api_ms": "Mill command time (p95, ms)",
    "system": "Commands",
    "wall": "Wall routes"
  };
  function kpiLabel(k) {
    k = str(k);
    if (KPI_LABELS[k]) return KPI_LABELS[k];
    var leaf = k.replace(/^[a-z-]+\./, "").replace(/^task\./, "");
    leaf = leaf.replace(/_/g, " ");
    return leaf.charAt(0).toUpperCase() + leaf.slice(1);
  }

  /* ---- scope + desks ---- */
  function normScope(scope, rosterNames) {
    scope = scope || {};
    var rosters = Array.isArray(scope.rosters) ? scope.rosters.filter(Boolean) : [];
    if (!rosters.length) rosters = ["Office"];
    if (Array.isArray(rosterNames) && rosterNames.length) {
      var ok = rosters.filter(function (r) { return rosterNames.indexOf(r) >= 0; });
      if (ok.length) rosters = ok;
    }
    /* only: the desks of the station picked on the Wall rail (null = every desk on the roster). */
    var only = null;
    if (Array.isArray(scope.only)) {
      only = {};
      scope.only.forEach(function (n) { if (str(n)) only[str(n)] = 1; });
    }
    return {
      rosters: rosters,
      only: only,
      label: str(scope.label) || rosters.join(" + "),
      range: RANGES.indexOf(scope.range) >= 0 ? scope.range : "7d"
    };
  }

  function deskRecord(owner, seats, view, st, ctx) {
    var seatLive = seats.some(function (a) { return a.alive !== false && a.stale !== true; });
    var vStale = !!view && (view.alive === false || view.stale === true);
    var connected = seats.length ? seatLive : !!(st && st.connected && !vStale);
    var doingText = view && !vStale ? str(view.doing) : "";
    var waitingOn = view ? (view.waiting_on || null) : null;
    if (!waitingOn) seats.forEach(function (a) { if (!waitingOn && str(a.waiting_on)) waitingOn = str(a.waiting_on); });
    var state = !connected ? "disconnected" : (doingText ? "working" : (waitingOn ? "waiting" : "idle"));
    var lc = st ? utc(st.last_connected) : null;
    /* A last-connected time in the future is not a reading; the seat heartbeat stands in. */
    if (lc != null && lc > ctx.now + 5 * MIN) lc = null;
    if (lc == null) seats.forEach(function (a) { var t = utc(a.heartbeat); if (t != null && t <= ctx.now + 5 * MIN && (lc == null || t > lc)) lc = t; });
    var ra = st && st.recent_activity ? st.recent_activity : null;
    var raAt = ra ? utc(ra.at) : null;
    if (raAt != null && raAt > ctx.now + 5 * MIN) raAt = null;
    var w = view && view.waiting_on_it ? view.waiting_on_it : null;
    var L = (w && w.letters) || {}, C = (w && w.cards) || {};
    var last = view && view.last ? view.last : null;
    return {
      name: owner,
      rosters: [],
      connected: connected,
      stale: vStale,
      state: state,
      doing: doingText,
      on: view && !vStale ? str(view.on) : "",
      age: view && !vStale && doingText ? str(view.age) : "",
      idle: view && !vStale && !doingText ? str(view.idle) : "",
      leftover: vStale ? str(view.doing) || (last ? str(last.doing) : "") : "",
      leftoverOn: vStale ? (str(view.on) || (last ? str(last.on) : "")) : "",
      last: last ? { doing: str(last.doing), on: str(last.on), ended: endWord(last.ended_by) } : null,
      waitingOn: waitingOn,
      wait: w ? {
        letters: num(L.n) || 0,
        overDay: has(L, "n_over_day") ? (num(L.n_over_day) || 0) : null,
        oldestAt: has(L, "oldest_at") && str(L.oldest_at) ? utc(L.oldest_at) : null,
        cards: num(C.n) || 0
      } : null,
      lastSeenAt: lc,
      recentAt: raAt != null ? raAt : lc,
      recent: ra ? { type: str(ra.type), thing: str(ra.thing) } : null
    };
  }

  function base(data, scope, now) {
    data = data || {};
    now = now == null ? Date.now() : now;
    var rosterNames = Array.isArray(data.rosterList) ? data.rosterList.map(function (r) { return str(r.name); }) : null;
    var sc = normScope(scope, rosterNames);
    var ctx = { now: now };
    var deleted = {};
    eachRoster(data.names, sc.rosters, function (rows) {
      (rows || []).forEach(function (n) { if (n && n.kind === "desk" && n.deleted) deleted[str(n.name)] = 1; });
    });
    var seats = {}, rostersOf = {}, order = [];
    var agentsKnown = eachRoster(data.agents, sc.rosters, function (rows, r) {
      (rows || []).forEach(function (a) {
        var o = str(a && a.owner);
        if (!o || deleted[o]) return;
        if (!seats[o]) { seats[o] = []; rostersOf[o] = []; order.push(o); }
        seats[o].push(a);
        if (rostersOf[o].indexOf(r) < 0) rostersOf[o].push(r);
      });
    });
    var byStation = {};
    (Array.isArray(data.stations) ? data.stations : []).forEach(function (s) {
      var n = str(s && s.name);
      if (n && !byStation[n]) byStation[n] = s;
    });
    var doing = data.doing || {};
    var start = rangeStart(sc.range, now);
    var all = [];
    order.forEach(function (o) {
      var d = deskRecord(o, seats[o], doing[o] || null, byStation[o] || null, ctx);
      d.rosters = rostersOf[o];
      /* In range: connected now, or last seen since the range start. Never seen: left out. */
      if (!d.connected && (d.lastSeenAt == null || d.lastSeenAt < start)) return;
      d.checked = !sc.only || !!sc.only[o];
      all.push(d);
    });
    var byName = {};
    all.forEach(function (d) { byName[d.name] = d; });
    var desks = all.filter(function (d) { return d.checked; });
    var b = {
      scope: sc, now: now, start: start, data: data,
      agentsKnown: agentsKnown,
      all: all, desks: desks, byName: byName,
      inScope: function (name) { var d = byName[str(name)]; return !!d && d.checked; },
      /* On the picked roster (any seat, any age) and at the picked station: the focused desks. */
      member: function (name) { var n = str(name); return !!seats[n] && !deleted[n] && (!sc.only || !!sc.only[n]); },
      offDesk: function (name) { return !!sc.only && !sc.only[str(name)]; },
      isDeleted: function (name) { return !!deleted[str(name)]; }
    };
    b.kpis = collectKpis(b);
    b.labels = collectLabels(b);
    b.cards = collectCards(b);
    b.letters = collectLetters(b);
    return b;
  }

  /* ---- shared collections ---- */
  function collectKpis(b) {
    var seen = {}, out = [];
    var known = eachRoster(b.data.scores, b.scope.rosters, function (rows, r) {
      (rows || []).forEach(function (k) {
        var id = k && k.id != null ? String(k.id) : null;
        var key = id || (str(k.kpi) + "|" + str(k.owner) + "|" + r);
        if (seen[key]) return;
        seen[key] = 1;
        out.push(Object.assign({ roster: str(k.roster_id) || r }, k));
      });
    });
    return known ? out : null;
  }
  function collectLabels(b) {
    var byDesk = {}, checks = [];
    var known = eachRoster(b.data.labels, b.scope.rosters, function (doc) {
      ((doc && doc.rows) || []).forEach(function (row) {
        if (!row || str(row.type) !== "todo") return;
        var desk = str(row.label);
        if (!desk) return;
        var list = byDesk[desk] || (byDesk[desk] = []);
        if (list.some(function (x) { return x.id === row.id; })) return;
        var card = row.card || {};
        list.push({
          id: row.id, ord: num(row.ord), need: str(card.need), status: str(card.status),
          volunteer: str(card.volunteer), roster: str(card.roster),
          lastActAt: utc(card.last_activity_at), lastActKind: str(card.last_activity_kind)
        });
      });
      (((doc && doc.checks) || {}).off_roster || []).forEach(function (c) { checks.push(c); });
    });
    if (!known) return null;
    Object.keys(byDesk).forEach(function (k) {
      byDesk[k].sort(function (a, c) { return (a.ord == null ? 1e9 : a.ord) - (c.ord == null ? 1e9 : c.ord) || a.id - c.id; });
      byDesk[k].forEach(function (x, i) { x.pos = i + 1; });
    });
    return { byDesk: byDesk, offRoster: checks };
  }
  function collectCards(b) {
    var seen = {}, out = [];
    var known = eachRoster(b.data.todos, b.scope.rosters, function (doc, r) {
      var rows = [].concat((doc && doc.needs) || [], (doc && doc.issues) || []);
      rows.forEach(function (c) {
        if (!c || c.id == null || seen[c.id]) return;
        seen[c.id] = 1;
        out.push({
          id: Number(c.id), roster: str(c.roster_id) || r, status: str(c.status) || "open",
          title: firstLine(c.detail, 110) || ("card " + c.id), detail: str(c.detail),
          trunc: !!c.detail_trunc, desk: str(c.assigned || c.volunteer), creator: str(c.creator)
        });
      });
    });
    if (!known) return null;
    var ix = {};
    out.forEach(function (c) { ix[c.id] = c; });
    out.byId = ix;
    return out;
  }
  function collectLetters(b) {
    var seen = {}, out = [];
    var known = eachRoster(b.data.mail, b.scope.rosters, function (rows) {
      (rows || []).forEach(function (m) {
        if (!m || m.id == null || seen[m.id]) return;
        seen[m.id] = 1;
        var tos = Array.isArray(m.mail_tos) ? m.mail_tos : (m.to || []).map(function (t) { return { deskId: t, receipt: null }; });
        out.push({
          id: Number(m.id), at: utc(m.created), from: str(m.from || (m.sender && m.sender.deskId)),
          tos: tos.map(function (t) { return { desk: str(t && (t.deskId || t.desk || t)), unread: t && t.receipt === 0 }; }),
          body: str(m.body), trunc: !!m.body_trunc, root: m.root_id != null ? Number(m.root_id) : Number(m.id),
          tree: str(m.tree), roster: str(m.sender && m.sender.roster)
        });
      });
    });
    if (!known) return null;
    out.sort(function (a, c) { return (a.at || 0) - (c.at || 0) || a.id - c.id; });
    var ix = {};
    out.forEach(function (m) { ix[m.id] = m; });
    out.byId = ix;
    return out;
  }
  function inRange(b, at) { return at != null && at >= b.start; }

  /* ---- scores per desk ---- */
  function deskScores(b, desk) {
    if (!b.kpis) return null;
    var out = { doing: {}, system: null, health: [], off: 0, any: false };
    b.kpis.forEach(function (k) {
      if (str(k.owner) !== desk) return;
      var name = str(k.kpi), v = str(k.value);
      if (v === "") return;
      out.any = true;
      var row = { kpi: name, label: kpiLabel(name), value: v, target: str(k.target), note: str(k.note), off: kpiMiss(v, k.target), id: k.id };
      if (name.indexOf("doing.task.") === 0) { if (!out.doing[name]) out.doing[name] = row; }
      else if (name === "system") { if (!out.system) out.system = row; }
      else if (/^mill-desk\.|^mill-wall\.ticks$/.test(name)) out.health.push(row);
      if (row.off) out.off++;
    });
    var lr = out.doing["doing.task.last_run"];
    out.lastRun = lr ? lr.value : "";
    out.lastRunOff = !!(lr && lr.off);
    var er = out.doing["doing.task.end_reason"];
    out.ended = er ? endWord(er.value) : "";
    return out;
  }
  function rosterScores(b, roster) {
    if (!b.kpis) return null;
    return b.kpis.filter(function (k) { return !str(k.owner) && k.roster === roster && str(k.value) !== ""; })
      .map(function (k) { return { kpi: str(k.kpi), label: kpiLabel(k.kpi), value: str(k.value), target: str(k.target), note: str(k.note), off: kpiMiss(k.value, k.target), id: k.id }; });
  }
  function prioList(b, desk) {
    if (!b.labels) return null;
    return (b.labels.byDesk[desk] || []).map(function (p) {
      var c = b.cards && b.cards.byId[p.id];
      return Object.assign({}, p, { title: c ? c.title : p.need.replace(/-/g, " "), cardStatus: c ? c.status : p.status });
    });
  }

  /* ---- DESKS ---- */
  var SORTS = ["urgency", "az", "za", "recent"];
  function byName(a, c) { return a.name.localeCompare(c.name); }
  function byRecent(a, c) {
    var ta = a.recentAt == null ? -Infinity : a.recentAt, tc = c.recentAt == null ? -Infinity : c.recentAt;
    return (tc - ta) || byName(a, c);
  }
  function urgency(a, c) {
    /* Most active first: working, waiting, idle, then the latest activity inside a state. */
    var ra = STATE_RANK[a.state], rc = STATE_RANK[c.state];
    if (ra !== rc) return (ra == null ? 9 : ra) - (rc == null ? 9 : rc);
    return byRecent(a, c);
  }
  function sortDesks(rows, sort, away) {
    var cmp = sort === "az" ? byName : sort === "za" ? function (a, c) { return byName(c, a); }
      : sort === "recent" ? byRecent
      : away ? function (a, c) { return ((c.lastSeenAt || 0) - (a.lastSeenAt || 0)) || byName(a, c); } : urgency;
    return rows.slice().sort(cmp);
  }
  function deskRow(b, d) {
    var r = Object.assign({}, d);
    var p = prioList(b, d.name);
    r.prios = p ? p.slice(0, 3) : null;
    r.scores = deskScores(b, d.name);
    r.rosterOff = null;
    d.rosters.forEach(function (ro) {
      (rosterScores(b, ro) || []).forEach(function (k) { if (k.off && !r.rosterOff) r.rosterOff = { roster: ro, label: k.label, value: k.value, target: k.target }; });
    });
    return r;
  }
  function desks(b, opts) {
    opts = opts || {};
    var sort = SORTS.indexOf(opts.sort) >= 0 ? opts.sort : "urgency";
    var rows = b.desks.map(function (d) { return deskRow(b, d); });
    var live = sortDesks(rows.filter(function (r) { return r.connected; }), sort, false);
    var away = sortDesks(rows.filter(function (r) { return !r.connected; }), sort, true);
    var selected = str(opts.selected);
    if (!rows.some(function (r) { return r.name === selected; })) selected = (live[0] || away[0] || {}).name || "";
    return {
      sort: sort, connected: live, away: away, selected: selected,
      known: b.agentsKnown,
      scoreOff: live.filter(function (r) { return r.scores && r.scores.off; }).length
    };
  }

  function deskDetail(b, name) {
    var d = b.byName[str(name)];
    if (!d) return null;
    var r = deskRow(b, d);
    var plist = prioList(b, d.name);
    var cur = itemOf(r.on);
    var card = null;
    if (cur && cur.kind === "todo" && b.cards) {
      var c = b.cards.byId[cur.id];
      var rank = plist ? plist.filter(function (p) { return p.id === cur.id; })[0] : null;
      card = { id: cur.key, title: c ? c.title : "", status: c ? c.status : "", rank: rank ? rank.pos : null, ord: rank ? rank.ord : null, known: !!c };
    }
    var chat = null;
    if (b.letters) {
      chat = b.letters.filter(function (m) { return m.from === d.name || m.tos.some(function (t) { return t.desk === d.name; }); })
        .slice().reverse();
    }
    var holds = collectHolds(b);
    var trail = Array.isArray((b.data.history || {})[d.name]) ? b.data.history[d.name] : null;
    var rost = d.rosters.map(function (ro) { return { roster: ro, rows: rosterScores(b, ro) }; })
      .filter(function (x) { return x.rows && x.rows.length; });
    var runs = deskRuns(b, d.name);
    return {
      desk: r,
      card: card, chat: chat, holds: holds ? holds.filter(function (h0) { return h0.desk === d.name; }) : null,
      trail: trail ? trail.slice(0, 6).map(function (t) {
        return { at: utc(t.at), doing: str(t.doing), on: str(t.on), ended: t.ended ? endWord(t.ended_by) : "", current: !t.ended };
      }) : null,
      rosterScores: rost, runs: runs
    };
  }
  function prioNote(p, desk) {
    var st = p.cardStatus || p.status;
    if (st === "claimed" && p.volunteer && p.volunteer !== desk) return "claimed by " + p.volunteer;
    if (st === "claimed") return "claimed, not the current doing";
    if (st === "open") return "ranked, not started";
    if (st === "parked") return "parked";
    if (st === "done" || st === "shipped") return st;
    return st;
  }
  function lastActivity(b, id) {
    if (!b.labels) return null;
    var t = null;
    Object.keys(b.labels.byDesk).forEach(function (k) {
      b.labels.byDesk[k].forEach(function (p) { if (p.id === id && p.lastActAt != null && (t == null || p.lastActAt > t)) t = p.lastActAt; });
    });
    return t;
  }
  function deskRuns(b, desk) {
    var rows = [];
    var known = eachRoster(b.data.runs, b.scope.rosters, function (list) {
      (list || []).forEach(function (x) { if (x && str(x.desk) === desk && x.dwell_active_ms != null && rows.every(function (y) { return y.id !== x.id; })) rows.push(x); });
    });
    if (!known) return null;
    rows.sort(function (a, c) { return a.id - c.id; });
    return rows.slice(-12).map(function (x) { return { ms: num(x.dwell_active_ms) || 0, phase: str(x.phase), ended: endWord(x.end_reason) }; });
  }

  /* ---- TODO: cards across the roster, grouped by what a person asks ---- */
  function todo(b, opts) {
    if (!b.cards) return null;
    var working = {};
    b.desks.forEach(function (d) { var it = itemOf(d.on); if (d.state === "working" && it && it.kind === "todo") working[it.id] = d; });
    var groups = { attention: [], doing: [], claimed: [], open: [], parked: [], done: [] };
    b.cards.forEach(function (c) {
      if (c.desk && b.offDesk(c.desk)) return;
      var ranks = [];
      if (b.labels) Object.keys(b.labels.byDesk).forEach(function (k) {
        b.labels.byDesk[k].forEach(function (p) { if (p.id === c.id) ranks.push({ desk: k, pos: p.pos, ord: p.ord }); });
      });
      var row = { id: c.id, title: c.title, desk: c.desk, status: c.status, ranks: ranks, flag: "", heat: "", when: "", note: "" };
      var holder = c.desk ? b.byName[c.desk] : null;
      var la = lastActivity(b, c.id);
      if (c.status === "done" || c.status === "shipped") { row.note = c.status; groups.done.push(row); return; }
      if (c.status === "parked") { row.note = "parked"; groups.parked.push(row); return; }
      if (working[c.id]) {
        var d = working[c.id];
        row.desk = row.desk || d.name;
        row.when = d.age;
        var s = deskScores(b, d.name);
        if (s && s.lastRunOff) { row.flag = "last run " + s.lastRun; row.heat = "older"; }
        groups.doing.push(row);
        return;
      }
      if (c.status === "claimed") {
        if (c.desk && (!holder || !holder.connected)) {
          row.flag = "holder away"; row.heat = "hot";
          row.when = holder && holder.lastSeenAt != null ? "seen " + ago(b.now - holder.lastSeenAt) : "not seen in range";
          row.sortKey = holder && holder.lastSeenAt != null ? holder.lastSeenAt : 0;
          groups.attention.push(row);
          return;
        }
        if (la != null && b.now - la > STUCK_MS) {
          row.flag = "no activity " + dur(b.now - la); row.heat = "older"; row.sortKey = la;
          groups.attention.push(row);
          return;
        }
        if (la != null) row.when = "last activity " + ago(b.now - la);
        else if (holder && holder.on !== "todo-" + c.id) row.note = "claimed, not the current doing";
        groups.claimed.push(row);
        return;
      }
      row.note = ranks.length ? "" : "not started";
      groups.open.push(row);
    });
    groups.attention.sort(function (a, c) { return (a.sortKey || 0) - (c.sortKey || 0) || a.id - c.id; });
    var rankKey = function (r) { return r.ranks.length ? Math.min.apply(null, r.ranks.map(function (x) { return x.pos; })) : 1e9; };
    groups.open.sort(function (a, c) { return rankKey(a) - rankKey(c) || c.id - a.id; });
    groups.claimed.sort(function (a, c) { return rankKey(a) - rankKey(c) || c.id - a.id; });
    groups.done.sort(function (a, c) { return c.id - a.id; });
    var list = [
      { key: "attention", label: "Needs attention", rows: groups.attention, hint: "claimed by an away desk, or no activity in 2 days" },
      { key: "doing", label: "Doing", rows: groups.doing, hint: "a connected desk is on it now" },
      { key: "claimed", label: "Claimed", rows: groups.claimed, hint: "someone has it" },
      { key: "open", label: "Open", rows: groups.open, hint: "up next, ranked first" }
    ];
    if (groups.parked.length) list.push({ key: "parked", label: "Parked", rows: groups.parked, hint: "set aside" });
    /* The card route sends no finish time, so this is every done card it sent, not "today". */
    list.push({ key: "done", label: "Done", rows: groups.done, hint: "done or shipped" });
    var open = b.cards.filter(function (c) { return !/^(done|shipped|parked)$/.test(c.status); }).length;
    var selected = pickSelected(list, opts && opts.selected, function (r) { return "todo-" + r.id; });
    return { groups: list, open: open, attention: groups.attention.length, selected: selected, detail: selected ? cardDetail(b, Number(selected.slice(5))) : null };
  }
  function pickSelected(groups, want, keyOf) {
    var first = "", ok = false;
    groups.forEach(function (g) {
      g.rows.forEach(function (r) { var k = keyOf(r); if (!first) first = k; if (k === want) ok = true; });
    });
    return ok ? want : first;
  }
  function cardDetail(b, id) {
    var c = b.cards && b.cards.byId[id];
    if (!c) return null;
    var ranks = [];
    if (b.labels) Object.keys(b.labels.byDesk).forEach(function (k) {
      b.labels.byDesk[k].forEach(function (p) { if (p.id === id) ranks.push({ desk: k, pos: p.pos, ord: p.ord }); });
    });
    var re = new RegExp("\\b(card|todo)[ -#]?" + id + "\\b", "i");
    var mentions = b.letters ? b.letters.filter(function (m) { return re.test(m.body); }).slice(-4).reverse() : null;
    var holder = c.desk ? b.byName[c.desk] : null;
    return { id: id, title: c.title, detail: c.detail, trunc: c.trunc, status: c.status, desk: c.desk, creator: c.creator,
      ranks: ranks, current: !!(holder && holder.on === "todo-" + id), lastAct: lastActivity(b, id), mentions: mentions };
  }

  /* ---- MAIL: who is waiting on whom, oldest first ---- */
  var MAIL_ROWS = 8;
  function mail(b, opts) {
    if (!b.letters) return null;
    var by = {};
    b.letters.forEach(function (m) {
      if (!inRange(b, m.at)) return;
      m.tos.forEach(function (t) {
        if (!t.unread || !t.desk || t.desk === "*" || b.offDesk(t.desk) || b.isDeleted(t.desk)) return;
        (by[t.desk] || (by[t.desk] = [])).push(m);
      });
    });
    var groups = Object.keys(by).map(function (desk) {
      var rows = by[desk];
      var d = b.byName[desk];
      return {
        key: desk, desk: desk, away: !!d && !d.connected, rows: rows.slice(0, MAIL_ROWS).map(function (m) { return letterRow(b, m, desk); }),
        n: rows.length, more: Math.max(0, rows.length - MAIL_ROWS), oldest: rows[0].at || 0,
        overDay: rows.filter(function (m) { return m.at != null && b.now - m.at > DAY; }).length
      };
    });
    groups.sort(function (a, c) { return (c.overDay ? 1 : 0) - (a.overDay ? 1 : 0) || a.oldest - c.oldest || a.desk.localeCompare(c.desk); });
    var waiting = groups.reduce(function (s, g) { return s + g.n; }, 0);
    var selected = pickSelected(groups, opts && opts.selected, function (r) { return r.key; });
    var sel = selected ? b.letters.byId[Number(selected.slice(5))] : null;
    var waitDesk = "";
    groups.forEach(function (g) { if (!waitDesk && g.rows.some(function (r) { return r.key === selected; })) waitDesk = g.desk; });
    return {
      groups: groups, waiting: waiting, overDay: groups.reduce(function (s, g) { return s + g.overDay; }, 0),
      selected: selected,
      detail: sel ? {
        letter: letterRow(b, sel, waitDesk), body: sel.body, trunc: sel.trunc, waitingOn: waitDesk,
        thread: b.letters.filter(function (m) { return m.root === sel.root; }).map(function (m) { return letterRow(b, m, ""); })
      } : null
    };
  }
  function letterRow(b, m, to) {
    var age = m.at != null ? b.now - m.at : null;
    return {
      key: "mail-" + m.id, id: m.id, from: m.from, to: to || (m.tos[0] ? m.tos[0].desk : ""), toN: m.tos.length,
      text: firstLine(m.body, 140) || "(no text)", at: m.at, when: dur(age),
      heat: age == null ? "" : age > DAY ? "older" : age > 4 * HOUR ? "hot" : ""
    };
  }

  /* ---- PRIORITIES: every desk's ranked list side by side ---- */
  function priorities(b, opts) {
    if (!b.labels) return null;
    var dm = desks(b, { sort: "urgency" });
    var cols = dm.connected.concat(dm.away).map(function (d) {
      var list = prioList(b, d.name) || [];
      return {
        key: d.name, desk: d.name, away: !d.connected,
        sub: d.connected ? String(list.length) : "away " + dur(d.lastSeenAt != null ? b.now - d.lastSeenAt : null),
        rows: list.map(function (p) {
          var current = d.on === "todo-" + p.id;
          var la = p.lastActAt != null ? b.now - p.lastActAt : null;
          return { key: d.name + "|" + p.id, id: p.id, pos: p.pos, ord: p.ord, title: p.title,
            note: current ? "current doing" : prioNote(p, d.name), when: current ? d.age : (la != null ? "active " + ago(la) : ""),
            current: current, stuck: !current && p.status === "claimed" && la != null && la > STUCK_MS };
        })
      };
    });
    var lists = cols.filter(function (c) { return c.rows.length; }).length;
    var selected = pickSelected(cols, opts && opts.selected, function (r) { return r.key; });
    var detail = null;
    if (selected) {
      var parts = selected.split("|"), desk = parts[0], id = Number(parts[1]);
      var p = (prioList(b, desk) || []).filter(function (x) { return x.id === id; })[0];
      if (p) {
        var cd = cardDetail(b, id);
        detail = { desk: desk, pos: p.pos, ord: p.ord, id: id, title: p.title, status: p.cardStatus || p.status, volunteer: p.volunteer,
          body: cd ? cd.detail : "", current: (b.byName[desk] || {}).on === "todo-" + id,
          offRoster: b.labels.offRoster.filter(function (c) { return str(c.label) === desk; }) };
      }
    }
    return { cols: cols, lists: lists, selected: selected, detail: detail };
  }

  /* ---- SCORE: platform scores by impact, desks as rows ---- */
  function score(b, opts) {
    if (!b.kpis) return null;
    var groups = {
      wakes: { key: "wakes", label: "Wakes", hint: "impact first", rows: [] },
      doing: { key: "doing", label: "Doing", hint: "desks as rows", rows: [] },
      health: { key: "health", label: "Quiet while sitting", hint: "desks as rows", rows: [] },
      system: { key: "system", label: "System", hint: "commands and routes", rows: [] },
      other: { key: "other", label: "Other scores", hint: "", rows: [] }
    };
    var deskSet = {};
    b.desks.forEach(function (d) { deskSet[d.name] = d; });
    var perDesk = {}, perHealth = {};
    b.kpis.forEach(function (k) {
      var owner = str(k.owner), name = str(k.kpi), v = str(k.value);
      if (v === "") return;
      if (owner && !deskSet[owner]) return;
      var row = { key: "score-" + k.id, kpi: name, label: kpiLabel(name), desk: owner, roster: owner ? "" : k.roster,
        value: v, target: str(k.target), note: str(k.note), off: kpiMiss(v, k.target), meta: [], ids: [k.id], updated: utc(k.updated) };
      if (/^mill-office\./.test(name) || /wake/.test(name)) { groups.wakes.rows.push(row); return; }
      if (owner && name.indexOf("doing.task.") === 0) {
        var pd = perDesk[owner] || (perDesk[owner] = {});
        pd[name] = row;
        return;
      }
      if (owner && (/^mill-desk\./.test(name) || name === "mill-wall.ticks")) { (perHealth[owner] || (perHealth[owner] = [])).push(row); return; }
      if (name === "system" || name === "wall" || /^mill-wall\./.test(name)) { groups.system.rows.push(row); return; }
      groups.other.rows.push(row);
    });
    /* One Doing row per desk: the last run, with how it ended and its dwell. */
    Object.keys(perDesk).forEach(function (desk) {
      var pd = perDesk[desk];
      var lr = pd["doing.task.last_run"], er = pd["doing.task.end_reason"];
      var act = pd["doing.task.dwell_active_ms"], idl = pd["doing.task.dwell_idle_ms"], wt = pd["doing.task.dwell_waiting_ms"];
      var lead = lr || er || act || idl || wt;
      var row = { key: "doing-" + desk, kpi: lead.kpi, label: lr ? "Last run" : lead.label, desk: desk, roster: "",
        value: lr ? lr.value : (lead === act || lead === idl || lead === wt ? msText(lead.value) : endWord(lead.value)), target: "",
        note: "", off: Object.keys(pd).some(function (k) { return pd[k].off; }), meta: [], ids: [], updated: lead.updated };
      Object.keys(pd).forEach(function (k) { row.ids.push(pd[k].ids[0]); });
      if (er && lr) row.meta.push("ended " + endWord(er.value));
      if (act) row.meta.push("active " + msText(act.value));
      if (idl) row.meta.push("idle " + msText(idl.value));
      if (wt) row.meta.push("waiting " + msText(wt.value));
      groups.doing.rows.push(row);
    });
    /* One row per desk for the sitting checks: each is a count with a target of 0. */
    Object.keys(perHealth).forEach(function (desk) {
      var list = perHealth[desk];
      var bad = list.filter(function (r) { return r.off; });
      var lead = bad[0] || list[0];
      groups.health.rows.push({ key: "health-" + desk, kpi: lead.kpi, label: bad.length ? lead.label : "Quiet while sitting", desk: desk, roster: "",
        value: bad.length ? lead.value : String(list.length - bad.length) + " of " + list.length, target: bad.length ? lead.target : "",
        note: list.map(function (r) { return r.label + ": " + r.note; }).join(" "), off: bad.length > 0,
        meta: list.map(function (r) { return r.label.toLowerCase() + " " + r.value + (r.target ? " / " + r.target : ""); }),
        ids: list.map(function (r) { return r.ids[0]; }), updated: lead.updated, okText: bad.length ? "" : "on target" });
    });
    var order = ["wakes", "doing", "health", "system", "other"];
    var list = order.map(function (k) { return groups[k]; }).filter(function (g) { return g.rows.length; });
    list.forEach(function (g) {
      g.rows.sort(function (a, c) { return (c.off ? 1 : 0) - (a.off ? 1 : 0) || (a.desk || "~").localeCompare(c.desk || "~") || a.label.localeCompare(c.label); });
      g.off = g.rows.filter(function (r) { return r.off; }).length;
    });
    var off = list.reduce(function (s, g) { return s + g.off; }, 0);
    var selected = pickSelected(list, opts && opts.selected, function (r) { return r.key; });
    var sel = null;
    list.forEach(function (g) { g.rows.forEach(function (r) { if (r.key === selected) sel = Object.assign({ group: g.label }, r); }); });
    if (sel && sel.desk && /^doing-/.test(sel.key)) sel.runs = deskRuns(b, sel.desk);
    return { groups: list, off: off, selected: selected, detail: sel };
  }

  /* ---- COLLAB: what blocks someone now, then holds, rooms, trees ---- */
  function collectHolds(b) {
    var seen = {}, out = [];
    var known = eachRoster(b.data.holds, b.scope.rosters, function (rows) {
      (rows || []).forEach(function (l) {
        if (!l || seen[l.id]) return;
        seen[l.id] = 1;
        out.push({ id: l.id, resource: str(l.resource), desk: str(l.owner), dead: !!l.holder_dead, roster: str(l.roster_id) });
      });
    });
    return known ? out : null;
  }
  function collab(b, opts) {
    var holds = collectHolds(b);
    var blocking = [];
    b.desks.forEach(function (d) {
      var w = d.waitingOn;
      if (!w || !d.connected) return;
      var on = typeof w === "string" ? w : str(w.on);
      var why = typeof w === "string" ? "" : str(w.why);
      var onName = on.replace(/^desk-/, "");
      blocking.push({ key: "wait-" + d.name, kind: "wait", desk: d.name, title: d.name + " is waiting on " + onName, note: why,
        on: /^desk-/.test(on) ? party(b, onName) : { t: "text", v: onName }, me: party(b, d.name), since: null });
    });
    /* Letters nobody has opened: oldest first. */
    b.desks.forEach(function (d) {
      if (!d.wait || !d.wait.letters) return;
      blocking.push({ key: "unread-" + d.name, kind: "unread", desk: d.name, title: plural(d.wait.letters, "letter") + " waiting on " + d.name,
        note: d.wait.oldestAt != null ? "oldest " + dur(b.now - d.wait.oldestAt) : "", since: d.wait.oldestAt });
    });
    blocking.forEach(function (r) { if (!r.me) r.me = party(b, r.desk) || { t: "text", v: r.desk }; });
    blocking.sort(function (x, y) { return (x.since == null ? 1 : 0) - (y.since == null ? 1 : 0) || (x.since || 0) - (y.since || 0); });
    var held = [];
    (holds || []).forEach(function (l) {
      if (b.offDesk(l.desk)) return;
      var d = b.byName[l.desk];
      var row = { key: "hold-" + l.id, kind: "hold", desk: l.desk, title: l.resource, id: l.id, note: "" };
      if (l.dead || !d || !d.connected) {
        row.note = l.dead ? "the holder is gone" : (d && d.lastSeenAt != null ? "away, seen " + ago(b.now - d.lastSeenAt) : "not seen in range");
        blocking.push(Object.assign({}, row, { title: l.resource, kind: "hold", me: party(b, l.desk) || { t: "text", v: l.desk }, since: null }));
        return;
      }
      held.push(row);
    });
    var rooms = null;
    var roomsKnown = eachRoster(b.data.rooms, b.scope.rosters, function () {});
    if (roomsKnown && b.letters) {
      var named = {};
      eachRoster(b.data.rooms, b.scope.rosters, function (trees) {
        (trees || []).forEach(function (t) { if (t && !t.hidden && t.name) named[t.name] = t; });
      });
      var act = {};
      b.letters.forEach(function (m) {
        if (!m.tree || !named[m.tree] || !inRange(b, m.at)) return;
        var a = act[m.tree] || (act[m.tree] = { key: "room-" + m.tree, name: m.tree, n: 0, last: 0, who: [] });
        a.n++;
        if ((m.at || 0) > a.last) a.last = m.at || 0;
        [m.from].concat(m.tos.map(function (t) { return t.desk; })).forEach(function (w) { if (w && w !== "*" && a.who.indexOf(w) < 0) a.who.push(w); });
      });
      rooms = Object.keys(act).map(function (k) { return act[k]; }).sort(function (a, c) { return c.last - a.last; })
        .map(function (a) { return Object.assign(a, { when: ago(b.now - a.last) }); });
    }
    var trees = null;
    var treesKnown = eachRoster(b.data.trees, b.scope.rosters, function () {});
    if (treesKnown) {
      trees = [];
      eachRoster(b.data.trees, b.scope.rosters, function (list) {
        (list || []).forEach(function (t) {
          if (!t || t.hidden || trees.some(function (x) { return x.name === t.name; })) return;
          var nodes = Array.isArray(t.nodes) ? t.nodes : [];
          var root = nodes[0] || {};
          trees.push({ key: "tree-" + t.name, name: t.name, title: str(root.title), who: str(root.who), n: root.rgt && root.lft ? Math.round((root.rgt - root.lft + 1) / 2) : nodes.length });
        });
      });
    }
    var groups = [
      { key: "blocking", label: "Blocking someone now", rows: blocking, hint: "waits and promises held by away desks" },
      { key: "holds", label: "Promises held now", rows: holds ? held : null, hint: "who holds which file or branch" },
      { key: "rooms", label: "Active rooms", rows: rooms, hint: "rooms with letters in range" },
      { key: "trees", label: "Card trees", rows: trees, hint: "cards placed under other cards" }
    ].filter(function (g) { return g.rows != null; });
    var shared = (holds ? holds.length : 0) + (rooms ? rooms.length : 0);
    var selected = pickSelected(groups, opts && opts.selected, function (r) { return r.key; });
    var sel = null;
    groups.forEach(function (g) { g.rows.forEach(function (r) { if (r.key === selected) sel = Object.assign({ group: g.label }, r); }); });
    if (sel && sel.name && b.letters) {
      sel.letters = b.letters.filter(function (m) { return m.tree === sel.name; }).slice(-5).reverse().map(function (m) { return letterRow(b, m, ""); });
    }
    return { groups: groups, shared: holds || rooms ? shared : null, blocking: blocking.length, selected: selected, detail: sel };
  }

  /* ---- office activity feed (DESKS, very wide screens) ---- */
  function feed(b, limit) {
    var seen = {}, rows = [];
    var known = eachRoster(b.data.events, b.scope.rosters, function (list) {
      (list || []).forEach(function (e) {
        var k = e.kind + ":" + e.id;
        if (!e || seen[k]) return;
        seen[k] = 1;
        rows.push(e);
      });
    });
    if (!known) return null;
    rows.sort(function (a, c) { return (utc(c.at) || 0) - (utc(a.at) || 0); });
    var out = [];
    rows.forEach(function (e) {
      if (out.length >= (limit || 14)) return;
      var who = str(e.owner);
      if (who !== "System" && !b.inScope(who)) return;
      var kind = str(e.kind), text = "";
      if (kind === "mail") {
        var m = b.letters && b.letters.byId[e.id];
        if (!m) return;
        text = "sent mail-" + m.id + (m.tos[0] ? " to " + m.tos.map(function (t) { return t.desk; }).slice(0, 3).join(", ") : "") + ": " + firstLine(m.body, 90);
      } else if (kind === "doing") {
        var d = b.byName[who];
        if (!d || !d.doing || out.some(function (x) { return x.kind === "doing" && x.who === who; })) return;
        text = d.doing;
      } else if (kind === "score") {
        var k = b.kpis && b.kpis.filter(function (x) { return x.id === e.id; })[0];
        if (!k || !kpiMiss(k.value, k.target)) return;
        text = kpiLabel(k.kpi) + " " + (/end_reason$/.test(str(k.kpi)) ? endWord(k.value) : str(k.value)) + (str(k.target) ? " / " + str(k.target) : "") + ", off target";
      } else if (kind === "hold" || kind === "todo") {
        text = kind === "hold" ? "promise hold-" + e.id : "card todo-" + e.id + (e.state ? " " + str(e.state) : "");
      } else return;
      out.push({ at: utc(e.at), who: who, kind: kind, text: text });
    });
    return out;
  }

  /* ---- COLLAB replay: the desks' recorded activity, played back ----
   * One stream from the activity table (GET /api/v1/events: each item's latest move), the
   * letters (mailbox), and the move rows that rebuild a card or a promise (doing history
   * on=ITEM: create, claim, ship, done, back, hold, drop ...) plus each focused desk's own
   * focus rows (doing history desk=D). A move row stands for the activity row of the same
   * item, so nothing shows twice. A row shows when one of its desks is on the picked roster
   * or station; a desk off it is drawn as "outside". Windows roll back from now. */
  /* The window is a row count: the N most recent rows, or the N rows ending where the
   * viewport was dragged to. */
  var REPLAY_COUNTS = [100, 300, 1000], REPLAY_COUNT_DEFAULT = 300;
  /* A window never spans less than this, so a burst of rows still has room to move. */
  var REPLAY_MIN_SPAN = 60000;
  /* How far back the move rows of cards and promises are read for the replay. */
  var REPLAY_FETCH_MS = 7 * DAY;
  /* The six kinds the activity table records; each has its own icon. */
  var REPLAY_KINDS = ["mail", "todo", "hold", "wake", "doing", "score"];
  /* Every window plays back in this long at 1x, whatever time its rows span. */
  var REPLAY_PLAY_MS = 120000;
  var REPLAY_SPEEDS = [0.25, 0.5, 1, 2, 4];
  var CARD_WORD = { none: "", open: "OPEN", parked: "PARKED", claimed: "CLAIMED", shipped: "SHIPPED", done: "DONE", removed: "REMOVED" };
  var CARD_ACT = {
    create: "filed", park: "filed parked", claim: "claimed", unclaim: "let go of", assign: "assigned", unpark: "reopened",
    ship: "shipped", done: "closed", back: "sent back", note: "updated", rename: "renamed",
    retire: "retired", remove: "removed", reclaim: "brought back"
  };
  function foldCard(s, vol, act, desk) {
    var prev = vol;
    switch (act) {
      case "create": return { s: "open", vol: null, peer: null };
      case "park": return { s: "parked", vol: vol, peer: null };
      case "claim": return { s: "claimed", vol: desk, peer: prev && prev !== desk ? prev : null };
      case "assign": return { s: "claimed", vol: vol, peer: null };
      case "unclaim": return { s: "open", vol: null, peer: prev && prev !== desk ? prev : null };
      case "unpark": return { s: "open", vol: vol, peer: null };
      case "ship": return { s: "shipped", vol: vol, peer: null };
      case "done": return { s: "done", vol: vol, peer: null };
      case "back": return { s: s === "done" ? "shipped" : (vol ? "claimed" : "open"), vol: vol, peer: null };
      case "retire": case "remove": return { s: "removed", vol: vol, peer: null };
      case "reclaim": return { s: "open", vol: vol, peer: null };
      default: return { s: s, vol: vol, peer: null };
    }
  }
  function replayEvents(b) {
    var d = b.data || {}, out = [], have = {};
    var cards = b.cards ? b.cards.byId : {};
    var holdName = {}, kpiById = {}, holders = {}, holderNow = {};
    (b.kpis || []).forEach(function (k) { if (k && k.id != null) kpiById[k.id] = k; });
    eachRoster(d.holds, b.scope.rosters, function (rows) { (rows || []).forEach(function (l) { if (l && l.id != null) { holdName[l.id] = str(l.resource); holderNow["hold-" + l.id] = str(l.owner); } }); });
    function push(e) { if (e.at != null) out.push(e); }
    /* Letters: sender to every recipient. */
    (b.letters || []).forEach(function (m) {
      var tos = m.tos.map(function (t) { return t.desk; }).filter(Boolean);
      have["mail-" + m.id] = 1;
      push({ key: "mail-" + m.id, item: "mail-" + m.id, at: m.at, kind: "mail", act: m.root !== m.id ? "reply" : "send",
        actor: m.from, peers: tos, text: firstLine(m.body, 120) || "(no text)",
        read: m.tos.filter(function (t) { return t.unread === false; }).map(function (t) { return t.desk; }) });
    });
    /* Moves: each item's rows in order rebuild it, so the from and to are the platform's own fold. */
    var moves = d.moves || {};
    Object.keys(moves).forEach(function (key) {
      var it = itemOf(key);
      if (!it || !Array.isArray(moves[key])) return;
      var rows = moves[key].filter(function (r) { return r && str(r.act) && str(r.act) !== "focus" && str(r.act) !== "clear"; })
        .slice().sort(function (x, y) { return (utc(x.at) || 0) - (utc(y.at) || 0) || Number(x.id) - Number(y.id); });
      if (!rows.length) return;
      have[key] = 1;
      var s = "none", vol = null;
      var card = it.kind === "todo" ? cards[it.id] : null;
      rows.forEach(function (r) {
        var act = str(r.act), desk = str(r.desk), at = utc(r.at);
        if (it.kind === "todo") {
          var f = foldCard(s, vol, act, desk);
          /* The move row's second desk (doing.peer_id) when the server sends it; else the fold's. */
          var peers = [], sent = str(r.peer || r.peer_desk);
          if (sent && sent !== desk) peers.push(sent);
          else if (f.peer) peers.push(f.peer);
          /* Links come only from the transition rows: the row's own second desk, or the
           * volunteer the earlier rows of this card leave behind. Not from the card's current
           * creator or assignee, which may not be who it was then. */
          push({ key: "move-" + r.id, item: key, at: at, kind: "todo", act: act, actor: desk, peers: peers, roster: str(r.roster),
            vol: f.vol || "", prevVol: vol || "", rowPeer: sent && sent !== desk ? sent : "", dir: act === "claim" ? "in" : "out",
            text: card ? card.title : "", from: s !== f.s ? CARD_WORD[s] : "", to: s !== f.s ? CARD_WORD[f.s] : "" });
          s = f.s; vol = f.vol;
        } else if (it.kind === "hold") {
          var contest = act === "wait" || act === "refuse" || act === "contest";
          var holder = (holders[key] || []).filter(function (x) { return x.at <= at; }).pop();
          var before = (holders[key] || []).filter(function (x) { return x.at < at; });
          var lastTaker = before.filter(function (x) { return x.desk; }).pop();
          push({ key: "move-" + r.id, item: key, at: at, kind: "hold", act: contest ? "wait" : act, actor: desk, roster: str(r.roster),
            prevHolder: act === "hold" && lastTaker && lastTaker.desk !== desk ? lastTaker.desk : "",
            peers: contest && holder && holder.desk && holder.desk !== desk ? [holder.desk] : [], text: holdName[it.id] || "" });
          if (act === "hold") (holders[key] = holders[key] || []).push({ at: at, desk: desk });
          if (act === "drop") (holders[key] = holders[key] || []).push({ at: at, desk: "" });
        }
      });
    });
    /* Each focused desk's own focus rows: what it set out to do, and who it waits on. */
    var trail = d.trail || {};
    Object.keys(trail).forEach(function (desk) {
      have["doing-" + desk] = 1;
      (trail[desk] || []).forEach(function (r) {
        if (!r || str(r.act || "focus") !== "focus" || !str(r.doing)) return;
        var w = r.waiting_on && str(r.waiting_on.on), wd = /^desk-/.test(w || "") ? w.replace(/^desk-/, "") : "";
        /* Waiting on a promise another desk holds: the resource is contested. */
        var wh = itemOf(w);
        if (wh && wh.kind === "hold") {
          var at0 = utc(r.at), held = (holders[wh.key] || []).filter(function (x) { return x.at <= at0; }).pop();
          /* The holder from the promise's own take rows; the holds table of now only while
           * this wait row is still open, so it is the holder being waited on. */
          var open = !r.ended && !str(r.ended_at);
          var by = held ? held.desk : open ? holderNow[wh.key] : "";
          push({ key: "focus-" + r.id, item: wh.key, at: at0, kind: "hold", act: "wait", actor: str(r.desk) || desk, roster: str(r.roster),
            peers: by && by !== (str(r.desk) || desk) ? [by] : [], text: holdName[wh.id] || "" });
          return;
        }
        push({ key: "focus-" + r.id, item: str(r.on), at: utc(r.at), kind: "doing", act: wd ? "wait" : "focus", actor: str(r.desk) || desk, roster: str(r.roster),
          peers: wd ? [wd] : [], text: wd ? (str(r.waiting_on.why) || firstLine(r.doing, 120)) : firstLine(r.doing, 120),
          ended: !!(r.ended || r.ended_by || r.ended_at), endedBy: str(r.ended_by), endedAt: utc(r.ended_at) });
      });
    });
    /* The activity table: each item's latest move, where no letter or move row above has it. */
    var seen = {};
    eachRoster(d.events, b.scope.rosters, function (list) {
      (list || []).forEach(function (e) {
        if (!e) return;
        var kind = str(e.kind || e.type), key = kind + "-" + e.id;
        if (seen[key]) return;
        seen[key] = 1;
        if (REPLAY_KINDS.indexOf(kind) < 0) return;
        if (have[key] || (kind === "doing" && have["doing-" + str(e.owner)])) return;
        var card = kind === "todo" ? cards[e.id] : null;
        var kpi = kind === "score" ? kpiById[e.id] : null;
        /* A wake row names no desk (the office sends it); it belongs to its roster. */
        var office = kind === "wake" || !str(e.owner) || str(e.owner) === "System";
        if (office && b.scope.rosters.indexOf(str(e.roster_id)) < 0 && str(e.roster_id)) return;
        push({ key: "act-" + key, item: kind === "doing" || kind === "wake" || kind === "score" ? "" : key, at: utc(e.at), kind: kind, act: str(e.act) || "touch", roster: str(e.roster_id),
          actor: office ? "" : str(e.owner), office: office, peers: [], n: num(e.items),
          kpi: kpi ? { label: kpiLabel(kpi.kpi), value: scoreText(str(kpi.kpi), str(kpi.value)), target: str(kpi.target), off: kpiMiss(kpi.value, kpi.target) } : null,
          text: kind === "todo" ? (card ? card.title : "") : kind === "hold" ? (holdName[e.id] || "") : "", deleted: str(e.state) === "deleted",
          to: card && CARD_WORD[card.status] ? CARD_WORD[card.status] : "" });
      });
    });
    var mine = out.filter(function (e) {
      return e.office || b.member(e.actor) || e.peers.some(function (p) { return b.member(p); });
    });
    mine.sort(function (x, y) { return x.at - y.at || (x.key < y.key ? -1 : 1); });
    return mine;
  }
  /* One row as parts of a plain sentence. A desk off the focused set is a cloud: "outside". */
  /* The person at the office: the human mailbox names the Wall already knows. */
  var HUMAN_NAMES = { human: 1, "setter-upper": 1 };
  function party(b, name) {
    var n = str(name);
    if (!n) return null;
    if (HUMAN_NAMES[n.toLowerCase()]) return { t: "human", name: n };
    if (b.member(n)) { var d = b.byName[n]; return { t: "desk", name: n, state: d ? d.state : "disconnected" }; }
    if (n === "*" ) return { t: "text", v: "everyone" };
    var rosters = Array.isArray(b.data.rosterList) ? b.data.rosterList.map(function (r) { return str(r.name); }) : [];
    if (rosters.indexOf(n) >= 0 || b.scope.rosters.indexOf(n) >= 0) return { t: "text", v: "everyone on " + n };
    return { t: "cloud", name: n };
  }
  function peerParts(b, peers) {
    var parts = [], clouds = [];
    peers.forEach(function (p) {
      var x = party(b, p);
      if (!x) return;
      if (x.t === "cloud") { clouds.push(x.name); return; }
      if (parts.length) parts.push({ t: "text", v: "," });
      x.role = "peer";
      parts.push(x);
    });
    if (clouds.length) {
      if (parts.length) parts.push({ t: "text", v: "and" });
      parts.push({ t: "cloud", names: clouds, role: "peer" });
    }
    return parts;
  }
  function sentence(b, e) {
    var who = e.office ? { t: "text", v: "the office" } : (party(b, e.actor) || { t: "text", v: "someone" });
    if (who.t === "cloud") who = { t: "cloud", names: [who.name] };
    who.role = "actor";
    var p = [who], it = itemOf(e.item);
    var ref = it ? (it.kind === "todo" ? "card " + it.id : it.kind === "hold" ? "promise " + it.id : "letter " + it.id) : "";
    if (e.kind === "mail") {
      p.push({ t: "text", v: e.act === "reply" ? "replied to" : "mailed" });
      p = p.concat(peerParts(b, e.peers));
      p.push({ t: "quote", v: e.text });
    } else if (e.kind === "todo") {
      p.push({ t: "text", v: CARD_ACT[e.act] || "touched" }, { t: "item", key: e.item, v: ref });
      if (e.peers.length) {
        p.push({ t: "text", v: e.act === "claim" || e.act === "unclaim" ? "from" : e.act === "assign" ? "to" : "for" });
        p = p.concat(peerParts(b, e.peers));
      }
      if (e.to) p.push({ t: "move", from: e.from || "", to: e.to });
      if (e.text) p.push({ t: "quote", v: e.text });
    } else if (e.kind === "hold") {
      if (e.act === "wait") {
        p.push({ t: "text", v: "is waiting for" }, { t: "item", key: e.item, v: e.text || ref });
        if (e.peers.length) { p.push({ t: "text", v: "held by" }); p = p.concat(peerParts(b, e.peers)); }
      } else p.push({ t: "text", v: e.act === "drop" ? "released" : e.act === "hold" ? "took" : "touched" }, { t: "item", key: e.item, v: e.text || ref });
    } else if (e.kind === "wake") {
      p.push({ t: "text", v: e.n > 1 ? "sent " + e.n + " wakes" : "sent a wake" });
    } else if (e.kind === "score") {
      if (e.kpi) p.push({ t: "text", v: "score" }, { t: "quote", v: e.kpi.label }, { t: "text", v: "now " + e.kpi.value + (e.kpi.target ? " / " + e.kpi.target : "") }, { t: "score", off: e.kpi.off });
      else p.push({ t: "text", v: e.office ? "wrote an office score" : "wrote a score" });
    } else if (e.kind === "doing") {
      if (e.act === "wait") { p.push({ t: "text", v: "is waiting on" }); p = p.concat(peerParts(b, e.peers)); }
      else p.push({ t: "text", v: e.text || it ? "started" : "changed what it is on" });
      if (it) p.push({ t: "item", key: e.item, v: ref });
      if (e.text) p.push({ t: "quote", v: e.text });
    }
    if (e.deleted) p.push({ t: "flag", v: "deleted" });
    return p;
  }
  /* ---- Tags: each activity's labels, trees, watchers and roster ----
   * Joined client-side: the activity and transition rows carry none of the first three, so an
   * item key (todo-N, mail-N) is looked up in the labels rows (type + id -> label), in the card
   * trees and mail rooms (a node of that type and id -> its tree, depth and root title), and in
   * the watchers lists the doing feed carries for cards. Roster: the item's own roster (card,
   * letter, promise), else the activity or transition row's. Nothing is guessed: an item the
   * data does not tag shows no chip for it. */
  function itemTags(b) {
    if (b._tags) return b._tags;
    var out = {}, roots = {};
    function at(key) { return out[key] || (out[key] = { labels: [], trees: [], watchers: [], roster: "" }); }
    function each(map, fn) { Object.keys(map || {}).forEach(function (r) { if (map[r] != null) fn(map[r], r); }); }
    each(b.data.labels, function (doc) {
      ((doc && doc.rows) || []).forEach(function (r) {
        var t = str(r.type), name = str(r.label);
        if (!name || (t !== "todo" && t !== "mail") || r.id == null) return;
        var L = at(t + "-" + r.id).labels;
        if (L.every(function (x) { return x.name !== name; })) L.push({ name: name, ord: r.ord != null ? Number(r.ord) : null });
      });
    });
    function trees(map, kind) {
      each(map, function (list) {
        (list || []).forEach(function (tr) {
          if (!tr || !str(tr.name)) return;
          var nodes = tr.nodes || [], root = nodes.filter(function (n) { return n && Number(n.depth) === 0; })[0] || nodes[0] || {};
          roots[str(tr.name)] = { title: str(root.title), key: root.type && root.id != null ? str(root.type) + "-" + root.id : "", hidden: !!tr.hidden };
          nodes.forEach(function (n) {
            var t = str(n && n.type);
            if (!n || n.id == null || (t !== "todo" && t !== "mail")) return;
            var T = at(t + "-" + n.id).trees;
            if (T.some(function (x) { return x.name === tr.name; })) return;
            T.push({ name: str(tr.name), kind: kind, depth: n.depth != null ? Number(n.depth) : null, root: str(root.title), rootKey: root.type && root.id != null ? str(root.type) + "-" + root.id : "", hidden: !!tr.hidden });
          });
        });
      });
    }
    trees(b.data.trees, "tree");
    trees(b.data.rooms, "room");
    /* A letter names its own room (the rooms list carries only each room's root node). */
    (b.letters || []).forEach(function (m) {
      if (!m.tree) return;
      var T = at("mail-" + m.id).trees, r = roots[m.tree] || {};
      if (T.every(function (x) { return x.name !== m.tree; })) T.push({ name: m.tree, kind: "room", depth: m.root === m.id ? 0 : null, root: r.title || "", rootKey: r.key || "mail-" + m.root, hidden: !!r.hidden });
    });
    each(b.data.todos, function (doc, r) { ((doc && doc.needs) || []).forEach(function (n) { if (n && n.id != null) at("todo-" + n.id).roster = str(n.roster_id) || r; }); });
    each(b.data.holds, function (list, r) { (list || []).forEach(function (l) { if (l && l.id != null) at("hold-" + l.id).roster = str(l.roster_id) || r; }); });
    (b.letters || []).forEach(function (m) { if (m.roster) at("mail-" + m.id).roster = m.roster; });
    /* Watchers: the doing feed lists them on the cards it carries ({ id: "todo-N", watchers }). */
    (function walk(x, depth) {
      if (!x || typeof x !== "object" || depth > 6) return;
      if (Array.isArray(x)) { x.forEach(function (y) { walk(y, depth + 1); }); return; }
      if (Array.isArray(x.watchers) && itemOf(x.id)) {
        var W = at(itemOf(x.id).key).watchers;
        x.watchers.forEach(function (w) { w = str(w); if (w && W.indexOf(w) < 0) W.push(w); });
        if (x.roster && !at(itemOf(x.id).key).roster) at(itemOf(x.id).key).roster = str(x.roster);
      }
      Object.keys(x).forEach(function (k) { if (x[k] && typeof x[k] === "object") walk(x[k], depth + 1); });
    })(b.data.doing, 0);
    b._tags = out;
    return out;
  }
  function tagsOf(b, item, roster) {
    var t = itemTags(b)[str(item)];
    var o = { labels: t ? t.labels : [], trees: t ? t.trees : [], watchers: t ? t.watchers : [], roster: (t && t.roster) || str(roster) };
    return o.labels.length || o.trees.length || o.watchers.length || o.roster ? o : null;
  }
  /* ---- Direction: the one axis config both subtabs read ----
   * "lr": time and motion run left to right (desk pills in a column on the left, items fly
   * right; activity lanes as rows). "tb": top to bottom (pills in a row on top, items fall;
   * lanes as columns). Both subtabs start left to right; each keeps its own choice. */
  var REPLAY_DIR_DEFAULT = { desks: "lr", activity: "lr" };
  function replayAxis(dir) {
    return dir === "tb" ? { dir: "tb", main: "y", cross: "x", size: "height", crossSize: "width", start: "top", crossStart: "left", client: "clientY", crossClient: "clientX" }
      : { dir: "lr", main: "x", cross: "y", size: "width", crossSize: "height", start: "left", crossStart: "top", client: "clientX", crossClient: "clientY" };
  }
  function replayCount(n) { return REPLAY_COUNTS.indexOf(Number(n)) >= 0 ? Number(n) : REPLAY_COUNT_DEFAULT; }
  function collabReplay(b, opts) {
    opts = opts || {};
    var all = replayEvents(b).filter(function (e) { return e.at != null; }).sort(function (x, y) { return x.at - y.at || (x.key < y.key ? -1 : x.key > y.key ? 1 : 0); });
    var count = replayCount(opts.count);
    /* The window ends now, or at opts.end when the viewport was dragged back into the history. */
    var live = opts.end == null || opts.end >= b.now, end = live ? b.now : opts.end;
    var upto = all.filter(function (e) { return e.at <= (live ? end + MIN : end); });
    var win = upto.slice(-count);
    /* The window spans from its oldest row to its end (at least REPLAY_MIN_SPAN). That span is
     * also the age axis: an item travels from its desk to the far edge over one span. */
    var span = Math.max(REPLAY_MIN_SPAN, end - (win.length ? win[0].at : end)), since = end - span;
    var pick = pickIndex(b);
    /* The pool: every row that can be on screen for a playhead inside the window. */
    var pool = upto.filter(function (e) { return e.at >= since - span; }).map(function (e) {
      return { key: e.key, item: e.item, at: e.at, kind: e.kind, act: e.act, actor: e.actor, dir: e.dir || "out", parts: sentence(b, e),
        outside: e.peers.concat([e.actor]).some(function (n) { var x = party(b, n); return x && x.t === "cloud"; }), read: e.read || null,
        lane: e.office || !e.actor ? "@office" : laneOf(b, e.actor), flows: flowsOf(b, e, pick), text: e.text || "",
        tags: tagsOf(b, e.item, e.roster), state: stateDesks(e),
        ended: e.ended || false, endedBy: e.endedBy || "", endedAt: e.endedAt != null ? e.endedAt : null };
    }).map(function (r) {
      var st = r.state, ls = [r.lane];
      st.holders.concat(st.from, st.waiting).forEach(function (d) { var l = laneOf(b, d); if (ls.indexOf(l) < 0) ls.push(l); });
      r.flows.forEach(function (f) { [f.from, f.to].forEach(function (l) { if (ls.indexOf(l) < 0) ls.push(l); }); });
      r.stateLanes = ls;
      return r;
    });
    var rows = pool.filter(function (r) { return r.at >= since; });
    var lanes = replayLanes(b, pool);
    var known = !!(b.letters || b.data.events);
    /* Each desk's focus rows, oldest first: its state changes, to recolor its pill as the playhead moves. */
    var states = {};
    Object.keys(b.data.trail || {}).forEach(function (desk) {
      states[desk] = (b.data.trail[desk] || []).filter(function (r) { return r && str(r.act || "focus") === "focus"; }).map(function (r) {
        var w = r.waiting_on && str(r.waiting_on.on);
        return { at: utc(r.at), state: w ? "waiting" : "working", by: str(r.ended_by), end: utc(r.ended_at) };
      }).filter(function (x) { return x.at != null; }).sort(function (x, y) { return x.at - y.at; });
    });
    var heldNow = {};
    eachRoster(b.data.holds, b.scope.rosters, function (list) {
      (list || []).forEach(function (l) { if (l && str(l.owner)) (heldNow[laneOf(b, l.owner)] = heldNow[laneOf(b, l.owner)] || []).push({ item: "hold-" + l.id, text: str(l.resource) }); });
    });
    return { known: known, count: count, since: since, until: end, live: live, now: b.now, ms: span, rows: rows, pool: pool, states: states,
      lanes: lanes, heldNow: heldNow, doingClose: replayDoingClose(b), total: all.length, before: upto.length - win.length,
      oldest: all.length ? all[0].at : null, ticks: all.map(function (e) { return { at: e.at, kind: e.kind }; }),
      /* The earliest end a dragged window may have: it still holds `count` rows. */
      floorEnd: all.length > count ? all[count - 1].at : null };
  }
  /* Dragging the viewport: the window's end moved by dt, never past now nor so far back it
   * would hold fewer than `count` loaded rows. null means "ends now". */
  function replayPan(rep, end0, dt) {
    var now = rep.now, end = (end0 == null ? now : end0) + dt;
    if (rep.floorEnd == null) return null;
    end = Math.max(rep.floorEnd, Math.min(now, end));
    return end >= now - 1000 ? null : Math.round(end);
  }
  /* Arrow buttons (and Left/Right on the strip): move the window by a fixed
   * REPLAY_PAN_ROWS rows, never past now or the earliest end that still holds
   * a full window. null means "ends now". dir < 0 is earlier (previous 100). */
  var REPLAY_PAN_ROWS = 100;
  function replayPanRows(rep, end0, dir) {
    dir = dir < 0 ? -1 : 1;
    var ticks = rep.ticks || [], n = ticks.length, now = rep.now, floor = rep.floorEnd, i, j, lo, t;
    if (!n || floor == null) return end0 == null || end0 >= now - 1000 ? null : Math.round(Math.max(floor, Math.min(now, end0)));
    var end = end0 == null ? now : end0;
    i = n - 1;
    while (i >= 0 && ticks[i].at > end) i--;
    if (i < 0) i = 0;
    lo = 0;
    while (lo < n && ticks[lo].at < floor) lo++;
    j = i + dir * REPLAY_PAN_ROWS;
    if (j < lo) j = lo;
    if (j >= n || ticks[j].at >= now - 1000) return null;
    t = ticks[j].at < floor ? floor : ticks[j].at;
    return t >= now - 1000 ? null : Math.round(t);
  }
  function replayPanCan(rep, end0, dir) {
    var next = replayPanRows(rep, end0, dir);
    var cur = (end0 == null || end0 >= rep.now - 1000) ? null : end0;
    if (dir < 0) return next != null && (cur == null || next < cur - 1);
    return cur != null && (next == null || next > cur + 1);
  }
  /* ---- Age is position ----
   * An item enters at its desk when the playhead reaches its time and travels outward as it
   * ages, leaving at the far edge once it is one window span old. A pure function of the
   * playhead t, the item's time and the span: scrubbing either way puts it back. null: not on
   * screen (not happened yet, or aged out). */
  function replayAge(t, at, span) {
    var a = t - at;
    return a < 0 || a > span || !(span > 0) ? null : a / span;
  }
  /* A two-desk transition is joined by a line for as long as its tick is
   * in the window. The line is not drawn before the playhead reaches it.
   * Age may dim it slightly, but never below REPLAY_LINK_FADE of full
   * strength: it does not fade out. */
  var REPLAY_LINK_FADE = 0.7;
  function replayLinkFade(pos) {
    if (pos == null || pos < 0 || pos > 1) return 0;
    return Math.max(REPLAY_LINK_FADE, 1 - pos * (1 - REPLAY_LINK_FADE));
  }

  /* ---- Elastic time: squeeze empty stretches so playback crosses them quickly ----
   * timeScale(rows, doingSpans, lo, hi) maps office time onto the display
   * axis. Only a stretch with no event and no doing covering it, longer
   * than the threshold, collapses to a short fixed width, marked as a
   * break with the real duration skipped. A doing that covers a quiet
   * gap stays proportional. toPos is 0 at lo and 1 at hi, monotonic;
   * toTime inverts it. Tooltips and the ruler keep real times. The
   * overview bar stays linear in real time. */
  var REPLAY_VOID_MIN_MS = 5 * 60 * 1000, REPLAY_VOID_FRAC = 0.06, REPLAY_VOID_MARK_FRAC = 0.03;
  var REPLAY_RULER_STEPS = [60000, 120000, 300000, 600000, 900000, 1800000, 3600000, 7200000, 10800000, 21600000, 43200000, 86400000];
  function timeScale(rows, doingSpans, lo, hi, opts) {
    opts = opts || {};
    if (lo && typeof lo === "object") { opts = lo; lo = opts.lo; hi = opts.hi != null ? opts.hi : hi; }
    rows = rows || [];
    doingSpans = doingSpans || [];
    if (lo == null || hi == null) {
      var times = [], j;
      for (j = 0; j < rows.length; j++) if (rows[j] && rows[j].at != null) times.push(rows[j].at);
      for (j = 0; j < doingSpans.length; j++) {
        if (doingSpans[j] && doingSpans[j].start != null) times.push(doingSpans[j].start);
        if (doingSpans[j] && doingSpans[j].end != null) times.push(doingSpans[j].end);
      }
      if (lo == null) lo = times.length ? Math.min.apply(null, times) : 0;
      if (hi == null) hi = times.length ? Math.max.apply(null, times) : lo;
    }
    lo = Number(lo); hi = Number(hi);
    function identity() {
      var span = Math.max(1, hi - lo);
      return {
        lo: lo, hi: hi, breaks: [], display: span,
        toPos: function (t) { return (t - lo) / span; },
        toTime: function (p) { return lo + p * span; }
      };
    }
    if (!(hi > lo)) return identity();
    var occ = [], i, s, a, b;
    for (i = 0; i < doingSpans.length; i++) {
      s = doingSpans[i];
      if (!s || s.start == null) continue;
      a = Math.max(lo, s.start);
      b = Math.min(hi, s.end != null ? s.end : hi);
      if (b > a) occ.push([a, b]);
    }
    occ.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1]; });
    var merged = [];
    for (i = 0; i < occ.length; i++) {
      if (!merged.length || occ[i][0] > merged[merged.length - 1][1]) merged.push([occ[i][0], occ[i][1]]);
      else merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], occ[i][1]);
    }
    var threshold = opts.threshold != null ? opts.threshold : Math.max(REPLAY_VOID_MIN_MS, REPLAY_VOID_FRAC * (hi - lo));
    var mark = opts.mark != null ? opts.mark : Math.max(1000, Math.min(threshold * 0.4, REPLAY_VOID_MARK_FRAC * (hi - lo)));
    var ev = [];
    for (i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i].at != null && rows[i].at >= lo && rows[i].at <= hi) ev.push(rows[i].at);
    }
    ev.sort(function (x, y) { return x - y; });
    var ev2 = [];
    for (i = 0; i < ev.length; i++) if (!ev2.length || ev[i] !== ev2[ev2.length - 1]) ev2.push(ev[i]);
    ev = ev2;
    function eventsIn(ga, gb) {
      var out = [], k;
      for (k = 0; k < ev.length; k++) if (ev[k] > ga && ev[k] < gb) out.push(ev[k]);
      return out;
    }
    var gaps = [], cursor = lo, insides, g0, e;
    function pushGap(ga, gb) { if (gb - ga > threshold) gaps.push([ga, gb]); }
    function cutGap(ga, gb) {
      insides = eventsIn(ga, gb);
      g0 = ga;
      for (e = 0; e < insides.length; e++) { pushGap(g0, insides[e]); g0 = insides[e]; }
      pushGap(g0, gb);
    }
    for (i = 0; i < merged.length; i++) {
      if (merged[i][0] > cursor) cutGap(cursor, merged[i][0]);
      cursor = Math.max(cursor, merged[i][1]);
    }
    if (cursor < hi) cutGap(cursor, hi);
    var segs = [], d = 0, t0 = lo, gi, w;
    function addSeg(x0, x1, kind) {
      if (!(x1 > x0)) return;
      w = kind === "void" ? mark : (x1 - x0);
      segs.push({ t0: x0, t1: x1, kind: kind, d0: d, d1: d + w });
      d += w;
    }
    for (gi = 0; gi < gaps.length; gi++) {
      addSeg(t0, gaps[gi][0], "active");
      addSeg(gaps[gi][0], gaps[gi][1], "void");
      t0 = gaps[gi][1];
    }
    addSeg(t0, hi, "active");
    if (!d || !segs.length) return identity();
    var breaks = [];
    for (i = 0; i < segs.length; i++) if (segs[i].kind === "void") {
      breaks.push({ start: segs[i].t0, end: segs[i].t1, skip: segs[i].t1 - segs[i].t0, lo: segs[i].d0 / d, hi: segs[i].d1 / d });
    }
    function findSegByT(t) {
      var loI = 0, hiI = segs.length - 1, mid, s;
      if (t <= segs[0].t0) return segs[0];
      if (t >= segs[hiI].t1) return segs[hiI];
      while (loI <= hiI) {
        mid = (loI + hiI) >> 1;
        s = segs[mid];
        if (t < s.t0) hiI = mid - 1;
        else if (t > s.t1) loI = mid + 1;
        else return s;
      }
      return segs[Math.max(0, Math.min(segs.length - 1, loI))];
    }
    function findSegByD(x) {
      var loI = 0, hiI = segs.length - 1, mid, s;
      if (x <= 0) return segs[0];
      if (x >= d) return segs[hiI];
      while (loI <= hiI) {
        mid = (loI + hiI) >> 1;
        s = segs[mid];
        if (x < s.d0) hiI = mid - 1;
        else if (x > s.d1) loI = mid + 1;
        else return s;
      }
      return segs[Math.max(0, Math.min(segs.length - 1, loI))];
    }
    function toPos(t) {
      if (t <= lo) return (t - lo) / d;
      if (t >= hi) return 1 + (t - hi) / d;
      var s = findSegByT(t);
      if (s.kind === "void") {
        if (!(s.t1 > s.t0)) return s.d0 / d;
        return (s.d0 + (t - s.t0) / (s.t1 - s.t0) * (s.d1 - s.d0)) / d;
      }
      return (s.d0 + (t - s.t0)) / d;
    }
    function toTime(p) {
      if (p <= 0) return lo + p * d;
      if (p >= 1) return hi + (p - 1) * d;
      var x = p * d, s = findSegByD(x);
      if (s.kind === "void") {
        if (!(s.d1 > s.d0)) return s.t0;
        return s.t0 + (x - s.d0) / (s.d1 - s.d0) * (s.t1 - s.t0);
      }
      return s.t0 + (x - s.d0);
    }
    return { lo: lo, hi: hi, breaks: breaks, display: d, toPos: toPos, toTime: toTime };
  }
  function replayPlayhead(scale, t0, wallMs, speed) {
    if (!scale) return t0;
    speed = speed == null ? 1 : speed;
    var p = scale.toPos(t0) + (Math.max(0, wallMs) * speed) / REPLAY_PLAY_MS;
    if (p <= 0) return scale.lo;
    if (p >= 1) return scale.hi;
    return scale.toTime(p);
  }
  function replayScaledAge(scale, t, at) {
    if (!scale) return null;
    var p = scale.toPos(t) - scale.toPos(at);
    if (p < 0 || p > 1) return null;
    return p;
  }
  function rulerLabel(at, step) {
    var d = new Date(at);
    function pad(n) { return n < 10 ? "0" + n : String(n); }
    if (step >= 86400000) return d.toLocaleDateString([], { month: "short", day: "numeric" });
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function replayRulerTimes(scale, t, opts) {
    opts = opts || {};
    if (!scale) return [];
    var visLo = scale.toTime(Math.max(0, scale.toPos(t) - 1));
    var visHi = t;
    if (!(visHi > visLo)) return [];
    var span = visHi - visLo, raw = span / (opts.count || 8), step = REPLAY_RULER_STEPS[REPLAY_RULER_STEPS.length - 1], i;
    for (i = 0; i < REPLAY_RULER_STEPS.length; i++) if (REPLAY_RULER_STEPS[i] >= raw) { step = REPLAY_RULER_STEPS[i]; break; }
    var t0 = Math.ceil(visLo / step) * step, out = [], lastPos = null, p, at, brs = scale.breaks || [];
    function nearVoid(at, p) {
      var j, br, a, b;
      for (j = 0; j < brs.length; j++) {
        br = brs[j];
        if (at >= br.start - 1 && at <= br.end + 1) return true;
        a = scale.toPos(t) - scale.toPos(br.end);
        b = scale.toPos(t) - scale.toPos(br.start);
        if (p >= a - 0.02 && p <= b + 0.02) return true;
      }
      return false;
    }
    for (at = t0; at <= visHi + 1; at += step) {
      p = scale.toPos(t) - scale.toPos(at);
      if (p < 0 || p > 1) continue;
      if (nearVoid(at, p)) continue;
      if (lastPos != null && Math.abs(p - lastPos) < 0.035) continue;
      out.push({ at: at, pos: p, label: rulerLabel(at, step) });
      lastPos = p;
    }
    return out;
  }
  /* ---- Packing: items keep their time, collisions go across the lane ----
   * Greedy interval packing per lane, each frame. An item stays at its age along the
   * time axis; if its interval would overlap another on the same sub-row, it moves to
   * the next sub-row (vertical when time runs left to right, horizontal when time
   * runs top to bottom). A lane grows with the number of sub-rows, up to
   * REPLAY_PACK_ROWS. Leftovers become +N overflow chips, clustered by overlap, on
   * one extra strip so they do not cover a visible item. */
  var REPLAY_PACK_ROWS = 4;
  function replayPack(items, opts) {
    opts = opts || {};
    var maxRows = opts.maxRows || REPLAY_PACK_ROWS, gap = opts.gap != null ? opts.gap : 2;
    var moreW = opts.overflowMain || 22;
    var sizeOf = opts.sizeOf || function () { return { main: 14, cross: 14 }; };
    var lenOf = opts.lenOf || function () { return opts.len || 1; };
    var byLane = {}, place = {}, overflow = [], rows = {}, i, r, it, list, lane;
    for (i = 0; i < items.length; i++) {
      it = items[i];
      (byLane[it.lane] = byLane[it.lane] || []).push(it);
    }
    Object.keys(byLane).forEach(function (lane) {
      list = byLane[lane].slice().sort(function (a, b) { return a.pos - b.pos || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0); });
      var ends = [], hidden = [];
      list.forEach(function (it) {
        var main = Math.max(1, (sizeOf(it).main || 14)), len = Math.max(1, lenOf(it));
        var start = it.pos * len, end = start + main + gap, row = -1;
        for (r = 0; r < ends.length; r++) if (ends[r] <= start + 0.01) { row = r; break; }
        if (row < 0 && ends.length < maxRows) { row = ends.length; ends.push(0); }
        if (row >= 0) { ends[row] = end; place[it.id] = { row: row, hide: false }; }
        else hidden.push(it);
      });
      var clusters = [];
      hidden.forEach(function (it) {
        var len = Math.max(1, lenOf(it)), start = it.pos * len;
        var end = start + Math.max(moreW, (sizeOf(it).main || 14)) + gap;
        var last = clusters[clusters.length - 1];
        if (last && start < last.end) { last.ids.push(it.id); last.items.push(it); last.end = Math.max(last.end, end); }
        else clusters.push({ ids: [it.id], items: [it], start: start, end: end, pos: it.pos, lane: lane });
      });
      hidden.forEach(function (it) { place[it.id] = { row: -1, hide: true }; });
      var strip = clusters.length ? 1 : 0;
      clusters.forEach(function (c, n) {
        overflow.push({ id: "more-" + lane + "-" + n, lane: lane, pos: c.pos, n: c.ids.length, ids: c.ids, items: c.items, row: ends.length });
      });
      rows[lane] = Math.max(1, ends.length + strip);
    });
    return { place: place, overflow: overflow, rows: rows };
  }
  /* Group mode (the default): items of the same kind on the same lane that fall in
   * the same time bucket merge into one mark. Size grows with the count (square
   * root, clamped). The playhead does not change which bucket an item is in, because
   * buckets are locked to the item's own time. */
  var REPLAY_CLUSTER_DEFAULT = { desks: "group", activity: "group" };
  var REPLAY_GROUP_BUCKETS = 36;
  function replayCluster(v) { return v === "spread" ? "spread" : "group"; }
  function groupScale(n) {
    if (!(n > 1)) return 1;
    var s = Math.sqrt(n);
    return s < 1 ? 1 : s > 2.6 ? 2.6 : s;
  }
  function replayGroup(items, opts) {
    opts = opts || {};
    var nB = opts.buckets || REPLAY_GROUP_BUCKETS, span = Math.max(1, opts.span || 1);
    var bucketMs = span / nB, groups = {}, order = [], i, it, id, g, at, b;
    for (i = 0; i < (items || []).length; i++) {
      it = items[i];
      at = it.row && it.row.at != null ? it.row.at : 0;
      b = Math.floor(at / Math.max(1, bucketMs));
      id = "grp-" + it.lane + "-" + it.kind + "-" + b;
      if (!groups[id]) { groups[id] = { id: id, lane: it.lane, kind: it.kind, pos: 0, at: at, n: 0, items: [], scale: 1 }; order.push(id); }
      g = groups[id];
      g.items.push(it);
      g.n++;
      g.pos = (g.pos * (g.n - 1) + it.pos) / g.n;
      if (it.row && it.row.at != null && it.row.at < g.at) g.at = it.row.at;
    }
    return order.map(function (id) { g = groups[id]; g.scale = groupScale(g.n); return g; });
  }
  /* The same instances, two views: desks places each on every desk lane in its state (and
   * joins a two-desk transition with a line); activity places each once on its kind lane. */
  function replayItemsAt(rep, t, cap, view) {
    var items = [], links = [], activity = view === "activity";
    cap = cap || 400;
    var scale = replayScale(rep), far = scale ? scale.toTime(scale.toPos(t) - 1) : t - rep.ms;
    for (var i = rep.pool.length - 1; i >= 0; i--) {
      var r = rep.pool[i], pos = scale ? replayScaledAge(scale, t, r.at) : replayAge(t, r.at, rep.ms);
      if (pos == null) { if (r.at < far) break; continue; }
      if (activity) {
        if (items.length < cap) items.push({ id: r.key, key: r.key, kind: r.kind, lane: r.kind, pos: pos, row: r });
      } else {
        if (items.length < cap) {
          r.stateLanes.forEach(function (lane) { items.push({ id: r.key + "@" + lane, key: r.key, kind: r.kind, lane: lane, pos: pos, row: r }); });
        }
        /* Every in-window transition keeps its line, even when tick packing
         * hits the cap. Fade is slight; a line never drops out with age. */
        r.flows.forEach(function (f) {
          links.push({ id: r.key + ">" + f.from + ">" + f.to, key: r.key, kind: r.kind, from: f.from, to: f.to, pos: pos, fade: replayLinkFade(pos) });
        });
      }
    }
    return { items: items, links: links };
  }
  function replayVisibleKeys(rep, t) {
    var scale = replayScale(rep);
    return (rep.pool || []).filter(function (r) {
      return scale ? replayScaledAge(scale, t, r.at) != null : replayAge(t, r.at, rep.ms) != null;
    }).map(function (r) { return r.key; }).sort();
  }
  /* Activity view: one fixed pill per kind, always all six, in REPLAY_KINDS order. */
  function replayKindLanes() {
    return REPLAY_KINDS.map(function (k) { return { id: k, t: "kind", name: k }; });
  }
  /* ---- The overview: the whole loaded history, and the viewport on it ----
   * The strip at the top buckets every loaded row from the oldest to now; the viewport is the
   * slice the big pane shows at playhead t: [t - span, t]. */
  function replayOverview(rep, n) {
    n = n || 160;
    var lo = rep.oldest != null ? Math.min(rep.oldest, rep.since) : rep.since, hi = Math.max(rep.now, rep.until), w = Math.max(1, hi - lo), total = [], kinds = {}, peak = 0;
    for (var i = 0; i < n; i++) total.push(0);
    REPLAY_KINDS.forEach(function (k) { kinds[k] = total.slice(); });
    (rep.ticks || []).forEach(function (x) {
      var i = Math.min(n - 1, Math.max(0, Math.floor((x.at - lo) / w * n)));
      total[i]++;
      if (kinds[x.kind]) kinds[x.kind][i]++;
      if (total[i] > peak) peak = total[i];
    });
    return { n: n, lo: lo, hi: hi, total: total, kinds: kinds, peak: peak };
  }
  function replayViewport(rep, t, ov) {
    var w = Math.max(1, ov.hi - ov.lo), c = function (x) { return Math.max(0, Math.min(1, x)); };
    return { lo: c((t - rep.ms - ov.lo) / w), hi: c((t - ov.lo) / w), at: c((t - ov.lo) / w), winLo: c((rep.since - ov.lo) / w), winHi: c((rep.until - ov.lo) / w) };
  }
  /* ---- The stage: one column per desk, the activity drops from its desk ----
   * A lane is a focused desk (its name), the person, the office (rows no desk sent, like a wake),
   * or "outside" (every desk off the pick, one cloud). */
  function laneOf(b, name) {
    var x = party(b, name);
    if (!x) return "@office";
    return x.t === "desk" ? x.name : x.t === "human" ? "@human" : x.t === "cloud" ? "@out" : "@office";
  }
  function replayLanes(b, rows) {
    var used = {}, outside = {};
    rows.forEach(function (r) {
      used[r.lane] = 1;
      r.flows.forEach(function (f) { used[f.to] = 1; used[f.from] = 1; });
    });
    (b.data.trail ? Object.keys(b.data.trail) : []).forEach(function (n) { if (b.member(n)) used[n] = 1; });
    b.desks.forEach(function (d) { if (b.member(d.name)) used[d.name] = 1; });
    rows.forEach(function (r) { (r.parts || []).forEach(function (p) { if (p.t === "cloud") (p.names || [p.name]).forEach(function (n) { if (n) outside[n] = 1; }); }); });
    /* Fixed order: the desks as the DESKS list sorts them, then any others a-z. */
    var order = {};
    b.desks.forEach(function (d, i) { order[d.name] = i; });
    var desks = Object.keys(used).filter(function (k) { return k.charAt(0) !== "@"; }).sort(function (x, y) {
      var ox = order[x] != null ? order[x] : 1e6, oy = order[y] != null ? order[y] : 1e6;
      return ox - oy || (x.toLowerCase() < y.toLowerCase() ? -1 : 1);
    });
    var out = [];
    if (used["@office"]) out.push({ id: "@office", t: "office", name: "office" });
    if (used["@human"]) out.push({ id: "@human", t: "human", name: "you" });
    desks.forEach(function (n) { var d = b.byName[n]; out.push({ id: n, t: "desk", name: n, state: d ? d.state : "disconnected" }); });
    if (used["@out"]) out.push({ id: "@out", t: "cloud", name: "outside", names: Object.keys(outside).sort() });
    return out;
  }
  /* What each pickup is read from: a desk's focus rows (on=ITEM), the move rows of a card or a
   * promise, and the letters of each thread. */
  function pickIndex(b) {
    var focus = {}, moves = {}, replies = {};
    Object.keys(b.data.trail || {}).forEach(function (desk) {
      (b.data.trail[desk] || []).forEach(function (r) {
        if (!r || !str(r.on)) return;
        var k = (str(r.desk) || desk) + "|" + str(r.on);
        (focus[k] = focus[k] || []).push(utc(r.at));
      });
    });
    Object.keys(b.data.moves || {}).forEach(function (key) {
      moves[key] = (b.data.moves[key] || []).filter(Boolean).map(function (r) { return { at: utc(r.at), desk: str(r.desk), act: str(r.act) }; })
        .filter(function (r) { return r.at != null; }).sort(function (x, y) { return x.at - y.at; });
    });
    (b.letters || []).forEach(function (m) { (replies[m.root] = replies[m.root] || []).push({ at: m.at, from: m.from }); });
    return { focus: focus, moves: moves, replies: replies };
  }
  function firstAfter(list, at, ok) {
    var hit = null;
    (list || []).forEach(function (x) { var t = x && x.at != null ? x.at : x; if (t != null && t >= at && (!ok || ok(x)) && (hit == null || t < hit)) hit = t; });
    return hit;
  }
  /* The flows of one row: who it travels from and to, and when the receiver picked it up
   * (null: not yet, so it waits in the receiver's column).
   *   mail: the recipient's first focus row on the letter, or its first letter in the thread
   *         after it; read with no such row: picked up on arrival.
   *   todo: a claim is taken on the spot (from the desk that let it go); a hand-off (ship, done,
   *         assign, back) waits for the receiver's next move on the card.
   *   hold: a desk waiting on a promise another desk holds waits until it takes the hold. */
  /* ---- State: the desk(s) an activity is attached to ----
   * Each kind's state is a set of desks, read from its transition row:
   *   todo  - who has claimed it (the fold of its move rows); a row's own second desk (peer)
   *           when the server sends one
   *   mail  - who sent it (from) and who it went to (holders)
   *   wake  - who was woken, and by whom: the activity row names neither today (owner System,
   *           desk 0), so a wake has no desks and no link
   *   doing - the desk doing it
   *   hold  - who holds it; a wait row adds the desk waiting for it
   *   score - whose score it is
   * A drop lands on every desk in the state at the transition; a link is drawn only when the
   * transition moves the state from one desk to another (from -> holders), or, for a contested
   * hold, between the holder and the desk waiting for it. */
  function stateDesks(e) {
    var a = str(e.actor), none = { holders: [], from: [], waiting: [] };
    function uniq(xs) { return xs.filter(function (x, i) { return x && xs.indexOf(x) === i; }); }
    switch (e.kind) {
      case "mail": return { holders: uniq(e.peers.filter(function (p) { return p !== a; })), from: [a], waiting: [] };
      case "todo":
        if (e.rowPeer) return e.dir === "in" ? { holders: [a], from: [e.rowPeer], waiting: [] } : { holders: [e.rowPeer], from: [a], waiting: [] };
        if (e.act === "claim") return { holders: [a], from: e.prevVol && e.prevVol !== a ? [e.prevVol] : [], waiting: [] };
        if (e.act === "unclaim") return { holders: [], from: uniq([e.prevVol || a]), waiting: [] };
        return { holders: e.vol ? [e.vol] : [], from: [], waiting: [] };
      case "hold":
        if (e.act === "wait") return { holders: uniq(e.peers.filter(function (p) { return p !== a; })), from: [], waiting: [a] };
        if (e.act === "drop") return { holders: [], from: [a], waiting: [] };
        return { holders: a ? [a] : [], from: e.prevHolder ? [e.prevHolder] : [], waiting: [] };
      case "wake": return e.woken ? { holders: [e.woken], from: e.waker ? [e.waker] : [], waiting: [] } : none;
      case "doing": case "score": return { holders: a ? [a] : [], from: [], waiting: [] };
    }
    return none;
  }
  function flowsOf(b, e, ix) {
    var st = stateDesks(e), out = [];
    function link(f, t, desk, pickAt) {
      var lf = laneOf(b, f), lt = laneOf(b, t);
      if (lf !== lt && out.every(function (x) { return x.from !== lf || x.to !== lt; })) out.push({ from: lf, to: lt, desk: desk, pickAt: pickAt });
    }
    if (e.kind === "mail") {
      var m = b.letters && b.letters.byId ? b.letters.byId[Number(String(e.item).replace(/^mail-/, ""))] : null;
      st.holders.forEach(function (p) {
        var at = firstAfter(ix.focus[p + "|" + e.item], e.at);
        var rep = m ? firstAfter(ix.replies[m.root], e.at + 1, function (x) { return x.from === p; }) : null;
        if (rep != null && (at == null || rep < at)) at = rep;
        if (at == null && e.read && e.read.indexOf(p) >= 0) at = e.at;
        link(st.from[0], p, p, at);
      });
    } else if (e.kind === "hold" && e.act === "wait") {
      st.holders.forEach(function (h) { link(h, e.actor, e.actor, firstAfter(ix.moves[e.item], e.at + 1, function (x) { return x.desk === e.actor && x.act === "hold"; })); });
    } else {
      /* The state moved: from each earlier desk to each desk that has it now. */
      st.from.forEach(function (f) {
        st.holders.forEach(function (t) {
          var taken = t === e.actor ? e.at : firstAfter(ix.moves[e.item], e.at + 1, function (x) { return x.desk === t; });
          link(f, t, t, taken);
        });
      });
    }
    return out;
  }
  /* The locks on each lane at t: promises held (from the move rows; at now, the holds table) and
   * promises waited on (a faded lock) until the waiter takes it. */
  function replayLocksAt(rep, t) {
    if (rep.live !== false && t >= rep.until) {
      var now = {};
      Object.keys(rep.heldNow || {}).forEach(function (l) { now[l] = rep.heldNow[l].map(function (x) { return { item: x.item, text: x.text, wait: false }; }); });
      replayPendingHolds(rep, t, now);
      return now;
    }
    var held = {};
    (rep.pool || rep.rows).forEach(function (r) {
      if (r.at > t || r.kind !== "hold") return;
      if (r.act === "hold") { Object.keys(held).forEach(function (l) { delete held[l][r.item]; }); (held[r.lane] = held[r.lane] || {})[r.item] = r.text; }
      if (r.act === "drop" && held[r.lane]) delete held[r.lane][r.item];
    });
    var out = {};
    Object.keys(held).forEach(function (l) { out[l] = Object.keys(held[l]).map(function (k) { return { item: k, text: held[l][k], wait: false }; }); });
    replayPendingHolds(rep, t, out);
    return out;
  }
  function replayPendingHolds(rep, t, out) {
    (rep.pool || rep.rows).forEach(function (r) {
      if (r.at > t || r.kind !== "hold" || r.act !== "wait") return;
      var f = r.flows[0], until = f ? f.pickAt : null;
      if (until != null && until <= t) return;
      var l = out[r.lane] = out[r.lane] || [];
      if (!l.some(function (x) { return x.item === r.item; })) l.push({ item: r.item, text: r.text, wait: true });
    });
  }
  /* How many two-desk transitions reached each lane by t and are not picked up yet: one small
   * count on the pill, not a queue of icons. */
  function replayWaitingAt(rep, t) {
    var out = {};
    rep.pool.forEach(function (r) {
      if (r.at > t || t - r.at > rep.ms) return;
      r.flows.forEach(function (f) { if (f.pickAt == null || f.pickAt > t) out[f.to] = (out[f.to] || 0) + 1; });
    });
    return out;
  }
  function replaySince(rep, desk, t) {
    var list = rep && rep.states && rep.states[desk], cur = null;
    for (var i = 0; list && i < list.length && list[i].at <= t; i++) cur = list[i];
    return cur && (cur.end == null || cur.end > t) ? cur.at : null;
  }
  function replayStateAt(rep, desk, t) {
    var list = rep && rep.states && rep.states[desk];
    if (!list || !list.length) return "";
    var cur = null;
    for (var i = 0; i < list.length && list[i].at <= t; i++) cur = list[i];
    if (!cur) return "";
    if (cur.end != null && cur.end <= t) return cur.by === "cleared" ? "disconnected" : "idle";
    return cur.state;
  }
  function replayAt(rep, t, cap) {
    var out = [];
    for (var i = rep.rows.length - 1; i >= 0 && out.length < (cap || 60); i--) if (rep.rows[i].at <= t) out.push(rep.rows[i]);
    return out;
  }
  /* The items whose move rows the replay needs: todo and hold rows in the week, newest first. */
  function replayItems(b, cap) {
    var since = b.now - REPLAY_FETCH_MS, seen = {}, rows = [];
    eachRoster(b.data.events, b.scope.rosters, function (list) {
      (list || []).forEach(function (e) {
        var k = e && (str(e.kind || e.type) + "-" + e.id);
        if (!e || seen[k] || (e.kind !== "todo" && e.kind !== "hold")) return;
        var at = utc(e.at);
        if (at == null || at < since) return;
        seen[k] = 1;
        rows.push({ key: k, at: at });
      });
    });
    rows.sort(function (x, y) { return y.at - x.at; });
    return rows.slice(0, cap || 40).map(function (r) { return r.key; });
  }

  /* ---- which platform scores each tab shows (SCORE shows every one) ----
   * One table, first match wins. A tab with no match gets no score strip: nothing is made up. */
  var SCORE_TABS = [
    { re: /^doing\./, tabs: ["desks"] },
    { re: /^mill-desk\./, tabs: ["desks"] },
    { re: /^mill-wall\.ticks$/, tabs: ["desks"] },
    { re: /^system$/, tabs: ["desks"] },
    { re: /^cards$/, tabs: ["todo"] },
    { re: /^(todo|card)\./, tabs: ["todo"] },
    { re: /wake/, tabs: ["mail"] },
    { re: /^(mail|letter)\./, tabs: ["mail"] },
    { re: /^(hold|room|tree)\./, tabs: ["collab"] },
    { re: /^(label|prio)\./, tabs: ["priorities"] }
  ];
  function scoreTabs(kpi) {
    var k = str(kpi);
    for (var i = 0; i < SCORE_TABS.length; i++) if (SCORE_TABS[i].re.test(k)) return SCORE_TABS[i].tabs.concat(["score"]);
    return ["score"];
  }
  function scoreText(kpi, v) {
    if (/_ms$/.test(kpi)) return msText(v);
    if (/(end_reason|last_run)$/.test(kpi)) return endWord(v);
    return str(v);
  }
  /* The tab's score strip: roster scores, and desk scores that are off target (the on-target
   * desk scores are counted, not listed). Off target first. */
  function tabScores(b, tab) {
    if (!b.kpis) return null;
    var rows = [], onDesk = 0;
    b.kpis.forEach(function (k) {
      var name = str(k.kpi), owner = str(k.owner), v = str(k.value);
      if (v === "" || scoreTabs(name).indexOf(tab) < 0) return;
      if (owner && !b.inScope(owner)) return;
      var off = kpiMiss(v, k.target);
      if (owner && !off) { onDesk++; return; }
      rows.push({ kpi: name, label: kpiLabel(name), desk: owner, value: scoreText(name, v), target: str(k.target), note: str(k.note), off: off });
    });
    rows.sort(function (a, c) { return (c.off ? 1 : 0) - (a.off ? 1 : 0) || (a.desk || "").localeCompare(c.desk || "") || a.label.localeCompare(c.label); });
    return { rows: rows, off: rows.filter(function (r) { return r.off; }).length, onDesk: onDesk };
  }

  /* ---- strip cards + summary line ---- */
  function strip(b, m) {
    var dk = m.desks, td = m.todo, ml = m.mail, pr = m.priorities, sc = m.score, cb = m.collab;
    var waiting = 0, waitKnown = false, overDay = 0;
    b.desks.forEach(function (d) { if (d.wait) { waitKnown = true; waiting += d.wait.letters; overDay += d.wait.overDay || 0; } });
    return [
      { tab: "desks", label: "DESKS", n: dk ? dk.connected.length : null, cue: dk ? dk.away.length + " away" : "", warn: false },
      { tab: "todo", label: "TODO", n: td ? td.open : null, cue: "open cards", warn: !!(td && td.attention) },
      { tab: "mail", label: "MAIL", n: ml ? ml.waiting : (waitKnown ? waiting : null), cue: "waiting", warn: ml ? !!ml.overDay : overDay > 0 },
      { tab: "priorities", label: "PRIORITIES", n: pr ? pr.lists : null, cue: "lists", warn: false },
      { tab: "score", label: "SCORE", n: sc ? sc.off : null, cue: "off target", warn: !!(sc && sc.off) },
      { tab: "collab", label: "COLLAB", n: cb ? cb.shared : null, cue: "shared", warn: !!(cb && cb.blocking) }
    ];
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function rosterText(sc) { return sc.label || sc.rosters.join(" + "); }
  function rangeText(r) { return r === "today" ? "today" : r === "30d" ? "last 30 days" : "last 7 days"; }
  function hero(b, tab, m) {
    var R = rosterText(b.scope);
    if (tab === "todo" && m) return { lead: plural(m.open, "open card") + " on " + R + ".", rest: "Kanban, list and tree are the same cards: parked, open, claimed, shipped, done." };
    if (tab === "mail" && m) return { lead: plural(m.waiting, "letter") + " waiting on " + R + ".", rest: "Rooms is each conversation with its thread and party; Letters is every letter, newest first." };
    if (tab === "priorities" && m) return { lead: plural(m.lists, "ranked list") + " on this scope.", rest: "Each desk\u2019s ranked list." };
    if (tab === "score" && m) return { lead: plural(m.off, "score") + " off target on " + R + ".", rest: "Grouped by impact. Desks are rows inside each group. Platform scores only." };
    if (tab === "collab" && m) return { lead: m.blocking ? plural(m.blocking, "thing") + " blocking someone now." : "Nothing is blocking anyone now.", rest: "Replay plays the focused desks\u2019 letters, card moves and promises back in order; a desk off this scope shows as outside." };
    if (tab === "desks" && m) {
      return { lead: plural(m.connected.length, "desk") + " connected, " + m.away.length + " disconnected on " + R + ".",
        rest: "Most active first." };
    }
    return { lead: "Loading " + R + "\u2026", rest: "" };
  }

  /* ---- Anticipation: a desk pill swells before it emits ----
   * A pure function of the playhead. Lead time is a fixed slice of the window
   * (REPLAY_LEAD_PLAY_MS of the 2 min playback). Scale grows with the number of
   * upcoming emits on that lane: 1 + k*sqrt(n), capped at 1.25, ramped up to the
   * soonest emit, then eased back over a short settle. Tint follows the same
   * ramp toward the dominant upcoming kind. */
  var REPLAY_LEAD_PLAY_MS = 1250, REPLAY_SETTLE_PLAY_MS = 500, REPLAY_LEAD_K = 0.1, REPLAY_LEAD_MAX = 1.25;
  function replayLeadMs(rep, play) {
    return ((play || REPLAY_LEAD_PLAY_MS) / REPLAY_PLAY_MS) * Math.max(1, rep.ms || 1);
  }
  function replayAnticipateScale(n) {
    if (!(n > 0)) return 1;
    var s = 1 + REPLAY_LEAD_K * Math.sqrt(n);
    return s > REPLAY_LEAD_MAX ? REPLAY_LEAD_MAX : s;
  }
  function replayAnticipate(rep, t, view) {
    var scale = replayScale(rep);
    var leadPos = REPLAY_LEAD_PLAY_MS / REPLAY_PLAY_MS, settlePos = REPLAY_SETTLE_PLAY_MS / REPLAY_PLAY_MS;
    var tPos = scale ? scale.toPos(t) : null;
    var lead = replayLeadMs(rep, REPLAY_LEAD_PLAY_MS), settle = replayLeadMs(rep, REPLAY_SETTLE_PLAY_MS);
    var activity = view === "activity", by = {}, out = {}, a, key;
    function slot(id) {
      return by[id] || (by[id] = { up: [], upKinds: {}, next: null, down: [], downKinds: {}, last: null });
    }
    function add(map, kind) { map[kind] = (map[kind] || 0) + 1; }
    function dominant(kinds, fallback) {
      var best = "", n = 0, k;
      for (k in kinds) if (kinds[k] > n || (kinds[k] === n && k === fallback)) { n = kinds[k]; best = k; }
      return best || fallback || "";
    }
    (rep.pool || []).forEach(function (r) {
      if (r.at == null) return;
      key = activity ? r.kind : r.lane;
      if (!key) return;
      a = slot(key);
      if (scale) {
        var p = scale.toPos(r.at);
        if (p > tPos && p <= tPos + leadPos) {
          a.up.push(r);
          add(a.upKinds, r.kind);
          if (a.next == null || r.at < a.next) a.next = r.at;
        } else if (p <= tPos && tPos - p <= settlePos) {
          a.down.push(r);
          add(a.downKinds, r.kind);
          if (a.last == null || r.at > a.last) a.last = r.at;
        }
      } else if (r.at > t && r.at <= t + lead) {
        a.up.push(r);
        add(a.upKinds, r.kind);
        if (a.next == null || r.at < a.next) a.next = r.at;
      } else if (r.at <= t && t - r.at <= settle) {
        a.down.push(r);
        add(a.downKinds, r.kind);
        if (a.last == null || r.at > a.last) a.last = r.at;
      }
    });
    Object.keys(by).forEach(function (id) {
      a = by[id];
      var n, kind, ramp, target;
      if (a.up.length) {
        n = a.up.length;
        kind = dominant(a.upKinds, a.up[0] && a.up[0].kind);
        ramp = scale
          ? Math.max(0, Math.min(1, (leadPos - (scale.toPos(a.next) - tPos)) / leadPos))
          : Math.max(0, Math.min(1, (lead - (a.next - t)) / lead));
      } else if (a.down.length) {
        n = a.down.length;
        kind = dominant(a.downKinds, a.down[0] && a.down[0].kind);
        ramp = scale
          ? Math.max(0, Math.min(1, 1 - (tPos - scale.toPos(a.last)) / settlePos))
          : Math.max(0, Math.min(1, 1 - (t - a.last) / settle));
      } else return;
      target = replayAnticipateScale(n);
      out[id] = { n: n, scale: 1 + (target - 1) * ramp, tint: ramp, kind: kind, next: a.next, last: a.last };
    });
    return out;
  }

  /* Doing duration: GET /api/v1/doing/history sends ended (bool) and
   * ended_by ("finished" | "cleared" | "newer" | null). It does not send
   * ended_at: the SQL computes that time, but the rpc uses it only to
   * pick ended_by and then drops it. The trail cache keeps ended_at when
   * a row has it.
   * Start is the focus row's at. End is:
   *   1. ended_at on the row, when present (utc).
   *   2. Else the next focus/doing row on the same desk (a newer doing
   *      replaces; this is also how a "newer" end is timed).
   *   3. Else if the row is not ended (no ended flag, no ended_by): the
   *      span is open and runs to the playhead, unless that desk is no
   *      longer working (stale, disconnected, or idle). Then the span
   *      follows the last run of activity on that desk, plus a short
   *      grace, and does not jump to last-seen across a quiet gap.
   *   4. Else ended is true but no timestamp and no next row: the end
   *      time was not sent, so we do not invent one; the start tick
   *      stays and there is no span.
   * Wait-on-hold focus rows are kind "hold", not doing, and have no span. */
  function replayDoingClose(b) {
    var close = {};
    (b && b.all ? b.all : []).forEach(function (d) {
      if (!d || (d.connected && d.doing)) return;
      if (d.lastSeenAt != null) close[d.name] = d.lastSeenAt;
      else close[d.name] = null;
    });
    return close;
  }
  var REPLAY_DOING_GRACE_MS = 2 * 60 * 60 * 1000;
  function replayDoingEnd(row, nextAt, closeAt) {
    if (row.endedAt != null) return { end: row.endedAt, open: false, how: row.endedBy || "" };
    if (nextAt != null) return { end: nextAt, open: false, how: row.endedBy || "newer" };
    if (!row.ended && !row.endedBy) {
      if (closeAt !== undefined) {
        if (closeAt != null && closeAt > row.at) return { end: closeAt, open: false, how: "stale" };
        return { end: null, open: false, how: "stale" };
      }
      return { end: null, open: true, how: "" };
    }
    return { end: null, open: false, how: row.endedBy || "ended" };
  }
  /* Walk activity on one desk from the doing's start, in time order, and
   * stop at the first gap longer than the grace. last-seen is kept only
   * when it still sits in that run. */
  function replayDoingLastRun(rep, desk, start, nextAt, closeAt) {
    var times = [], cap = nextAt, i, last;
    (rep && rep.pool || []).forEach(function (r) {
      if (!r || r.at == null || r.at < start) return;
      if (cap != null && !(r.at < cap)) return;
      if ((r.actor || r.lane || "") !== desk) return;
      times.push(r.at);
    });
    if (closeAt != null && closeAt >= start && (cap == null || closeAt < cap)) times.push(closeAt);
    times.sort(function (a, b) { return a - b; });
    last = start;
    for (i = 0; i < times.length; i++) {
      if (times[i] - last <= REPLAY_DOING_GRACE_MS) last = times[i];
      else break;
    }
    return last;
  }
  function replayDoingSpanEnd(rep, row, nextAt, desk) {
    var ev = replayDoingEnd(row, nextAt, (rep.doingClose || {})[desk]);
    /* A later focus row would otherwise stretch the earlier doing all
     * the way to that newer start, even across days of quiet time. */
    if (ev.end != null && (ev.how === "stale" || ev.how === "newer") &&
        Object.prototype.hasOwnProperty.call(rep.doingClose || {}, desk)) {
      ev = { end: replayDoingLastRun(rep, desk, row.at, nextAt, ev.end), open: false, how: ev.how };
    }
    return ev;
  }
  /* Doing intervals for the window scale: open spans run to hi, not the playhead,
   * so the map stays fixed for a given window. A stale desk's leftover doing
   * follows the last run of activity on that desk, so it does not occupy a
   * later quiet stretch and block a void. */
  function replayDoingIntervals(rep, hi) {
    hi = hi != null ? hi : (rep && rep.until);
    var byDesk = {}, spans = [];
    (rep.pool || []).forEach(function (r) {
      if (r.kind !== "doing" || r.at == null) return;
      var desk = r.actor || r.lane || "";
      (byDesk[desk] = byDesk[desk] || []).push(r);
    });
    Object.keys(byDesk).forEach(function (desk) {
      var list = byDesk[desk].slice().sort(function (a, b) { return a.at - b.at || (a.key < b.key ? -1 : 1); });
      list.forEach(function (r, i) {
        var ev = replayDoingSpanEnd(rep, r, list[i + 1] ? list[i + 1].at : null, desk);
        if (!ev.open && ev.end == null) return;
        var end = ev.open || ev.end == null ? hi : ev.end;
        if (!(end > r.at)) return;
        spans.push({ start: r.at, end: end, open: !!ev.open, desk: desk, key: r.key });
      });
    });
    return spans;
  }
  function replayScale(rep) {
    if (!rep || rep.since == null || rep.until == null || !(rep.until > rep.since)) return null;
    if (rep.scale && rep.scale.lo === rep.since && rep.scale.hi === rep.until) return rep.scale;
    rep.scale = timeScale(rep.pool, replayDoingIntervals(rep, rep.until), rep.since, rep.until);
    return rep.scale;
  }
  function replayDoingSpans(rep, t, view) {
    var activity = view === "activity", ms = Math.max(1, rep.ms || 1), byDesk = {}, spans = [];
    var scale = replayScale(rep), far = scale ? scale.toTime(scale.toPos(t) - 1) : t - ms;
    (rep.pool || []).forEach(function (r) {
      if (r.kind !== "doing" || r.at == null) return;
      var desk = r.actor || r.lane || "";
      (byDesk[desk] = byDesk[desk] || []).push(r);
    });
    Object.keys(byDesk).forEach(function (desk) {
      var list = byDesk[desk].slice().sort(function (a, b) { return a.at - b.at || (a.key < b.key ? -1 : 1); });
      list.forEach(function (r, i) {
        var ev = replayDoingSpanEnd(rep, r, list[i + 1] ? list[i + 1].at : null, desk);
        if (!ev.open && ev.end == null) return;
        if (t < r.at) return;
        var endDraw = ev.open || ev.end == null || ev.end > t ? t : ev.end;
        if (endDraw <= r.at || endDraw <= far) return;
        var lo = scale ? (scale.toPos(t) - scale.toPos(endDraw)) : (t - endDraw) / ms;
        var hi = scale ? (scale.toPos(t) - scale.toPos(r.at)) : (t - r.at) / ms;
        lo = Math.max(0, lo);
        hi = Math.min(1, hi);
        if (!(hi > lo)) return;
        spans.push({
          id: "doing-span-" + r.key, key: r.key, lane: activity ? "doing" : (r.lane || desk),
          desk: desk, row: r, start: r.at, end: ev.open ? null : ev.end,
          open: !!(ev.open || (ev.end != null && ev.end > t)), how: ev.how,
          text: r.text || "", item: r.item || "", pos0: lo, pos1: hi
        });
      });
    });
    /* Stack overlapping spans on a lane. One desk should not overlap; the
     * activity view places every desk on the doing lane, so they often do. */
    var byLane = {};
    spans.forEach(function (s) { (byLane[s.lane] = byLane[s.lane] || []).push(s); });
    Object.keys(byLane).forEach(function (lane) {
      var ends = [];
      byLane[lane].sort(function (a, b) { return a.pos0 - b.pos0 || a.pos1 - b.pos1; }).forEach(function (s) {
        var row = 0;
        for (; row < ends.length; row++) if (s.pos0 >= ends[row] - 1e-6) break;
        ends[row] = s.pos1;
        s.rowIndex = row;
      });
    });
    return spans;
  }
  global.WallRd = {
    base: base, desks: desks, deskDetail: deskDetail, todo: todo, mail: mail, priorities: priorities,
    score: score, collab: collab, collabReplay: collabReplay, replayAt: replayAt, replayWaitingAt: replayWaitingAt, replayLocksAt: replayLocksAt, replayPan: replayPan, replayPanRows: replayPanRows, replayPanCan: replayPanCan, REPLAY_PAN_ROWS: REPLAY_PAN_ROWS, stateDesks: stateDesks, itemTags: itemTags, tagsOf: tagsOf, replayItems: replayItems, replayStateAt: replayStateAt,
    REPLAY_DIR_DEFAULT: REPLAY_DIR_DEFAULT, replayAxis: replayAxis, REPLAY_COUNTS: REPLAY_COUNTS, REPLAY_COUNT_DEFAULT: REPLAY_COUNT_DEFAULT, replayCount: replayCount, replayAge: replayAge, timeScale: timeScale, replayScale: replayScale, replayPlayhead: replayPlayhead, replayScaledAge: replayScaledAge, replayRulerTimes: replayRulerTimes, replayDoingIntervals: replayDoingIntervals, REPLAY_VOID_MIN_MS: REPLAY_VOID_MIN_MS, REPLAY_VOID_FRAC: REPLAY_VOID_FRAC, REPLAY_VOID_MARK_FRAC: REPLAY_VOID_MARK_FRAC, replayItemsAt: replayItemsAt, replayPack: replayPack, REPLAY_PACK_ROWS: REPLAY_PACK_ROWS, replayGroup: replayGroup, groupScale: groupScale, replayCluster: replayCluster, REPLAY_CLUSTER_DEFAULT: REPLAY_CLUSTER_DEFAULT, REPLAY_GROUP_BUCKETS: REPLAY_GROUP_BUCKETS, replayVisibleKeys: replayVisibleKeys, replayKindLanes: replayKindLanes, replayOverview: replayOverview, replayViewport: replayViewport, REPLAY_LINK_FADE: REPLAY_LINK_FADE, replayLinkFade: replayLinkFade, REPLAY_PLAY_MS: REPLAY_PLAY_MS, REPLAY_LEAD_PLAY_MS: REPLAY_LEAD_PLAY_MS, REPLAY_SETTLE_PLAY_MS: REPLAY_SETTLE_PLAY_MS, replayDoingEnd: replayDoingEnd, replayDoingLastRun: replayDoingLastRun, REPLAY_DOING_GRACE_MS: REPLAY_DOING_GRACE_MS, replayDoingSpans: replayDoingSpans, replayAnticipate: replayAnticipate, replayAnticipateScale: replayAnticipateScale, replayLeadMs: replayLeadMs, REPLAY_SPEEDS: REPLAY_SPEEDS, replaySince: replaySince, REPLAY_KINDS: REPLAY_KINDS, feed: feed, strip: strip, hero: hero, tabScores: tabScores, scoreTabs: scoreTabs,
    normScope: normScope, kpiMiss: kpiMiss, kpiLabel: kpiLabel,
    dur: dur, ago: ago, msText: msText, utc: utc, firstLine: firstLine, itemOf: itemOf, rangeText: rangeText,
    SORTS: SORTS.slice(), RANGES: RANGES.slice()
  };
  global.WALL_UI_DEFAULT_RD_MODEL = "WALL_UI_DEFAULT_RD_MODEL";
})(typeof window !== "undefined" ? window : globalThis);
