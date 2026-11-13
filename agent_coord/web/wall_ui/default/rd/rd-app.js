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
    /* COLLAB Replay: letters, cards, promises and the activity table; the move rows come after. */
    collab: ["events", "mail", "todos", "holds", "scores"]
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
    todo: { pane: "pane-todo", legacy: "jobs", views: [{ key: "board", label: "Kanban" }, { key: "list", label: "List" }, { key: "nest", label: "Tree" }] },
    mail: { pane: "pane-mail", legacy: "mail", attr: "data-mail-view", views: [{ key: "rooms", label: "Rooms" }, { key: "letters", label: "Letters" }] },
    /* Replay is this shell's own; Timeline is the Wall's pane (the old Between ring is gone). */
    collab: { pane: "pane-floor", legacy: "floor", attr: "data-floor-mode", own: "replay", views: [{ key: "replay", label: "Replay" }, { key: "timeline", label: "Timeline" }] },
    priorities: { pane: "pane-priorities", legacy: "priorities", views: [] }
  };
  /* Wide enough for kanban, list and tree side by side. */
  var WIDE_Q = "(min-width: 1600px)";
  var TODO_VIEW_KEY = "rd-todo-view";
  /* Card 1193: these reads take ?window=1d|7d|30d on the tab that shows a time range. */
  var WINDOWED = { desks: ["agents"], score: ["scores"] };
  var WINDOW_Q = { today: "1d", "7d": "7d", "30d": "30d" };
  var FRESH_MS = { agents: 20000, names: 300000, todos: 30000, mail: 30000, labels: 60000, scores: 30000, holds: 30000, rooms: 120000, trees: 120000, events: 30000, runs: 60000 };
  var RANGE_KEY = "rd-range", TAB_KEY = "rd-tab", COLLAB_VIEW_KEY = "rd-collab-view", RP_WIN_KEY = "rd-replay-window", RP_SPEED_KEY = "rd-replay-speed";

  var data = { agents: {}, names: {}, todos: {}, mail: {}, labels: {}, scores: {}, holds: {}, rooms: {}, trees: {}, events: {}, runs: {}, history: {}, moves: {}, trail: {}, doing: null, stations: null, rosterList: null };
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
  function fetchPart(kind, roster, force, win) {
    win = win || "";
    var key = kind + "|" + roster + "|" + win;
    if (inflight[key]) return inflight[key];
    if (!force && gotAt[key] && Date.now() - gotAt[key] < FRESH_MS[kind]) return Promise.resolve();
    var url = ROUTE[kind].replace("%R", encodeURIComponent(roster)) + (win ? "&window=" + win : "");
    inflight[key] = getJson(url).then(function (j) {
      inflight[key] = null;
      if (j && !j.error) {
        var rows = PICK[kind](j) || [];
        if (win) (winData[kind + "|" + win] || (winData[kind + "|" + win] = {}))[roster] = rows;
        else data[kind][roster] = rows;
        gotAt[key] = Date.now();
      } else if (win) {
        /* A server before card 1193 refuses the window; read the whole list and cut it here. */
        noWindow[kind] = true;
        return fetchPart(kind, roster, force, "");
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
        if (j && Array.isArray(j.result)) {
          var by = {};
          j.result.forEach(function (v) { if (v && v.owner) by[v.owner] = v; });
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
  function savedTodoView() {
    var v = load(TODO_VIEW_KEY, "board");
    return v === "list" || v === "nest" ? v : "board";
  }
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
    var all = isWide(), mode = all ? "all" : savedTodoView();
    el.classList.toggle("rd-todo-all", all);
    if (mode === todoMode) return;
    todoMode = mode;
    W.setJobsView(all ? "nest" : mode);
  }
  function collabView() { return load(COLLAB_VIEW_KEY, "replay") === "timeline" ? "timeline" : "replay"; }
  /* The tab hosts its pane unless it is on a view this shell draws itself. */
  function hosted(tab) { var cfg = HOSTED[tab]; return !!cfg && !(cfg.own && tab === "collab" && collabView() === cfg.own); }
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
    if (t === "collab") {
      var tl = document.querySelector('[data-floor-mode="timeline"]');
      if (tl && !tl.classList.contains("on")) tl.click();
    }
    var all = t === "todo" && isWide();
    setHtml(root.querySelector(".rd-host-head"), V.hostHead(t, b, cfg.views, viewOn(t), all), "host");
    root.setAttribute("data-rd-host", t);
  }
  /* A card picked in one TODO view: open it in the other two and bring it into sight there. */
  function linkTodo(from) {
    var W = legacy();
    if (!W || !W.linkTodo) return;
    var id = W.linkTodo();
    if (!id) return;
    (window.requestAnimationFrame || setTimeout)(function () {
      [["jobs-kanban", '[data-todo-id="' + id + '"]'], ["jobs-list", '[data-todo-id="' + id + '"]'], ["jobs-outline", '.todo-tree-card[data-id="' + id + '"]']].forEach(function (p) {
        var box = document.getElementById(p[0]);
        if (!box || box === from) return;
        var hit = box.querySelector(p[1]);
        if (hit && hit.scrollIntoView) hit.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
    });
  }

  function paint() {
    if (state.legacy) return;
    var now = Date.now();
    var b = R.base(dataFor(state.tab), scope(), now);
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
      html = V.paneHead("collab", b, V.viewSwitch(HOSTED.collab.views, "replay")) +
        '<div class="rd-pane-body rd-collab-body">' + V.replay(replayModel(b), m.collab ? m.collab.groups[0].rows : null, rp) + "</div>";
    } else {
      var model = m[t];
      var body = model ? V[t](model) : '<div class="rd-loading">Loading ' + t.toUpperCase() + "\u2026</div>";
      if (model && model.selected) state.sel[t] = model.selected;
      html = V.paneHead(t, b) + '<div class="rd-pane-body rd-tab-body">' + body + "</div>";
      html = html.replace('class="rd-tab-groups', 'data-rd-scroll="groups" class="rd-tab-groups').replace('<aside class="rd-tab-detail"', '<aside data-rd-scroll="detail" class="rd-tab-detail"');
    }
    pane.setAttribute("data-rd-pane", t);
    var fresh = setHtml(pane, html, "pane");
    if (t === "collab") { if (fresh) rp.drawn = null; drawReplay(false); fetchReplay(b); }
    root.classList.toggle("rd-desk-open", t === "desks" && state.phoneDesk);
  }


  /* ---- COLLAB replay: plays the recorded rows back; motion only on rows the playhead reaches ----
   * Parked at the end (the default) the list is still: every row up to now, newest first. Play
   * rewinds the window and walks the playhead forward in R.REPLAY_PLAY_MS / speed; each row it
   * passes slides in at the top. The rows come from the reads, nothing is made up. */
  var RP_CAP = 60;
  var rp = { playing: false, t: null, t0: 0, wall0: 0, rep: null, raf: 0, drawn: null, speed: Number(load(RP_SPEED_KEY, "1")) || 1 };
  if (R.REPLAY_SPEEDS.indexOf(rp.speed) < 0) rp.speed = 1;
  function replayModel(b) {
    var rep = R.collabReplay(b, { window: load(RP_WIN_KEY, "auto") });
    if (!rp.playing) rp.rep = rep;
    return rep;
  }
  function rpRep() { return rp.rep; }
  /* Playhead in office time: span/REPLAY_PLAY_MS of the window per wall ms, times the speed. */
  function rpNow() {
    var rep = rpRep();
    if (!rep) return null;
    if (!rp.playing) return rp.t == null ? rep.until : rp.t;
    return Math.min(rep.until, rp.t0 + (Date.now() - rp.wall0) * rp.speed * (rep.ms / R.REPLAY_PLAY_MS));
  }
  function drawReplay(animate) {
    var rep = rpRep(), list = root.querySelector("[data-rp-list]");
    if (!rep) return;
    var t = rpNow();
    var rows = R.replayAt(rep, t, RP_CAP);
    var keys = rows.map(function (r) { return r.key; });
    var sig = keys.join("|");
    var scrub = root.querySelector("[data-rp-scrub]"), clockEl = root.querySelector("[data-rp-clock]"), play = root.querySelector("[data-rp-play]");
    if (scrub && document.activeElement !== scrub) scrub.value = String(Math.round(1000 * (t - rep.since) / Math.max(1, rep.until - rep.since)));
    if (clockEl) { var d = new Date(t); clockEl.textContent = (rp.t == null && !rp.playing ? "now " : "") + d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }); }
    if (play) { play.textContent = rp.playing ? "\u23f8" : "\u25b6"; play.setAttribute("aria-label", rp.playing ? "Pause" : "Play"); }
    if (list && sig !== rp.drawn) drawRows(list, rows, keys, sig, animate);
    /* In the past, each pill takes its desk's state at the playhead from the recorded state
     * changes; at now it keeps the current state the row was drawn with. */
    if (list) {
      var past = rp.playing || rp.t != null;
      list.classList.toggle("rd-rp-past", past);
      if (past) {
        var memo = {};
        list.querySelectorAll(".rd-pill[data-rd-desk]").forEach(function (el) {
          var n = el.getAttribute("data-rd-desk");
          if (!(n in memo)) memo[n] = R.replayStateAt(rep, n, t) || "unknown";
          if (el.getAttribute("data-st") !== memo[n]) { el.setAttribute("data-st", memo[n]); el.title = n + ", " + (memo[n] === "unknown" ? "no state recorded yet" : memo[n]) + " then"; }
          /* Doing is time spent: the bar under the pill grows from the focus start, full at a quarter window. */
          var since = R.replaySince(rep, n, t);
          el.style.setProperty("--dw", since == null ? "0" : String(Math.min(1, (t - since) / (rep.ms / 4)).toFixed(3)));
        });
      }
    }
  }
  function drawRows(list, rows, keys, sig, animate) {
    var prev = rp.drawn == null ? null : rp.drawn.split("|");
    /* While playing, rows the playhead just passed sit above the ones shown: add only those. */
    if (animate && prev && prev.length && keys.indexOf(prev[0]) > 0) {
      var cut = keys.indexOf(prev[0]), fresh = {};
      rows.slice(0, cut).forEach(function (r) { fresh[r.key] = 1; });
      list.insertAdjacentHTML("afterbegin", V.replayRows(rows.slice(0, cut), fresh));
      while (list.children.length > RP_CAP) list.removeChild(list.lastElementChild);
      for (var i = 0; i < cut && i < 6 && i < list.children.length; i++) kindFx(list.children[i]);
    } else if (animate && prev && !prev[0] && rows.length) {
      var all = {};
      rows.forEach(function (r) { all[r.key] = 1; });
      list.innerHTML = V.replayRows(rows, all);
      for (var j = 0; j < 6 && j < list.children.length; j++) kindFx(list.children[j]);
    } else {
      list.innerHTML = rows.length ? V.replayRows(rows, null) : '<li class="rd-rp-empty">' + (rp.playing || rp.t != null ? "Nothing yet at this point in the window." : "No activity for these desks in this window.") + "</li>";
    }
    rp.drawn = sig;
  }
  /* Each kind's motion, on a row the playhead just reached, measured from where its desks sit:
   * mail flies from the sender's pill to the recipient's, a card goes from its old column to
   * its new one, a promise locks or lets go, a wake pulses, doing turns, a score dot fills. */
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  function kindFx(li) {
    if (!li || !li.animate || (still && still.matches)) return;
    var k = li.getAttribute("data-k"), act = li.getAttribute("data-act"), icon = li.querySelector(".rd-ki");
    if (!icon) return;
    var ease = { duration: 700, easing: "ease-out" };
    function fly(a, z) {
      if (!a || !z) return false;
      var box = li.getBoundingClientRect(), ra = a.getBoundingClientRect(), rz = z.getBoundingClientRect();
      var ghost = icon.cloneNode(true);
      ghost.classList.add("rd-ghost");
      ghost.style.left = (ra.left + ra.width / 2 - box.left - 6) + "px";
      ghost.style.top = (ra.top + ra.height / 2 - box.top - 6) + "px";
      li.appendChild(ghost);
      var dx = (rz.left + rz.width / 2) - (ra.left + ra.width / 2), dy = (rz.top + rz.height / 2) - (ra.top + ra.height / 2);
      var run = ghost.animate([{ transform: "translate(0,0) scale(1.3)", opacity: 1 }, { transform: "translate(" + dx + "px," + dy + "px) scale(1)", opacity: 0.2 }], { duration: 900, easing: "ease-in-out" });
      run.onfinish = function () { if (ghost.parentNode) ghost.parentNode.removeChild(ghost); };
      return true;
    }
    if (k === "mail") { fly(li.querySelector('[data-party="actor"]'), li.querySelector('[data-party="peer"]')); return; }
    if (k === "todo") {
      /* A handoff: the card goes from the desk that let it go to the desk that took it. */
      var me = li.querySelector('[data-party="actor"]'), other = li.querySelector('[data-party="peer"]');
      if (other && fly(li.getAttribute("data-dir") === "in" ? other : me, li.getAttribute("data-dir") === "in" ? me : other)) return;
      var to = li.querySelector(".rd-st.to");
      if (!fly(li.querySelector(".rd-st:not(.to)"), to) && to) to.animate([{ transform: "scale(.4)", opacity: 0 }, { transform: "none", opacity: 1 }], ease);
      return;
    }
    if (k === "hold") {
      /* A hold is a resource the desk takes and lets go: its lock fades in on the desk's pill, or out. */
      var pill = li.querySelector('[data-party="actor"]');
      if (!pill) return;
      var box2 = li.getBoundingClientRect(), rp2 = pill.getBoundingClientRect(), lock = icon.cloneNode(true);
      lock.classList.add("rd-ghost");
      lock.style.left = (rp2.right - box2.left - 8) + "px";
      lock.style.top = (rp2.top - box2.top - 6) + "px";
      li.appendChild(lock);
      if (act === "wait") {
        /* Contested: a faded lock on the waiting desk, its edge amber, until it takes the hold. */
        lock.classList.add("rd-lock-wait");
        pill.classList.add("rd-contest");
        lock.animate([{ opacity: 0 }, { opacity: 0.45 }], { duration: 600, fill: "forwards" });
        return;
      }
      var fade = lock.animate(act === "drop" ? [{ opacity: 1 }, { opacity: 0 }] : [{ opacity: 0 }, { opacity: 1 }], { duration: 800, easing: "ease-in-out", fill: "forwards" });
      if (act === "drop") fade.onfinish = function () { if (lock.parentNode) lock.parentNode.removeChild(lock); };
      return;
    }
    if (k === "wake") {
      var who = li.querySelector('[data-party="peer"]') || li.querySelector('[data-party="actor"]') || icon;
      who.animate([{ boxShadow: "0 0 0 0 rgba(228,181,106,.8)" }, { boxShadow: "0 0 0 8px rgba(228,181,106,0)" }], { duration: 800, iterations: 2 });
      return;
    }
    if (k === "doing") { icon.animate([{ transform: "rotate(0)" }, { transform: "rotate(360deg)" }], { duration: 800, easing: "ease-in-out" }); return; }
    if (k === "score") {
      var dot = li.querySelector(".rd-sdot") || icon;
      dot.animate([{ opacity: 0.2, transform: "scale(.5)" }, { opacity: 1, transform: "scale(1.3)" }, { transform: "none" }], ease);
    }
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
  root.addEventListener("input", function (ev) {
    var el = ev.target;
    if (!el || !el.getAttribute || !el.getAttribute("data-rp-scrub")) return;
    var rep = rpRep();
    if (!rep) return;
    rp.playing = false;
    var v = Number(el.value) || 0;
    rp.t = v >= 1000 ? null : rep.since + (rep.until - rep.since) * v / 1000;
    drawReplay(false);
  });
  /* The move rows (the transitions) of the cards and promises in the week, and each focused
   * desk's own focus rows. Read again only when the item moved, or once a minute for a desk. */
  var movesAt = {};
  function fetchReplay(b) {
    if (state.tab !== "collab" || !b.data.events) return;
    var at = {};
    R.replayItems(b, 40).forEach(function (key) { at[key] = 1; });
    Object.keys(at).forEach(function (key) {
      var stamp = itemStamp(b, key);
      var k = "moves|" + key;
      if (inflight[k] || movesAt[key] === stamp) return;
      inflight[k] = getJson("/api/v1/doing/history?on=" + encodeURIComponent(key)).then(function (j) {
        inflight[k] = null;
        if (j && Array.isArray(j.history)) { data.moves[key] = j.history; movesAt[key] = stamp; if (!rp.playing) paintSoon(); }
      });
    });
    var since = new Date(b.now - R.REPLAY_WINDOWS.week).toISOString().slice(0, 19).replace("T", " ");
    b.desks.slice(0, 40).forEach(function (d) {
      var k = "trail|" + d.name;
      if (inflight[k] || (gotAt[k] && Date.now() - gotAt[k] < 60000)) return;
      inflight[k] = getJson("/api/v1/doing/history?desk=" + encodeURIComponent(d.name) + "&since=" + encodeURIComponent(since)).then(function (j) {
        inflight[k] = null;
        gotAt[k] = Date.now();
        if (j && Array.isArray(j.history)) { data.trail[d.name] = j.history; if (!rp.playing) paintSoon(); }
      });
    });
  }
  function itemStamp(b, key) {
    var hit = "";
    Object.keys(b.data.events || {}).forEach(function (r) {
      (b.data.events[r] || []).forEach(function (e) { if (e && (e.kind + "-" + e.id) === key) hit = String(e.at); });
    });
    return hit;
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
    if (changed) { last.pane = null; rpStop(); }
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
      else if (state.tab === "collab") { save(COLLAB_VIEW_KEY, v); rpStop(); last.pane = null; if (v === "replay") unhostAll(); }
      else if (cfg && cfg.attr) {
        var btn = document.querySelector("[" + cfg.attr + '="' + v + '"]');
        if (btn && btn !== el) btn.click();
      }
      last.host = null;
      paint();
      return;
    }
    if (state.tab === "todo" && isWide() && (el = closest(t, "#pane-todo [data-todo-id], #pane-todo .todo-tree-card"))) {
      var from = closest(el, "#jobs-kanban, #jobs-list, #jobs-outline");
      /* After boot.js's own click opened the card. */
      setTimeout(function () { linkTodo(from); }, 0);
      return;
    }
    if ((el = closest(t, "[data-rp-play]"))) { if (rp.playing) rpPause(); else rpPlay(); return; }
    if ((el = closest(t, "[data-rp-step]"))) { rpStep(); return; }
    if ((el = closest(t, "[data-rp-win]"))) { save(RP_WIN_KEY, el.getAttribute("data-rp-win")); rpStop(); paint(); return; }
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
