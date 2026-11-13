/* WALL_UI_DEFAULT_RD_APP - wires the Wall redesign into the page: reads, scope, tabs, clicks.
 * Marker: WALL_UI_DEFAULT_RD_APP
 * Reads are plain GETs on the routes the Wall already uses. Each tab asks only for what it
 * paints; the strip counts fill in as the reads land. Scope is the station or roster picked on
 * the Wall's own left rail (boot.js calls railPick). The time range sits on the tabs it cuts.
 * TODO, MAIL, COLLAB and PRIORITIES host the Wall's own full panes (every view, filter and
 * click they had); this shell moves the pane in beside the strip and drives its view switch.
 * The other old panes (GUIDE, GLOSSARY, ADMIN, WIRE) still open from More; on those hashes
 * the old shell shows and this one steps aside. */
(function () {
  "use strict";
  var R = window.WallRd, V = window.WallRdView;
  var root = document.getElementById("rd");
  if (!root || !R || !V) return;

  var TABS = ["desks", "todo", "mail", "priorities", "score", "collab"];
  var ALIAS = {
    "": "", desks: "desks", session: "desks", here: "desks", jobs: "todo", todo: "todo", plan: "todo", trees: "todo",
    nest: "todo", backlog: "todo", board: "todo", issues: "todo", mail: "mail", priorities: "priorities",
    score: "score", scorecards: "score", floor: "collab", collab: "collab"
  };
  var NEEDS = {
    desks: ["labels", "scores", "todos", "holds", "mail", "events"],
    /* The hosted panes read their own data through boot.js; the strip counts come from fetchCounts. */
    todo: [], mail: [], priorities: [],
    score: ["scores", "runs"],
    /* COLLAB Replay: the rows come from /api/v1/replay (fetchReplay); these only name and tag
     * the items on them (card titles, promise names, letter first lines, labels, trees). */
    collab: ["mail", "todos", "holds", "labels", "trees", "rooms"]
  };
  var ROUTE = {
    agents: "/api/v1/agents?project=%R&limit=500",
    names: "/api/v1/names?project=%R&limit=500",
    todos: "/api/v1/todos?project=%R&limit=500",
    mail: "/api/v1/mailbox?project=%R&limit=500",
    labels: "/api/v1/labels?project=%R&limit=500",
    scores: "/api/v1/scores?project=%R&limit=500",
    holds: "/api/v1/holds?project=%R&limit=500",
    rooms: "/api/v1/rooms?project=%R",
    trees: "/api/v1/tree-todo?project=%R",
    events: "/api/v1/events?project=%R&limit=500",
    runs: "/api/v1/score-runs?project=%R&limit=300"
  };
  var PICK = {
    agents: function (j) { return j.agents; }, names: function (j) { return j.catalog; },
    todos: function (j) { return { needs: j.needs || [], issues: j.issues || [] }; },
    mail: function (j) { return j.mailbox; }, labels: function (j) { return { rows: j.rows || [], checks: j.checks || {} }; },
    scores: function (j) { return j.kpis; }, holds: function (j) { return j.locks; }, rooms: function (j) { return j.trees; },
    trees: function (j) { return j.trees; }, events: function (j) { return j.events; }, runs: function (j) { return j.rows; }
  };
  /* Tabs that host the Wall's own pane. views: the pane's view switch; attr: the old button
   * that switches it (TODO switches through setJobsView). */
  var HOSTED = {
    /* Kanban and List are one toggle over the same cards; Tree (how cards nest) is its own button. */
    todo: { pane: "pane-todo", legacy: "jobs", views: [{ key: "board", label: "Kanban" }, { key: "list", label: "List" }, { key: "nest", label: "Tree", alone: true }] },
    mail: { pane: "pane-mail", legacy: "mail", attr: "data-mail-view", views: [{ key: "rooms", label: "Rooms" }, { key: "letters", label: "Letters" }] },
    /* Replay is this shell's own; Timeline is the Wall's pane (the old Between ring is gone). */
    collab: { pane: "pane-floor", legacy: "floor", attr: "data-floor-mode", own: "all", views: [{ key: "desks", label: "Desks" }, { key: "activity", label: "Activity" }] },
    priorities: { pane: "pane-priorities", legacy: "priorities", views: [] }
  };
  /* Wide enough that TODO opens on Kanban; narrower opens on List (until the reader picks). */
  var WIDE_Q = "(min-width: 900px)";
  var TODO_VIEW_KEY = "rd-todo-view";
  /* Card 1193: these reads take ?window=1d|7d|30d on the tab that shows a time range. */
  var WINDOWED = { desks: ["agents"], score: ["scores"] };
  var WINDOW_Q = { today: "1d", "7d": "7d", "30d": "30d" };
  var FRESH_MS = { agents: 20000, names: 300000, todos: 30000, mail: 30000, labels: 60000, scores: 30000, holds: 30000, rooms: 120000, trees: 120000, events: 30000, runs: 60000 };
  var RANGE_KEY = "rd-range", TAB_KEY = "rd-tab", COLLAB_VIEW_KEY = "rd-collab-subtab", RP_COUNT_KEY = "rd-replay-count", RP_SPEED_KEY = "rd-replay-speed", RP_DIR_KEY = "rd-replay-dir-", RP_CLUSTER_KEY = "rd-replay-cluster-";

  var data = { agents: {}, names: {}, todos: {}, mail: {}, labels: {}, scores: {}, holds: {}, rooms: {}, trees: {}, events: {}, runs: {}, history: {}, replay: null, doing: null, stations: null, rosterList: null };
  var winData = {}, noWindow = {};
  var gotAt = {}, inflight = {};
  var state = { tab: "desks", legacy: false, pick: loadPick(), range: loadRange(), sel: {}, phoneDesk: false };

  function load(k, d) { try { var v = localStorage.getItem(k); return v == null || v === "" ? d : v; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  /* The rail pick boot.js saved for this tab ({kind: "project"|"lan"|"role", id}). */
  function loadPick() {
    var p = null;
    try { p = JSON.parse(sessionStorage.getItem("mill-rail-pick") || "null"); } catch (e) { p = null; }
    return p && p.kind && p.id ? { kind: String(p.kind), id: String(p.id) } : null;
  }
  function loadRange() {
    var r = {};
    try { r = JSON.parse(localStorage.getItem(RANGE_KEY) || "{}") || {}; } catch (e) { r = {}; }
    return r;
  }
  function rangeOf(tab) { return R.RANGES.indexOf(state.range[tab]) >= 0 ? state.range[tab] : "7d"; }
  /* Roster pick: that roster. Station pick: the desks seen at that station, on the Office roster. */
  function scope() {
    var p = state.pick, sc = { rosters: ["Office"], label: "Office", range: rangeOf(state.tab) };
    if (p && p.kind === "project") { sc.rosters = [p.id]; sc.label = p.id; }
    else if (p && p.kind === "lan") {
      sc.label = "station " + p.id;
      sc.only = (data.stations || []).filter(function (r) { return String(r.lan_ip || "").trim() === p.id; })
        .map(function (r) { return String(r.name || ""); });
    }
    return sc;
  }
  function rosters() { return scope().rosters; }
  function windowFor(kind, tab) {
    return WINDOWED[tab] && WINDOWED[tab].indexOf(kind) >= 0 && !noWindow[kind] ? WINDOW_Q[rangeOf(tab)] : "";
  }

  function getJson(url) {
    return fetch(url, { cache: "no-store", credentials: "same-origin" }).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }
  /* Labels are office-wide. The live mill answers GET /api/v1/labels only
   * with project=Office; a roster such as the-mill is a 400. Other parts
   * still use the focused roster. */
  function partRoster(kind, roster) {
    return kind === "labels" ? "Office" : roster;
  }
  function storePart(kind, roster, win, rows) {
    if (win) (winData[kind + "|" + win] || (winData[kind + "|" + win] = {}))[roster] = rows;
    else data[kind][roster] = rows;
  }
  function fetchPart(kind, roster, force, win) {
    win = win || "";
    var req = partRoster(kind, roster);
    var key = kind + "|" + req + "|" + win;
    if (inflight[key]) return inflight[key];
    if (!force && gotAt[key] && Date.now() - gotAt[key] < FRESH_MS[kind]) return Promise.resolve();
    var url = ROUTE[kind].replace("%R", encodeURIComponent(req)) + (win ? "&window=" + win : "");
    inflight[key] = getJson(url).then(function (j) {
      inflight[key] = null;
      if (j && !j.error) {
        var rows = PICK[kind](j) || [];
        storePart(kind, req, win, rows);
        if (roster !== req) storePart(kind, roster, win, rows);
        gotAt[key] = Date.now();
      } else if (win) {
        /* A server before card 1193 refuses the window; read the whole list and cut it here. */
        noWindow[kind] = true;
        return fetchPart(kind, roster, force, "");
      } else if (kind === "labels") {
        /* A 400 or a dropped read must not block the tab or retry every paint. */
        var empty = { rows: [], checks: {} };
        storePart(kind, req, win, empty);
        if (roster !== req) storePart(kind, roster, win, empty);
        gotAt[key] = Date.now();
      }
      paintSoon();
    }).catch(function () {
      inflight[key] = null;
      if (kind === "labels") {
        var empty = { rows: [], checks: {} };
        storePart(kind, req, win, empty);
        if (roster !== req) storePart(kind, roster, win, empty);
        gotAt[key] = Date.now();
      }
      paintSoon();
    });
    return inflight[key];
  }
  /* The data a tab paints from: its windowed reads where it has them, the full lists otherwise. */
  function dataFor(tab) {
    var out = Object.assign({}, data);
    (WINDOWED[tab] || []).forEach(function (kind) {
      var w = windowFor(kind, tab), got = w ? winData[kind + "|" + w] : null;
      if (got) out[kind] = Object.assign({}, data[kind], got);
    });
    return out;
  }
  function fetchCore(force) {
    var jobs = [];
    if (force || !gotAt.doing || Date.now() - gotAt.doing > 15000) {
      jobs.push(getJson("/api/v1/doing?all=1").then(function (j) {
        /* The same three shapes doing-paint.js accepts: a list, {desks}, {result}. */
        var list = Array.isArray(j) ? j : j && Array.isArray(j.desks) ? j.desks : j && Array.isArray(j.result) ? j.result : null;
        if (list) {
          var by = {};
          list.forEach(function (v) { if (v && v.owner) by[v.owner] = v; });
          data.doing = by;
          gotAt.doing = Date.now();
        }
        paintSoon();
      }));
      jobs.push(getJson("/api/pov?part=desks").then(function (j) {
        if (j && Array.isArray(j.rows)) data.stations = j.rows;
        paintSoon();
      }));
    }
    if (!data.rosterList) {
      jobs.push(getJson("/api/pov?part=rosters").then(function (j) {
        if (j && Array.isArray(j.rows)) data.rosterList = j.rows;
        paintSoon();
      }));
    }
    rosters().forEach(function (r) {
      jobs.push(fetchPart("agents", r, force));
      var w = windowFor("agents", state.tab);
      if (w) jobs.push(fetchPart("agents", r, force, w));
      jobs.push(fetchPart("names", r));
    });
    return Promise.all(jobs);
  }
  function fetchTab(tab, force) {
    var jobs = [];
    (NEEDS[tab] || []).forEach(function (k) {
      rosters().forEach(function (r) { jobs.push(fetchPart(k, r, force, windowFor(k, tab))); });
    });
    return Promise.all(jobs);
  }
  /* The strip counts every tab: after the open tab, read the small parts for the rest. */
  function fetchCounts() {
    ["todos", "labels", "scores", "holds", "mail", "rooms"].forEach(function (k) {
      rosters().forEach(function (r) { fetchPart(k, r); });
    });
  }
  function fetchHistory(desk) {
    if (!desk) return;
    var key = "history|" + desk;
    if (inflight[key] || (gotAt[key] && Date.now() - gotAt[key] < 30000)) return;
    inflight[key] = getJson("/api/v1/doing/history?desk=" + encodeURIComponent(desk)).then(function (j) {
      inflight[key] = null;
      if (j && Array.isArray(j.history)) { data.history[desk] = j.history; gotAt[key] = Date.now(); paintSoon(); }
    });
  }

  /* ---- paint ---- */
  var queued = false, last = {};
  function paintSoon() {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || setTimeout)(function () { queued = false; paint(); });
  }
  function setHtml(el, html, keyName) {
    if (!el || last[keyName] === html) return false;
    last[keyName] = html;
    var keep = [];
    el.querySelectorAll("[data-rd-scroll]").forEach(function (n) { keep.push([n.getAttribute("data-rd-scroll"), n.scrollTop, n.scrollLeft]); });
    el.innerHTML = html;
    keep.forEach(function (k) {
      var n = el.querySelector('[data-rd-scroll="' + k[0] + '"]');
      if (n) { n.scrollTop = k[1]; n.scrollLeft = k[2]; }
    });
    return true;
  }
  function models(b) {
    var m = {};
    m.desks = R.desks(b, { selected: state.sel.desks });
    m.todo = R.todo(b, { selected: state.sel.todo });
    m.mail = R.mail(b, { selected: state.sel.mail });
    m.priorities = R.priorities(b, { selected: state.sel.priorities });
    m.score = R.score(b, { selected: state.sel.score });
    m.collab = R.collab(b, { selected: state.sel.collab });
    return m;
  }
  function scrollWrap(name, cls, html, tag) {
    tag = tag || "div";
    return "<" + tag + ' class="' + cls + '" data-rd-scroll="' + name + '">' + html + "</" + tag + ">";
  }
  /* ---- hosted panes ---- */
  var homes = {}, todoMode = "";
  function legacy() { return window.WallLegacy || null; }
  function isWide() { return !!(window.matchMedia && window.matchMedia(WIDE_Q).matches); }
  function savedTodoView() { return R.todoView(load(TODO_VIEW_KEY, ""), isWide()); }
  function hostPane(tab) {
    var cfg = HOSTED[tab], el = cfg && document.getElementById(cfg.pane), slot = root.querySelector(".rd-host-body");
    if (!el || !slot || el.parentNode === slot) return el;
    if (!homes[cfg.pane]) homes[cfg.pane] = { parent: el.parentNode, next: el.nextSibling };
    slot.appendChild(el);
    return el;
  }
  /* Back where boot.js put them, for the old shell's own hashes. */
  function unhostAll() {
    Object.keys(homes).forEach(function (id) {
      var el = document.getElementById(id), home = homes[id];
      if (!el || !home.parent) return;
      if (home.next && home.next.parentNode === home.parent) home.parent.insertBefore(el, home.next);
      else home.parent.appendChild(el);
    });
    homes = {};
    todoMode = "";
  }
  function legacyTab() { return hosted(state.tab) ? HOSTED[state.tab].legacy : "session"; }
  /* Have boot.js paint and poll the pane on show (it owns the data for the hosted panes). */
  function syncLegacy() {
    var W = legacy();
    if (!W || !W.started || !W.showTab) return;
    var cfg = hosted(state.tab) ? HOSTED[state.tab] : null;
    var want = document.getElementById(cfg ? cfg.pane : "pane-session");
    if (want && !want.classList.contains("on")) W.showTab(legacyTab());
  }
  function syncTodoMode(el) {
    var W = legacy();
    if (!W || !W.started || !W.setJobsView || !el) return;
    var mode = savedTodoView();
    if (mode === todoMode) return;
    todoMode = mode;
    W.setJobsView(mode);
  }
  /* COLLAB's two subtabs, both drawn here on one replay clock: Desks (the stage) and Activity
   * (one heart-monitor line per desk). */
  function collabView() { return load(COLLAB_VIEW_KEY, "desks") === "activity" ? "activity" : "desks"; }
  /* The tab hosts its pane unless it is on a view this shell draws itself. */
  function hosted(tab) { var cfg = HOSTED[tab]; return !!cfg && cfg.own !== "all"; }
  function viewOn(tab) {
    if (tab === "todo") return savedTodoView();
    if (tab === "collab") return collabView();
    var cfg = HOSTED[tab], on = cfg.attr ? document.querySelector("[" + cfg.attr + "].on") : null;
    return on ? on.getAttribute(cfg.attr) : (cfg.views[0] && cfg.views[0].key);
  }
  function paintHosted(b) {
    var t = state.tab, cfg = HOSTED[t];
    root.querySelector(".rd-pane").hidden = true;
    root.querySelector(".rd-host").hidden = false;
    var el = hostPane(t);
    syncLegacy();
    if (t === "todo") syncTodoMode(el);
    setHtml(root.querySelector(".rd-host-head"), V.hostHead(t, b, cfg.views, viewOn(t)), "host");
    root.setAttribute("data-rd-host", t);
  }
  var lastBase = null;
  function rpBase() { return lastBase; }
  function paint() {
    if (state.legacy) return;
    var now = Date.now();
    var b = R.base(dataFor(state.tab), scope(), now);
    lastBase = b;
    var m = models(b);
    setHtml(root.querySelector(".rd-strip"), V.strip(R.strip(b, m), state.tab), "strip");
    setHtml(root.querySelector(".rd-hero"), V.hero(R.hero(b, state.tab, m[state.tab])), "hero");
    var t = state.tab, html;
    if (hosted(t)) { paintHosted(b); return; }
    root.removeAttribute("data-rd-host");
    root.querySelector(".rd-host").hidden = true;
    var pane = root.querySelector(".rd-pane");
    pane.hidden = false;
    syncLegacy();
    if (t === "desks") {
      var dm = m.desks;
      state.sel.desks = dm.selected;
      var dd = dm.selected ? R.deskDetail(b, dm.selected) : null;
      if (dm.selected) fetchHistory(dm.selected);
      html = V.paneHead("desks", b) +
        '<div class="rd-pane-body"><div class="rd-here-split">' +
        '<div class="rd-here-col">' + scrollWrap("here", "rd-here", V.desksList(dm, now)) + "</div>" +
        scrollWrap("desk", "rd-here-desk", V.deskDetail(dd, now), "aside") +
        scrollWrap("feed", "rd-office-feed", V.feed(R.feed(b)), "aside") + "</div></div>";
    } else if (t === "collab") {
      rp.view = collabView();
      html = V.paneHead("collab", b, V.viewSwitch(HOSTED.collab.views, rp.view)) +
        '<div class="rd-pane-body rd-collab-body">' + V.replay(replayModel(b), rp) + "</div>";
    } else {
      var model = m[t];
      var body = model ? V[t](model) : '<div class="rd-loading">Loading ' + t.toUpperCase() + "\u2026</div>";
      if (model && model.selected) state.sel[t] = model.selected;
      html = V.paneHead(t, b) + '<div class="rd-pane-body rd-tab-body">' + body + "</div>";
      html = html.replace('class="rd-tab-groups', 'data-rd-scroll="groups" class="rd-tab-groups').replace('<aside class="rd-tab-detail"', '<aside data-rd-scroll="detail" class="rd-tab-detail"');
    }
    pane.setAttribute("data-rd-pane", t);
    var fresh = setHtml(pane, html, "pane");
    if (t === "collab") { if (fresh) rp.drawn = null; drawReplay(false); fetchReplay(); }
    root.classList.toggle("rd-desk-open", t === "desks" && state.phoneDesk);
  }


  /* ---- COLLAB replay: the same rows, two views, one clock ----
   * Parked at the end (the default) the items sit still at their age for now. Play rewinds
   * the window and walks the playhead forward in R.REPLAY_PLAY_MS / speed. Position is a
   * function of the playhead, the item's time and the span: nothing else moves. */
  var rp = { playing: false, t: null, t0: 0, wall0: 0, rep: null, raf: 0, drawn: null, speed: Number(load(RP_SPEED_KEY, "1")) || 1,
    view: "desks", lastT: null, st: null, live: 0, dirs: { desks: dirOf("desks"), activity: dirOf("activity") },
    clusters: { desks: clusterOf("desks"), activity: clusterOf("activity") } };
  /* Each subtab keeps its own direction; both start left to right. */
  function dirOf(view) { var v = load(RP_DIR_KEY + view, R.REPLAY_DIR_DEFAULT[view]); return v === "tb" ? "tb" : "lr"; }
  /* Display: group is the default; spread is the alternate. Each subtab remembers its own. */
  function clusterOf(view) { return R.replayCluster(load(RP_CLUSTER_KEY + view, R.REPLAY_CLUSTER_DEFAULT[view])); }
  function rpAxis() { return R.replayAxis(rp.dirs[rp.view]); }
  if (R.REPLAY_SPEEDS.indexOf(rp.speed) < 0) rp.speed = 1;
  function replayModel(b) {
    var rep = R.collabReplay(b, { count: R.replayCount(load(RP_COUNT_KEY, String(R.REPLAY_COUNT_DEFAULT))), end: rp.end });
    if (!rp.playing) rp.rep = rep;
    return rep;
  }
  function rpRep() { return rp.rep; }
  /* Playhead in office time: the 2 min playback advances at a constant
   * rate along the display axis, so a squeezed void is crossed quickly.
   * When the scale is linear this is the same as span/REPLAY_PLAY_MS. */
  function rpNow() {
    var rep = rpRep();
    if (!rep) return null;
    if (!rp.playing) return rp.t == null ? rep.until : rp.t;
    var scale = R.replayScale && R.replayScale(rep);
    if (scale && R.replayPlayhead) {
      return Math.min(rep.until, R.replayPlayhead(scale, rp.t0, Date.now() - rp.wall0, rp.speed));
    }
    return Math.min(rep.until, rp.t0 + (Date.now() - rp.wall0) * rp.speed * (rep.ms / R.REPLAY_PLAY_MS));
  }
  function drawReplay(animate) {
    var rep = rpRep();
    if (!rep) return;
    var t = rpNow();
    var clockEl = root.querySelector("[data-rp-clock]"), play = root.querySelector("[data-rp-play]");
    /* The overview: the viewport box is the slice the big pane shows ([t - span, t]); the
     * lit bars run up to the playhead. */
    var ovEl = root.querySelector("[data-rp-ov]");
    if (ovEl) {
      var vp = R.replayViewport(rep, t, { lo: Number(ovEl.getAttribute("data-lo")), hi: Number(ovEl.getAttribute("data-hi")) });
      var box = ovEl.querySelector("[data-rp-vp]"), head = ovEl.querySelector("[data-rp-head]"), clip = ovEl.querySelector("[data-rp-clip]");
      if (box) { box.setAttribute("x", (vp.lo * 1000).toFixed(1)); box.setAttribute("width", Math.max(2, (vp.hi - vp.lo) * 1000).toFixed(1)); }
      if (head) { head.setAttribute("x1", (vp.at * 1000).toFixed(1)); head.setAttribute("x2", (vp.at * 1000).toFixed(1)); }
      if (clip) clip.setAttribute("width", (vp.at * 1000).toFixed(1));
      ovEl.setAttribute("aria-valuenow", String(Math.round(1000 * vp.at)));
      var back = root.querySelector("[data-rp-ov-dir='-1']"), fwd = root.querySelector("[data-rp-ov-dir='1']");
      if (back && R.replayPanCan) back.disabled = !R.replayPanCan(rep, rp.end, -1) && !rep.more;
      if (fwd && R.replayPanCan) fwd.disabled = !R.replayPanCan(rep, rp.end, 1);
    }
    var span = root.querySelector("[data-rp-span]");
    if (span) span.textContent = spanText(rep);
    if (clockEl) { var d = new Date(t); clockEl.textContent = (rp.t == null && !rp.playing ? "now " : "") + d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }); }
    if (play) { play.textContent = rp.playing ? "\u23f8" : "\u25b6"; play.setAttribute("aria-label", rp.playing ? "Pause" : "Play"); }
    /* In the past, each pill takes its desk's state at the playhead from the recorded state
     * changes; at now it keeps the current state the row was drawn with. */
    var sec = root.querySelector(".rd-replay");
    if (sec) {
      var past = rp.playing || rp.t != null || rep.live === false;
      sec.classList.toggle("rd-rp-past", past);
      sec.classList.toggle("rd-rp-playing", !!rp.playing);
      if (past) {
        var memo = {};
        sec.querySelectorAll(".rd-pill[data-rd-desk]").forEach(function (el) {
          var n = el.getAttribute("data-rd-desk");
          if (!(n in memo)) memo[n] = R.replayStateAt(rep, n, t) || "unknown";
          if (el.getAttribute("data-st") !== memo[n]) { el.setAttribute("data-st", memo[n]); el.title = n + ", " + (memo[n] === "unknown" ? "no state recorded yet" : memo[n]) + " then"; }
          /* Doing is time spent: the bar under the pill grows from the focus start, full at a quarter window. */
          var since = R.replaySince(rep, n, t);
          el.style.setProperty("--dw", since == null ? "0" : String(Math.min(1, (t - since) / (rep.ms / 4)).toFixed(3)));
        });
      }
    }
    drawStage(rep, t, animate);
    tipTick();
  }
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  function moving() { return !(still && still.matches); }
  /* ---- Age is position: the items of both subtabs ----
   * Every frame the items on screen come from R.replayItemsAt(rep, t): an activity enters at its
   * lane (each desk in its state) when the playhead reaches it and sits as far out along the
   * lane as it is old, across the whole stage, leaving at the far edge one span later. Scrub
   * either way and it is put back. Motion is transform and opacity only. A two-desk transition
   * is joined by a line while it is young. Each item carries one chip; the rest is on hover. */
  var RP_ITEMS = 360, RP_ICON = 14, rpText = {};
  function stageEls() {
    var field = root.querySelector("[data-rp-field]");
    if (!field) return null;
    if (rp.st && rp.st.field === field) return rp.st;
    var st = root.querySelector(".rd-rp-stage[data-rp-lanes]"), lanes = {};
    root.querySelectorAll(".rd-replay [data-lane]").forEach(function (el) {
      lanes[el.getAttribute("data-lane")] = { head: el, pill: el.firstElementChild, locks: el.querySelector("[data-rp-locks]") };
    });
    root.querySelectorAll(".rd-replay [data-col]").forEach(function (el) {
      var id = el.getAttribute("data-col");
      (lanes[id] = lanes[id] || {}).track = el;
    });
    if (st) st.style.setProperty("--lanes", String(Object.keys(lanes).length || 1));
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "rd-rp-links");
    svg.setAttribute("aria-hidden", "true");
    field.appendChild(svg);
    rp.st = { el: st, field: field, lanes: lanes, locks: "", waits: "", items: {}, spans: {}, geo: null, svg: svg, links: "" };
    return rp.st;
  }
  /* Each lane's place in the field: its centre across the flow, and where along the flow its
   * items start and how far they may travel (the whole stage, or the lane's own track). */
  function rpGeom(S) {
    var ax = rpAxis(), fb = S.field.getBoundingClientRect(), key = [Math.round(fb.width), Math.round(fb.height), ax.dir].join(",");
    if (S.geo && S.geo.key === key) return S.geo;
    var g = { key: key, ax: ax, lanes: {} };
    Object.keys(S.lanes).forEach(function (id) {
      var l = S.lanes[id], ref = l.track || l.head;
      if (!ref) return;
      var r = ref.getBoundingClientRect(), start, len;
      var cross = ax.cross === "x" ? r.left + r.width / 2 - fb.left : r.top + r.height / 2 - fb.top;
      if (l.track) { start = ax.main === "x" ? r.left - fb.left : r.top - fb.top; len = ax.main === "x" ? r.width : r.height; }
      else { start = 4; len = (ax.main === "x" ? fb.width : fb.height) - 8; }
      var room = l.track ? (ax.main === "x" ? r.height : r.width) : (ax.main === "x" ? 40 : 72);
      g.lanes[id] = { cross: cross, start: start, len: Math.max(0, len - RP_ICON), room: room };
    });
    S.geo = g;
    return g;
  }
  function rowText(r) {
    if (!rpText[r.key]) { var d = document.createElement("div"); d.innerHTML = V.replayRows([r]); rpText[r.key] = (d.textContent || "").replace(/\s+/g, " ").trim(); }
    return rpText[r.key];
  }
  /* One chip at most: its first label, else its tree, else a watcher, else its roster. */
  function firstTag(tags) {
    if (!tags) return null;
    if (tags.labels.length) return { labels: [tags.labels[0]], trees: [], watchers: [], roster: "" };
    if (tags.trees.length) return { labels: [], trees: [tags.trees[0]], watchers: [], roster: "" };
    if ((tags.watchers || []).length) return { labels: [], trees: [], watchers: [tags.watchers[0]], roster: "" };
    return null;
  }
  function icon(kind, cls, title, tags) {
    var el = document.createElement("span");
    el.className = ((cls || "").indexOf("rd-rp-lock") >= 0 ? "" : "rd-rp-item ") + cls;
    el.innerHTML = V.kindIcon(kind);
    if ((cls || "").indexOf("rd-rp-lock") >= 0 && title) el.setAttribute("data-lock-text", title);
    var one = firstTag(tags);
    if (one) {
      var w = document.createElement("span");
      w.innerHTML = V.tagsHtml(one, 1);
      var chip = w.firstChild;
      chip.className += " rd-tags-mini";
      el.appendChild(chip);
    }
    return el;
  }
  function laneWord(id) {
    return id === "@out" ? "outside" : id === "@office" ? "office" : id === "@human" ? "you" : (id || "");
  }
  function nameChip(id, t, kind) {
    var s = document.createElement("span"), st = id && id.charAt(0) !== "@" ? (R.replayStateAt(rpRep(), id, t) || "") : "";
    s.className = "rd-dnm" + (kind ? " k-" + kind : "") + (st ? " st-" + st : "") + (id === "@out" ? " rd-cloud-nm" : "");
    s.textContent = laneWord(id);
    return s;
  }
  /* Activity view: one small desk-name chip, or from->to when two desks share the instance. */
  function tickItem(kind, extra) {
    var el = document.createElement("span");
    el.className = "rd-rp-item rd-rp-tick k-" + kind + (extra ? " " + extra : "");
    el.innerHTML = '<i class="rd-rp-hash" aria-hidden="true"></i>';
    return el;
  }
  function deskItem(it, t) {
    var el = document.createElement("span"), r = it.row, f = r.flows && r.flows[0];
    var a = f && f.from !== f.to ? f.from : (r.lane || (f && f.from) || r.actor);
    var b = f && f.from !== f.to ? f.to : "";
    el.className = "rd-rp-item rd-rp-dchip k-" + it.kind;
    var chip = nameChip(a, t, it.kind);
    if (b) chip.textContent = laneWord(a) + "\u2192" + laneWord(b);
    el.appendChild(chip);
    return el;
  }

  var TIP_ID = "rd-rp-tip", tipOn = null;
  function tipHost() { return closest(root.querySelector("[data-rp-stage]"), ".rd-pane") || root; }
  function tipEl() {
    var host = tipHost(), el = (host && host.querySelector("#" + TIP_ID)) || root.querySelector("#" + TIP_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = TIP_ID;
      el.className = "rd-rp-tip";
      el.setAttribute("role", "tooltip");
      el.hidden = true;
      (host || root).appendChild(el);
    } else if (host && el.parentNode !== host) host.appendChild(el);
    return el;
  }
  function tipTarget(t) { return closest(t, "[data-rp-tip]"); }
  function prepItem(el, it) {
    el.tabIndex = 0;
    el.setAttribute("data-rp-tip", "item");
    el.removeAttribute("title");
    el.rdRow = it && it.row ? it.row : it;
    var lab = ((it && it.kind) || (el.rdRow && el.rdRow.kind) || "") + (el.rdRow && el.rdRow.text ? ", " + el.rdRow.text : "");
    if (lab) el.setAttribute("aria-label", lab);
  }
  function hideTip() {
    var t = root.querySelector("#" + TIP_ID);
    if (tipOn && tipOn.el) tipOn.el.removeAttribute("aria-describedby");
    tipOn = null;
    applyLinkHot(null);
    if (t) { t.hidden = true; t.style.left = ""; t.style.top = ""; }
  }
  function placeTip(x, y, anchor) {
    var tip = tipEl();
    tip.style.left = "0px";
    tip.style.top = "0px";
    var w = tip.offsetWidth || 160, h = tip.offsetHeight || 80, pad = 8, left, top;
    if (anchor) {
      left = anchor.left;
      top = anchor.bottom + 8;
      if (top + h + pad > window.innerHeight) top = anchor.top - h - 8;
      if (left + w + pad > window.innerWidth) left = window.innerWidth - w - pad;
    } else {
      left = x + 14;
      top = y + 18;
      if (left + w + pad > window.innerWidth) left = x - w - 12;
      if (top + h + pad > window.innerHeight) top = y - h - 12;
    }
    left = Math.max(pad, Math.min(left, window.innerWidth - w - pad));
    top = Math.max(pad, Math.min(top, window.innerHeight - h - pad));
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }
  function laneWinCount(rep, t, laneId) {
    if (!rep || !laneId) return 0;
    var n = 0, items = R.replayItemsAt(rep, t, RP_ITEMS, rp.view).items, i;
    for (i = 0; i < items.length; i++) if (items[i].lane === laneId) n++;
    return n;
  }
  function fillTip(el) {
    var tip = tipEl(), html = "", kind = el.getAttribute("data-rp-tip"), id, name, k, row;
    if (kind === "lane") {
      id = (closest(el, "[data-lane]") || {}).getAttribute ? closest(el, "[data-lane]").getAttribute("data-lane") : "";
      name = (el.getAttribute("data-rd-desk") || el.getAttribute("aria-label") || el.textContent || id).replace(/\s+/g, " ").trim();
      k = el.classList.contains("rd-kind") ? id : "";
      html = V.replayLaneTip({ name: name, kind: k || undefined, count: laneWinCount(rpRep(), rpNow(), id) });
    } else if (kind === "group" || kind === "more") {
      var list = (el.rdGroup && el.rdGroup.items) || (el.rdOverflow && el.rdOverflow.items) || [];
      var rows = list.map(function (it) { return it.row || it; }).filter(Boolean);
      if (!rows.length) return false;
      html = rows.length === 1 ? V.replayTip(rows[0], rpNow()) : V.replayOverflowTip(rows, rpNow());
    } else {
      row = el.rdRow;
      if (!row) return false;
      html = V.replayTip(row, rpNow(), el.rdSpan || null);
    }
    if (!html) return false;
    tip.innerHTML = html;
    tip.hidden = false;
    el.setAttribute("aria-describedby", TIP_ID);
    return true;
  }
  function showTip(el, ev, fromFocus) {
    if (!el || dragTrace) return;
    if (tipOn && tipOn.el && tipOn.el !== el) tipOn.el.removeAttribute("aria-describedby");
    if (!fillTip(el)) { hideTip(); return; }
    var ptr = ev && ev.clientX != null ? { x: ev.clientX, y: ev.clientY } : (tipOn && tipOn.ptr) || null;
    tipOn = { el: el, ptr: fromFocus ? null : ptr, fromFocus: !!fromFocus };
    applyLinkHot(el);
    if (fromFocus || !ptr) placeTip(0, 0, el.getBoundingClientRect());
    else placeTip(ptr.x, ptr.y);
  }
  function tipTick() {
    if (!tipOn) return;
    if (!tipOn.el || !tipOn.el.isConnected) { hideTip(); return; }
    if (!tipOn.fromFocus && tipOn.ptr && document.elementFromPoint) {
      var under = document.elementFromPoint(tipOn.ptr.x, tipOn.ptr.y), el = under && tipTarget(under);
      if (!el) { hideTip(); return; }
      if (el !== tipOn.el) { showTip(el, { clientX: tipOn.ptr.x, clientY: tipOn.ptr.y }, false); return; }
    }
    fillTip(tipOn.el);
    applyLinkHot(tipOn.el);
    if (tipOn.fromFocus) placeTip(0, 0, tipOn.el.getBoundingClientRect());
    else if (tipOn.ptr) placeTip(tipOn.ptr.x, tipOn.ptr.y);
  }
  /* Hovering a tick or a line lights that activity's desk-to-desk line
   * and quiets the others a little. */
  function linkKeysOf(el) {
    if (!el) return [];
    var kind = el.getAttribute("data-rp-tip"), keys = [], list, i, it;
    if (kind === "link") {
      if (el.getAttribute("data-rp-key")) keys.push(el.getAttribute("data-rp-key"));
      return keys;
    }
    if (kind === "group" || kind === "more") {
      list = (el.rdGroup && el.rdGroup.items) || (el.rdOverflow && el.rdOverflow.items) || [];
      for (i = 0; i < list.length; i++) {
        it = list[i];
        if (it && it.key) keys.push(it.key);
        else if (it && it.row && it.row.key) keys.push(it.row.key);
      }
      return keys;
    }
    if (el.rdRow && el.rdRow.key) keys.push(el.rdRow.key);
    return keys;
  }
  function applyLinkHot(el) {
    var svg = root.querySelector(".rd-rp-links");
    if (!svg) return;
    var keys = linkKeysOf(el), i, on = {};
    for (i = 0; i < keys.length; i++) on[keys[i]] = 1;
    svg.classList.toggle("is-hot", keys.length > 0);
    Array.prototype.forEach.call(svg.querySelectorAll("path[data-rp-key]"), function (p) {
      p.classList.toggle("is-hot", !!on[p.getAttribute("data-rp-key")]);
    });
  }
  function bindLinkTips(S) {
    var by = {}, pool = (rpRep() && rpRep().pool) || [], i;
    for (i = 0; i < pool.length; i++) by[pool[i].key] = pool[i];
    Array.prototype.forEach.call(S.svg.querySelectorAll('[data-rp-tip="link"]'), function (p) {
      p.rdRow = by[p.getAttribute("data-rp-key")] || null;
    });
  }
  function fitItem(el, ax, room) {
    if (ax.main === "x") { el.style.maxWidth = "16ch"; el.style.maxHeight = ""; }
    else { el.style.maxWidth = Math.max(16, room || 72) + "px"; el.style.maxHeight = ""; }
  }
  function applyLanePitch(S, ax, pitch) {
    if (!S.el) return;
    var ids = [];
    S.el.querySelectorAll("[data-lane]").forEach(function (el) { ids.push(el.getAttribute("data-lane")); });
    var tmpl = ids.map(function (id) { return Math.round(pitch[id] || 40) + "px"; }).join(" ");
    if (S.pitch === tmpl) return;
    S.pitch = tmpl;
    var heads = S.el.querySelector(".rd-rp-heads"), rain = S.el.querySelector(".rd-rp-rain");
    var prop = ax.main === "x" ? "gridTemplateRows" : "gridTemplateColumns";
    var clr = ax.main === "x" ? "gridTemplateColumns" : "gridTemplateRows";
    [heads, rain].forEach(function (el) { if (!el) return; el.style[prop] = tmpl; el.style[clr] = ""; });
    if (ax.main === "y") {
      var sum = ids.reduce(function (n, id) { return n + (pitch[id] || 40); }, 0) + "px";
      if (heads) heads.style.minWidth = sum;
      if (rain) rain.style.minWidth = sum;
    }
    S.geo = null;
  }
  function moreChip(ov) {
    var el = document.createElement("button");
    el.type = "button";
    el.className = "rd-rp-item rd-rp-more";
    el.textContent = "+" + ov.n;
    el.tabIndex = 0;
    el.setAttribute("data-rp-tip", "more");
    el.setAttribute("aria-label", "+" + ov.n + " more");
    el.rdOverflow = ov;
    return el;
  }
  function groupMark(g) {
    var el = tickItem(g.kind, "rd-rp-group");
    if (g.n > 1) {
      var n = document.createElement("span");
      n.className = "rd-rp-gn";
      n.textContent = String(g.n);
      el.appendChild(n);
    }
    el.tabIndex = 0;
    el.setAttribute("data-rp-tip", "group");
    el.setAttribute("aria-label", g.n + " " + g.kind);
    el.style.setProperty("--rd-gs", String(g.scale));
    el.rdGroup = g;
    return el;
  }
  function clearMore(S, keep) {
    S.more = S.more || {};
    Object.keys(S.more).forEach(function (id) {
      if (keep && keep[id]) return;
      var el = S.more[id];
      if (el && el.parentNode) el.parentNode.removeChild(el);
      delete S.more[id];
    });
  }
  function placePacked(S, ax, items, pack, sizes) {
    var g = rpGeom(S);
    items.forEach(function (it) {
      var L = g.lanes[it.lane], el = S.items[it.id], p = pack.place[it.id];
      if (!L || !el) return;
      if (p && p.hide) { el.hidden = true; el.style.opacity = "0"; return; }
      el.hidden = false;
      var sz = sizes[it.id] || { main: RP_ICON, cross: RP_ICON };
      var rows = pack.rows[it.lane] || 1, rowH = L.room / rows, row = p ? p.row : 0;
      var origin = L.cross - L.room / 2;
      var c = origin + row * rowH + Math.max(0, (rowH - sz.cross) / 2);
      var m = L.start + it.pos * L.len;
      var tf = ax.main === "x" ? "translate(" + m.toFixed(1) + "px," + c.toFixed(1) + "px)" : "translate(" + c.toFixed(1) + "px," + m.toFixed(1) + "px)";
      var POP = ((R.REPLAY_LEAD_PLAY_MS || 1250) / 4) / (R.REPLAY_PLAY_MS || 120000);
      var pop = it.pos < POP ? (0.55 + 0.45 * (it.pos / POP)) : 1;
      if (!moving()) pop = 1;
      if (pop !== 1) tf += " scale(" + pop.toFixed(3) + ")";
      if (el.rdTf !== tf) { el.style.transform = tf; el.rdTf = tf; }
      var op;
      if (it.pos > 0.92) op = ((1 - it.pos) / 0.08).toFixed(2);
      else if (it.pos < POP) op = Math.max(0.4, it.pos / POP).toFixed(2);
      else op = "1";
      if (el.rdOp !== op) { el.style.opacity = op; el.rdOp = op; }
    });
    return g;
  }
  function measureItems(S, ids, ax) {
    var sizes = {};
    ids.forEach(function (id) {
      var el = S.items[id];
      if (!el) return;
      sizes[id] = ax.main === "x"
        ? { main: el.offsetWidth || RP_ICON, cross: el.offsetHeight || RP_ICON }
        : { main: el.offsetHeight || RP_ICON, cross: Math.min(el.offsetWidth || RP_ICON, 72) };
    });
    return sizes;
  }
  function packAndGrow(S, ax, items, sizes) {
    var g0 = rpGeom(S);
    var pack = R.replayPack(items, {
      maxRows: R.REPLAY_PACK_ROWS,
      sizeOf: function (it) { return sizes[it.id] || { main: RP_ICON, cross: RP_ICON }; },
      lenOf: function (it) { return (g0.lanes[it.lane] && g0.lanes[it.lane].len) || 1; }
    });
    var pitch = {};
    Object.keys(g0.lanes).forEach(function (id) {
      var rows = pack.rows[id] || 1, xh = 16;
      items.forEach(function (it) {
        var p = pack.place[it.id];
        if (it.lane === id && sizes[it.id] && (!p || !p.hide)) xh = Math.max(xh, sizes[it.id].cross);
      });
      pitch[id] = Math.max(40, rows * (xh + 4) + 8);
    });
    if (S.doingNeed) Object.keys(S.doingNeed).forEach(function (id) {
      pitch[id] = Math.max(pitch[id] || 40, S.doingNeed[id]);
    });
    applyLanePitch(S, ax, pitch);
    return pack;
  }
  function drawSpreadItems(S, rep, t, ax, got, seen) {
    var g = rpGeom(S);
    got.items.forEach(function (it) {
      var L = g.lanes[it.lane];
      if (!L) return;
      var el = S.items[it.id];
      if (!el || el.rdGroup) {
        if (el && el.parentNode) el.parentNode.removeChild(el);
        el = S.items[it.id] = tickItem(it.kind);
        prepItem(el, it);
        S.field.appendChild(el);
      } else el.rdRow = it.row;
      seen[it.id] = 1;
      el.hidden = false;
      fitItem(el, ax, L.room);
    });
    var sizes = measureItems(S, Object.keys(seen), ax);
    var pack = packAndGrow(S, ax, got.items.filter(function (it) { return !!rpGeom(S).lanes[it.lane]; }), sizes);
    placePacked(S, ax, got.items, pack, sizes);
    S.more = S.more || {};
    var keep = {};
    pack.overflow.forEach(function (ov) {
      keep[ov.id] = 1;
      var el = S.more[ov.id];
      if (!el) { el = S.more[ov.id] = moreChip(ov); S.field.appendChild(el); }
      else { el.rdOverflow = ov; el.textContent = "+" + ov.n; el.setAttribute("aria-label", "+" + ov.n + " more"); }
      /* Place the +N as a virtual item on the overflow strip. */
      var fake = { id: ov.id, lane: ov.lane, pos: ov.pos };
      sizes[ov.id] = ax.main === "x" ? { main: el.offsetWidth || 22, cross: el.offsetHeight || 16 } : { main: el.offsetHeight || 16, cross: el.offsetWidth || 22 };
      S.items[ov.id] = el;
      pack.place[ov.id] = { row: ov.row, hide: false };
      seen[ov.id] = 1;
      placePacked(S, ax, [fake], pack, sizes);
      delete S.items[ov.id];
    });
    clearMore(S, keep);
  }
  function drawGroupItems(S, rep, t, ax, got, seen) {
    var marks = R.replayGroup(got.items, { span: rep.ms, buckets: R.REPLAY_GROUP_BUCKETS });
    var g = rpGeom(S);
    marks.forEach(function (m) {
      var L = g.lanes[m.lane];
      if (!L) return;
      var el = S.items[m.id], it = m.items[0];
      if (m.n === 1) {
        if (!el || el.rdGroup) {
          if (el && el.parentNode) el.parentNode.removeChild(el);
          el = S.items[m.id] = tickItem(it.kind);
          prepItem(el, it);
          S.field.appendChild(el);
        } else el.rdRow = it.row;
      } else {
        if (!el || !el.rdGroup) {
          if (el && el.parentNode) el.parentNode.removeChild(el);
          el = S.items[m.id] = groupMark(m);
          S.field.appendChild(el);
        } else {
          el.rdGroup = m;
          var gn = el.querySelector(".rd-rp-gn");
          if (gn && gn.textContent !== String(m.n)) gn.textContent = String(m.n);
          el.style.setProperty("--rd-gs", String(m.scale));
          el.setAttribute("aria-label", m.n + " " + m.kind);
        }
      }
      seen[m.id] = 1;
      el.hidden = false;
      fitItem(el, ax, L.room);
    });
    var packed = marks.filter(function (m) { return !!rpGeom(S).lanes[m.lane]; });
    var sizes = measureItems(S, packed.map(function (m) { return m.id; }), ax);
    var pack = packAndGrow(S, ax, packed, sizes);
    placePacked(S, ax, packed, pack, sizes);
    clearMore(S, {});
  }
  function drawItems(S, rep, t) {
    var g = rpGeom(S), ax = g.ax, got = R.replayItemsAt(rep, t, RP_ITEMS, rp.view), seen = {};
    var spans = R.replayDoingSpans ? R.replayDoingSpans(rep, t, rp.view) : [];
    S.doingNeed = {};
    spans.forEach(function (sp) {
      S.doingNeed[sp.lane] = Math.max(S.doingNeed[sp.lane] || 40, ((sp.rowIndex || 0) + 1) * 8 + 20);
    });
    var mode = (rp.clusters && rp.clusters[rp.view]) === "spread" ? "spread" : "group";
    if (mode === "spread") drawSpreadItems(S, rep, t, ax, got, seen);
    else drawGroupItems(S, rep, t, ax, got, seen);
    drawDoingSpans(S, ax, spans);
    Object.keys(S.items).forEach(function (id) {
      if (seen[id]) return;
      var el = S.items[id];
      if (el && el.parentNode) el.parentNode.removeChild(el);
      delete S.items[id];
    });
    g = rpGeom(S);
    var paths = got.links.map(function (k) {
      var A = g.lanes[k.from], B = g.lanes[k.to];
      if (!A || !B) return "";
      var ma = A.start + k.pos * A.len + RP_ICON / 2, mb = B.start + k.pos * B.len + RP_ICON / 2, bend = 10 + Math.min(40, Math.abs(B.cross - A.cross) / 6);
      var d = ax.main === "x" ? "M" + ma.toFixed(1) + " " + A.cross.toFixed(1) + " Q" + ((ma + mb) / 2 + bend).toFixed(1) + " " + ((A.cross + B.cross) / 2).toFixed(1) + " " + mb.toFixed(1) + " " + B.cross.toFixed(1)
        : "M" + A.cross.toFixed(1) + " " + ma.toFixed(1) + " Q" + ((A.cross + B.cross) / 2).toFixed(1) + " " + ((ma + mb) / 2 + bend).toFixed(1) + " " + B.cross.toFixed(1) + " " + mb.toFixed(1);
      var op = (0.9 * (k.fade != null ? k.fade : 1)).toFixed(2);
      var key = k.key || (k.id && k.id.split(">")[0]) || "";
      return '<path class="k-' + k.kind + '" data-rp-key="' + key + '" stroke-opacity="' + op + '" d="' + d + '"/>' +
        '<path class="rd-rp-hit" data-rp-tip="link" data-rp-key="' + key + '" d="' + d + '"/>';
    }).join("");
    if (paths !== S.links) {
      S.links = paths;
      S.svg.innerHTML = paths;
      bindLinkTips(S);
    }
    if (tipOn && tipOn.el) applyLinkHot(tipOn.el);
  }
  function drawStage(rep, t, animate) {
    var S = stageEls();
    if (!S) { rp.lastT = t; return; }
    /* Locks: held promises (solid) and waited-on ones (faded, amber edge) fade in and out
     * beside the pill, never over it. */
    var L = R.replayLocksAt(rep, t), ls = JSON.stringify(L);
    if (ls !== S.locks) {
      S.locks = ls;
      Object.keys(S.lanes).forEach(function (id) {
        var box = S.lanes[id].locks, want = {}, have = {};
        if (!box) return;
        (L[id] || []).forEach(function (x) { want[x.item + (x.wait ? "~w" : "")] = x; });
        Array.prototype.slice.call(box.children).forEach(function (el) {
          var k = el.getAttribute("data-k2");
          if (want[k] && !el.classList.contains("rd-out")) { have[k] = 1; return; }
          if (el.classList.contains("rd-out")) return;
          el.classList.add("rd-out");
          setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 450);
        });
        S.lanes[id].head.classList.toggle("rd-contest", (L[id] || []).some(function (x) { return x.wait; }));
        Object.keys(want).forEach(function (k) {
          if (have[k]) return;
          var x = want[k], txt = (x.wait ? "waiting for " : "holds ") + (x.text || x.item);
          var el = icon("hold", "rd-rp-lock rd-in" + (x.wait ? " rd-lock-wait" : ""), txt);
          el.setAttribute("data-k2", k);
          prepItem(el, { kind: "hold", row: { kind: "hold", text: txt, at: null, state: {}, tags: null } });
          box.appendChild(el);
          (window.requestAnimationFrame || setTimeout)(function () { el.classList.remove("rd-in"); });
        });
      });
    }
    /* Not picked up yet: one small count on the pill. */
    var W = R.replayWaitingAt(rep, t), ws = JSON.stringify(W);
    if (ws !== S.waits) {
      S.waits = ws;
      Object.keys(S.lanes).forEach(function (id) {
        var el = S.lanes[id].wait;
        if (!el) return;
        el.textContent = W[id] ? String(W[id]) : "";
        el.title = W[id] ? W[id] + " handed over and not picked up yet" : "";
      });
    }
    drawItems(S, rep, t);
    applyAnticipate(S, rep, t);
    drawRuler(S, rep, t);
    var prev = rp.lastT;
    rp.lastT = t;
    if (!animate || prev == null || t <= prev || !moving()) return;
    rep.pool.forEach(function (r) { r.flows.forEach(function (f) { if (f.pickAt != null && f.pickAt > prev && f.pickAt <= t) catchAt(S, f.to); }); });
  }

  function drawRuler(S, rep, t) {
    if (!R.replayScale || !R.replayRulerTimes) return;
    var scale = R.replayScale(rep), g = rpGeom(S), ax = g.ax, id, lane = null;
    if (!scale) return;
    for (id in g.lanes) { if (g.lanes[id]) { lane = g.lanes[id]; break; } }
    if (!lane) return;
    var box = S.ruler;
    if (!box) {
      box = S.ruler = document.createElement("div");
      box.className = "rd-rp-ruler";
      box.setAttribute("aria-hidden", "true");
      S.field.insertBefore(box, S.field.firstChild);
    }
    var start = lane.start, len = lane.len, ticks = R.replayRulerTimes(scale, t);
    var key = ax.main + "|" + start.toFixed(1) + "|" + len.toFixed(1) + "|" + t + "|" + ticks.map(function (tk) { return tk.at + ":" + tk.pos.toFixed(4); }).join(",") + "|" + (scale.breaks || []).map(function (br) { return br.start + "-" + br.end; }).join(",");
    if (key === S.rulerKey) return;
    S.rulerKey = key;
    box.textContent = "";
    function place(el, along, size) {
      if (ax.main === "x") { el.style.left = along.toFixed(1) + "px"; if (size != null) el.style.width = size.toFixed(1) + "px"; }
      else { el.style.top = along.toFixed(1) + "px"; if (size != null) el.style.height = size.toFixed(1) + "px"; }
      box.appendChild(el);
    }
    ticks.forEach(function (tk) {
      var px = start + tk.pos * len, grid = document.createElement("i"), lab = document.createElement("span");
      grid.className = "rd-rp-grid";
      lab.className = "rd-rp-rlabel";
      lab.textContent = tk.label;
      place(grid, px);
      place(lab, px);
    });
    (scale.breaks || []).forEach(function (br) {
      var p0 = scale.toPos(t) - scale.toPos(br.end), p1 = scale.toPos(t) - scale.toPos(br.start);
      if (p1 < 0 || p0 > 1) return;
      var a = start + Math.max(0, p0) * len, b = start + Math.min(1, p1) * len, w = Math.max(8, b - a);
      var el = document.createElement("i"), lab = R.dur ? R.dur(br.skip) : "";
      el.className = "rd-rp-void";
      if (lab) {
        var s = document.createElement("span");
        s.className = "rd-rp-void-lab";
        s.textContent = lab;
        el.appendChild(s);
      }
      place(el, a, w);
    });
  }

  function applyAnticipate(S, rep, t) {
    var ant = R.replayAnticipate ? R.replayAnticipate(rep, t, rp.view) : {}, reduce = !moving();
    Object.keys(S.lanes).forEach(function (id) {
      var pill = S.lanes[id] && S.lanes[id].pill, a = ant[id] || { scale: 1, tint: 0, kind: "" };
      var sc = reduce ? 1 : (a.scale || 1);
      var key = sc.toFixed(3) + "," + (a.tint || 0).toFixed(3) + "," + (a.kind || "");
      if (!pill || pill.rdAnt === key) return;
      pill.rdAnt = key;
      pill.style.setProperty("--rd-ant", String(sc));
      pill.style.setProperty("--rd-ant-tint", String(a.tint || 0));
      if (a.kind && a.tint) {
        pill.style.setProperty("--rd-k-ant", "var(--rd-k-" + a.kind + ")");
        pill.setAttribute("data-rp-ant", a.kind);
      } else {
        pill.style.removeProperty("--rd-k-ant");
        pill.removeAttribute("data-rp-ant");
      }
    });
  }
  /* Spans: a tw run (rd-rp-doing) or a held promise (rd-rp-hold). Live, a span keeps its kind
   * colour; once the playhead passes its end the whole bar takes its outcome colour
   * (data-end), with a short settle while playing and a plain swap when paused, scrubbing
   * or under reduced motion (CSS). A held promise has a lock cap at its grant and an end cap
   * shaped by how it ended (drop, force, expire). Waiting stretches of a run are shaded. */
  var DOING_BAR = 6, DOING_GAP = 2, CAP = 7;
  function doingBarEl(span) {
    var el = document.createElement("span");
    el.className = "rd-rp-item rd-rp-lapse " + (span.kind === "hold" ? "rd-rp-hold" : "rd-rp-doing");
    el.setAttribute("data-rp-tip", "doing");
    el.tabIndex = 0;
    return el;
  }
  function capEl(cls) {
    var el = document.createElement("i");
    el.className = "rd-rp-cap " + cls;
    el.setAttribute("aria-hidden", "true");
    return el;
  }
  function spanLabel(sp) {
    return (sp.kind === "hold" ? "held" : "doing") + (sp.text ? ", " + sp.text : "") + (sp.open ? ", ongoing" : sp.how ? ", " + sp.how : "");
  }
  function shadeOf(sp, ax) {
    if (!sp.shade || !sp.shade.length) return "none";
    var stops = [], dir = ax.main === "x" ? "to right" : "to bottom";
    sp.shade.forEach(function (s) {
      var a = (s[0] * 100).toFixed(1) + "%", b = (s[1] * 100).toFixed(1) + "%";
      stops.push("transparent " + a, "var(--rd-wait-shade) " + a, "var(--rd-wait-shade) " + b, "transparent " + b);
    });
    return "linear-gradient(" + dir + ", " + stops.join(", ") + ")";
  }
  function drawDoingSpans(S, ax, spans) {
    S.spans = S.spans || {};
    S.caps = S.caps || {};
    var seen = {}, capSeen = {}, g = rpGeom(S), maxRow = {};
    (spans || []).forEach(function (sp) { maxRow[sp.lane] = Math.max(maxRow[sp.lane] || 0, sp.rowIndex || 0); });
    function place(id, cls, along, cross) {
      var el = S.caps[id];
      if (!el) { el = S.caps[id] = capEl(cls); S.field.appendChild(el); }
      else if (el.rdCls !== cls) el.className = "rd-rp-cap " + cls;
      el.rdCls = cls;
      capSeen[id] = 1;
      var tf = ax.main === "x" ? "translate(" + (along - CAP / 2).toFixed(1) + "px," + (cross - CAP / 2).toFixed(1) + "px)"
        : "translate(" + (cross - CAP / 2).toFixed(1) + "px," + (along - CAP / 2).toFixed(1) + "px)";
      if (el.rdTf !== tf) { el.style.transform = tf; el.rdTf = tf; }
    }
    (spans || []).forEach(function (sp) {
      var L = g.lanes[sp.lane], el = S.spans[sp.id];
      if (!L) return;
      if (!el) { el = S.spans[sp.id] = doingBarEl(sp); S.field.appendChild(el); }
      el.rdRow = sp.row; el.rdSpan = sp;
      el.classList.toggle("is-open", !!sp.open);
      var end = sp.ended ? sp.how : "";
      if (el.getAttribute("data-end") !== end) { if (end) el.setAttribute("data-end", end); else el.removeAttribute("data-end"); }
      var lab = spanLabel(sp);
      if (el.rdLab !== lab) { el.setAttribute("aria-label", lab); el.rdLab = lab; }
      var shade = shadeOf(sp, ax);
      if (el.rdShade !== shade) { el.style.setProperty("--rd-shade", shade); el.rdShade = shade; }
      seen[sp.id] = 1;
      el.hidden = false;
      var x0 = L.start + sp.pos0 * L.len, x1 = L.start + sp.pos1 * L.len;
      var w = Math.max(1, x1 - x0);
      var n = (maxRow[sp.lane] || 0) + 1, stackH = n * (DOING_BAR + DOING_GAP) - DOING_GAP;
      var y = L.cross - stackH / 2 + (sp.rowIndex || 0) * (DOING_BAR + DOING_GAP);
      var tf = ax.main === "x"
        ? "translate(" + x0.toFixed(1) + "px," + y.toFixed(1) + "px) scaleX(" + w.toFixed(1) + ")"
        : "translate(" + y.toFixed(1) + "px," + x0.toFixed(1) + "px) scaleY(" + w.toFixed(1) + ")";
      if (el.rdTf !== tf) { el.style.transform = tf; el.rdTf = tf; }
      if (el.rdOp !== "1") { el.style.opacity = "1"; el.rdOp = "1"; }
      if (sp.kind === "hold") {
        var mid = y + DOING_BAR / 2;
        if (sp.pos1 < 1) place(sp.id + ":s", "rd-cap-lock", x1, mid);
        if (sp.ended) place(sp.id + ":e", "rd-cap-" + sp.how, x0, mid);
      }
    });
    Object.keys(S.spans).forEach(function (id) {
      if (seen[id]) return;
      var el = S.spans[id];
      if (el && el.parentNode) el.parentNode.removeChild(el);
      delete S.spans[id];
    });
    Object.keys(S.caps).forEach(function (id) {
      if (capSeen[id]) return;
      var el = S.caps[id];
      if (el && el.parentNode) el.parentNode.removeChild(el);
      delete S.caps[id];
    });
  }
  /* Picked up: a quiet ring on the receiver. Pill scale is owned by
     anticipation (--rd-ant), so a WAAPI scale here would fight the playhead-driven size. */
  function catchAt(S, id) {
    var l = S.lanes[id];
    if (!l || !l.head) return;
    var ring = document.createElement("i");
    ring.className = "rd-rp-catch";
    l.head.appendChild(ring);
    if (!ring.animate) { if (ring.parentNode) ring.parentNode.removeChild(ring); return; }
    var run = ring.animate([{ transform: "scale(.6)", opacity: 0.9 }, { transform: "scale(1.6)", opacity: 0 }], { duration: 650, easing: "ease-out" });
    run.onfinish = run.oncancel = function () { if (ring.parentNode) ring.parentNode.removeChild(ring); };
  }
  function rpTick() {
    rp.raf = 0;
    if (!rp.playing) return;
    var rep = rpRep();
    if (rpNow() >= rep.until) { rp.playing = false; rp.t = null; drawReplay(true); return; }
    drawReplay(true);
    rp.raf = (window.requestAnimationFrame || setTimeout)(rpTick);
  }
  function rpPlay() {
    var rep = rpRep();
    if (!rep) return;
    var from = rp.t != null && rp.t < rep.until ? rp.t : rep.since;
    rp.playing = true; rp.t0 = from; rp.wall0 = Date.now(); rp.t = from;
    rp.drawn = "";
    drawReplay(false);
    rp.raf = (window.requestAnimationFrame || setTimeout)(rpTick);
  }
  /* Full screen: the pane (it outlives repaints, so a redraw does not drop it) goes native full
   * screen; without the API it covers the viewport. rd-rp-fs on the pane drives the layout either way. */
  function fsEl() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
  function rpFull(on) {
    var pane = root.querySelector(".rd-pane");
    if (!pane) return;
    rp.full = !!on;
    pane.classList.toggle("rd-rp-fs", rp.full);
    if (rp.full && !fsEl()) {
      var req = pane.requestFullscreen || pane.webkitRequestFullscreen;
      if (req) { var p = req.call(pane); if (p && p.catch) p.catch(function () {}); }
    } else if (!rp.full && fsEl()) {
      var ex = document.exitFullscreen || document.webkitExitFullscreen;
      if (ex) { var q = ex.call(document); if (q && q.catch) q.catch(function () {}); }
    }
    if (state.tab === "collab") paint();
  }
  /* Esc (or the browser's own exit) leaves native full screen: follow it. */
  ["fullscreenchange", "webkitfullscreenchange"].forEach(function (n) {
    document.addEventListener(n, function () { if (rp.full && !fsEl()) rpFull(false); });
  });
  /* The folded blocking list keeps its open state across repaints. */
  root.addEventListener("toggle", function (ev) {
    var el = ev.target;
    if (el && el.getAttribute && el.getAttribute("data-rp-blocking")) rp.blockOpen = el.open;
  }, true);
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && rp.full && !fsEl()) rpFull(false); });
  /* Paused, one event at a time: the playhead jumps to the next row and plays only its motion. */
  function rpStep() {
    var rep = rpRep();
    if (!rep) return;
    var at = rp.playing ? rpNow() : (rp.t == null ? rep.since - 1 : rp.t);
    rp.playing = false;
    var next = null;
    for (var i = 0; i < rep.rows.length; i++) if (rep.rows[i].at > at) { next = rep.rows[i].at; break; }
    if (next == null) { rp.t = null; drawReplay(false); return; }
    if (rp.t == null) { rp.t = rep.since; rp.drawn = null; drawReplay(false); }
    rp.t = next;
    drawReplay(true);
  }
  function rpPause() { if (!rp.playing) return; rp.t = rpNow(); rp.playing = false; drawReplay(false); }
  function rpStop() { rp.playing = false; rp.t = null; rp.drawn = null; }
  /* Scrub on the trace: click or drag sets the playhead (and pauses); the far right is now. */
  function rpSeek(frac) {
    var rep = rpRep();
    if (!rep) return;
    rp.playing = false;
    frac = Math.max(0, Math.min(1, frac));
    rp.t = frac >= 0.999 ? null : rep.since + (rep.until - rep.since) * frac;
    drawReplay(false);
  }
  function traceFrac(el, ev) {
    var r = el.getBoundingClientRect();
    if (el.getAttribute("data-rp-axis") === "y") return r.height ? (ev.clientY - r.top) / r.height : 1;
    return r.width ? (ev.clientX - r.left) / r.width : 1;
  }
  /* On the overview: drag the viewport box (grab hand) to slide the window through the
   * loaded history (never past now); a click outside the box jumps the window there. */
  var dragTrace = null, PAN_PX = 4;
  function spanText(rep) {
    function f(t) { return new Date(t).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
    return f(rep.since) + " \u2013 " + (rep.live ? "now" : f(rep.until)) + (rpOlder.busy ? " \u00b7 loading older\u2026" : rpOlder.end && rep.oldest != null && rep.since <= rep.oldest ? " \u00b7 start of the record" : rep.more && rep.since <= (rep.oldest || 0) ? " \u00b7 older rows on the server" : "");
  }
  function rpPanTo(end) {
    if (end === rp.end) return;
    rp.end = end; rp.playing = false; rp.t = null; rp.drawn = null; rp.st = null;
    if (!rpPanTo.raf) rpPanTo.raf = (window.requestAnimationFrame || setTimeout)(function () { rpPanTo.raf = 0; last.pane = null; paint(); });
  }
  function ovFrac(el, ev) {
    var r = el.getBoundingClientRect();
    return r.width ? (ev.clientX - r.left) / r.width : 1;
  }
  function rpJump(frac) {
    var rep = rpRep(), ovEl = root.querySelector("[data-rp-ov]");
    if (!rep || !ovEl) return;
    var lo = Number(ovEl.getAttribute("data-lo")), hi = Number(ovEl.getAttribute("data-hi"));
    var T = lo + Math.max(0, Math.min(1, frac)) * Math.max(1, hi - lo);
    rp.playing = false;
    var end = T >= rep.now - 1000 ? null : R.replayPan(rep, Math.round(T), 0);
    rpPanTo(end);
    if (end != null) rpOlderFor(rep, end);
  }
  root.addEventListener("pointerover", function (ev) {
    if (dragTrace) return;
    var el = tipTarget(ev.target);
    if (el) showTip(el, ev, false);
  });
  root.addEventListener("pointermove", function (ev) {
    if (!tipOn || dragTrace || tipOn.fromFocus) return;
    tipOn.ptr = { x: ev.clientX, y: ev.clientY };
    if (tipTarget(ev.target) === tipOn.el) placeTip(ev.clientX, ev.clientY);
  });
  root.addEventListener("pointerout", function (ev) {
    if (!tipOn || tipOn.fromFocus) return;
    if (ev.relatedTarget && tipTarget(ev.relatedTarget) === tipOn.el) return;
    hideTip();
  });
  root.addEventListener("focusin", function (ev) {
    var el = tipTarget(ev.target);
    if (el) showTip(el, ev, true);
  });
  root.addEventListener("focusout", function (ev) {
    if (!tipOn || !tipOn.fromFocus) return;
    if (ev.relatedTarget && tipTarget(ev.relatedTarget)) return;
    hideTip();
  });
  root.addEventListener("pointerdown", function (ev) {
    var el = closest(ev.target, "[data-rp-ov]"), rep = rpRep();
    if (!el || !rep) return;
    hideTip();
    var bx = el.getBoundingClientRect(), frac = ovFrac(el, ev);
    var vp = R.replayViewport(rep, rpNow(), { lo: Number(el.getAttribute("data-lo")), hi: Number(el.getAttribute("data-hi")) });
    var onVp = frac >= vp.lo - 0.01 && frac <= vp.hi + 0.01;
    dragTrace = { el: el, x0: ev.clientX, w: bx.width || 1, end0: rp.end, ov: Math.max(1, Number(el.getAttribute("data-hi")) - Number(el.getAttribute("data-lo"))), onVp: onVp, moved: false };
    if (el.setPointerCapture) try { el.setPointerCapture(ev.pointerId); } catch (e) { /* capture is optional */ }
    ev.preventDefault();
  });
  root.addEventListener("pointermove", function (ev) {
    var d = dragTrace, rep = rpRep();
    if (!d || !rep || !d.onVp) return;
    var dx = ev.clientX - d.x0;
    if (!d.moved && Math.abs(dx) < PAN_PX) return;
    if (!d.moved) { d.moved = true; root.classList.add("rd-rp-panning"); }
    /* Drag right shows earlier time, as a map does: the window's end moves back. */
    var dt = -dx / d.w * d.ov;
    rpPanTo(R.replayPan(rep, d.end0, dt));
    if (dt < 0) rpOlderFor(rep, (d.end0 == null ? rep.now : d.end0) + dt);
  });
  ["pointerup", "pointercancel"].forEach(function (n) {
    root.addEventListener(n, function (ev) {
      var d = dragTrace;
      dragTrace = null;
      root.classList.remove("rd-rp-panning");
      if (d && !d.moved && n === "pointerup" && !d.onVp) rpJump(ovFrac(d.el, ev));
    });
  });
  /* Overview arrows: one click (or Left/Right on the focused strip) jumps a
   * fixed 100 rows; press-and-hold repeats the same jump. */
  var holdOv = null;
  function ovStep(dir) {
    var rep = rpRep();
    if (!rep) { ovHoldStop(); return; }
    if (!R.replayPanCan || !R.replayPanCan(rep, rp.end, dir)) {
      /* At the oldest loaded row: the previous 100 are on the server; read the older page. */
      if (dir < 0 && rep.more) rpOlderFor(rep, rep.floorEnd != null ? rep.floorEnd : rep.now);
      ovHoldStop();
      return;
    }
    var end = R.replayPanRows(rep, rp.end, dir);
    rpPanTo(end);
    if (dir < 0) rpOlderFor(rep, end == null ? rep.now : end);
  }
  function ovHoldStop() {
    if (!holdOv) return;
    if (holdOv.tid) clearTimeout(holdOv.tid);
    if (holdOv.iid) clearInterval(holdOv.iid);
    holdOv = null;
  }
  root.addEventListener("pointerdown", function (ev) {
    var btn = closest(ev.target, "[data-rp-ov-dir]");
    if (!btn || btn.disabled) return;
    var dir = Number(btn.getAttribute("data-rp-ov-dir"));
    if (!dir) return;
    ovStep(dir);
    holdOv = {
      dir: dir,
      tid: setTimeout(function () {
        if (!holdOv) return;
        holdOv.tid = 0;
        holdOv.iid = setInterval(function () { ovStep(dir); }, 160);
      }, 400)
    };
    if (btn.setPointerCapture) try { btn.setPointerCapture(ev.pointerId); } catch (e) { /* capture is optional */ }
    ev.preventDefault();
    ev.stopPropagation();
  });
  ["pointerup", "pointercancel"].forEach(function (n) {
    root.addEventListener(n, function () { ovHoldStop(); });
  });
  root.addEventListener("keydown", function (ev) {
    var el = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-rp-ov") ? ev.target : null, rep = rpRep();
    if (!el || !rep) return;
    if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      ev.preventDefault();
      ovStep(ev.key === "ArrowLeft" ? -1 : 1);
      return;
    }
    if (ev.key === "Home") { ev.preventDefault(); rpPanTo(rep.floorEnd); rpOlderFor(rep, rep.floorEnd); return; }
    if (ev.key === "End") { ev.preventDefault(); rpPanTo(null); return; }
  });
  /* ---- The record: GET /api/v1/replay pages, cached in memory by id range ----
   * The newest page is read first (limit = the window's row count). Rows newer than the
   * cache come with after=<newest id> (the head is re-read every RPL_HEAD_MS while COLLAB is
   * open); a pan, an arrow or a drag past the oldest loaded row reads before=<oldest id>.
   * A before= page never changes (the server marks it immutable), so each is read once and
   * kept under its id range. A 404 means the route is not on this mill yet: the pane says so
   * and draws nothing; no line is made up from other reads. */
  var RPL_HEAD_MS = 15000;
  var rpl = null, rpOlder = { busy: 0, end: false };
  function rplReset() {
    rpl = { key: rosters().join(","), pages: {}, byId: {}, oldest: null, newest: null, more: true, missing: false, loaded: false, headAt: 0 };
    rpOlder = { busy: 0, end: false };
    data.replay = null;
  }
  function rplUrl(q) {
    return "/api/v1/replay?project=" + encodeURIComponent(rpl.key) + "&limit=" + R.replayCount(load(RP_COUNT_KEY, String(R.REPLAY_COUNT_DEFAULT))) + q;
  }
  function rplGet(q) {
    return fetch(rplUrl(q), { credentials: "same-origin" }).then(function (r) {
      if (r.status === 404 || r.status === 405 || r.status === 501) return { missing: true };
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }
  function rplTake(j, older) {
    if (!j || !Array.isArray(j.rows)) return false;
    var before = Object.keys(rpl.byId).length;
    j.rows.forEach(function (r) { if (r && r.id != null) rpl.byId[r.id] = r; });
    if (j.rows.length) rpl.pages[j.oldest_id + "-" + j.newest_id] = j.rows.map(function (r) { return r.id; });
    if (j.oldest_id != null && (rpl.oldest == null || j.oldest_id < rpl.oldest)) rpl.oldest = j.oldest_id;
    if (j.newest_id != null && (rpl.newest == null || j.newest_id > rpl.newest)) rpl.newest = j.newest_id;
    if (older || !rpl.loaded) rpl.more = !!j.has_more;
    rpl.loaded = true;
    rplPublish();
    return Object.keys(rpl.byId).length > before;
  }
  function rplPublish() {
    var rows = Object.keys(rpl.byId).map(function (k) { return rpl.byId[k]; });
    data.replay = { rows: rows, oldest_id: rpl.oldest, newest_id: rpl.newest, more: rpl.more, missing: rpl.missing, loaded: rpl.loaded };
    rpOlder.end = rpl.loaded && !rpl.more;
  }
  function fetchReplay() {
    if (state.tab !== "collab") return;
    if (!rpl || rpl.key !== rosters().join(",")) rplReset();
    if (rpl.missing || inflight.rplHead || Date.now() - rpl.headAt < RPL_HEAD_MS) return;
    var q = rpl.newest != null ? "&after=" + rpl.newest : "";
    inflight.rplHead = rplGet(q).then(function (j) {
      inflight.rplHead = null;
      rpl.headAt = Date.now();
      if (j && j.missing) { rpl.missing = true; rplPublish(); last.pane = null; paintSoon(); return; }
      /* More new rows than one page: read the next newer page now, not in 15 s. */
      if (rplTake(j, false) && q && j.has_more) rpl.headAt = 0;
      if (!rp.playing) { last.pane = null; paintSoon(); }
    });
  }
  /* A pan reached back past the oldest loaded row: read the next older page. */
  function rpOlderFor(rep, wantEnd) {
    if (!rpl || !rpl.loaded || !rpl.more || rpl.missing || inflight.rplOlder || rpl.oldest == null || !rep) return;
    var need = (wantEnd != null ? wantEnd : rp.end == null ? rep.now : rp.end) - rep.ms;
    if (rep.oldest != null && rep.floorEnd != null && wantEnd != null && wantEnd > rep.floorEnd && need > rep.oldest) return;
    rpOlder.busy++;
    inflight.rplOlder = rplGet("&before=" + rpl.oldest).then(function (j) {
      inflight.rplOlder = null;
      rpOlder.busy--;
      if (j && !j.missing) rplTake(j, true);
      if (!rp.playing) { last.pane = null; paintSoon(); }
    });
  }

  /* ---- tabs + legacy panes ---- */
  function isPhone() { return window.matchMedia && window.matchMedia("(max-width: 720px)").matches; }
  function hashName() { return String(location.hash || "").replace(/^#/, "").trim().toLowerCase(); }
  function setLegacy(on) {
    state.legacy = on;
    if (on) unhostAll();
    document.body.classList.toggle("rd-on", !on);
    document.body.classList.toggle("rd-legacy", on);
  }
  function setTab(tab, fromHash) {
    if (TABS.indexOf(tab) < 0) tab = "desks";
    var changed = tab !== state.tab;
    state.tab = tab;
    save(TAB_KEY, tab);
    if (tab !== "desks") state.phoneDesk = false;
    setLegacy(false);
    if (!fromHash && hashName() !== tab) {
      try { history.replaceState(null, "", "#" + tab); } catch (e) { location.hash = tab; }
    }
    if (changed) { last.pane = null; rpStop(); if (rp.full) rpFull(false); }
    paint();
    fetchTab(tab).then(fetchCounts);
  }
  function onHash() {
    var n = hashName();
    if (has(ALIAS, n) && ALIAS[n]) { setTab(ALIAS[n], true); return; }
    if (n) setLegacy(true);
  }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  /* ---- clicks ---- */
  function closest(t, sel) { return t && t.closest ? t.closest(sel) : null; }
  function scopeChanged() {
    last = {};
    rpStop();
    fetchCore().then(function () { return fetchTab(state.tab); }).then(fetchCounts);
    paint();
  }
  root.addEventListener("click", function (ev) {
    var t = ev.target, el;
    if ((el = closest(t, "[data-rd-tab]"))) { setTab(el.getAttribute("data-rd-tab")); return; }
    if ((el = closest(t, "[data-rd-range]"))) {
      state.range[state.tab] = el.getAttribute("data-rd-range");
      save(RANGE_KEY, JSON.stringify(state.range));
      scopeChanged();
      return;
    }
    if ((el = closest(t, "[data-rd-back]"))) { state.phoneDesk = false; paint(); return; }
    if ((el = closest(t, "[data-rd-view]"))) {
      var v = el.getAttribute("data-rd-view"), cfg = HOSTED[state.tab];
      if (state.tab === "todo") { save(TODO_VIEW_KEY, v); todoMode = ""; }
      /* Switching subtabs keeps the playhead: same clock, other view. */
      else if (state.tab === "collab") { save(COLLAB_VIEW_KEY, v); last.pane = null; rp.st = null; }
      else if (cfg && cfg.attr) {
        var btn = document.querySelector("[" + cfg.attr + '="' + v + '"]');
        if (btn && btn !== el) btn.click();
      }
      last.host = null;
      paint();
      return;
    }
    if ((el = closest(t, "[data-rp-play]"))) { if (rp.playing) rpPause(); else rpPlay(); return; }
    if ((el = closest(t, "[data-rp-step]"))) { rpStep(); return; }
    if ((el = closest(t, "[data-rp-full]"))) { rpFull(!rp.full); return; }
    if ((el = closest(t, "[data-rp-dir]"))) {
      rp.dirs[rp.view] = el.getAttribute("data-rp-dir") === "tb" ? "tb" : "lr";
      save(RP_DIR_KEY + rp.view, rp.dirs[rp.view]);
      rp.st = null; rp.drawn = null; last.pane = null; paint();
      return;
    }
    if ((el = closest(t, "[data-rp-cluster]"))) {
      rp.clusters[rp.view] = R.replayCluster(el.getAttribute("data-rp-cluster"));
      save(RP_CLUSTER_KEY + rp.view, rp.clusters[rp.view]);
      rp.st = null; rp.drawn = null; last.pane = null; paint();
      return;
    }
    if ((el = closest(t, "[data-rp-count]"))) { save(RP_COUNT_KEY, el.getAttribute("data-rp-count")); rpStop(); paint(); return; }
    if ((el = closest(t, "[data-rp-speed]"))) {
      var sp = Number(el.getAttribute("data-rp-speed")) || 1;
      if (rp.playing) { var at = rpNow(); rp.speed = sp; rp.t0 = at; rp.wall0 = Date.now(); } else rp.speed = sp;
      save(RP_SPEED_KEY, String(sp));
      paint();
      return;
    }
    if ((el = closest(t, "[data-rd-go]"))) {
      ev.preventDefault();
      var tab = el.getAttribute("data-rd-go"), sel = el.getAttribute("data-rd-sel");
      if (sel) state.sel[tab] = sel;
      setTab(tab);
      return;
    }
    if ((el = closest(t, "[data-rd-desk]"))) {
      ev.stopPropagation();
      state.sel.desks = el.getAttribute("data-rd-desk");
      state.phoneDesk = isPhone();
      setTab("desks");
      return;
    }
    if ((el = closest(t, "[data-rd-pickdesk]"))) {
      state.sel.desks = el.getAttribute("data-rd-pickdesk");
      state.phoneDesk = isPhone();
      paint();
      var pane = root.querySelector('[data-rd-scroll="desk"]');
      if (pane) pane.scrollTop = 0;
      return;
    }
    if ((el = closest(t, "[data-rd-pick]"))) { state.sel[state.tab] = el.getAttribute("data-rd-pick"); paint(); }
  });
  root.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && ev.target && ev.target.getAttribute && ev.target.getAttribute("data-rd-pick")) ev.target.click();
  });

  /* ---- start ---- */
  function skeleton() {
    root.innerHTML = '<div class="rd-shell-main"><div class="rd-glance-band"><div class="rd-glance-status"><div class="rd-strip" role="tablist" aria-label="Office tabs"></div>' +
      '<div class="rd-hero" aria-live="polite"></div></div></div>' +
      '<div class="rd-main"><div class="rd-pane"></div>' +
      '<div class="rd-host" hidden><div class="rd-host-head"></div><div class="rd-host-body"></div></div></div></div>';
  }
  window.WallRdApp = {
    /* boot.js leaves these hashes to this shell, so it does not rewrite #todo to #session. */
    keepsHash: function (name) {
      var n = String(name || "").replace(/^#/, "").toLowerCase();
      return !state.legacy && has(ALIAS, n);
    },
    repaint: function () { last = {}; todoMode = ""; paint(); },
    /* boot.js: the old pane to open at start, so a hosted tab is live on first paint. */
    legacyTab: legacyTab,
    /* boot.js: the station or roster picked on the left rail changed. */
    railPick: function (pick) {
      var next = pick && pick.kind && pick.id ? { kind: String(pick.kind), id: String(pick.id) } : null;
      if (JSON.stringify(next) === JSON.stringify(state.pick)) return;
      state.pick = next;
      state.sel = {};
      scopeChanged();
    }
  };
  skeleton();
  var start = hashName();
  if (!start || !has(ALIAS, start)) {
    if (!start) {
      var saved = load(TAB_KEY, "desks");
      try { history.replaceState(null, "", "#" + (TABS.indexOf(saved) >= 0 ? saved : "desks")); } catch (e) { /* file: */ }
    }
  }
  window.addEventListener("hashchange", onHash);
  start = hashName();
  if (has(ALIAS, start) && ALIAS[start]) state.tab = ALIAS[start];
  else if (start) setLegacy(true);
  if (!state.legacy) setLegacy(false);
  paint();
  fetchCore(true).then(function () { return fetchTab(state.tab); }).then(fetchCounts);
  setInterval(function () {
    if (document.visibilityState === "hidden" || state.legacy) return;
    fetchCore().then(function () { return fetchTab(state.tab); });
  }, 15000);
  setInterval(function () { if (!state.legacy && document.visibilityState !== "hidden") paintSoon(); }, 30000);
  if (window.matchMedia) {
    var wq = window.matchMedia(WIDE_Q), onWide = function () { todoMode = ""; last.host = null; paintSoon(); };
    if (wq.addEventListener) wq.addEventListener("change", onWide); else if (wq.addListener) wq.addListener(onWide);
  }
})();
