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
    return {
      rosters: rosters,
      off: Object.assign({}, scope.off || {}),
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
      d.checked = !sc.off[o];
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
      offDesk: function (name) { return !!sc.off[str(name)]; }
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
  function waitingOn(b, desk) {
    if (!b.letters) return null;
    return b.letters.filter(function (m) {
      return m.tos.some(function (t) { return t.desk === desk && t.unread; });
    });
  }

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
    return b.kpis.filter(function (k) { return !str(k.owner) && (k.roster === roster || str(k.project_id) === roster) && str(k.value) !== ""; })
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
    /* Working desks always lead, then waiting, then idle; signals only order inside a state. */
    var ra = STATE_RANK[a.state], rc = STATE_RANK[c.state];
    if (ra !== rc) return (ra == null ? 9 : ra) - (rc == null ? 9 : rc);
    var oa = (a.wait && a.wait.overDay) || 0, oc = (c.wait && c.wait.overDay) || 0;
    if (oa !== oc) return oc - oa;
    var fa = a.scores && a.scores.off ? 1 : 0, fc = c.scores && c.scores.off ? 1 : 0;
    if (fa !== fc) return fc - fa;
    var na = a.wait ? a.wait.letters + a.wait.cards : 0, nc = c.wait ? c.wait.letters + c.wait.cards : 0;
    if (na !== nc) return nc - na;
    return byName(a, c);
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
      oldLetters: live.filter(function (r) { return r.wait && r.wait.overDay; }).length,
      scoreOff: live.filter(function (r) { return r.scores && r.scores.off; }).length
    };
  }

  function deskDetail(b, name) {
    var d = b.byName[str(name)];
    if (!d) return null;
    var r = deskRow(b, d);
    var waiting = waitingOn(b, d.name);
    var attn = [];
    if (waiting) {
      waiting.slice(0, 3).forEach(function (m) {
        var age = m.at != null ? b.now - m.at : null;
        attn.push({ kind: "letter", id: "mail-" + m.id, title: "from " + m.from, note: firstLine(m.body, 140), when: dur(age),
          flag: age != null && age > DAY ? "over a day" : "", heat: age == null ? "" : age > 2 * DAY ? "older" : age > DAY ? "hot" : "" });
      });
    }
    var moreLetters = r.wait ? Math.max(0, r.wait.letters - (waiting ? Math.min(3, waiting.length) : 0)) : 0;
    var plist = prioList(b, d.name);
    (plist || []).slice(0, 3).forEach(function (p) {
      var current = r.on === "todo-" + p.id;
      attn.push({ kind: "prio", rank: p.pos, ord: p.ord, id: "todo-" + p.id, title: p.title,
        note: current ? "current doing" + (r.age ? " \u00b7 for " + r.age : "") : prioNote(p, d.name) });
    });
    if (b.cards) {
      b.cards.forEach(function (c) {
        if (c.status !== "claimed" || c.desk !== d.name) return;
        var lab = lastActivity(b, c.id);
        if (lab == null || b.now - lab <= STUCK_MS) return;
        attn.push({ kind: "card", id: "todo-" + c.id, title: c.title, flag: "stuck " + dur(b.now - lab), heat: "older",
          note: "claimed, no activity for " + dur(b.now - lab), when: dur(b.now - lab) });
      });
    }
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
      desk: r, attention: attn, moreLetters: moreLetters, lettersKnown: !!waiting,
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
        if (!t.unread || !t.desk || t.desk === "*" || b.offDesk(t.desk)) return;
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
      blocking.push({ key: "wait-" + d.name, kind: "wait", desk: d.name, title: d.name + " is waiting on " + on.replace(/^desk-/, ""), note: why });
    });
    var held = [];
    (holds || []).forEach(function (l) {
      if (b.offDesk(l.desk)) return;
      var d = b.byName[l.desk];
      var row = { key: "hold-" + l.id, kind: "hold", desk: l.desk, title: l.resource, id: l.id, note: "" };
      if (l.dead || !d || !d.connected) {
        row.note = l.dead ? "the holder is gone" : (d && d.lastSeenAt != null ? "held by an away desk, seen " + ago(b.now - d.lastSeenAt) : "held by a desk not seen in range");
        blocking.push(Object.assign({}, row, { title: l.resource }));
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

  /* ---- strip cards + summary line ---- */
  function strip(b, m) {
    var dk = m.desks, td = m.todo, ml = m.mail, pr = m.priorities, sc = m.score, cb = m.collab;
    var waiting = 0, waitKnown = false, overDay = 0;
    b.desks.forEach(function (d) { if (d.wait) { waitKnown = true; waiting += d.wait.letters; overDay += d.wait.overDay || 0; } });
    return [
      { tab: "desks", label: "DESKS", n: dk ? dk.connected.length : null, cue: dk ? dk.away.length + " away" : "", warn: !!(dk && dk.oldLetters) },
      { tab: "todo", label: "TODO", n: td ? td.open : null, cue: "open cards", warn: !!(td && td.attention) },
      { tab: "mail", label: "MAIL", n: ml ? ml.waiting : (waitKnown ? waiting : null), cue: "waiting", warn: ml ? !!ml.overDay : overDay > 0 },
      { tab: "priorities", label: "PRIORITIES", n: pr ? pr.lists : null, cue: "lists", warn: false },
      { tab: "score", label: "SCORE", n: sc ? sc.off : null, cue: "off target", warn: !!(sc && sc.off) },
      { tab: "collab", label: "COLLAB", n: cb ? cb.shared : null, cue: "shared", warn: !!(cb && cb.blocking) }
    ];
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function rosterText(sc) { return sc.rosters.join(" + "); }
  function rangeText(r) { return r === "today" ? "today" : r === "30d" ? "last 30 days" : "last 7 days"; }
  function hero(b, tab, m) {
    var R = rosterText(b.scope);
    if (tab === "todo" && m) return { lead: plural(m.open, "open card") + " on " + R + ".", rest: "Grouped by state across the roster. The desk is a chip on each card." };
    if (tab === "mail" && m) return { lead: plural(m.waiting, "letter") + " waiting on " + R + ", " + rangeText(b.scope.range) + ".", rest: "Grouped by who they wait on, oldest first." };
    if (tab === "priorities" && m) return { lead: plural(m.lists, "ranked list") + " on this scope.", rest: "One column per desk. Ranks are 1-based; the stored ord is on hover." };
    if (tab === "score" && m) return { lead: plural(m.off, "score") + " off target on " + R + ".", rest: "Grouped by impact. Desks are rows inside each group. Platform scores only." };
    if (tab === "collab" && m) return { lead: m.blocking ? plural(m.blocking, "thing") + " blocking someone now." : "Nothing is blocking anyone now.", rest: "Shared work on " + R + ": promises, rooms and card trees, grouped by kind." };
    if (tab === "desks" && m) {
      var bits = [];
      if (m.oldLetters) bits.push(m.oldLetters + " " + (m.oldLetters === 1 ? "has" : "have") + " letters older than a day.");
      if (m.scoreOff) bits.push(m.scoreOff + " " + (m.scoreOff === 1 ? "has" : "have") + " a doing score off target.");
      return { lead: plural(m.connected.length, "desk") + " here, " + m.away.length + " disconnected.", rest: bits.join(" ") };
    }
    return { lead: "Loading " + R + "\u2026", rest: "" };
  }

  global.WallRd = {
    base: base, desks: desks, deskDetail: deskDetail, todo: todo, mail: mail, priorities: priorities,
    score: score, collab: collab, feed: feed, strip: strip, hero: hero,
    normScope: normScope, kpiMiss: kpiMiss, kpiLabel: kpiLabel,
    dur: dur, ago: ago, msText: msText, utc: utc, firstLine: firstLine, itemOf: itemOf, rangeText: rangeText,
    SORTS: SORTS.slice(), RANGES: RANGES.slice()
  };
  global.WALL_UI_DEFAULT_RD_MODEL = "WALL_UI_DEFAULT_RD_MODEL";
})(typeof window !== "undefined" ? window : globalThis);
