/* WALL_UI_DEFAULT_SERVICE_PAINT - split out of boot.js (#872).
 * Marker: WALL_UI_DEFAULT_SERVICE_PAINT
 * Loads on first use through lib/lazy.js (MODULES.servicePaint); boot.js keeps a stub for each entry.
 * Classic script on purpose: it shares boot.js globals (let/const state and functions),
 * and its function declarations replace the boot.js stubs.
 */


    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function glanceSafe(raw) {
      const t = String(raw == null ? "" : raw);
      if (!t) return "";
      const low = t.toLowerCase();
      if (low.indexOf("password=") >= 0) return "";
      if (low.indexOf("bearer ") >= 0) return "";
      if (low.indexOf("private-token") >= 0) return "";
      if (low.indexOf("invite=") >= 0) return "";
      if (t.indexOf("-----BEGIN") >= 0) return "";
      return t;
    }
    function glanceNum(cell) {
      if (!cell || cell.stored !== true || cell.value == null) return "not written";
      return String(cell.value);
    }
    function glanceTarget(cell) {
      if (!cell || cell.target == null || cell.target === "") return "";
      return glanceSafe(cell.target);
    }
    function glanceCount(n) {
      if (n == null || n === "") return "unavailable";
      const x = Number(n);
      return Number.isFinite(x) ? String(x) : "unavailable";
    }
    function glanceYes(v) { return v ? "yes" : "no"; }
    function glanceDl(rows) {
      let html = '<dl class="svc-dl">';
      rows.forEach(function (row) {
        const v = row[1] == null || row[1] === "" ? "-" : row[1];
        const wide = String(v).length > 48 ? ' class="svc-wide"' : "";
        html += "<div" + wide + "><dt>" + esc(row[0]) + "</dt><dd>" + esc(v) + "</dd></div>";
      });
      return html + "</dl>";
    }
    function glanceMeters(rows) {
      let html = '<div class="svc-meters">';
      rows.forEach(function (row) {
        const quiet = row[1] === "not written" ? ' class="svc-quiet"' : "";
        html += "<div" + quiet + "><dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd><span>";
        html += row[2] ? ("target " + esc(row[2])) : "";
        html += "</span></div>";
      });
      return html + "</div>";
    }
    function glanceTable(heads, rows) {
      let html = '<table class="svc-table"><thead><tr>';
      heads.forEach(function (h) { html += "<th>" + esc(h) + "</th>"; });
      html += "</tr></thead><tbody>";
      if (!rows.length) {
        html += '<tr><td colspan="' + heads.length + '">none</td></tr>';
      } else {
        rows.forEach(function (row) {
          html += "<tr>";
          row.forEach(function (cell) { html += "<td>" + esc(cell == null || cell === "" ? "-" : cell) + "</td>"; });
          html += "</tr>";
        });
      }
      return html + "</tbody></table>";
    }
    function paintGlanceAlerts(a) {
      a = a || {};
      const ver = a.version || {};
      const skew = !ver.installed
        ? "no installed pack to compare"
        : (ver.skew ? "installed pack differs from this process" : "installed pack matches this process");
      let html = '<h3 class="svc-h">Alerts</h3>';
      html += glanceMeters([
        ["Wall errors", glanceNum(a.err_n), glanceTarget(a.err_n)],
        ["Fanout misses", glanceNum(a.ws_miss), glanceTarget(a.ws_miss)],
        ["Hint drops", glanceNum(a.hint_drop), glanceTarget(a.hint_drop)],
      ]);
      const drain = a.drain;
      let drainText = "No drain.";
      if (drain && typeof drain === "object") {
        const phase = glanceSafe(drain.phase);
        const eta = glanceSafe(drain.eta_at);
        if (phase === "overdue") drainText = eta ? ("overdue since " + eta) : "overdue";
        else if (phase === "draining") drainText = eta ? ("draining until " + eta) : "draining";
        else if (phase) drainText = phase;
      }
      html += glanceDl([
        ["Drain", drainText],
        ["Routines missing", a.routines_missing == null ? "the routine check did not run" : glanceCount(a.routines_missing)],
      ]);
      (Array.isArray(a.standing) ? a.standing : []).forEach(function (row) {
        const line = glanceSafe(row && row.line);
        if (line) html += '<p class="svc-note">' + esc(line) + "</p>";
      });
      html += '<h3 class="svc-h">Version</h3>';
      html += glanceDl([
        ["Process", glanceSafe(ver.process) || "-"],
        ["Installed", ver.installed ? glanceSafe(ver.installed) : "none recorded"],
        ["Checkout", ver.checkout ? glanceSafe(ver.checkout) : "this process is the installed pack"],
        ["Skew", skew],
      ]);
      /* card 1098: wake-health row (filled after lazy admin fetch; empty when no session). */
      html += '<div id="svc-wake-alert" class="svc-wake-alert" hidden></div>';
      return html;
    }
    function paintGlanceOffice(o) {
      o = o || {};
      const mysql = o.mysql || {};
      const seeds = Array.isArray(o.seeds) ? o.seeds : [];
      function seedLine(type, name) {
        const row = seeds.find(function (item) {
          return item && item.type === type && item.name === name;
        });
        if (!row || !row.present) return "absent";
        return row.retired ? "retired" : "live";
      }
      const station = glanceSafe(o.station);
      return '<h3 class="svc-h">Office</h3>' + glanceDl([
        ["Door", glanceSafe(o.door) || "-"],
        ["Trust", glanceSafe(o.trust) || "-"],
        ["HTTPS", glanceYes(o.https)],
        ["Bind", glanceSafe(o.bind) || "-"],
        ["LAN-only", glanceYes(o.lan_only)],
        ["Cert", o.cert_present ? "present" : "absent"],
        ["One process", glanceYes(o.one_process)],
        ["API only", glanceYes(o.api_only)],
        ["Serves the glass", glanceYes(o.serves_glass)],
        ["Static cache", glanceSafe(o.static_cache) || "-"],
        ["API cache", glanceSafe(o.api_cache) || "-"],
        ["MySQL host", glanceSafe(mysql.host) || "-"],
        ["MySQL database", glanceSafe(mysql.database) || "-"],
        ["Office", seedLine("roster", "Office")],
        ["Admin", seedLine("roster", "Admin")],
        ["Station", station || "no station on this browser"],
        ["Signed in", glanceYes(o.signed_in)],
      ]);
    }
    function paintGlancePlatform(p) {
      p = p || {};
      const names = (Array.isArray(p.desks_here_without_names) ? p.desks_here_without_names : [])
        .map(glanceSafe).filter(Boolean);
      let who = names.length ? names.join(", ") : "none";
      if (p.desks_here_without != null && Number(p.desks_here_without) > names.length) who += " and more";
      let html = '<h3 class="svc-h">Platform</h3>';
      html += glanceDl([
        ["Desks with a command score", glanceCount(p.desks_with_score)],
        ["Commands today", glanceCount(p.verbs_today)],
        ["Desks here without a command score", glanceCount(p.desks_here_without)],
        ["Those desks", who],
        ["Ticks", glanceNum(p.ticks) + (glanceTarget(p.ticks) ? (" / " + glanceTarget(p.ticks)) : "")],
        ["Hint drops", glanceNum(p.hint_drop) + (glanceTarget(p.hint_drop) ? (" / " + glanceTarget(p.hint_drop)) : "")],
      ]);
      html += '<h3 class="svc-h">Routes this hour</h3>';
      const routes = [];
      (Array.isArray(p.routes) ? p.routes : []).forEach(function (row) {
        const route = glanceSafe(row && row.route);
        if (!route || route.indexOf("floor") >= 0) return;
        routes.push([route, glanceCount(row.n), glanceCount(row.ms)]);
      });
      html += glanceTable(["Route", "n", "ms"], routes);
      const episodes = [];
      (Array.isArray(p.episodes) ? p.episodes : []).forEach(function (row) {
        const kpi = glanceSafe(row && row.kpi);
        if (!kpi) return;
        episodes.push([kpi, glanceCount(row.value), glanceSafe(row.target)]);
      });
      if (episodes.length) {
        html += '<h3 class="svc-h">Episodes</h3>';
        html += glanceTable(["kpi", "Last", "Target"], episodes);
      }
      return html;
    }
    function paintGlanceLogs(block) {
      block = block || {};
      const win = Number(block.window_s);
      const every = Number(block.every_s);
      const span = win === 3600 ? "Last hour." : ("Window " + glanceCount(block.window_s) + " seconds.");
      const tick = every === 900 ? " Tick every 15 minutes." : (" Tick every " + glanceCount(block.every_s) + " seconds.");
      let html = '<h3 class="svc-h">Logs</h3><p class="svc-note">' + esc(span + tick) + "</p>";
      const rows = [];
      (Array.isArray(block.lines) ? block.lines : []).forEach(function (row) {
        const caption = glanceSafe(row && row.caption);
        const source = glanceSafe(row && row.source);
        if (!caption && !source) return;
        rows.push([caption || "-", source || "-", glanceNum(row), glanceTarget(row)]);
      });
      html += glanceTable(["Reading", "Source", "Last", "Target"], rows);
      return html;
    }
    function paintGlanceBook(b) {
      b = b || {};
      let html = '<h3 class="svc-h">Book</h3>';
      if (b.open === false) html += '<p class="svc-note">Activity counts could not be read.</p>';
      html += svcBookTypeTableHtml(b);
      html += svcBookTransitionsShellHtml();
      const admins = (Array.isArray(b.admin) ? b.admin : []).map(glanceSafe).filter(Boolean);
      html += glanceDl([
        ["Admin", admins.length ? admins.join(", ") : "none"],
      ]);
      const routines = b.routines || {};
      const missing = Array.isArray(routines.missing) ? routines.missing.map(glanceSafe).filter(Boolean) : null;
      const extra = Array.isArray(routines.extra) ? routines.extra.map(glanceSafe).filter(Boolean) : null;
      const watch = routines.watch || {};
      function watchLine(name) {
        if (watch[name] == null) return "unknown";
        return watch[name] ? "present" : "absent";
      }
      html += '<h3 class="svc-h">Routines</h3>';
      html += glanceDl([
        ["Pack", routines.pack == null ? "unavailable" : glanceCount(routines.pack)],
        ["Live", routines.live == null ? "unavailable" : glanceCount(routines.live)],
        ["Missing", missing == null ? "the routine check did not run" : (missing.length ? missing.join(", ") : "none")],
        ["Extra", extra == null ? "the routine check did not run" : (extra.length ? extra.join(", ") : "none")],
        ["mill_span", watchLine("mill_span")],
        ["mill_between", watchLine("mill_between")],
        ["mill_wall_event", watchLine("mill_wall_event")],
      ]);
      return html;
    }
    function paintGlanceDoor(d) {
      d = d || {};
      const counts = d.counts || {};
      const welcome = d.welcome || {};
      const directory = d.directory || {};
      const chart = d.trust_chart || {};
      let html = '<h3 class="svc-h">Door</h3>';
      html += glanceDl([
        ["Default TTL", glanceSafe(d.default_ttl) || "-"],
        ["Pending", glanceCount(counts.pending)],
        ["Enabled", glanceCount(counts.enabled)],
        ["Revoked", glanceCount(counts.revoked)],
        ["Expired", glanceCount(counts.expired)],
        ["Trust", glanceSafe(d.trust) || "-"],
        ["Allow enforced", glanceYes(d.allow_enforced)],
      ]);
      if (d.keys_stored === false) html += '<p class="svc-note">Key board could not be read.</p>';
      const keys = [];
      (Array.isArray(d.keys) ? d.keys : []).forEach(function (row) {
        const label = glanceSafe(row && row.label);
        keys.push([
          label || "(withheld)",
          glanceSafe(row && row.status) || "-",
          row && row.ttl_seconds == null ? "-" : glanceCount(row.ttl_seconds),
          glanceSafe(row && row.expires_at) || "-",
        ]);
      });
      html += '<h3 class="svc-h">Keys</h3>';
      html += glanceTable(["Label", "Status", "TTL seconds", "Expires"], keys);
      html += '<h3 class="svc-h">Welcome</h3>';
      if (welcome.stored === false) {
        html += '<p class="svc-note">Welcome counts could not be read.</p>';
      } else {
        html += glanceDl([
          ["Invite keys", glanceCount(welcome.invites)],
          ["Joins on those keys", glanceCount(welcome.joined)],
        ]);
      }
      const allow = (Array.isArray(d.allow) ? d.allow : []).map(glanceSafe).filter(Boolean);
      html += '<h3 class="svc-h">Allow</h3>';
      html += '<p class="svc-note">' + esc(allow.length ? allow.join(", ") : "none") + "</p>";
      html += '<h3 class="svc-h">Directory</h3>';
      html += glanceDl([
        ["Issuer set", glanceYes(directory.issuer_set)],
        ["Client id present", glanceYes(directory.client_id_present)],
        ["Logout URL present", glanceYes(directory.logout_url_present)],
        ["Sign out link", glanceYes(directory.sign_out_link)],
      ]);
      html += '<h3 class="svc-h">Trust</h3>';
      ["high", "limited", "assign"].forEach(function (key) {
        const line = glanceSafe(chart[key]);
        if (line) html += '<p class="svc-note">' + esc(line) + "</p>";
      });
      return html;
    }
    /* card 1098: shared lazy Admin transition fetch (Book + Alerts wake). */
    var _svcTrSince = "";
    var _svcTrCache = { at: 0, since: null, row: null, err: null, inflight: null };
    var SVC_TR_CACHE_MS = 60000;

    function svcTrNum(v) {
      var n = Number(v);
      return Number.isFinite(n) ? n : 0;
    }
    function svcTrSaved(row) {
      if (row && row.saved_rows != null && row.saved_rows !== "") return Math.max(0, svcTrNum(row.saved_rows));
      return Math.max(0, svcTrNum(row && row.events) - svcTrNum(row && row.rows));
    }
    function svcTrShare(saved, events) {
      var e = svcTrNum(events);
      if (e <= 0) return "0%";
      return (Math.round((1000 * svcTrNum(saved)) / e) / 10) + "%";
    }
    function svcBookLiveCell(name, row) {
      if (name === "doing") return "--";
      return glanceCount(row && row.live);
    }
    function svcBookTypeTableHtml(b) {
      b = b || {};
      const types = b.types || {};
      const order = ["mail", "todo", "doing", "hold", "score"];
      const rows = order.map(function (name) {
        const row = types[name] || {};
        let live = svcBookLiveCell(name, row);
        if (name === "hold" && b.promises_held != null && b.promises_held !== "") {
          /* promises_held mirrors hold live; show once when present. */
          live = glanceCount(row.live != null ? row.live : b.promises_held);
        }
        return [name, glanceCount(row.activity), live];
      });
      if (b.seats_here != null && b.seats_here !== "") {
        rows.push(["seats", "--", glanceCount(b.seats_here)]);
      }
      let html = glanceTable(["type", "ever written", "live now"], rows);
      const nameRow = types.name || {};
      const nLive = nameRow.live != null ? nameRow.live : null;
      const nRet = nameRow.retired != null ? nameRow.retired : b.retired_names;
      if (nLive != null || nRet != null) {
        html += '<p class="svc-note" data-svc-book="names-footnote">'
          + esc(glanceCount(nLive)) + " names, " + esc(glanceCount(nRet)) + " retired</p>";
      }
      const touched = b.activity_touched_last_hour;
      html += '<p class="svc-note" data-svc-book="touched">'
        + "touched last hour: " + esc(glanceNum(touched)) + "</p>";
      return html;
    }
    function svcBookTransitionsShellHtml() {
      return ''
        + '<h3 class="svc-h">Transition rows: compress or capture</h3>'
        + '<div id="svc-tr-block" class="svc-tr-block" data-svc-tr="1">'
        + '<p class="svc-note" id="svc-tr-mode-line">Mode: ...</p>'
        + '<div class="svc-tr-mode" role="group" aria-label="Transition rows: compress or capture">'
        + '<button type="button" id="svc-tr-compress" class="on" aria-pressed="true" title="compress cycles (config transition_mode)">compress</button>'
        + '<button type="button" id="svc-tr-capture" aria-pressed="false" title="capture every flip (config transition_mode)">capture</button>'
        + '</div>'
        + '<div class="svc-tr-since" role="group" aria-label="last 24h / 7d / all">'
        + '<button type="button" id="svc-tr-since-24h" data-tr-since="24h" aria-pressed="false">last 24h</button>'
        + '<button type="button" id="svc-tr-since-7d" data-tr-since="7d" aria-pressed="false">7d</button>'
        + '<button type="button" id="svc-tr-since-all" class="on" data-tr-since="" aria-pressed="true">all</button>'
        + '<button type="button" id="svc-tr-refresh">refresh</button>'
        + '</div>'
        + '<p class="svc-note svc-tr-error" id="svc-tr-error" hidden></p>'
        + '<p class="svc-note" id="svc-tr-wait">loading transition analysis...</p>'
        + '<div id="svc-tr-stats" class="svc-note"></div>'
        + '<div class="svc-tr-label">by type</div>'
        + '<div id="svc-tr-by-type"></div>'
        + '<div class="svc-tr-label">by pair</div>'
        + '<div id="svc-tr-by-pair"></div>'
        + '<div id="svc-tr-wake" class="svc-tr-wake" hidden><div class="svc-tr-label">wake health</div><dl id="svc-tr-wake-body"></dl></div>'
        + '<p class="svc-note" id="svc-tr-note"></p>'
        + '</div>';
    }
    function svcTrHtmlByType(analysis) {
      var a = analysis || {};
      var rows = a.by_type || [];
      if (a.error && !rows.length) return "";
      if (!rows.length) return '<p class="svc-note">no transition rows yet</p>';
      var body = rows.map(function (r) {
        var saved = svcTrSaved(r);
        var events = svcTrNum(r.events);
        return "<tr><td><code>" + esc(r.activity_type || "") + "</code></td>"
          + "<td>" + esc(String(svcTrNum(r.rows))) + "</td>"
          + "<td>" + esc(String(events)) + "</td>"
          + "<td>" + esc(String(saved)) + "</td>"
          + "<td>" + esc(svcTrShare(saved, events)) + "</td></tr>";
      }).join("");
      var savedAll = (a.saved_rows != null && a.saved_rows !== "") ? Math.max(0, svcTrNum(a.saved_rows)) : 0;
      var rowsAll = (a.total_rows != null) ? svcTrNum(a.total_rows) : 0;
      var eventsAll = (a.total_events != null) ? svcTrNum(a.total_events) : 0;
      if (a.saved_rows == null || a.saved_rows === "") {
        savedAll = Math.max(0, eventsAll - rowsAll);
      }
      return '<table class="svc-table" data-table="svc-tr-by-type"><thead><tr>'
        + "<th>type</th><th>rows</th><th>events</th><th>saved</th><th>share</th>"
        + "</tr></thead><tbody>" + body + "</tbody><tfoot><tr>"
        + "<td>total</td><td>" + esc(String(rowsAll)) + "</td><td>" + esc(String(eventsAll)) + "</td>"
        + "<td>" + esc(String(savedAll)) + "</td><td>" + esc(svcTrShare(savedAll, eventsAll)) + "</td>"
        + "</tr></tfoot></table>";
    }
    function svcTrHtmlByPair(analysis) {
      var list = (analysis && analysis.by_pair) || null;
      if (!list) return "";
      if (!list.length) return '<p class="svc-note">no configured pair rows</p>';
      var body = list.map(function (r) {
        var saved = svcTrSaved(r);
        return "<tr><td><code>" + esc(r.activity_type || "") + "</code></td>"
          + "<td>" + esc(r.from_state || "") + " -&gt; " + esc(r.to_state || "") + "</td>"
          + "<td>" + esc(String(svcTrNum(r.rows))) + "</td>"
          + "<td>" + esc(String(svcTrNum(r.events))) + "</td>"
          + "<td>" + esc(String(saved)) + "</td></tr>";
      }).join("");
      return '<table class="svc-table" data-table="svc-tr-by-pair"><thead><tr>'
        + "<th>type</th><th>from -&gt; to</th><th>rows</th><th>events</th><th>saved</th>"
        + "</tr></thead><tbody>" + body + "</tbody></table>";
    }
    function svcTrHtmlWake(wake) {
      var list = Array.isArray(wake) ? wake : [];
      if (!list.length) return "";
      return list.map(function (row) {
        return "<dt>" + esc((row && row.label) || "") + "</dt>"
          + "<dd>" + esc(String(row && row.value != null ? row.value : "")) + "</dd>";
      }).join("");
    }
    function svcTrWakeCounts(wake) {
      var out = { missed: 0, receipt_unopened: 0 };
      (Array.isArray(wake) ? wake : []).forEach(function (row) {
        var lab = String((row && row.label) || "");
        if (lab === "missed") out.missed = svcTrNum(row.value);
        if (lab === "receipt_unopened") out.receipt_unopened = svcTrNum(row.value);
      });
      return out;
    }
    function svcWakeAlertHtml(wake) {
      if (!wake || !wake.length) return "";
      var c = svcTrWakeCounts(wake);
      return '<p class="svc-note"><button type="button" class="svc-wake-jump" data-svc-jump="book">'
        + "Wake health: missed " + esc(String(c.missed))
        + ", receipts unopened " + esc(String(c.receipt_unopened))
        + " (see Book)</button></p>";
    }
    function svcTrSetSinceUi(since) {
      var val = (since === "24h" || since === "7d") ? since : "";
      _svcTrSince = val;
      [
        ["svc-tr-since-all", ""],
        ["svc-tr-since-24h", "24h"],
        ["svc-tr-since-7d", "7d"]
      ].forEach(function (pair) {
        var el = document.getElementById(pair[0]);
        if (!el) return;
        var on = pair[1] === val;
        el.classList.toggle("on", on);
        el.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    function svcTrSetModeUi(mode) {
      var isCapture = String(mode || "") === "capture";
      var compress = document.getElementById("svc-tr-compress");
      var capture = document.getElementById("svc-tr-capture");
      if (compress) {
        compress.classList.toggle("on", !isCapture);
        compress.setAttribute("aria-pressed", isCapture ? "false" : "true");
      }
      if (capture) {
        capture.classList.toggle("on", isCapture);
        capture.setAttribute("aria-pressed", isCapture ? "true" : "false");
      }
      var line = document.getElementById("svc-tr-mode-line");
      if (line) line.textContent = "Mode: " + (isCapture ? "capture" : "compress");
    }
    function svcTrPaintAnalysis(row) {
      row = row || {};
      var a = row.analysis || {};
      svcTrSetModeUi(row.mode || "compress");
      if (Object.prototype.hasOwnProperty.call(a, "since")) svcTrSetSinceUi(a.since);
      else svcTrSetSinceUi(_svcTrSince);
      var wait = document.getElementById("svc-tr-wait");
      if (wait) wait.hidden = true;
      var err = document.getElementById("svc-tr-error");
      if (err) {
        if (a.error) {
          err.hidden = false;
          err.textContent = String(a.error);
        } else {
          err.hidden = true;
          err.textContent = "";
        }
      }
      var stats = document.getElementById("svc-tr-stats");
      if (stats) {
        if (a.error && !(a.by_type || []).length) stats.textContent = "analysis unavailable";
        else {
          var saved = (a.saved_rows != null) ? svcTrNum(a.saved_rows) : Math.max(0, svcTrNum(a.total_events) - svcTrNum(a.total_rows));
          stats.textContent = (a.total_rows || 0) + " rows / " + (a.total_events || 0) + " events (saved " + saved + ")";
        }
      }
      var byType = document.getElementById("svc-tr-by-type");
      if (byType) byType.innerHTML = svcTrHtmlByType(a);
      var byPair = document.getElementById("svc-tr-by-pair");
      if (byPair) byPair.innerHTML = svcTrHtmlByPair(a);
      var wakeWrap = document.getElementById("svc-tr-wake");
      var wakeBody = document.getElementById("svc-tr-wake-body");
      var wakeHtml = svcTrHtmlWake(a.wake);
      if (wakeWrap && wakeBody) {
        if (wakeHtml) {
          wakeWrap.hidden = false;
          wakeBody.innerHTML = wakeHtml;
        } else {
          wakeWrap.hidden = true;
          wakeBody.innerHTML = "";
        }
      }
      var note = document.getElementById("svc-tr-note");
      if (note) note.textContent = row.note || "";
      /* keep write controls usable when analysis.error (Gardener). */
      ["svc-tr-compress", "svc-tr-capture"].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        var ro = typeof wallHumanReadonly === "function" && wallHumanReadonly();
        el.disabled = !!ro;
      });
    }
    function svcTrShowNeedAdmin(msg) {
      var wait = document.getElementById("svc-tr-wait");
      if (wait) wait.hidden = true;
      var err = document.getElementById("svc-tr-error");
      if (err) {
        err.hidden = false;
        err.textContent = msg || "admin session needed";
      }
      var line = document.getElementById("svc-tr-mode-line");
      if (line && line.textContent.indexOf("...") >= 0) line.textContent = "Mode: (unknown)";
    }
    function svcPaintWakeAlertFromCache() {
      var box = document.getElementById("svc-wake-alert");
      if (!box) return;
      var row = _svcTrCache.row;
      var wake = row && row.analysis && row.analysis.wake;
      var html = svcWakeAlertHtml(wake);
      if (!html) {
        box.hidden = true;
        box.innerHTML = "";
        return;
      }
      box.hidden = false;
      box.innerHTML = html;
      var btn = box.querySelector("[data-svc-jump='book']");
      if (btn) btn.addEventListener("click", function () {
        _svcSection = "book";
        if (typeof glanceMarkSection === "function") glanceMarkSection();
        paintWallService();
      });
    }
    async function svcAdminTransition(extra) {
      /* Same door/Admin session cookie as seat_count / invite pane; body owner is not proof. */
      var human = "";
      var desk = "";
      try { human = localStorage.getItem("factory-human") || ""; } catch (eH) {}
      try { desk = localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || ""; } catch (eD) {}
      var body = Object.assign({ action: "transition", owner: human || desk || "wall" }, extra || {});
      if (_svcTrSince) body.since = _svcTrSince;
      var r = await fetch("/api/admin/invites", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Mill-Wall": "1" },
        body: JSON.stringify(body)
      });
      var data = null;
      try { data = await r.json(); } catch (eJ) { data = null; }
      if (!r.ok || !data || data.error) {
        var msg = (data && data.error) ? String(data.error) : ("HTTP " + r.status);
        var err = new Error(msg);
        err.status = r.status;
        throw err;
      }
      return data;
    }
    function svcTrCacheFresh(since) {
      var want = (since === "24h" || since === "7d") ? since : "";
      if (!_svcTrCache.row) return false;
      if (_svcTrCache.since !== want) return false;
      if (_svcTrCache.err) return false;
      return (Date.now() - (_svcTrCache.at || 0)) < SVC_TR_CACHE_MS;
    }
    async function svcEnsureTransition(force) {
      var want = _svcTrSince || "";
      if (!force && svcTrCacheFresh(want)) return _svcTrCache.row;
      if (_svcTrCache.inflight) return _svcTrCache.inflight;
      _svcTrCache.inflight = (async function () {
        try {
          var row = await svcAdminTransition();
          _svcTrCache = { at: Date.now(), since: want, row: row, err: null, inflight: null };
          return row;
        } catch (e) {
          _svcTrCache = { at: Date.now(), since: want, row: null, err: e, inflight: null };
          throw e;
        }
      })();
      return _svcTrCache.inflight;
    }
    function svcIsAdminNeeded(err) {
      var msg = String((err && err.message) || err || "").toLowerCase();
      return msg.indexOf("admin") >= 0 || msg.indexOf("required") >= 0 || (err && err.status === 400);
    }
    async function svcLoadBookTransitions(force) {
      if (!document.getElementById("svc-tr-block")) return;
      try {
        var row = await svcEnsureTransition(!!force);
        svcTrPaintAnalysis(row);
      } catch (e) {
        if (svcIsAdminNeeded(e)) svcTrShowNeedAdmin("admin session needed");
        else svcTrShowNeedAdmin(String((e && e.message) || e));
      }
    }
    async function svcLoadWakeAlert() {
      if (_svcSection !== "alerts") return;
      if (svcTrCacheFresh(_svcTrSince || "")) {
        svcPaintWakeAlertFromCache();
        return;
      }
      try {
        await svcEnsureTransition(false);
        if (_svcSection === "alerts") svcPaintWakeAlertFromCache();
      } catch (e) {
        /* no admin session: show nothing rather than a placeholder (Gardener). */
        var box = document.getElementById("svc-wake-alert");
        if (box) { box.hidden = true; box.innerHTML = ""; }
      }
    }
    function svcWireBookTransitions() {
      if (!document.getElementById("svc-tr-block")) return;
      function setSince(v) {
        svcTrSetSinceUi(v);
        svcLoadBookTransitions(true);
      }
      var b24 = document.getElementById("svc-tr-since-24h");
      var b7 = document.getElementById("svc-tr-since-7d");
      var ball = document.getElementById("svc-tr-since-all");
      var bref = document.getElementById("svc-tr-refresh");
      if (b24) b24.addEventListener("click", function () { setSince("24h"); });
      if (b7) b7.addEventListener("click", function () { setSince("7d"); });
      if (ball) ball.addEventListener("click", function () { setSince(""); });
      if (bref) bref.addEventListener("click", function () { svcLoadBookTransitions(true); });
      async function setMode(mode) {
        if (typeof wallHumanReadonly === "function" && wallHumanReadonly()) return;
        try {
          var row = await svcAdminTransition({ mode: mode });
          _svcTrCache = { at: Date.now(), since: _svcTrSince || "", row: row, err: null, inflight: null };
          svcTrPaintAnalysis(row);
        } catch (e) {
          svcTrShowNeedAdmin(String((e && e.message) || e));
        }
      }
      var bc = document.getElementById("svc-tr-compress");
      var ba = document.getElementById("svc-tr-capture");
      if (bc) bc.addEventListener("click", function () { setMode("compress"); });
      if (ba) ba.addEventListener("click", function () { setMode("capture"); });
      var ro = typeof wallHumanReadonly === "function" && wallHumanReadonly();
      if (bc) bc.disabled = !!ro;
      if (ba) ba.disabled = !!ro;
      svcTrSetSinceUi(_svcTrSince);
      svcLoadBookTransitions(false);
    }
    function paintWallService() {
      const body = document.getElementById("wall-service-body");
      if (!body || !_svcPacket) return;
      const sec = _svcPacket[_svcSection];
      if (!sec || typeof sec !== "object") {
        body.innerHTML = '<p class="svc-wait">No reading.</p>';
        return;
      }
      let html = "";
      if (_svcSection === "alerts") html = paintGlanceAlerts(sec);
      else if (_svcSection === "office") html = paintGlanceOffice(sec);
      else if (_svcSection === "platform") html = paintGlancePlatform(sec);
      else if (_svcSection === "logs") html = paintGlanceLogs(sec);
      else if (_svcSection === "book") html = paintGlanceBook(sec);
      else if (_svcSection === "door") html = paintGlanceDoor(sec);
      else html = '<p class="svc-wait">No reading.</p>';
      body.innerHTML = html;
      if (_svcSection === "book") svcWireBookTransitions();
      if (_svcSection === "alerts") svcLoadWakeAlert();
    }
    /* test hooks (card 1098 Book / wake). */
    var WallServiceBook = {
      typeTableHtml: svcBookTypeTableHtml,
      transitionsShellHtml: svcBookTransitionsShellHtml,
      htmlByType: svcTrHtmlByType,
      htmlByPair: svcTrHtmlByPair,
      htmlWake: svcTrHtmlWake,
      wakeAlertHtml: svcWakeAlertHtml,
      wakeCounts: svcTrWakeCounts,
      paintAnalysis: svcTrPaintAnalysis,
      setSinceUi: svcTrSetSinceUi,
      getSince: function () { return _svcTrSince; },
      cache: function () { return _svcTrCache; },
      resetCache: function () { _svcTrCache = { at: 0, since: null, row: null, err: null, inflight: null }; }
    };
    try { window.WallServiceBook = WallServiceBook; } catch (eW) {}
var WALL_UI_DEFAULT_SERVICE_PAINT = "WALL_UI_DEFAULT_SERVICE_PAINT";
