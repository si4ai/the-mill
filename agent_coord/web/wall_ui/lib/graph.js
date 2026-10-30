/* WALL_UI_LIB_GRAPH - floor map / graph layout helpers (Path A).
 * Thin shared extract; default pack floor.js may still own pack-specific paint.
 * SoR: wall-contract; tests/wall
 * Marker: WALL_UI_LIB_GRAPH
 */
(function (global) {
  "use strict";

  function floorStateRank(st) {
    var s = String(st || "").toLowerCase();
    if (s === "working" || s === "busy") return 3;
    if (s === "waiting" || s === "blocked") return 2;
    if (s === "idle") return 1;
    if (s === "stale" || s === "dead") return 0;
    return 1;
  }

  function floorHostOf(d, hostByOwner) {
    hostByOwner = hostByOwner || {};
    var owner = String((d && d.owner) || "").trim();
    if (!owner) return "";
    if (d && d.host) return String(d.host);
    return String(hostByOwner[owner] || "");
  }

  function floorLayout(desks, opts) {
    desks = desks || [];
    opts = opts || {};
    var n = Math.max(desks.length, 1);
    var cx = opts.cx != null ? opts.cx : 400;
    var cy = opts.cy != null ? opts.cy : 170;
    var R = opts.R != null ? opts.R : Math.min(140, 40 + n * 28);
    return desks.map(function (d, i) {
      var ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
      var out = {};
      Object.keys(d || {}).forEach(function (k) { out[k] = d[k]; });
      out.x = cx + R * Math.cos(ang);
      out.y = cy + R * Math.sin(ang);
      return out;
    });
  }

  function honestEmptyGraph(reason) {
    return { desks: [], edges: [], empty: true, reason: reason || "no glance data" };
  }

  global.wallFloorStateRank = floorStateRank;
  global.wallFloorHostOf = floorHostOf;
  global.wallFloorLayout = floorLayout;
  global.wallHonestEmptyGraph = honestEmptyGraph;
  global.WALL_UI_LIB_GRAPH = "WALL_UI_LIB_GRAPH";
})(typeof window !== "undefined" ? window : globalThis);
