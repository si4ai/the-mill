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
      const order = ["mail", "todo", "doing", "hold", "score", "name"];
      const types = b.types || {};
      let html = '<h3 class="svc-h">Book</h3>';
      if (b.open === false) html += '<p class="svc-note">Activity counts could not be read.</p>';
      const typeRows = order.map(function (name) {
        const row = types[name] || {};
        return [
          name,
          glanceCount(row.activity),
          glanceCount(row.live),
          name === "name" ? glanceCount(row.retired) : "",
        ];
      });
      html += glanceTable(["Type", "Activity", "Live", "Retired"], typeRows);
      const admins = (Array.isArray(b.admin) ? b.admin : []).map(glanceSafe).filter(Boolean);
      html += glanceDl([
        ["Seats here", glanceCount(b.seats_here)],
        ["Promises held", glanceCount(b.promises_held)],
        ["Retired names", glanceCount(b.retired_names)],
        ["Admin", admins.length ? admins.join(", ") : "none"],
        ["Activity touched last hour", glanceNum(b.activity_touched_last_hour)],
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
    }
var WALL_UI_DEFAULT_SERVICE_PAINT = "WALL_UI_DEFAULT_SERVICE_PAINT";
