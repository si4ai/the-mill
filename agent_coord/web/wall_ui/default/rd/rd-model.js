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
  var REPLAY_WINDOWS = { hour: HOUR, day: DAY, week: 7 * DAY };
  var REPLAY_ORDER = ["hour", "day", "week"];
  /* The six kinds the activity table records; each has its own icon. */
  var REPLAY_KINDS = ["mail", "todo", "hold", "wake", "doing", "score"];
  /* Auto picks the shortest window with at least this many rows: enough to watch. */
  var REPLAY_WATCH_MIN = 150;
  /* Every window plays back in this long at 1x: an hour 30x, a day 720x, a week 5040x. */
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
          if (act === "assign" && card && card.desk && card.desk !== desk) peers.push(card.desk);
          if ((act === "ship" || act === "done") && card && card.creator && card.creator !== desk) peers.push(card.creator);
          push({ key: "move-" + r.id, item: key, at: at, kind: "todo", act: act, actor: desk, peers: peers, dir: act === "claim" ? "in" : "out",
            text: card ? card.title : "", from: s !== f.s ? CARD_WORD[s] : "", to: s !== f.s ? CARD_WORD[f.s] : "" });
          s = f.s; vol = f.vol;
        } else if (it.kind === "hold") {
          var contest = act === "wait" || act === "refuse" || act === "contest";
          var holder = (holders[key] || []).filter(function (x) { return x.at <= at; }).pop();
          push({ key: "move-" + r.id, item: key, at: at, kind: "hold", act: contest ? "wait" : act, actor: desk,
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
          var by = held ? held.desk : holderNow[wh.key];
          push({ key: "focus-" + r.id, item: wh.key, at: at0, kind: "hold", act: "wait", actor: str(r.desk) || desk,
            peers: by && by !== (str(r.desk) || desk) ? [by] : [], text: holdName[wh.id] || "" });
          return;
        }
        push({ key: "focus-" + r.id, item: str(r.on), at: utc(r.at), kind: "doing", act: wd ? "wait" : "focus", actor: str(r.desk) || desk,
          peers: wd ? [wd] : [], text: wd ? (str(r.waiting_on.why) || firstLine(r.doing, 120)) : firstLine(r.doing, 120) });
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
        push({ key: "act-" + key, item: kind === "doing" || kind === "wake" || kind === "score" ? "" : key, at: utc(e.at), kind: kind, act: str(e.act) || "touch",
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
  /* The rolling window: the one asked for, or the shortest holding enough rows to watch. */
  function replayWindow(events, now, want) {
    if (REPLAY_WINDOWS[want]) return want;
    for (var i = 0; i < REPLAY_ORDER.length; i++) {
      var w = REPLAY_ORDER[i], since = now - REPLAY_WINDOWS[w];
      var n = events.filter(function (e) { return e.at >= since && e.at <= now; }).length;
      if (n >= REPLAY_WATCH_MIN) return w;
    }
    return "week";
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
  function collabReplay(b, opts) {
    opts = opts || {};
    var all = replayEvents(b);
    var want = REPLAY_WINDOWS[opts.window] ? opts.window : "auto";
    /* The window ends now, or at opts.end when panned back into the history. */
    var live = opts.end == null || opts.end >= b.now, end = live ? b.now : opts.end;
    var win = replayWindow(all, end, want);
    var since = end - REPLAY_WINDOWS[win];
    var pick = pickIndex(b);
    var rows = all.filter(function (e) { return e.at >= since && e.at <= (live ? end + MIN : end); }).map(function (e) {
      return { key: e.key, item: e.item, at: e.at, kind: e.kind, act: e.act, actor: e.actor, dir: e.dir || "out", parts: sentence(b, e),
        outside: e.peers.concat([e.actor]).some(function (n) { var x = party(b, n); return x && x.t === "cloud"; }), read: e.read || null,
        lane: e.office || !e.actor ? "@office" : laneOf(b, e.actor), flows: flowsOf(b, e, pick), text: e.text || "" };
    });
    var lanes = replayLanes(b, rows);
    var known = !!(b.letters || b.data.events);
    var counts = {};
    REPLAY_ORDER.forEach(function (w) { var s0 = end - REPLAY_WINDOWS[w]; counts[w] = all.filter(function (e) { return e.at >= s0 && e.at <= end + MIN; }).length; });
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
    var oldest = null;
    all.forEach(function (e) { if (oldest == null || e.at < oldest) oldest = e.at; });
    return { known: known, want: want, window: win, since: since, until: end, live: live, now: b.now, oldest: oldest, ms: REPLAY_WINDOWS[win], rows: rows, counts: counts, states: states,
      lanes: lanes, heldNow: heldNow };
  }
  /* Panning: the window's end moved by dt, never past now nor before the oldest recorded row
   * (that row stays in the window). null means "ends now". */
  function replayPan(rep, end0, dt) {
    var now = rep.now, end = (end0 == null ? now : end0) + dt;
    var floor = rep.oldest != null ? Math.min(now, rep.oldest + rep.ms) : now;
    end = Math.max(floor, Math.min(now, end));
    return end >= now - 1000 ? null : Math.round(end);
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
  function flowsOf(b, e, ix) {
    var from = laneOf(b, e.actor), out = [];
    if (e.kind === "mail") {
      var m = b.letters && b.letters.byId ? b.letters.byId[Number(String(e.item).replace(/^mail-/, ""))] : null;
      e.peers.forEach(function (p) {
        var to = laneOf(b, p);
        if (to === from) return;
        var at = firstAfter(ix.focus[p + "|" + e.item], e.at);
        var rep = m ? firstAfter(ix.replies[m.root], e.at + 1, function (x) { return x.from === p; }) : null;
        if (rep != null && (at == null || rep < at)) at = rep;
        if (at == null && e.read && e.read.indexOf(p) >= 0) at = e.at;
        out.push({ from: from, to: to, desk: p, pickAt: at });
      });
    } else if (e.kind === "todo" && e.peers.length) {
      e.peers.forEach(function (p) {
        var lp = laneOf(b, p);
        if (lp === from) return;
        if (e.dir === "in") { out.push({ from: lp, to: from, desk: e.actor, pickAt: e.at }); return; }
        out.push({ from: from, to: lp, desk: p, pickAt: firstAfter(ix.moves[e.item], e.at + 1, function (x) { return x.desk === p; }) });
      });
    } else if (e.kind === "hold" && e.act === "wait" && e.peers.length) {
      var lh = laneOf(b, e.peers[0]);
      if (lh !== from) out.push({ from: lh, to: from, desk: e.actor, pickAt: firstAfter(ix.moves[e.item], e.at + 1, function (x) { return x.desk === e.actor && x.act === "hold"; }) });
    }
    return out;
  }
  /* What waits in each lane at t: flows that arrived and are not picked up yet. */
  function replayPending(rep, t) {
    var out = {};
    rep.rows.forEach(function (r) {
      if (r.at > t) return;
      r.flows.forEach(function (f, i) {
        if (f.pickAt != null && f.pickAt <= t) return;
        (out[f.to] = out[f.to] || []).push({ key: r.key + "~" + i, kind: r.kind, row: r, flow: f });
      });
    });
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
    rep.rows.forEach(function (r) {
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
    rep.rows.forEach(function (r) {
      if (r.at > t || r.kind !== "hold" || r.act !== "wait") return;
      var f = r.flows[0], until = f ? f.pickAt : null;
      if (until != null && until <= t) return;
      var l = out[r.lane] = out[r.lane] || [];
      if (!l.some(function (x) { return x.item === r.item; })) l.push({ item: r.item, text: r.text, wait: true });
    });
  }
  /* ---- The monitor: one heart-monitor trace per lane, rows per slice (as actor or receiver) ---- */
  function replayLaneTrace(rep, n) {
    n = n || 120;
    var span = Math.max(1, rep.until - rep.since), by = {}, peak = 0;
    rep.lanes.forEach(function (l) { var z = []; for (var i = 0; i < n; i++) z.push(0); by[l.id] = z; });
    rep.rows.forEach(function (r) {
      if (r.at < rep.since || r.at > rep.until) return;
      var i = Math.min(n - 1, Math.floor((r.at - rep.since) / span * n)), hit = {};
      hit[r.lane] = 1;
      r.flows.forEach(function (f) { hit[f.to] = 1; });
      Object.keys(hit).forEach(function (l) { if (by[l]) { by[l][i]++; if (by[l][i] > peak) peak = by[l][i]; } });
    });
    return { n: n, by: by, peak: peak };
  }
  /* A desk's state at office time t, from its recorded state changes; "" when none is recorded
   * before t. A focus row holds until the next one, or until its end when the server sends one
   * (finished: idle, cleared: disconnected). */
  /* When the desk's current focus at t began: doing is time spent, so its bar grows from here. */
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
  /* Rows up to playhead t, newest first, at most cap. */
  /* The heart-monitor trace: the window cut into n equal buckets, how many rows fall in each
   * (all kinds, and per kind), and the busiest bucket. Bursts spike; quiet stays flat. */
  function replayTrace(rep, n) {
    n = n || 160;
    var span = Math.max(1, rep.until - rep.since), total = [], kinds = {}, peak = 0;
    for (var i = 0; i < n; i++) total.push(0);
    REPLAY_KINDS.forEach(function (k) { kinds[k] = total.slice(); });
    rep.rows.forEach(function (r) {
      if (r.at < rep.since || r.at > rep.until) return;
      var b = Math.min(n - 1, Math.floor((r.at - rep.since) / span * n));
      total[b]++;
      if (kinds[r.kind]) kinds[r.kind][b]++;
      if (total[b] > peak) peak = total[b];
    });
    return { n: n, total: total, kinds: kinds, peak: peak };
  }
  function replayAt(rep, t, cap) {
    var out = [];
    for (var i = rep.rows.length - 1; i >= 0 && out.length < (cap || 60); i--) if (rep.rows[i].at <= t) out.push(rep.rows[i]);
    return out;
  }
  /* The items whose move rows the replay needs: todo and hold rows in the week, newest first. */
  function replayItems(b, cap) {
    var since = b.now - REPLAY_WINDOWS.week, seen = {}, rows = [];
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

  global.WallRd = {
    base: base, desks: desks, deskDetail: deskDetail, todo: todo, mail: mail, priorities: priorities,
    score: score, collab: collab, collabReplay: collabReplay, replayAt: replayAt, replayTrace: replayTrace, replayPending: replayPending, replayLocksAt: replayLocksAt, replayLaneTrace: replayLaneTrace, replayPan: replayPan, replayItems: replayItems, replayStateAt: replayStateAt,
    REPLAY_WINDOWS: REPLAY_WINDOWS, REPLAY_WATCH_MIN: REPLAY_WATCH_MIN, REPLAY_PLAY_MS: REPLAY_PLAY_MS, REPLAY_SPEEDS: REPLAY_SPEEDS, replaySince: replaySince, REPLAY_KINDS: REPLAY_KINDS, feed: feed, strip: strip, hero: hero, tabScores: tabScores, scoreTabs: scoreTabs,
    normScope: normScope, kpiMiss: kpiMiss, kpiLabel: kpiLabel,
    dur: dur, ago: ago, msText: msText, utc: utc, firstLine: firstLine, itemOf: itemOf, rangeText: rangeText,
    SORTS: SORTS.slice(), RANGES: RANGES.slice()
  };
  global.WALL_UI_DEFAULT_RD_MODEL = "WALL_UI_DEFAULT_RD_MODEL";
})(typeof window !== "undefined" ? window : globalThis);
