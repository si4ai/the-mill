/* WALL_UI_LIB_DATA - fetch + last-good + api-down helpers (Path A).
 * Extract from board.html paintApiDown / tick last-good / fetchJsonFirst.
 * SoR: wall-contract; tests/wall
 * Amend: wall-contract; tests/wall/test_wall_honest_empty_vs_down.py
 * Marker: WALL_UI_LIB_DATA
 * Marker: WALL_HONEST_EMPTY_VS_DOWN
 * Marker: MAINTENANCE_DRAIN
 */
(function (global) {
  "use strict";

  var API_DOWN_BANNER =
    "<b>mill API down.</b> Last-good wall kept if any \u2014 do not treat this as an empty office. " +
    "<span class=\"recovery-label\">Recovery:</span> Tell your Mill desk agent to restart the wall " +
    "(<code class=\"recovery-cmd\">install wall --apply</code> / restart wall service) \u2014 humans do not run schtasks.";

  var EMPTY_MSG = {
    session: "No desks are here. Ask your agent to join.",
    score_kpi: "Honest empty \u2014 no agent_kpi yet.",
    score_progress: "Honest empty \u2014 no desks/needs/spend yet.",
    score_bottlenecks: "None \u2014 no waiting tw runs / stalled JOBs.",
    mail: "no mail for this filter (floor-only or empty)",
    floor: "Honest empty \u2014 no floor glance yet.",
    spend: "no spend yet. After a model turn: mill spend --source grok --tokens N"
  };

  function keepLastGood(floor) {
    /* Never invent empty mill data - keep prior last-good snapshot. */
    return floor && typeof floor === "object" ? floor : {};
  }

  function classifyFetch(opts) {
    opts = opts || {};
    if (opts.networkError) return "down";
    if (opts.ok === false) return "down";
    var status = opts.status;
    if (status != null && Number(status) >= 400) return "down";
    if (status != null && Number(status) > 0 && Number(status) < 200) return "down";
    var ct = String(opts.contentType || "").toLowerCase();
    if (status != null && Number(status) >= 200 && Number(status) < 300) {
      if (ct && ct.indexOf("json") < 0) return "down";
      return "ok";
    }
    if (opts.ok === true) return "ok";
    if (opts.ok == null && status == null && !opts.networkError) return "ok";
    return "down";
  }

  function classifyOutcome(opts) {
    opts = opts || {};
    if (opts.fetch === "down") return "down";
    if (opts.paintError) return "paint_error";
    var payload = opts.payload;
    if (payload == null) return "empty";
    if (typeof payload === "object" && !Array.isArray(payload)) {
      var agents = payload.agents || payload.live_agents || [];
      var live = agents.filter(function (a) { return a && a.alive; });
      var kpis = payload.kpis || [];
      var mailbox = payload.mailbox;
      var needs = payload.needs || [];
      if (!live.length && !kpis.length && (mailbox == null || (Array.isArray(mailbox) && !mailbox.length)) && !needs.length) {
        return "empty";
      }
      if (!live.length && !kpis.length) return "empty";
      return "ok";
    }
    if ((Array.isArray(payload) && !payload.length) || (typeof payload === "object" && !Object.keys(payload).length)) {
      return "empty";
    }
    return "ok";
  }

  function honestLlmDisplay(tokens, tokensEst) {
    if (tokens != null && tokens !== "") {
      var n = Number(tokens);
      if (Number.isFinite(n)) return String(n);
    }
    if (tokensEst != null && tokensEst !== "") {
      var e = Number(tokensEst);
      if (Number.isFinite(e)) return String(e);
    }
    return "\u2014";
  }

  function honestMillBytesDisplay(millBytes, millRows) {
    if (!millRows) return "\u2014";
    if (millBytes == null || millBytes === "") return "\u2014";
    var n = Number(millBytes);
    if (!Number.isFinite(n)) return "\u2014";
    return String(n);
  }

  function sumLlmTokens(rows) {
    var total = null;
    (rows || []).forEach(function (r) {
      if (!r) return;
      if (String(r.source || "") === "mill") return;
      if (r.tokens == null || r.tokens === "") return;
      var n = Number(r.tokens);
      if (!Number.isFinite(n)) return;
      if (total == null) total = 0;
      total += n;
    });
    return total;
  }

  function maintenanceBannerHtml(maint) {
    if (!maint || !maint.eta_at) return "";
    var eta = String(maint.eta_at || "");
    var phase = String(maint.phase || "draining");
    var reason = String(maint.reason || "").trim();
    var why = reason ? (" " + reason) : "";
    if (phase === "overdue") {
      return "<b>maintenance overdue.</b> ETA was " + eta + "." + why +
        " Desks reconnecting (\u2264120s cadence). Not a surprise API outage.";
    }
    return "<b>maintenance / draining.</b> ETA " + eta + "." + why +
      " Desks sleep until ETA, then reconnect. Not false API-down.";
  }

  function paintApiDown(opts) {
    opts = opts || {};
    var msg = opts.msg || "wall API down - mill API or mill-wall";
    var clock = opts.clock;
    var banner = opts.banner;
    var lastGood = keepLastGood(opts.lastGood != null ? opts.lastGood : global._floor);
    var maint = lastGood && lastGood.maintenance;
    var intentional = !!(maint && maint.eta_at);
    if (typeof document !== "undefined") {
      if (!clock) clock = document.getElementById("clock");
      if (!banner) banner = document.getElementById("kpi-banner");
    }
    if (clock) {
      clock.classList.add("warn");
      clock.textContent = intentional
        ? ("maintenance " + String(maint.phase || "draining") + " eta " + String(maint.eta_at))
        : msg;
    }
    if (banner) {
      banner.classList.add("on");
      if (intentional) {
        banner.classList.remove("api-down");
        banner.classList.add("maintenance");
        banner.setAttribute("data-wall-api", "maintenance");
        banner.innerHTML = maintenanceBannerHtml(maint);
      } else {
        banner.classList.add("api-down");
        banner.setAttribute("data-wall-api", "down");
        banner.innerHTML = API_DOWN_BANNER;
      }
    }
    if (typeof opts.strip === "function") {
      try { opts.strip(lastGood); } catch (e) {}
    }
    return {
      apiOk: false,
      lastGood: lastGood,
      msg: msg,
      outcome: intentional ? "maintenance" : "down",
      maintenance: intentional ? maint : null
    };
  }

  function clearApiDownBanner(banner) {
    if (typeof document !== "undefined" && !banner) banner = document.getElementById("kpi-banner");
    if (!banner) return;
    var apiState = banner.getAttribute("data-wall-api");
    if (apiState === "down" || apiState === "maintenance" || banner.classList.contains("api-down") || banner.classList.contains("maintenance")) {
      banner.classList.remove("api-down");
      banner.classList.remove("maintenance");
      banner.removeAttribute("data-wall-api");
      banner.classList.remove("on");
      banner.textContent = "";
    }
  }

  function fetchJsonFirst(urls) {
    urls = urls || [];
    return (async function () {
      for (var i = 0; i < urls.length; i++) {
        var u = urls[i];
        try {
          var r = await fetch(u, { cache: "no-store" });
          var ct = ((r.headers.get("content-type") || "") + "").toLowerCase();
          if (r.ok && ct.indexOf("json") >= 0) return await r.json();
        } catch (e) { /* try next */ }
      }
      return null;
    })();
  }

  function rememberFloor(raw, cutFloor) {
    if (raw == null) return null;
    global._floorRaw = raw;
    var d = typeof cutFloor === "function" ? cutFloor(raw) : raw;
    global._floor = d;
    return d;
  }

  function paintThrowSafe(fn, label) {
    try {
      return typeof fn === "function" ? fn() : undefined;
    } catch (e) {
      try {
        var clock = typeof document !== "undefined" ? document.getElementById("clock") : null;
        if (clock) {
          clock.classList.add("warn");
          clock.title = "render warn:" + (label ? (" " + label + ":") : "") + " " + ((e && e.message) ? e.message : String(e));
        }
      } catch (e2) {}
      return { outcome: "paint_error", error: e };
    }
  }

  global.wallPaintApiDown = paintApiDown;
  global.wallMaintenanceBannerHtml = maintenanceBannerHtml;
  global.wallClearApiDownBanner = clearApiDownBanner;
  global.wallKeepLastGood = keepLastGood;
  global.wallFetchJsonFirst = fetchJsonFirst;
  global.wallRememberFloor = rememberFloor;
  global.wallClassifyFetch = classifyFetch;
  global.wallClassifyOutcome = classifyOutcome;
  global.wallHonestLlmDisplay = honestLlmDisplay;
  global.wallHonestMillBytesDisplay = honestMillBytesDisplay;
  global.wallSumLlmTokens = sumLlmTokens;

  /* #899 rule-act-labels: command-name acts from the 0.8.0 ENUM. Unknown acts show raw. */
  var WALL_ACT_LABELS = {
    create: "created",
    send: "sent",
    reply: "replied",
    note: "noted",
    park: "parked",
    claim: "claimed",
    unclaim: "unclaimed",
    assign: "assigned",
    unpark: "unparked",
    ship: "shipped",
    done: "done",
    back: "back",
    hold: "held",
    drop: "dropped",
    focus: "focused",
    clear: "cleared",
    finish: "finished",
    score: "scored",
    retire: "retired",
    reclaim: "reclaimed",
    remove: "removed",
    delete: "deleted",
    restore: "restored",
    purge: "purged",
    rename: "renamed",
    ring: "rang",
    task: "tasked",
    replace: "replaced"
  };
  var WALL_ACT_EVIDENCE = { ship: 1, done: 1 };

  function wallActLabel(act) {
    var a = String(act == null ? "" : act).trim();
    if (!a) return "";
    if (Object.prototype.hasOwnProperty.call(WALL_ACT_LABELS, a)) return WALL_ACT_LABELS[a];
    return a;
  }
  function wallActHasEvidence(act) {
    return !!WALL_ACT_EVIDENCE[String(act == null ? "" : act).trim()];
  }
  /* Newest ship/done evidence on a card trail; a later back clears it. */
  function wallCardEvidenceFromTrail(rows) {
    var list = rows || [];
    for (var i = list.length - 1; i >= 0; i--) {
      var e = list[i] || {};
      var act = String(e.act || "").trim();
      if (act === "back") return "";
      if (wallActHasEvidence(act)) {
        var ev = e.evidence;
        return ev == null ? "" : String(ev);
      }
    }
    return "";
  }


  /* Card 1191: stations from GET /api/pov?part=desks rows. A station is a lan_ip; its last
   * connection is the latest rows[].last_connected (ISO UTC, null = never). The rail shows
   * live stations and those seen inside windowDays; Admin lists every station. */
  var STATION_RAIL_DAYS = 7;
  /* Card 1207: the server sends at most this many live doings per desk (records.doing.DOINGS_CAP). */
  var DOINGS_CAP = 20;
  function wallIsoMs(raw) {
    if (raw == null || raw === "") return null;
    var t = Date.parse(String(raw));
    return Number.isFinite(t) ? t : null;
  }
  function wallAgoShort(ms) {
    /* "now", "5m ago", "3h ago", "2d ago"; "" when unknown. */
    if (ms == null || !Number.isFinite(ms)) return "";
    var m = Math.floor(Math.max(0, ms) / 60000);
    if (m < 1) return "now";
    if (m < 60) return m + "m ago";
    var h = Math.floor(m / 60);
    if (h < 48) return h + "h ago";
    return Math.floor(h / 24) + "d ago";
  }
  function wallStations(rows, nowMs) {
    /* Every station, live first, then most recent connection, then never-seen by name. */
    var by = {};
    var order = [];
    (rows || []).forEach(function (row) {
      if (!row) return;
      var ip = String(row.lan_ip || "").trim();
      var st = by[ip];
      if (!st) {
        st = by[ip] = { ip: ip, n: 0, live: false, last: null, desks: [] };
        order.push(st);
      }
      st.n += 1;
      if (row.connected) st.live = true;
      if (row.name) st.desks.push(String(row.name));
      var t = wallIsoMs(row.last_connected);
      if (t != null && (st.last == null || t > st.last)) st.last = t;
    });
    order.forEach(function (st) {
      st.ago = st.live ? "live" : (st.last == null ? "never" : wallAgoShort(nowMs - st.last));
      st.desks.sort(function (a, b) { return a.localeCompare(b); });
    });
    return order.sort(function (a, b) {
      if (a.live !== b.live) return a.live ? -1 : 1;
      var al = a.last == null ? -Infinity : a.last;
      var bl = b.last == null ? -Infinity : b.last;
      if (al !== bl) return bl - al;
      return a.ip.localeCompare(b.ip);
    });
  }
  function wallRailStations(rows, nowMs, days) {
    /* The rail's stations: live, or last connected inside days (default 7). */
    var win = (days == null ? STATION_RAIL_DAYS : days) * 86400000;
    return wallStations(rows, nowMs).filter(function (st) {
      return st.live || (st.last != null && nowMs - st.last <= win);
    });
  }

  global.wallPaintThrowSafe = paintThrowSafe;
  global.wallAgoShort = wallAgoShort;
  global.wallStations = wallStations;
  global.wallRailStations = wallRailStations;
  global.WALL_STATION_RAIL_DAYS = STATION_RAIL_DAYS;
  global.WALL_DOINGS_CAP = DOINGS_CAP;
  global.WALL_ACT_LABELS = WALL_ACT_LABELS;
  global.wallActLabel = wallActLabel;
  global.wallActHasEvidence = wallActHasEvidence;
  global.wallCardEvidenceFromTrail = wallCardEvidenceFromTrail;
  global.WALL_UI_LIB_DATA = "WALL_UI_LIB_DATA";
  global.WALL_UI_LIB_API_DOWN_BANNER = API_DOWN_BANNER;
  global.WALL_HONEST_EMPTY_VS_DOWN = "WALL_HONEST_EMPTY_VS_DOWN";
  global.WALL_HONEST_EMPTY_MSG = EMPTY_MSG;
})(typeof window !== "undefined" ? window : globalThis);
