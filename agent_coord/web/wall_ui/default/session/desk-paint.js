/* WALL_UI_DEFAULT_DESK_PAINT - split out of boot.js (#872).
 * Marker: WALL_UI_DEFAULT_DESK_PAINT
 * Loads on first use through lib/lazy.js (MODULES.deskPaint); boot.js keeps a stub for each entry.
 * Classic script on purpose: it shares boot.js globals (let/const state and functions),
 * and its function declarations replace the boot.js stubs.
 */


    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function hereDeskId(value) {
      if (value == null || value === "") return "";
      if (typeof value === "string") return value.trim();
      return String(value.deskId || value.desk || value.id || value.owner || "").trim();
    }
    function hereMailParty(m) {
      const ids = [];
      const push = (v) => {
        const id = hereDeskId(v);
        if (id) ids.push(id);
      };
      if (!m) return ids;
      push(m.sender || m.src || m.desk);
      const tos = m.mail_tos || m.tos;
      if (Array.isArray(tos)) tos.forEach(push);
      else push(m.dst || m.to);
      return ids;
    }
    function hereMailTouches(m, owner) {
      const o = String(owner || "").trim().toLowerCase();
      if (!o) return false;
      return hereMailParty(m).some(id => id.toLowerCase() === o);
    }
    function hereDeskKey(owner) {
      let scope = "";
      try { scope = String(floorScope().key || ""); } catch (eScope) { scope = ""; }
      return scope + "|" + String(owner || "").trim();
    }
    function hereDeskUrls() {
      const scope = floorScope();
      const lim = "&limit=50";
      const q = String(scope.query || "");
      const todosQ = String(scope.key || "").indexOf("lan:") === 0 ? floorProjectQuery() : q;
      /* A station todo query fails in the lan procedure. The card uses the project book. */
      return [
        "/api/v1/todos?" + todosQ + lim,
        "/api/v1/mailbox?" + q + lim,
        "/api/v1/holds?" + q + lim
      ];
    }
    function hereDeskLoad(owner) {
      owner = String(owner || "").trim();
      if (!owner) return;
      const key = hereDeskKey(owner);
      if (_hereDesk.key === key && (_hereDesk.ready || _hereDesk.inflight)) return;
      _hereDesk = { key: key, ready: false, inflight: true, got: {}, needs: [], issues: [], mailbox: [], locks: [] };
      const urls = hereDeskUrls();
      Promise.all(urls.map(function (url) {
        return fetch(url, { cache: "no-store" }).then(function (r) {
          if (!r.ok) return { down: true };
          return r.json().then(function (json) { return { down: false, json: json }; });
        }).catch(function () { return { down: true }; });
      })).then(function (rows) {
        if (_hereDesk.key !== key) return;
        const got = {};
        const needs = [];
        const issues = [];
        const mailbox = [];
        const locks = [];
        (rows || []).forEach(function (row) {
          if (!row || row.down || !row.json) return;
          const json = row.json;
          (Array.isArray(json.parts) ? json.parts : []).forEach(function (p) {
            if (p) got[p] = true;
          });
          if (Array.isArray(json.needs) || Array.isArray(json.issues)) got.todos = true;
          if (Array.isArray(json.mailbox)) got.mail = true;
          if (Array.isArray(json.locks)) got.holds = true;
          if (Array.isArray(json.needs)) needs.push.apply(needs, json.needs);
          if (Array.isArray(json.issues)) issues.push.apply(issues, json.issues);
          if (Array.isArray(json.mailbox)) mailbox.push.apply(mailbox, json.mailbox);
          if (Array.isArray(json.locks)) locks.push.apply(locks, json.locks);
        });
        _hereDesk = { key: key, ready: true, inflight: false, got: got, needs: needs, issues: issues, mailbox: mailbox, locks: locks };
        if (_hereOwner === owner) paintHereDesk(window._floor || {}, owner);
      });
    }
    function hereHoldFor(row, owner) {
      const o = String(owner || "").trim();
      if (!o) return false;
      return [row && row.owner, row && row.holder, row && row.desk, row && row.volunteer].some(v => String(v || "").trim() === o);
    }
    function paintHereDesk(d, owner) {
      const el = document.getElementById("here-desk");
      if (!el) return;
      d = d || window._floor || {};
      owner = String(owner || "").trim();
      if (!owner) {
        el.innerHTML = '<div class="idle">Open a desk</div>';
        return;
      }
      const agents = uniqueDesksByOwner(d.agents || []);
      const agent = agents.find(a => String(a.owner || "").trim() === owner) || { owner: owner, alive: false };
      const g = hereGlance(d, agent);
      const book = (_hereDesk.key === hereDeskKey(owner)) ? _hereDesk : null;
      const ready = !!(book && book.ready);
      const got = (book && book.got) || {};
      const jobs = (ready && got.todos) ? millJobsForOwner({ needs: book.needs, issues: book.issues }, owner, "") : [];
      const cardBody = !ready
        ? "Loading the card."
        : (!got.todos
          ? "The card list did not load."
          : (jobs.length
            ? jobs.slice(0, 8).map(card => {
                const title = card.detail || card.need_id || "claimed card";
                return `<div>${esc(title)}</div>`;
              }).join("")
            : "No claimed card in this slice"));
      const locks = (ready && got.holds) ? (book.locks || []).filter(L => hereHoldFor(L, owner)) : [];
      const promise = locks.length
        ? `<details class="here-fold"><summary>Promise</summary><div class="here-fold-body">` +
          locks.map(L => {
            const file = String(L.resource || L.path || "a file").split(/[/\\]/).pop();
            return `<div>${esc(file || "a file")}</div>`;
          }).join("") + `</div></details>`
        : "";
      const letters = (ready && got.mail) ? (book.mailbox || []).filter(m => hereMailTouches(m, owner)).slice(0, 8) : [];
      const chatBody = !ready
        ? "Loading the letters."
        : (!got.mail
          ? "The letters did not load."
          : (letters.length
            ? letters.map(m => {
                const who = hereDeskId(m.sender || m.src || m.desk);
                const line = String(m.body || m.subject || "").replace(/\s+/g, " ").slice(0, 80);
                return `<div class="here-letter"><b>${esc(who)}</b> ${esc(line)}</div>`;
              }).join("")
            : "No letters for this desk in this slice."));
      const give = (g.state === "idle" || g.state === "here" || g.state === "gone")
        ? `<details class="here-fold"><summary>Give a todo</summary><div class="here-fold-body">The wall cannot file a card yet. Tell your agent.</div></details>`
        : "";
      const histRows = [];
      if (ready) {
        letters.forEach(function (m) {
          const who = hereDeskId(m.sender || m.src || m.desk);
          const line = String(m.body || "").replace(/\s+/g, " ").trim().slice(0, 72);
          histRows.push({ at: String(m.created || ""), text: "letter " + (who || "desk") + (line ? ": " + line : "") });
        });
        jobs.forEach(function (card) {
          const title = String(card.detail || card.need_id || "card").replace(/\s+/g, " ").trim().slice(0, 72);
          const st = card.status ? String(card.status) + " " : "";
          histRows.push({ at: String(card.updated_at || card.asked_at || ""), text: "card " + st + title });
        });
        locks.forEach(function (L) {
          const file = String(L.resource || L.path || "a file").split(/[/\\]/).pop();
          histRows.push({ at: "", text: "promise " + (file || "a file") });
        });
        histRows.sort(function (a, b) { return String(b.at).localeCompare(String(a.at)); });
      }
      const histBody = !ready
        ? "Loading."
        : (histRows.length
          ? histRows.slice(0, 12).map(function (row) {
              const when = row.at ? dt(row.at).slice(5, 16) : "";
              return `<div class="here-letter">${when ? `<span class="here-when">${esc(when)}</span> ` : ""}${esc(row.text)}</div>`;
            }).join("")
          : "Nothing has changed for this desk in this slice.");
      const html =
        `<div class="here-desk-head"><b>${esc(millName("desk", owner))}</b> <span class="here-state">${esc(g.state || "")}</span></div>` +
        wallDoingBlock(owner, agent.doing) +
        `<details class="here-fold"><summary>Card</summary><div class="here-fold-body">${cardBody}</div></details>` +
        promise +
        `<details class="here-fold"><summary>Chat</summary><div class="here-fold-body">${chatBody}</div></details>` +
        `<details class="here-fold"><summary>History</summary><div class="here-fold-body">${histBody}</div></details>` +
        `<details class="here-fold" data-fold="doing"><summary>Doing trail</summary><div class="here-fold-body">${wallDoingTrailSlot("desk-" + owner)}</div></details>` +
        give;
      if (el.getAttribute("data-here-owner") === owner && el._hereHtml === html) return;
      const open = {};
      el.querySelectorAll("details.here-fold").forEach(node => {
        const sum = node.querySelector("summary");
        if (sum && node.open) open[String(sum.textContent || "")] = 1;
      });
      el.innerHTML = html;
      el.setAttribute("data-here-owner", owner);
      el._hereHtml = html;
      el.querySelectorAll("details.here-fold").forEach(node => {
        const sum = node.querySelector("summary");
        if (sum && open[String(sum.textContent || "")]) node.open = true;
      });
      try { wallDoingTrail(); } catch (eTrail) {}
    }
var WALL_UI_DEFAULT_DESK_PAINT = "WALL_UI_DEFAULT_DESK_PAINT";
