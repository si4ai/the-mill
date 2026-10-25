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
    todoEnsurePaintContract: todoEnsurePaintContract
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallTodo = api;
  global.WALL_UI_DEFAULT_TODO = "WALL_UI_DEFAULT_TODO";
})(typeof window !== "undefined" ? window : globalThis);
