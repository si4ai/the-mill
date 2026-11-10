/* WALL_UI_DEFAULT_ADMIN_INVITE - admin pane invite client (lazy; not on Session first paint).
 * Marker: WALL_UI_DEFAULT_ADMIN_INVITE
 */
(function (global) {
  "use strict";

  var _deps = null;
  var _wired = false;

  function esc(s) {
    if (_deps && typeof _deps.esc === "function") return _deps.esc(s);
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function wallHumanReadonly() {
    if (_deps && typeof _deps.wallHumanReadonly === "function") return _deps.wallHumanReadonly();
    if (typeof global.wallHumanReadonly === "function") return global.wallHumanReadonly();
    return true;
  }
  function applyAdminLadder(v) {
    if (_deps && typeof _deps.applyAdminLadder === "function") return _deps.applyAdminLadder(v);
  }

async function loadAdminInvites() {
    const body = document.getElementById("admin-keys-body");
    if (!body) return;
    try {
      const r = await fetch("/api/admin/invites", { cache: "no-store" });
      if (r.status === 403) {
        body.innerHTML = '<div class="idle">Admin sign-in required to list invite keys.</div>';
        return;
      }
      const data = await r.json();
      const doorEl = document.getElementById("admin-door-mode");
      if (doorEl) doorEl.textContent = "door: " + (data.door || "?") + " | ladder hint: " + (data.ladder || "?");
      if (data.ladder && !localStorage.getItem("factory-admin-ladder")) applyAdminLadder(data.ladder);
      else applyAdminLadder(localStorage.getItem("factory-admin-ladder") || "solo");
      adminLoadTransitions();
      const keys = data.keys || [];
      if (!keys.length) {
        body.innerHTML = '<div class="idle">No invite keys yet. Mint one (Office ladder) or <code>invite --mint</code>.</div>';
      } else {
        const rows = keys.map(k => {
          const st = k.status || "";
          const exp = k.expires_at || (k.ttl_seconds ? ("ttl " + k.ttl_seconds + "s") : "-");
          const actions = st === "active"
            ? `<button type="button" data-revoke="${esc(k.key_id)}">revoke</button> <button type="button" data-ttl="${esc(k.key_id)}">set TTL</button>`
            : "";
          return `<tr>
            <td><code>${esc(k.key_id)}</code><div class="note">${esc(k.label || "")}</div></td>
            <td>${esc(k.created_at || "")}<div class="note">${esc(k.created_by || "")}</div></td>
            <td>${esc(String(exp))}</td>
            <td>${esc(String(k.joins ?? 0))}</td>
            <td class="st-${esc(st)}">${esc(st)}</td>
            <td class="admin-full-only">${actions}</td>
          </tr>`;
        }).join("");
        body.innerHTML = `<table class="keys" data-table="admin-keys"><thead><tr>
          <th>key</th><th>created</th><th>TTL / expiry</th><th>joins</th><th>status</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table>`;
        body.querySelectorAll("[data-revoke]").forEach(btn => btn.addEventListener("click", () => adminRevoke(btn.getAttribute("data-revoke"))));
        body.querySelectorAll("[data-ttl]").forEach(btn => btn.addEventListener("click", () => adminSetTtl(btn.getAttribute("data-ttl"))));
      }
      const prov = document.getElementById("admin-oidc-providers");
      const oidc = (data.oidc || {});
      if (prov) {
        const list = oidc.providers || [];
        prov.innerHTML = list.map(p => {
          const name = (typeof p === 'string') ? p : (p && (p.id || p.name)) || 'oidc';
          return `<span class="oidc-prov disabled" title="Connect disabled">${esc(name)} <em>disabled</em></span>`;
        }).join('') || '<span class="oidc-prov disabled">oidc <em>disabled</em></span>';
      }

      const net = data.network || {};
      const httpsEl = document.getElementById("admin-net-https");
      if (httpsEl) httpsEl.textContent = net.https_only ? "required (HTTP -> 301 HTTPS; no cleartext mode)" : "missing";
      const lanEl = document.getElementById("admin-net-lan");
      if (lanEl) {
        lanEl.textContent = net.lan_only ? "ON - private/loopback Listen only" : "OFF - public/wildcard bind allowed (still HTTPS)";
        lanEl.className = net.lan_only ? "net-flag" : "net-warn";
      }
      const bindEl = document.getElementById("admin-net-bind");
      if (bindEl) bindEl.textContent = "bind=" + (net.dashboard_bind || "?") + " listen=" + ((net.listen_hosts || []).join(", ") || "?");
      const certEl = document.getElementById("admin-net-cert");
      if (certEl) {
        const c = net.cert || {};
        certEl.textContent = (c.cert || "(no cert yet)") + (c.cert_exists ? " v" : " (run install wall --apply)");
      }
      const nnote = document.getElementById("admin-net-note");
      if (nnote) nnote.textContent = net.lan_only ? (net.flip_for_cloud || "") : (net.flip_lan_only || "");
      const onote = document.getElementById("admin-oidc-note");
      if (onote) onote.textContent = oidc.note || "OIDC stub only.";
    } catch (e) {
      body.innerHTML = `<div class="idle">Admin invites load failed: ${esc(String(e))}</div>`;
    }
  }
  async function adminPost(payload) {
    if (wallHumanReadonly()) throw new Error("Wall is human-readonly"); /* WALL_HUMAN_READONLY */
    const human = localStorage.getItem("factory-human") || "";
    const desk = localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || "builder";
    const body = Object.assign({ owner: human || desk }, payload);
    const r = await fetch("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Mill-Wall": "1" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || ("HTTP " + r.status));
    return data;
  }


  /* card 1098: compress/capture switch, pair chips, analysis tables */
  var _trPairs = [];
  var _trDefaultPairs = "doing:seated/connected,hold:free/held,hold:held/held";
  var _trBusy = false;
  var _trSince = ""; /* "" = all time; "24h" | "7d" */

  function trJoinPairs(pairs) {
    return (pairs || []).map(function (p) { return String(p || "").trim(); }).filter(Boolean).join(",");
  }

  function trSplitPairs(raw) {
    return String(raw || "").split(",").map(function (p) { return p.trim(); }).filter(Boolean);
  }

  function trNum(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function trTypeSaved(row) {
    if (row && row.saved_rows != null && row.saved_rows !== "") return Math.max(0, trNum(row.saved_rows));
    return Math.max(0, trNum(row && row.events) - trNum(row && row.rows));
  }

  function trSharePct(saved, events) {
    var e = trNum(events);
    if (e <= 0) return "0%";
    return (Math.round((1000 * trNum(saved)) / e) / 10) + "%";
  }

  function trSyncPairsInput() {
    var input = document.getElementById("admin-tr-pairs-input");
    if (input) input.value = trJoinPairs(_trPairs);
  }

  function trSetBusy(on) {
    _trBusy = !!on;
    ["admin-tr-compress", "admin-tr-capture", "admin-tr-save-pairs", "admin-tr-refresh", "admin-tr-add-pair", "admin-tr-reset-pairs", "admin-tr-since-all", "admin-tr-since-24h", "admin-tr-since-7d"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.disabled = _trBusy;
    });
    var add = document.getElementById("admin-tr-pair-add");
    if (add) add.disabled = _trBusy;
  }

  function trSetModeUi(mode) {
    var compress = document.getElementById("admin-tr-compress");
    var capture = document.getElementById("admin-tr-capture");
    var isCapture = String(mode || "") === "capture";
    if (compress) {
      compress.classList.toggle("on", !isCapture);
      compress.setAttribute("aria-pressed", isCapture ? "false" : "true");
    }
    if (capture) {
      capture.classList.toggle("on", isCapture);
      capture.setAttribute("aria-pressed", isCapture ? "true" : "false");
    }
  }

  function trHtmlChips(pairs) {
    var list = pairs || [];
    if (!list.length) return '<span class="admin-tr-empty">no pairs (every flip writes its own row)</span>';
    return list.map(function (p, i) {
      return '<span class="admin-tr-chip"><code>' + esc(p) + '</code>'
        + '<button type="button" class="admin-tr-chip-x" data-tr-rm="' + i + '" aria-label="remove pair">x</button></span>';
    }).join("");
  }

  function trPaintChips() {
    var el = document.getElementById("admin-tr-chips");
    if (!el) return;
    el.innerHTML = trHtmlChips(_trPairs);
    el.querySelectorAll("[data-tr-rm]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (_trBusy) return;
        var i = Number(btn.getAttribute("data-tr-rm"));
        if (!Number.isFinite(i)) return;
        _trPairs = _trPairs.filter(function (_p, idx) { return idx !== i; });
        trSyncPairsInput();
        trPaintChips();
      });
    });
    trSyncPairsInput();
  }

  function trHtmlByType(analysis) {
    var a = analysis || {};
    var rows = a.by_type || [];
    if (a.error && !rows.length) return "";
    if (!rows.length) return '<p class="note admin-tr-empty">no transition rows yet</p>';
    var totalRows = 0, totalEvents = 0, totalSaved = 0;
    var body = rows.map(function (r) {
      var saved = trTypeSaved(r);
      var events = trNum(r.events);
      var rr = trNum(r.rows);
      totalRows += rr;
      totalEvents += events;
      totalSaved += saved;
      return "<tr><td><code>" + esc(r.activity_type || "") + "</code></td>"
        + "<td>" + esc(String(rr)) + "</td>"
        + "<td>" + esc(String(events)) + "</td>"
        + "<td>" + esc(String(saved)) + "</td>"
        + "<td>" + esc(trSharePct(saved, events)) + "</td></tr>";
    }).join("");
    var savedAll = (a.saved_rows != null && a.saved_rows !== "") ? Math.max(0, trNum(a.saved_rows)) : totalSaved;
    var rowsAll = (a.total_rows != null) ? trNum(a.total_rows) : totalRows;
    var eventsAll = (a.total_events != null) ? trNum(a.total_events) : totalEvents;
    return '<table class="admin-tr-table" data-table="admin-tr-by-type"><thead><tr>'
      + "<th>type</th><th>rows</th><th>events</th><th>saved</th><th>share</th>"
      + "</tr></thead><tbody>" + body + "</tbody><tfoot><tr>"
      + "<td>total</td>"
      + "<td>" + esc(String(rowsAll)) + "</td>"
      + "<td>" + esc(String(eventsAll)) + "</td>"
      + "<td>" + esc(String(savedAll)) + "</td>"
      + "<td>" + esc(trSharePct(savedAll, eventsAll)) + "</td>"
      + "</tr></tfoot></table>";
  }

  function trHtmlByPair(analysis) {
    var list = (analysis && analysis.by_pair) || null;
    if (!list) return "";
    if (!list.length) return '<p class="note admin-tr-empty">no configured pair rows</p>';
    var body = list.map(function (r) {
      var saved = trTypeSaved(r);
      return "<tr><td><code>" + esc(r.activity_type || "") + "</code></td>"
        + "<td>" + esc(r.from_state || "") + " -&gt; " + esc(r.to_state || "") + "</td>"
        + "<td>" + esc(String(trNum(r.rows))) + "</td>"
        + "<td>" + esc(String(trNum(r.events))) + "</td>"
        + "<td>" + esc(String(saved)) + "</td></tr>";
    }).join("");
    return '<div class="admin-tr-label">by pair</div>'
      + '<table class="admin-tr-table" data-table="admin-tr-by-pair"><thead><tr>'
      + "<th>type</th><th>from -&gt; to</th><th>rows</th><th>events</th><th>saved</th>"
      + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function trHtmlCompressed(analysis) {
    var top = (analysis && analysis.top_compressed) || [];
    if (!top.length) return '<p class="note admin-tr-empty">no compressed rows yet</p>';
    var body = top.map(function (r) {
      return "<tr><td><code>" + esc(r.activity_type || "") + "</code></td>"
        + "<td>" + esc(r.from_state || "") + " -&gt; " + esc(r.to_state || "") + "</td>"
        + "<td>" + esc(String(trNum(r.n))) + "</td>"
        + "<td>" + esc(r.at || "") + "</td></tr>";
    }).join("");
    return '<div class="admin-tr-label">compressed</div>'
      + '<table class="admin-tr-table" data-table="admin-tr-compressed"><thead><tr>'
      + "<th>type</th><th>from -&gt; to</th><th>n</th><th>at</th>"
      + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  var TR_WAKE_HINT = {
    queued: "wake events waiting to send",
    sent: "wake delivered to the desk",
    missed: "wake owed never delivered",
    done: "wake finished by the desk",
    auto_done: "wake finished automatically",
    receipt_unopened: "receipt row not yet opened",
    receipt_opened: "receipt row opened"
  };

  function trSincePayload(extra) {
    var body = Object.assign({ action: "transition" }, extra || {});
    if (_trSince) body.since = _trSince;
    return body;
  }

  function trSetSinceUi(since) {
    var val = (since === "24h" || since === "7d") ? since : "";
    _trSince = val;
    [
      ["admin-tr-since-all", ""],
      ["admin-tr-since-24h", "24h"],
      ["admin-tr-since-7d", "7d"]
    ].forEach(function (pair) {
      var el = document.getElementById(pair[0]);
      if (!el) return;
      var on = pair[1] === val;
      el.classList.toggle("on", on);
      el.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var label = document.getElementById("admin-tr-since-label");
    if (label) label.textContent = "window: " + (val || "all time");
  }

  function trHtmlWake(wake) {
    var list = [];
    if (Array.isArray(wake)) list = wake;
    else if (wake && typeof wake === "object") {
      list = Object.keys(wake).map(function (k) { return { label: k, value: wake[k] }; });
    }
    if (!list.length) return "";
    return list.map(function (row) {
      var lab = String((row && row.label) || "");
      var hint = TR_WAKE_HINT[lab] || "";
      var dt = esc(lab) + (hint ? (' <span class="admin-tr-hint">' + esc(hint) + "</span>") : "");
      return "<dt>" + dt + "</dt><dd>" + esc(String(row && row.value != null ? row.value : "")) + "</dd>";
    }).join("");
  }

  function trHtmlStats(analysis) {
    var a = analysis || {};
    if (a.error && !(a.by_type || []).length) {
      return "analysis unavailable";
    }
    var saved = (a.saved_rows != null) ? trNum(a.saved_rows) : Math.max(0, trNum(a.total_events) - trNum(a.total_rows));
    return (a.total_rows || 0) + " rows / " + (a.total_events || 0) + " events (saved " + saved + ")";
  }

  function adminPaintTransitions(row) {
    row = row || {};
    var a = row.analysis || {};
    trSetModeUi(row.mode || "compress");
    /* echo analysis.since when present; else keep local all-time */
    if (Object.prototype.hasOwnProperty.call(a, "since")) trSetSinceUi(a.since);
    else trSetSinceUi(_trSince);
    if (Array.isArray(row.pairs)) _trPairs = row.pairs.slice();
    else if (row.pairs_raw) _trPairs = trSplitPairs(row.pairs_raw);
    if (row.default_pairs) _trDefaultPairs = String(row.default_pairs);
    trPaintChips();
    var err = document.getElementById("admin-tr-error");
    if (err) {
      if (a.error) {
        err.hidden = false;
        err.textContent = String(a.error);
      } else {
        err.hidden = true;
        err.textContent = "";
      }
    }
    var statsEl = document.getElementById("admin-tr-stats");
    if (statsEl) statsEl.textContent = trHtmlStats(a);
    var byType = document.getElementById("admin-tr-by-type");
    if (byType) byType.innerHTML = trHtmlByType(a);
    var byPair = document.getElementById("admin-tr-by-pair");
    if (byPair) byPair.innerHTML = trHtmlByPair(a);
    var listEl = document.getElementById("admin-tr-compressed");
    if (listEl) listEl.innerHTML = trHtmlCompressed(a);
    var wakeWrap = document.getElementById("admin-tr-wake");
    var wakeBody = document.getElementById("admin-tr-wake-body");
    var wakeHtml = trHtmlWake(a.wake);
    if (wakeWrap && wakeBody) {
      if (wakeHtml) {
        wakeWrap.hidden = false;
        wakeBody.innerHTML = wakeHtml;
      } else {
        wakeWrap.hidden = true;
        wakeBody.innerHTML = "";
      }
    }
    var noteEl = document.getElementById("admin-tr-note");
    if (noteEl) noteEl.textContent = row.note || "";
  }

  async function adminLoadTransitions() {
    try {
      trSetBusy(true);
      const row = await adminPost(trSincePayload());
      adminPaintTransitions(row);
    } catch (e) {
      const noteEl = document.getElementById("admin-tr-note");
      if (noteEl) noteEl.textContent = String(e && e.message || e);
    } finally {
      trSetBusy(false);
    }
  }

  async function adminSetTransitionMode(mode) {
    try {
      trSetBusy(true);
      const row = await adminPost(trSincePayload({ mode: mode }));
      adminPaintTransitions(row);
    } catch (e) {
      const noteEl = document.getElementById("admin-tr-note");
      if (noteEl) noteEl.textContent = String(e && e.message || e);
    } finally {
      trSetBusy(false);
    }
  }

  async function adminSaveTransitionPairs() {
    const pairs = trJoinPairs(_trPairs);
    try {
      trSetBusy(true);
      const row = await adminPost(trSincePayload({ pairs: pairs }));
      adminPaintTransitions(row);
    } catch (e) {
      const noteEl = document.getElementById("admin-tr-note");
      if (noteEl) noteEl.textContent = String(e && e.message || e);
    } finally {
      trSetBusy(false);
    }
  }

  function adminAddTransitionPair() {
    if (_trBusy) return;
    var input = document.getElementById("admin-tr-pair-add");
    var raw = input && input.value || "";
    var p = String(raw).trim();
    if (!p) return;
    if (_trPairs.indexOf(p) < 0) _trPairs.push(p);
    if (input) input.value = "";
    trPaintChips();
  }

  function adminResetTransitionPairs() {
    if (_trBusy) return;
    _trPairs = trSplitPairs(_trDefaultPairs);
    trPaintChips();
  }

  async function adminSetTransitionSince(since) {
    if (_trBusy) return;
    trSetSinceUi(since);
    await adminLoadTransitions();
  }

  async function adminSetLan(on) {
    try {
      const row = await adminPost({ action: "network", lan_only: !!on });
      const note = document.getElementById("admin-net-note");
      if (note) note.textContent = (row.note || "") + " - re-run install wall --apply to rewrite Listen.";
      await loadAdminInvites();
    } catch (e) {
      alert("network failed: " + e.message + " (CLI: invite --lan-only on|off)");
    }
  }
  async function adminMint() {
    const label = (document.getElementById("admin-label") || {}).value || "";
    const ttl = (document.getElementById("admin-ttl") || {}).value || "";
    try {
      const row = await adminPost({ action: "mint", label, ttl: ttl || null });
      const note = document.getElementById("admin-mint-note");
      if (note) {
        note.hidden = false;
        note.textContent = "Minted " + (row.key_id || "") + " - copy once: " + (location.origin || "") + (row.invite_path || "");
      }
      await loadAdminInvites();
    } catch (e) {
      alert("mint failed: " + e.message + " (CLI: mill invite --mint)");
    }
  }
  async function adminRevoke(keyId) {
    if (!keyId || !confirm("Revoke key " + keyId + " and cohort humans who joined via it?")) return;
    try {
      await adminPost({ action: "revoke", key_id: keyId });
      await loadAdminInvites();
    } catch (e) {
      alert("revoke failed: " + e.message);
    }
  }
  async function adminSetTtl(keyId) {
    const ttl = prompt("TTL for " + keyId + " (e.g. 7d, 24h, 0=never)", "7d");
    if (ttl === null) return;
    try {
      await adminPost({ action: "ttl", key_id: keyId, ttl });
      await loadAdminInvites();
    } catch (e) {
      alert("ttl failed: " + e.message);
    }
  }

  function wire(deps) {
    if (_wired) {
      if (deps) _deps = deps;
      return;
    }
    _deps = deps || {};
    _wired = true;
    var ladder = document.getElementById("admin-ladder");
    if (ladder) {
      ladder.querySelectorAll("button").forEach(function (b) {
        b.addEventListener("click", function () {
          applyAdminLadder(b.getAttribute("data-ladder"));
        });
      });
    }
    var lanOn = document.getElementById("admin-lan-on");
    if (lanOn) lanOn.addEventListener("click", function () { adminSetLan(true); });
    var lanOff = document.getElementById("admin-lan-off");
    if (lanOff) lanOff.addEventListener("click", function () { adminSetLan(false); });
    var trCompress = document.getElementById("admin-tr-compress");
    if (trCompress) trCompress.addEventListener("click", function () { adminSetTransitionMode("compress"); });
    var trCapture = document.getElementById("admin-tr-capture");
    if (trCapture) trCapture.addEventListener("click", function () { adminSetTransitionMode("capture"); });
    var trSave = document.getElementById("admin-tr-save-pairs");
    if (trSave) trSave.addEventListener("click", function () { adminSaveTransitionPairs(); });
    var trRefresh = document.getElementById("admin-tr-refresh");
    if (trRefresh) trRefresh.addEventListener("click", function () { adminLoadTransitions(); });
    var trAdd = document.getElementById("admin-tr-add-pair");
    if (trAdd) trAdd.addEventListener("click", function () { adminAddTransitionPair(); });
    var trReset = document.getElementById("admin-tr-reset-pairs");
    if (trReset) trReset.addEventListener("click", function () { adminResetTransitionPairs(); });
    var trAddInput = document.getElementById("admin-tr-pair-add");
    if (trAddInput) trAddInput.addEventListener("keydown", function (ev) {
      if (ev && ev.key === "Enter") { ev.preventDefault(); adminAddTransitionPair(); }
    });
    ["admin-tr-since-all", "admin-tr-since-24h", "admin-tr-since-7d"].forEach(function (id) {
      var btn = document.getElementById(id);
      if (!btn) return;
      btn.addEventListener("click", function () {
        adminSetTransitionSince(btn.getAttribute("data-tr-since") || "");
      });
    });
    var netRefresh = document.getElementById("admin-net-refresh");
    if (netRefresh) netRefresh.addEventListener("click", function () { loadAdminInvites(); });
    var mint = document.getElementById("admin-mint");
    if (mint) mint.addEventListener("click", adminMint);
    var refresh = document.getElementById("admin-refresh");
    if (refresh) refresh.addEventListener("click", loadAdminInvites);
  }

  function ensureAndLoad(deps) {
    wire(deps);
    return loadAdminInvites();
  }

  global.WallAdminInvites = {
    wire: wire,
    load: loadAdminInvites,
    ensureAndLoad: ensureAndLoad,
    paintTransitions: adminPaintTransitions,
    joinPairs: trJoinPairs,
    splitPairs: trSplitPairs,
    typeSaved: trTypeSaved,
    sharePct: trSharePct,
    sincePayload: trSincePayload,
    setSinceUi: trSetSinceUi,
    htmlByType: trHtmlByType,
    htmlByPair: trHtmlByPair,
    htmlCompressed: trHtmlCompressed,
    htmlWake: trHtmlWake,
    htmlChips: trHtmlChips,
    htmlStats: trHtmlStats,
    getSince: function () { return _trSince; },
    marker: "WALL_UI_DEFAULT_ADMIN_INVITE"
  };
  global.WALL_UI_DEFAULT_ADMIN_INVITE = "WALL_UI_DEFAULT_ADMIN_INVITE";
})(typeof window !== "undefined" ? window : globalThis);
