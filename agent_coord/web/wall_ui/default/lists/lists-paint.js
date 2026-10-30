/* WALL_UI_DEFAULT_LISTS_PAINT - split out of boot.js (#872).
 * Marker: WALL_UI_DEFAULT_LISTS_PAINT
 * Loads on first use through lib/lazy.js (MODULES.listsPaint); boot.js keeps a stub for each entry.
 * Classic script on purpose: it shares boot.js globals (let/const state and functions),
 * and its function declarations replace the boot.js stubs.
 */


    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function wallWatcherKey(r) {
      return String((r && r.type) || "") + ":" + String((r && r.id) || "");
    }
    function wallPaintTreesKind(kind) {
      const d = window._floor;
      if (!d) return;
      if (kind === "tree-mail" || kind === "trees") {
        try {
          if (typeof mailView !== "undefined" && mailView === "rooms" && typeof paintMailRooms === "function") {
            paintMailRooms(d);
          } else if (typeof mailView !== "undefined" && mailView === "letters" && typeof mail === "function") {
            mail(d);
          }
        } catch (eM) {}
      }
      if (kind === "tree-todo" || kind === "trees") {
        try { if (typeof paintPlan === "function") paintPlan(d); } catch (eP) {}
        try { if (typeof board === "function") board(d); } catch (eB) {}
        try { if (typeof issues === "function") issues(d); } catch (eI) {}
      }
    }
    async function wallFetchTreeExpand(parentType, parentId, opts) {
      /* GET ?parent_id=type:id&limit=50 (+cursor) -> splice direct children under parent. */
      opts = opts || {};
      const typ = String(parentType || "").toLowerCase();
      const id = String(parentId || "");
      if (!typ || !id) return false;
      const parentKey = typ + ":" + id;
      const kind = opts.kind || wallActiveTreeKind() || (typ === "todo" ? "tree-todo" : "tree-mail");
      const cursor = opts.cursor != null ? opts.cursor : _wallTreeExpandNext[parentKey];
      if (opts.cursor === undefined && _wallTreeExpandInflight[parentKey]) {
        return _wallTreeExpandInflight[parentKey];
      }
      const scope = (typeof floorScope === "function") ? floorScope() : null;
      if (!scope || !String(scope.query || "").trim()) return false;
      const q = String(scope.query || "");
      const path = (kind === "tree-todo" || (kind === "trees" && typ === "todo"))
        ? "/api/v1/tree-todo"
        : "/api/v1/tree-mail";
      let url = path + "?" + q + (q ? "&" : "") + "limit=50&parent_id=" + encodeURIComponent(parentKey);
      url += wallTreesWindowQuery();
      if (cursor) url += "&cursor=" + encodeURIComponent(String(cursor));
      const p = (async function () {
        try {
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) return false;
          const ct = (r.headers.get("content-type") || "").toLowerCase();
          if (ct.indexOf("json") < 0) return false;
          const json = await r.json();
          if (!wallAppendTreesPage(json, kind)) return false;
          const nxt = json && json.next;
          _wallTreeExpandNext[parentKey] = (nxt == null || nxt === "") ? null : String(nxt);
          wallPaintTreesKind(kind);
          try { if (typeof markOverflow === "function") markOverflow(); } catch (eMore) {}
          return true;
        } catch (eFetch) {
          return false;
        } finally {
          _wallTreeExpandInflight[parentKey] = null;
        }
      })();
      _wallTreeExpandInflight[parentKey] = p;
      return p;
    }
    function wallAppendMailboxPage(json) {
      if (!json || !Array.isArray(json.mailbox)) return false;
      const d = window._floor;
      if (!d) return false;
      d.mailbox = wallDedupeAppend(Array.isArray(d.mailbox) ? d.mailbox : [], json.mailbox);
      if (json.desk_unread && typeof json.desk_unread === "object") {
        d.desk_unread = Object.assign({}, d.desk_unread || {}, json.desk_unread);
      }
      wallRememberListNext("mailbox", json);
      try {
        if (_floorBook && typeof _floorBook === "object") {
          _floorBook.mailbox = d.mailbox;
          if (d.desk_unread) _floorBook.desk_unread = d.desk_unread;
        }
      } catch (eBook) {}
      return true;
    }
    function wallAppendTodosPage(json) {
      if (!json) return false;
      const d = window._floor;
      if (!d) return false;
      if (Array.isArray(json.needs)) d.needs = wallDedupeAppend(Array.isArray(d.needs) ? d.needs : [], json.needs);
      if (Array.isArray(json.issues)) d.issues = wallDedupeAppend(Array.isArray(d.issues) ? d.issues : [], json.issues);
      wallRememberListNext("todos", json);
      try {
        if (_floorBook && typeof _floorBook === "object") {
          if (d.needs) _floorBook.needs = d.needs;
          if (d.issues) _floorBook.issues = d.issues;
        }
      } catch (eBook) {}
      return true;
    }
    function wallAppendFloorKindPage(kind, json) {
      /* append agents/scores/holds/watchers/events from floor page. */
      const d = window._floor;
      if (!d || !json || typeof json !== "object") return false;
      if (kind === "agents" && Array.isArray(json.agents)) {
        d.agents = wallDedupeAppend(Array.isArray(d.agents) ? d.agents : [], json.agents);
        try { if (_floorBook) _floorBook.agents = d.agents; } catch (eB) {}
      } else if (kind === "scores" && Array.isArray(json.kpis)) {
        d.kpis = wallDedupeAppend(Array.isArray(d.kpis) ? d.kpis : [], json.kpis);
        try { if (_floorBook) _floorBook.kpis = d.kpis; } catch (eB) {}
      } else if (kind === "holds" && Array.isArray(json.locks)) {
        d.locks = wallDedupeAppend(Array.isArray(d.locks) ? d.locks : [], json.locks);
        try { if (_floorBook) _floorBook.locks = d.locks; } catch (eB) {}
      } else if (kind === "watchers" && Array.isArray(json.watchers)) {
        d.watchers = wallDedupeAppend(Array.isArray(d.watchers) ? d.watchers : [], json.watchers, wallWatcherKey);
        try { if (_floorBook) _floorBook.watchers = d.watchers; } catch (eB) {}
      } else if (kind === "events" && Array.isArray(json.events)) {
        d.events = wallDedupeAppend(Array.isArray(d.events) ? d.events : [], json.events, wallWatcherKey);
        try { if (_floorBook) _floorBook.events = d.events; } catch (eB) {}
      } else if (kind === "names" && Array.isArray(json.catalog)) {
        d.catalog = wallDedupeAppend(Array.isArray(d.catalog) ? d.catalog : [], json.catalog, function (r) {
          return String((r && r.kind) || "") + ":" + String((r && r.name) || "");
        });
        try { if (_floorBook) _floorBook.catalog = d.catalog; } catch (eB) {}
      } else {
        return false;
      }
      wallRememberListNext(kind, json);
      return true;
    }
    function wallAppendActivityPage(json) {
      if (!json || !Array.isArray(json.rows)) return false;
      _presenceRows = wallDedupeAppend(Array.isArray(_presenceRows) ? _presenceRows : [], json.rows);
      wallRememberListNext("activity", json);
      return true;
    }
    function wallPaintListKind(kind) {
      const d = window._floor;
      if (kind === "mailbox") { try { mail(d); } catch (e) {} return; }
      if (kind === "tree-mail" || kind === "tree-todo" || kind === "trees") {
        try { wallPaintTreesKind(kind); } catch (eT) {}
        return;
      }
      if (kind === "todos") {
        try { board(d); } catch (e) {}
        try { issues(d); } catch (e2) {}
        try { if (typeof paintPlan === "function") paintPlan(d); } catch (e3) {}
        return;
      }
      if (kind === "agents") { try { board(d, { hereOnly: true }); } catch (e) {} return; }
      if (kind === "scores") { try { cards(d); } catch (e) {} return; }
      if (kind === "holds") { try { stations(d); } catch (e) {} return; }
      if (kind === "watchers") { try { paintWatchers(d); } catch (e) {} return; }
      if (kind === "activity") { try { if (d) paintSessionWire(d); } catch (e) {} return; }
      if (kind === "events") {
        try { wire(d); } catch (eW) {}
        try { if (d) paintSessionWire(d); } catch (eS) {}
        try {
          const floorOn = document.getElementById("pane-floor");
          if (floorOn && floorOn.classList.contains("on") && typeof ensureFloorPaint === "function") ensureFloorPaint();
        } catch (eF) {}
        return;
      }
    }
    async function wallFetchListNextPage(kind) {
      if (!WALL_LIST_KINDS[kind]) return false;
      const cursor = _wallListNext[kind];
      if (cursor == null || cursor === "") return false;
      if (_wallListInflight[kind]) return _wallListInflight[kind];
      const scope = (typeof floorScope === "function") ? floorScope() : null;
      if (!scope || !String(scope.query || "").trim()) return false;
      const q = String(scope.query || "");
      let url = "";
      if (kind === "mailbox" || kind === "todos") {
        const path = (kind === "mailbox") ? "/api/v1/mailbox" : "/api/v1/todos";
        url = path + "?" + q + (q ? "&" : "") + "limit=50&cursor=" + encodeURIComponent(cursor);
      } else if (kind === "tree-mail" || kind === "tree-todo" || kind === "trees") {
        const treePath = (kind === "tree-todo" || (kind === "trees" && wallActiveTreeKind() === "tree-todo"))
          ? "/api/v1/tree-todo"
          : "/api/v1/tree-mail";
        url = treePath + "?" + q + (q ? "&" : "") + "limit=50&cursor=" + encodeURIComponent(cursor);
        url += wallTreesWindowQuery();
      } else if (kind === "agents" || kind === "scores" || kind === "holds" ||
                 kind === "watchers" || kind === "events" || kind === "names") {
        const v1Path = ({
          agents: "/api/v1/agents",
          scores: "/api/v1/scores",
          holds: "/api/v1/holds",
          watchers: "/api/v1/watchers",
          events: "/api/v1/events",
          names: "/api/v1/names"
        })[kind];
        url = v1Path + "?" + q + (q ? "&" : "") + "limit=50&cursor=" + encodeURIComponent(cursor);
      } else if (kind === "activity") {
        url = activitySpanQuery().url + "&cursor=" + encodeURIComponent(cursor);
      } else {
        return false;
      }
      const p = (async function () {
        try {
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) return false;
          const ct = (r.headers.get("content-type") || "").toLowerCase();
          if (ct.indexOf("json") < 0) return false;
          const json = await r.json();
          let ok = false;
          if (kind === "mailbox") ok = wallAppendMailboxPage(json);
          else if (kind === "todos") ok = wallAppendTodosPage(json);
          else if (kind === "tree-mail" || kind === "tree-todo" || kind === "trees") ok = wallAppendTreesPage(json, kind);
          else if (kind === "activity") ok = wallAppendActivityPage(json);
          else ok = wallAppendFloorKindPage(kind, json);
          if (!ok) return false;
          wallPaintListKind(kind);
          try { if (typeof markOverflow === "function") markOverflow(); } catch (eMore) {}
          return true;
        } catch (eFetch) {
          return false;
        } finally {
          _wallListInflight[kind] = null;
        }
      })();
      _wallListInflight[kind] = p;
      return p;
    }
var WALL_UI_DEFAULT_LISTS_PAINT = "WALL_UI_DEFAULT_LISTS_PAINT";
