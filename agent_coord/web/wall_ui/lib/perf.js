/* WALL_UI_LIB_PERF - opt-in Wall Performance marks/measures (cold/load debug).
 * Loaded ONLY when board.html WALL_UI_PERF_GATE sees ?wall_perf=1 or localStorage.wall_perf=1.
 * Default path: this file is never fetched - zero marks, zero fetch wrap, zero timers, zero HUD.
 * append timings=1 on /api/v1/* GET; parse body.timings; opt-in strip under tab strip.
 * Marker: WALL_UI_LIB_PERF
 */
(function (global) {
  "use strict";

  function enabled() {
    try {
      var q = new URLSearchParams((typeof location !== "undefined" && location.search) || "");
      var v = String(q.get("wall_perf") || "").trim().toLowerCase();
      if (v === "1" || v === "on" || v === "true" || v === "yes") return true;
      var ls = String(localStorage.getItem("wall_perf") || "").trim().toLowerCase();
      if (ls === "1" || ls === "on" || ls === "true" || ls === "yes") return true;
    } catch (e) {}
    return false;
  }

  /* Defense in depth: if somehow loaded when off, export nothing and exit. */
  if (!enabled()) return;

  var rows = [];
  var fetchSeq = 0;
  var dumped = false;
  var firstDone = {};
  var stripEl = null;


  function mark(name) {
    try { performance.mark(name); } catch (e) {}
  }

  function pushRow(name, startMark, endMark, bytes, extra) {
    var ms = null;
    try {
      performance.measure(name, startMark, endMark);
      var ents = performance.getEntriesByName(name, "measure");
      if (ents && ents.length) ms = Math.round(ents[ents.length - 1].duration * 10) / 10;
    } catch (e) {}
    var row = { name: name, ms: ms };
    if (bytes != null && Number.isFinite(Number(bytes))) row.bytes = Number(bytes);
    if (extra && typeof extra === "object") {
      if (extra.sql_ms != null) row.sql_ms = extra.sql_ms;
      if (extra.resp_b != null) row.resp_b = extra.resp_b;
      if (extra.n != null) row.n = extra.n;
      if (extra.route) row.route = extra.route;
    }
    rows.push(row);
    return row;
  }

  function dump() {
    try {
      console.table(rows.map(function (r) {
        return {
          name: r.name,
          ms: r.ms,
          bytes: (r.bytes != null ? r.bytes : ""),
          sql_ms: (r.sql_ms != null ? r.sql_ms : ""),
          resp_b: (r.resp_b != null ? r.resp_b : ""),
          n: (r.n != null ? r.n : ""),
        };
      }));
    } catch (e) {}
    dumped = true;
  }

  function scheduleDump(ms) {
    try { setTimeout(dump, ms || 0); } catch (e) {}
  }

  function ensureStyle() {
    /* Rules live in welcome.css so a strict style-src can load this strip (card 815). */
  }

  function ensureStrip() {
    if (stripEl && stripEl.isConnected) return stripEl;
    if (typeof document === "undefined") return null;
    ensureStyle();
    var existing = document.getElementById("wall-perf-strip");
    if (existing) { stripEl = existing; return stripEl; }
    var stack = document.querySelector(".strip-stack");
    var strip = document.getElementById("strip");
    var el = document.createElement("div");
    el.id = "wall-perf-strip";
    el.className = "wall-perf-strip";
    el.setAttribute("aria-label", "wall perf timings");
    el.hidden = true;
    try {
      if (stack && strip && strip.parentNode === stack) {
        var sub = document.getElementById("subnav");
        if (sub && sub.parentNode === stack) stack.insertBefore(el, sub);
        else if (strip.nextSibling) stack.insertBefore(el, strip.nextSibling);
        else stack.appendChild(el);
      } else if (stack) {
        stack.appendChild(el);
      } else if (strip && strip.parentNode) {
        if (strip.nextSibling) strip.parentNode.insertBefore(el, strip.nextSibling);
        else strip.parentNode.appendChild(el);
      } else {
        return null;
      }
    } catch (e2) { return null; }
    stripEl = el;
    return stripEl;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showStrip(route, rttMs, timings) {
    var el = ensureStrip();
    if (!el) return;
    var bits = [];
    bits.push('<span class="wp-route">' + esc(route) + "</span>");
    bits.push("rtt=<b>" + esc(String(rttMs)) + "</b>ms");
    if (timings && typeof timings === "object") {
      if (timings.sql_ms != null) bits.push("sql_ms=<b>" + esc(String(timings.sql_ms)) + "</b>");
      if (timings.resp_b != null) bits.push("resp_b=<b>" + esc(String(timings.resp_b)) + "</b>");
      if (timings.n != null) bits.push("n=<b>" + esc(String(timings.n)) + "</b>");
    }
    /* fp hit: empty part + echoed fp already visible in payload/Network - no new strip field. */
    el.innerHTML = bits.join(" . ");
    el.hidden = false;
  }

  mark("wall_perf:boot");

  function bootReady() {
    mark("wall_perf:boot_ready");
    pushRow("boot", "wall_perf:boot", "wall_perf:boot_ready");
    ensureStrip();
  }

  function first(label) {
    var key = String(label || "");
    if (!key || firstDone[key]) return;
    firstDone[key] = true;
    var m = "wall_perf:first_" + key;
    mark(m);
    pushRow("first_" + key, "wall_perf:boot", m);
    if (!dumped) scheduleDump(400);
  }

  function pathOf(url) {
    var path = "";
    try {
      if (typeof url !== "string") url = (url && url.url) || "";
      path = String(url).indexOf("http") === 0
        ? new URL(String(url), location.origin).pathname
        : String(url).split("?")[0];
    } catch (e) {
      path = String(url || "").split("?")[0];
    }
    return path;
  }

  function trackUrl(url) {
    var path = pathOf(url);
    return path.indexOf("/api/v1/") === 0;
  }

  function isV1Path(path) {
    return String(path || "").indexOf("/api/v1/") === 0;
  }

  function requestMethod(input, init) {
    try {
      if (init && init.method) return String(init.method).toUpperCase();
      if (input && typeof input !== "string" && input.method) return String(input.method).toUpperCase();
    } catch (e) {}
    return "GET";
  }

  /* Append timings=1 to /api/v1/* GETs only (floor has no timings API - skip). */
  function withTimingsParam(url) {
    try {
      var raw = String(url || "");
      var abs = raw.indexOf("http") === 0;
      var u = new URL(raw, (typeof location !== "undefined" && location.origin) || "http://local");
      if (u.pathname.indexOf("/api/v1/") !== 0) return url;
      if (u.searchParams.has("timings")) return url;
      u.searchParams.set("timings", "1");
      if (abs) return u.toString();
      return u.pathname + u.search + u.hash;
    } catch (e) {
      if (String(url).indexOf("timings=") >= 0) return url;
      return String(url) + (String(url).indexOf("?") >= 0 ? "&" : "?") + "timings=1";
    }
  }

  function wrapFetch() {
    if (typeof global.fetch !== "function" || global.fetch._wallPerf) return;
    var orig = global.fetch.bind(global);
    function wallFetch(input, init) {
      var url = "";
      try { url = typeof input === "string" ? input : ((input && input.url) || ""); } catch (e) {}
      if (!trackUrl(url)) return orig(input, init);
      var path = pathOf(url);
      var method = requestMethod(input, init);
      var nextInput = input;
      var nextInit = init;
      if (method === "GET" && isV1Path(path)) {
        var timed = withTimingsParam(url);
        if (timed !== url) {
          if (typeof input === "string") nextInput = timed;
          else {
            try {
              nextInit = init ? Object.assign({}, init) : {};
              nextInput = timed;
            } catch (e4) { nextInput = timed; }
          }
          url = timed;
        }
      }
      var seq = ++fetchSeq;
      var label = path.replace(/^\//, "").replace(/\//g, "_");
      var start = "wall_perf:fetch_" + seq + "_s";
      var end = "wall_perf:fetch_" + seq + "_e";
      mark(start);
      return orig(nextInput, nextInit).then(function (resp) {
        mark(end);
        var rtt = null;
        try {
          performance.measure("wall_perf:_rtt_" + seq, start, end);
          var me = performance.getEntriesByName("wall_perf:_rtt_" + seq, "measure");
          if (me && me.length) rtt = Math.round(me[me.length - 1].duration * 10) / 10;
        } catch (e7) {}
        var finish = function (bytes, timings) {
          var extra = { route: path };
          if (timings && typeof timings === "object") {
            extra.sql_ms = timings.sql_ms;
            extra.resp_b = timings.resp_b;
            extra.n = timings.n;
            if (bytes == null && timings.resp_b != null) bytes = timings.resp_b;
          }
          pushRow("fetch:" + label + "#" + seq, start, end, bytes, extra);
          showStrip(path, (rtt != null ? rtt : "?"), timings || null);
        };
        /* Prefer JSON parse for timings on v1; else Content-Length / arrayBuffer for bytes. */
        if (isV1Path(path) && resp && typeof resp.clone === "function") {
          return resp.clone().json().then(function (data) {
            var timings = (data && data.timings && typeof data.timings === "object") ? data.timings : null;
            var bytes = timings && timings.resp_b != null ? Number(timings.resp_b) : null;
            if (bytes == null || !Number.isFinite(bytes)) {
              try {
                var cl = resp.headers && resp.headers.get("content-length");
                if (cl != null && cl !== "") bytes = Number(cl);
              } catch (e8) {}
            }
            finish(bytes, timings);
            return resp;
          }, function () {
            var bytes = null;
            try {
              var cl2 = resp.headers && resp.headers.get("content-length");
              if (cl2 != null && cl2 !== "") bytes = Number(cl2);
            } catch (e9) {}
            if ((bytes == null || !Number.isFinite(bytes)) && typeof resp.clone === "function") {
              return resp.clone().arrayBuffer().then(function (buf) {
                finish(buf ? buf.byteLength : null, null);
                return resp;
              }, function () {
                finish(null, null);
                return resp;
              });
            }
            finish(bytes, null);
            return resp;
          });
        }
        var bytes2 = null;
        try {
          var cl3 = resp.headers && resp.headers.get("content-length");
          if (cl3 != null && cl3 !== "") bytes2 = Number(cl3);
        } catch (e10) {}
        if ((bytes2 == null || !Number.isFinite(bytes2)) && resp && typeof resp.clone === "function") {
          return resp.clone().arrayBuffer().then(function (buf) {
            finish(buf ? buf.byteLength : null, null);
            return resp;
          }, function () {
            finish(null, null);
            return resp;
          });
        }
        finish(bytes2, null);
        return resp;
      }, function (err) {
        mark(end);
        pushRow("fetch:" + label + "#" + seq + ":err", start, end, null, { route: path });
        throw err;
      });
    }
    wallFetch._wallPerf = true;
    global.fetch = wallFetch;
  }

  wrapFetch();

  if (typeof document !== "undefined") {
    if (document.readyState === "complete") bootReady();
    else global.addEventListener("load", bootReady);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { ensureStrip(); });
    } else {
      ensureStrip();
    }
    scheduleDump(3000);
  }

  global.wallPerfEnabled = function () { return true; };
  global.wallPerfFirst = first;
  global.wallPerfDump = dump;
  global.wallPerfMark = mark;
  global.wallPerfWithTimings = withTimingsParam;
  global.WALL_UI_LIB_PERF = "WALL_UI_LIB_PERF";
})(typeof window !== "undefined" ? window : globalThis);
