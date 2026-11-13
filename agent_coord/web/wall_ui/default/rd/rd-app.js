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
    collab: []
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
    events: "/api/v1/events?project=%R&limit=200",
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
    collab: { pane: "pane-floor", legacy: "floor", attr: "data-floor-mode", views: [{ key: "map", label: "Between" }, { key: "timeline", label: "Timeline" }] },
    priorities: { pane: "pane-priorities", legacy: "priorities", views: [] }
  };
  /* Wide enough for kanban, list and tree side by side. */
  var WIDE_Q = "(min-width: 1600px)";
  var TODO_VIEW_KEY = "rd-todo-view";
  /* Card 1193: these reads take ?window=1d|7d|30d on the tab that shows a time range. */
  var WINDOWED = { desks: ["agents"], score: ["scores"] };
  var WINDOW_Q = { today: "1d", "7d": "7d", "30d": "30d" };
  var FRESH_MS = { agents: 20000, names: 300000, todos: 30000, mail: 30000, labels: 60000, scores: 30000, holds: 30000, rooms: 120000, trees: 120000, events: 30000, runs: 60000 };
  var RANGE_KEY = "rd-range", TAB_KEY = "rd-tab";

  var data = { agents: {}, names: {}, todos: {}, mail: {}, labels: {}, scores: {}, holds: {}, rooms: {}, trees: {}, events: {}, runs: {}, history: {}, doing: null, stations: null, rosterList: null };
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
  function legacyTab() { return HOSTED[state.tab] ? HOSTED[state.tab].legacy : "session"; }
  /* Have boot.js paint and poll the pane on show (it owns the data for the hosted panes). */
  function syncLegacy() {
    var W = legacy();
    if (!W || !W.started || !W.showTab) return;
    var cfg = HOSTED[state.tab];
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
  function viewOn(tab) {
    if (tab === "todo") return savedTodoView();
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
    if (HOSTED[t]) { paintHosted(b); return; }
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
    } else {
      var model = m[t];
      var body = model ? V[t](model) : '<div class="rd-loading">Loading ' + t.toUpperCase() + "\u2026</div>";
      if (model && model.selected) state.sel[t] = model.selected;
      html = V.paneHead(t, b) + '<div class="rd-pane-body rd-tab-body">' + body + "</div>";
      html = html.replace('class="rd-tab-groups', 'data-rd-scroll="groups" class="rd-tab-groups').replace('<aside class="rd-tab-detail"', '<aside data-rd-scroll="detail" class="rd-tab-detail"');
    }
    pane.setAttribute("data-rd-pane", t);
    setHtml(pane, html, "pane");
    root.classList.toggle("rd-desk-open", t === "desks" && state.phoneDesk);
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
    if (changed) { last.pane = null; }
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
