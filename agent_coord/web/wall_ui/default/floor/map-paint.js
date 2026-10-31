/* WALL_UI_DEFAULT_FLOOR_MAP - COLLAB map paint (lazy; not on Session first paint).
 * Expects window.__wallMapDeps with paint helpers from boot.
 * Marker: WALL_UI_DEFAULT_FLOOR_MAP
 */
(function (global) {
  "use strict";

  function deps() {
    return global.__wallMapDeps || {};
  }
  function D(name) {
    var d = deps();
    if (typeof d[name] === "function") return d[name];
    return d[name];
  }

  function paintFloorMap(g) {
    var mapEl = document.getElementById("floor-map");
    if (!mapEl) return;
    var paintFloorSpan = D("paintFloorSpan");
    var paintFloorAgg = D("paintFloorAgg");
    var aggregateFloorGlance = D("aggregateFloorGlance");
    var floorLayout = D("floorLayout");
    var floorEdgeLabel = D("floorEdgeLabel");
    var esc = D("esc");
    var hereGlance = D("hereGlance");
    var wallDoingText = D("wallDoingText");
    var millNameBare = D("millNameBare");
    var floorSpanLabel = D("floorSpanLabel");
    var showFloorEdge = D("showFloorEdge");
    var showFloorDesk = D("showFloorDesk");
    var getFloorAgg = D("getFloorAgg");
    var getFloorSpan = D("getFloorSpan");
    var floorAgg = typeof getFloorAgg === "function" ? getFloorAgg() : D("floorAgg");
    var floorSpan = typeof getFloorSpan === "function" ? getFloorSpan() : D("floorSpan");
    if (typeof paintFloorSpan === "function") paintFloorSpan();
    if (typeof paintFloorAgg === "function") paintFloorAgg();
    var gUse = (typeof aggregateFloorGlance === "function" ? aggregateFloorGlance(g) : null) || g;
    var desksIn = (gUse && gUse.desks) || [];
    var edges = (gUse && gUse.edges) || [];
    if (!desksIn.length) {
      mapEl.innerHTML = '<div class="idle map-empty">Nothing between desks yet. A desk shows up when a letter, a card, or a promise joins it to another desk.</div>';
      return;
    }
    var nodes = floorLayout(desksIn);
    var byOwner = {};
    nodes.forEach(function (n) { byOwner[n.owner] = n; });
    var maxE = Math.max(1, ...edges.map(function (e) { return Number(e.count || 0); }));
    var edgeSvg = edges.filter(function (e) { return byOwner[e.a] && byOwner[e.b] && e.a !== e.b; }).map(function (e) {
      var a = byOwner[e.a], b = byOwner[e.b];
      var w = 1.2 + 6 * (Number(e.count || 0) / maxE);
      var cls = e.back_and_forth ? "floor-edge both" : "floor-edge";
      var etip = e.a + " <-> " + e.b + " | " + floorEdgeLabel(e) + (e.back_and_forth ? " | back-and-forth" : "");
      return '<path class="' + cls + '" data-edge-a="' + esc(e.a) + '" data-edge-b="' + esc(e.b) + '" data-count="' + esc(e.count) + '" ' +
        'd="M' + a.x.toFixed(1) + " " + a.y.toFixed(1) + " L" + b.x.toFixed(1) + " " + b.y.toFixed(1) + '" stroke-width="' + w.toFixed(2) + '"><title>' + esc(etip) + "</title></path>";
    }).join("");
    var nodeSvg = nodes.map(function (n) {
      var dFloor = global._floor || {};
      var isWs = n.kind === "workstation" || floorAgg === "workstation";
      var st = n.rollup_state || (n.stale ? "stale" : "idle");
      var doingStored = String(n.doing || "").trim();
      if (!isWs) {
        var agent = (dFloor.agents || []).find(function (a) { return a.owner === n.owner && a.alive; })
          || (dFloor.agents || []).find(function (a) { return a.owner === n.owner; })
          || { owner: n.owner, doing: n.doing || "", waiting_on: n.waiting_on || "", stale: n.stale };
        var gState = hereGlance(dFloor, agent);
        st = gState.state || (n.stale ? "stale" : "idle");
        if (!doingStored) doingStored = String(agent.doing || "").trim();
      }
      var now = isWs ? doingStored : wallDoingText(n.owner, doingStored);
      var unread = Number(n.unread || 0);
      var label = isWs ? String(n.owner || "").replace(/^Workstation-/i, "WS-") : millNameBare("desk", n.owner);
      var doing = now.length > 22 ? now.slice(0, 21) + "..." : now;
      var tip = [label, st, now].concat(unread ? [unread + " unread"] : []).filter(Boolean).join(" | ");
      var badge = unread > 0
        ? '<circle cx="' + (n.x + 18).toFixed(1) + '" cy="' + (n.y - 18).toFixed(1) + '" r="9" fill="var(--amber)" /><text text-anchor="middle" x="' + (n.x + 18).toFixed(1) + '" y="' + (n.y - 14).toFixed(1) + '" fill="#111" font-size="9" font-weight="800">' + (unread > 99 ? "99+" : unread) + "</text>"
        : "";
      var doingTxt = doing
        ? '<text class="floor-doing" text-anchor="middle" x="' + n.x.toFixed(1) + '" y="' + (n.y + 36).toFixed(1) + '">' + esc(doing) + "</text>"
        : "";
      return '<g class="floor-node ' + esc(st) + (n.stale ? " stale" : "") + '" data-owner="' + esc(n.owner) + '" data-kind="' + esc(isWs ? "workstation" : "desk") + '">' +
        "<title>" + esc(tip) + "</title>" +
        '<circle cx="' + n.x.toFixed(1) + '" cy="' + n.y.toFixed(1) + '" r="22" />' +
        '<text text-anchor="middle" x="' + n.x.toFixed(1) + '" y="' + (n.y + 4).toFixed(1) + '">' + esc(label) + "</text>" +
        badge + doingTxt + "</g>";
    }).join("");
    var spanVal = (g && g.window) || floorSpan;
    mapEl.innerHTML = '<svg viewBox="0 0 800 340" role="img" aria-label="Collab between ' + esc(floorSpanLabel(spanVal)) + '">' + edgeSvg + nodeSvg + "</svg>";
    mapEl.onclick = function (ev) {
      var pop = document.getElementById("floor-pop");
      var edge = ev.target.closest(".floor-edge");
      mapEl.querySelectorAll(".floor-edge.on, .floor-node.on").forEach(function (el) { el.classList.remove("on"); });
      if (edge) {
        edge.classList.add("on");
        showFloorEdge(edge.getAttribute("data-edge-a"), edge.getAttribute("data-edge-b"));
        return;
      }
      var node = ev.target.closest(".floor-node");
      if (node) {
        node.classList.add("on");
        showFloorDesk(node.getAttribute("data-owner"), node.getAttribute("data-kind") || "desk");
        return;
      }
      if (pop) pop.hidden = true;
    };
  }

  global.WallFloorMap = {
    paint: paintFloorMap,
    marker: "WALL_UI_DEFAULT_FLOOR_MAP"
  };
  global.WALL_UI_DEFAULT_FLOOR_MAP = "WALL_UI_DEFAULT_FLOOR_MAP";
})(typeof window !== "undefined" ? window : globalThis);
