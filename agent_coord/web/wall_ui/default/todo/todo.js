/* WALL_UI_DEFAULT_TODO - thin pure-rule module for default pack (Wave 2 lazy domain).
 * Path A: mill todo card book helpers. Packs may override this file.
 * Marker: WALL_UI_DEFAULT_TODO
 */
(function (global) {
  "use strict";

  function isMillNeedId(nid) {
    nid = String(nid || "");
    return !!(nid && nid !== "leftover" && nid.indexOf("idle-") !== 0);
  }

  function millTodoCards(d) {
    /* mill todo: rec_todo. parked lives in floor.issues; needs = not parked. */
    var STAT = { parked: 1, open: 1, claimed: 1, shipped: 1, done: 1 };
    d = d || {};
    var rows = [].concat(
      (d.needs || []).filter(function (r) {
        return String(r.status || "").toLowerCase() !== "parked";
      }),
      (d.issues || []).filter(function (r) {
        return String(r.status || "").toLowerCase() === "parked";
      })
    );
    var seen = {};
    var out = [];
    rows.forEach(function (r) {
      var st = String(r.status || "").toLowerCase();
      if (!STAT[st] || !isMillNeedId(r.need_id)) return;
      var key = String(r.need_id || r.id || "");
      if (!key || seen[key]) return;
      seen[key] = true;
      out.push(r);
    });
    return out;
  }

  function millGid(r) {
    return String((r && r.roster_id) || ""); /* #869 rule-roster-fields */
  }

  function millJobsForOwner(d, owner, projectId) {
    var want = String(owner || "").trim();
    function name(x) { return String(x || "").trim() === want; }
    d = d || {};
    var pool = [].concat(d.on_it || [], d.needs || []);
    return pool.filter(function (r) {
      if (!isMillNeedId(r.need_id)) return false;
      if (r.holder_dead) return false;
      var st = r.status || "";
      if (st !== "claimed" && st !== "shipped") return false;
      if (!name(r.volunteer) && !name(r.owner)) return false;
      if (projectId && millGid(r) && String(millGid(r)) !== String(projectId)) return false;
      return true;
    });
  }

  /* TODO List view: a Jira-style table, one row per card. Pure (no DOM) so the wall
   * tests run it in node. A column shows only when the payload serves its field. */
  var TODO_STATES = ["parked", "open", "claimed", "shipped", "done"];
  var TODO_LIST_COLS = [
    { key: "id", label: "ID" },
    { key: "title", label: "Title" },
    { key: "state", label: "State" },
    { key: "claimant", label: "Claimant", ifServed: true },
    { key: "asker", label: "Asker", ifServed: true },
    /* TODO(card 1194): "age" (time in the current state) needs a state-since stamp on
     * each card; /api/v1/todos does not serve one yet, so the column stays out. */
    { key: "eta", label: "ETA", ifServed: true }
  ];

  function todoListRow(r) {
    r = r || {};
    return {
      id: String(r.id != null && r.id !== "" ? r.id : (r.need_id || "")),
      title: String(r.detail || r.title || "").replace(/\s+/g, " ").trim(),
      state: String(r.status || "").toLowerCase(),
      claimant: String(r.assigned || r.volunteer || r.owner || "").trim(),
      asker: String(r.creator || r.asker || r.src || "").trim(),
      eta: r.eta ? String(r.eta) : ""
    };
  }

  /* Columns to draw: the fixed three, plus each served column some row fills, in the
   * reader's saved order (todoColOrder) when one is given. */
  function todoListCols(rows, order) {
    var cols = TODO_LIST_COLS.filter(function (c) {
      return !c.ifServed || (rows || []).some(function (r) { return !!r[c.key]; });
    });
    var at = {};
    cols.forEach(function (c) { at[c.key] = c; });
    return todoColOrder(order, cols.map(function (c) { return c.key; })).map(function (k) { return at[k]; });
  }

  /* The list's settings when nothing is saved, and what Reset columns goes back to. Text
   * fit (Overflow | Wrap | Clip) is the Wall's shared TEXT control, not kept here. */
  var TODO_LIST_DEFAULT = { col: "state", dir: "asc", desk: "", state: "", order: [] };
  function todoListDefaults() {
    var o = {};
    Object.keys(TODO_LIST_DEFAULT).forEach(function (k) { o[k] = TODO_LIST_DEFAULT[k]; });
    o.order = [];
    return o;
  }

  /* A saved column order over the columns drawn now. Saved keys not drawn now drop out
   * (and come back in place if their column returns); a drawn key the saved order never
   * had goes right after the column it follows in the default order. */
  function todoColOrder(saved, keys) {
    keys = (keys || []).slice();
    var have = {};
    keys.forEach(function (k) { have[k] = 1; });
    var out = [];
    (Array.isArray(saved) ? saved : []).forEach(function (k) {
      if (have[k] && out.indexOf(k) < 0) out.push(k);
    });
    var base = TODO_LIST_COLS.map(function (c) { return c.key; });
    keys.forEach(function (k) {
      if (out.indexOf(k) >= 0) return;
      var at = 0;
      for (var i = base.indexOf(k) - 1; i >= 0; i--) {
        var j = out.indexOf(base[i]);
        if (j >= 0) { at = j + 1; break; }
      }
      out.splice(at, 0, k);
    });
    return out;
  }

  /* Move one column by delta places (keyboard), clamped to the ends. */
  function todoColMove(order, key, delta) {
    var out = (order || []).slice(), i = out.indexOf(key);
    if (i < 0) return out;
    var j = Math.max(0, Math.min(out.length - 1, i + (Number(delta) || 0)));
    out.splice(i, 1);
    out.splice(j, 0, key);
    return out;
  }

  /* Drop one column on another (drag): it takes the target's place. */
  function todoColDrop(order, key, onto) {
    var i = (order || []).indexOf(key), j = (order || []).indexOf(onto);
    if (i < 0 || j < 0) return (order || []).slice();
    return todoColMove(order, key, j - i);
  }

  function todoListCmp(col) {
    return function (a, b) {
      var x = a[col], y = b[col];
      if (col === "id") return (Number(x) || 0) - (Number(y) || 0);
      if (col === "state") return TODO_STATES.indexOf(x) - TODO_STATES.indexOf(y);
      return String(x).toLowerCase() < String(y).toLowerCase() ? -1 : (String(x).toLowerCase() > String(y).toLowerCase() ? 1 : 0);
    };
  }

  /* Filter by desk (claimant or asker) and state, then sort on one column. A blank cell
   * sorts last either way; ties fall back to the newest card first. */
  function todoListView(rows, opt) {
    opt = opt || {};
    var desk = String(opt.desk || ""), state = String(opt.state || "");
    var col = TODO_LIST_COLS.some(function (c) { return c.key === opt.col; }) ? opt.col : "state";
    var dir = opt.dir === "desc" ? -1 : 1, cmp = todoListCmp(col);
    var byId = todoListCmp("id");
    return (rows || []).filter(function (r) {
      if (desk && r.claimant !== desk && r.asker !== desk) return false;
      return !state || r.state === state;
    }).sort(function (a, b) {
      var ea = a[col] === "", eb = b[col] === "";
      if (ea !== eb) return ea ? 1 : -1;
      return dir * cmp(a, b) || -byId(a, b);
    });
  }

  /* Filter choices: every desk named on a row, every state present, in workflow order. */
  function todoListChoices(rows) {
    var desks = {}, states = {};
    (rows || []).forEach(function (r) {
      if (r.claimant) desks[r.claimant] = 1;
      if (r.asker) desks[r.asker] = 1;
      if (r.state) states[r.state] = 1;
    });
    return {
      desks: Object.keys(desks).sort(),
      states: TODO_STATES.filter(function (s) { return states[s]; })
    };
  }

  /* Tree outline: nested-set nodes (lft/rgt) -> one line per card in reading order, with
   * its depth and how many lines sit directly under it. keep (id -> truthy) limits the
   * cards shown (it must keep each kept card's parents); a card in collapsed hides
   * everything under it. more: the server says it has children not loaded yet. */
  function todoOutline(nodes, opt) {
    opt = opt || {};
    var keep = opt.keep || null, collapsed = opt.collapsed || {};
    var list = (nodes || []).filter(function (n) {
      return n && (!keep || keep[String(n.id)]);
    }).slice().sort(function (a, b) { return (Number(a.lft) || 0) - (Number(b.lft) || 0); });
    var rows = [], stack = [];
    list.forEach(function (n) {
      var lft = Number(n.lft) || 0;
      while (stack.length && !(lft < stack[stack.length - 1].rgt)) stack.pop();
      var parent = stack.length ? stack[stack.length - 1] : null;
      var row = { id: String(n.id), node: n, depth: stack.length, kids: 0, parent: parent ? parent.row.id : "" };
      if (parent) parent.row.kids += 1;
      rows.push(row);
      stack.push({ rgt: Number(n.rgt) || 0, row: row });
    });
    var out = [], hideBelow = -1;
    rows.forEach(function (r) {
      if (hideBelow >= 0 && r.depth > hideBelow) return;
      hideBelow = -1;
      var hint = r.node.has_children === true || r.node.has_children === 1 || r.node.has_children === "1";
      r.more = !r.kids && hint;
      r.collapsed = !!collapsed[r.id] && (r.kids > 0 || r.more);
      if (r.collapsed) hideBelow = r.depth;
      out.push(r);
    });
    return out;
  }

  function todoEnsurePaintContract() {
    return {
      marker: "WALL_UI_DEFAULT_TODO",
      cold_load: true,
      tab_enter: true,
      lazy_css: true
    };
  }

  var api = {
    isMillNeedId: isMillNeedId,
    millTodoCards: millTodoCards,
    millJobsForOwner: millJobsForOwner,
    todoListRow: todoListRow,
    todoListCols: todoListCols,
    todoListDefaults: todoListDefaults,
    todoColOrder: todoColOrder,
    todoColMove: todoColMove,
    todoColDrop: todoColDrop,
    todoListView: todoListView,
    todoListChoices: todoListChoices,
    todoOutline: todoOutline,
    todoEnsurePaintContract: todoEnsurePaintContract
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallTodo = api;
  global.WALL_UI_DEFAULT_TODO = "WALL_UI_DEFAULT_TODO";
})(typeof window !== "undefined" ? window : globalThis);
