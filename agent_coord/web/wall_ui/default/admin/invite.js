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
    marker: "WALL_UI_DEFAULT_ADMIN_INVITE"
  };
  global.WALL_UI_DEFAULT_ADMIN_INVITE = "WALL_UI_DEFAULT_ADMIN_INVITE";
})(typeof window !== "undefined" ? window : globalThis);
