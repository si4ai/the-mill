/* WALL_UI_DEFAULT_DOING_PAINT - what each desk is doing, on what, for how long, and who
 * waits on it (#818 PR C).
 * Marker: WALL_UI_DEFAULT_DOING_PAINT
 * Loads through lib/lazy.js (MODULES.doingPaint) after the first CONNECTED paint. Classic
 * script on purpose: it shares boot.js globals, and its function declarations replace the
 * boot.js stubs (wallDoingSync, wallDoingTrail).
 *
 * Two GET reads, the server's own views (humans are read-only; nothing here writes):
 *   /api/v1/doing?all=1                        the `mill connected` desk views
 *   /api/v1/doing/history?desk=D | ?on=ITEM    the `mill connected --history` page (ended_by)
 * The Wall shows what they say and computes nothing. If a route is not there (404), the
 * Wall stays on the seat's doing text with no error and no made-up field, and asks again
 * every 10 minutes.
 */
var WALL_DOING_URL = "/api/v1/doing?all=1";
var WALL_DOING_HISTORY_URL = "/api/v1/doing/history";
var WALL_DOING_TTL_MS = 15000;
var WALL_DOING_TRAIL_TTL_MS = 30000;
var WALL_DOING_ABSENT_MS = 600000;
var WALL_DOING_TRAIL_MAX = 12;
var WALL_DOING_ITEM = /^(mail|todo|hold|score)-(\d+)$/;
var WALL_DOING_TAB = { mail: "mail", todo: "jobs", score: "score" };
window.WALL_DOING = window.WALL_DOING || { state: "unknown", byOwner: null, at: 0, sig: "", inflight: null, trails: {}, historyAbsentAt: 0 };

/* A route that is not there yet. Anything else that is not ok is "down" (shown as no view). */
function wallDoingMissing(status) {
  return status === 404 || status === 405 || status === 501;
}
function wallDoingList(json) {
  if (Array.isArray(json)) return json;
  if (json && Array.isArray(json.desks)) return json.desks;
  if (json && Array.isArray(json.result)) return json.result;
  return null;
}
function wallDoingRepaint() {
  const d = window._floor;
  if (!d) return;
  try { board(d, { hereOnly: true }); } catch (eHere) {}
  try { if (typeof paintHero === "function") paintHero(d); } catch (eHero) {}
}
function wallDoingSync(force) {
  const st = window.WALL_DOING;
  const now = Date.now();
  if (st.inflight) return st.inflight;
  if (!force) {
    if (st.state === "absent" && now - st.at < WALL_DOING_ABSENT_MS) return Promise.resolve(st);
    if ((st.state === "ok" || st.state === "down") && now - st.at < WALL_DOING_TTL_MS) return Promise.resolve(st);
  }
  const was = st.state;
  st.inflight = fetch(WALL_DOING_URL, { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (r) {
      if (wallDoingMissing(r.status)) { st.state = "absent"; return null; }
      if (!r.ok) { st.state = "down"; return null; }
      return r.json();
    })
    .then(function (json) {
      st.at = Date.now();
      if (json == null) { st.byOwner = null; st.sig = ""; return; }
      const list = wallDoingList(json);
      if (!list) { st.state = "down"; st.byOwner = null; st.sig = ""; return; }
      const by = {};
      list.forEach(function (v) {
        const o = String((v && v.owner) || "").trim();
        if (o) by[o] = v;
      });
      const sig = JSON.stringify(list);
      st.byOwner = by;
      st.state = "ok";
      if (sig !== st.sig || was !== "ok") {
        st.sig = sig;
        wallDoingRepaint();
      }
    })
    .catch(function () { st.state = "down"; st.byOwner = null; st.sig = ""; st.at = Date.now(); })
    .then(function () {
      st.inflight = null;
      if (was === "ok" && st.state !== "ok") wallDoingRepaint();
      try { wallDoingTrail(); } catch (eTrail) {}
      return st;
    });
  return st.inflight;
}

function wallDoingItemHtml(on) {
  const item = String(on || "").trim();
  if (!item) return "";
  const m = WALL_DOING_ITEM.exec(item);
  const tab = m ? WALL_DOING_TAB[m[1]] : "";
  if (!tab) return `<span class="doing-on">${esc(item)}</span>`;
  return `<a class="doing-on" href="#${tab}" data-doing-go="${esc(item)}" title="Open ${esc(item)}">${esc(item)}</a>`;
}
function wallDoingEndedHtml(by) {
  const how = String(by || "").trim();
  return `<span class="doing-ended" data-slot="ended_by" data-ended-by="${esc(how)}">${how ? esc("ended: " + how) : ""}</span>`;
}
function wallDoingAskedHtml(x) {
  /* Slot for the coming asked-vs-copied flag on mail_to. Blank until the server sends it. */
  const a = x && x.asked;
  const txt = a === true ? "asked" : (a === false ? "copied" : "");
  return `<span class="doing-asked" data-slot="asked">${esc(txt)}</span>`;
}
function wallDoingWaitHtml(owner, v) {
  const w = (v && v.waiting_on_it) || {};
  const L = w.letters || {};
  const C = w.cards || {};
  const nl = Number(L.n) || 0;
  const nc = Number(C.n) || 0;
  const n = nl + nc;
  const who = millName("desk", owner);
  if (!n) {
    return `<span class="doing-wait zero" title="${esc("Nothing is waiting on " + who)}">0 waiting</span>`;
  }
  const title = [nl ? (nl + " unanswered letter" + (nl === 1 ? "" : "s")) : "", nc ? (nc + " watched card" + (nc === 1 ? "" : "s") + " it claimed") : ""]
    .filter(Boolean).join(" and ") + " wait on " + who;
  const letters = (L.newest || []).slice(0, 3).map(function (x) {
    return `<span class="dw-row">${wallDoingItemHtml(x.id)} <span class="dw-from">from ${esc(millName("desk", x.from || ""))}</span> <span class="dw-age">${esc(x.age || "")}</span> ${wallDoingAskedHtml(x)}</span>`;
  }).join("");
  const cards = (C.newest || []).slice(0, 3).map(function (x) {
    const watch = (x.watchers || []).length ? ("watched by " + x.watchers.join(", ")) : "";
    return `<span class="dw-row">${wallDoingItemHtml(x.id)} <span class="dw-need">${esc(x.need || "")}</span> <span class="dw-from">${esc(watch)}</span> <span class="dw-age">${esc(x.age || "")}</span></span>`;
  }).join("");
  const moreL = nl > 3 ? `<span class="dw-more">${esc((nl - 3) + " older letters")}</span>` : "";
  const moreC = nc > 3 ? `<span class="dw-more">${esc((nc - 3) + " older cards")}</span>` : "";
  return `<details class="doing-wait"><summary title="${esc(title)}">${esc(n + " waiting")}</summary>` +
    `<span class="doing-pop" role="note">` +
    (nl ? `<span class="dw-head">${esc(nl + " letter" + (nl === 1 ? "" : "s") + ", newest")}</span>${letters}${moreL}` : "") +
    (nc ? `<span class="dw-head">${esc(nc + " card" + (nc === 1 ? "" : "s") + ", newest")}</span>${cards}${moreC}` : "") +
    `</span></details>`;
}
/* The text in the row button: the doing, or idle and the last one. Plain text (it sits in a button). */
function wallDoingRowHtml(owner, seatText) {
  const v = wallDoingView(owner);
  if (!v) return "";
  const line = String(v.line || "");
  if (String(v.doing || "").trim()) {
    return `<span class="here-doing" title="${esc(line)}">${esc(v.doing)}</span>`;
  }
  const last = v.last && String(v.last.doing || "").trim();
  const idle = "idle" + (v.idle ? " " + v.idle : "");
  return `<span class="here-doing is-idle" title="${esc(line)}">${esc(idle)}${last ? `<span class="doing-last"> | last: ${esc(last)}</span>` : ""}</span>`;
}
/* Beside the row button: link, age, ended_by, waiting-on pill. */
function wallDoingMetaHtml(owner) {
  const v = wallDoingView(owner);
  if (!v) return "";
  const cur = String(v.doing || "").trim();
  const last = v.last || null;
  const on = cur ? v.on : (last && last.on);
  const age = cur ? v.age : (last && last.age);
  const ended = cur ? "" : (last && last.ended_by);
  return `<span class="doing-meta">` +
    wallDoingItemHtml(on) +
    `<span class="doing-age" title="${esc(cur ? "doing this for" : "last doing started")}">${esc(age || "")}</span>` +
    wallDoingEndedHtml(ended) +
    wallDoingWaitHtml(owner, v) +
    `</span>`;
}
/* The desk panel and the COLLAB desk detail: the whole view, with links. */
function wallDoingDeskHtml(owner, seatText) {
  const v = wallDoingView(owner);
  if (!v) return "";
  const cur = String(v.doing || "").trim();
  const last = v.last || null;
  let head;
  if (cur) {
    head = `<div class="here-doing-now">${esc(cur)}</div>` +
      `<div class="doing-facts">${v.on ? "on " + wallDoingItemHtml(v.on) : ""}<span class="doing-age">${esc(v.age ? "for " + v.age : "")}</span></div>`;
  } else {
    head = `<div class="here-doing-now is-idle">${esc("idle" + (v.idle ? " " + v.idle : ""))}</div>` +
      (last && last.doing
        ? `<div class="doing-facts">last: ${esc(last.doing)} ${last.on ? "on " + wallDoingItemHtml(last.on) : ""}<span class="doing-age">${esc(last.age || "")}</span>${wallDoingEndedHtml(last.ended_by)}</div>`
        : "");
  }
  return `<div class="here-doing doing-view" title="${esc(String(v.line || ""))}">${head}` +
    `<div class="doing-facts">Waiting on it: ${wallDoingWaitHtml(owner, v)}</div></div>`;
}

/* Trails: a card's doing rows (on=todo-N) or a desk's (desk=D), oldest first. */
function wallDoingTrailUrl(key) {
  const k = String(key || "");
  if (k.indexOf("desk-") === 0) return WALL_DOING_HISTORY_URL + "?desk=" + encodeURIComponent(k.slice(5));
  if (WALL_DOING_ITEM.test(k)) return WALL_DOING_HISTORY_URL + "?on=" + encodeURIComponent(k);
  return "";
}
function wallDoingTrailHtml(key) {
  const got = window.WALL_DOING.trails[String(key || "")];
  if (!got || got.state !== "ok") return "";
  const byDesk = String(key).indexOf("desk-") === 0;
  const rows = (got.rows || []).slice(0, WALL_DOING_TRAIL_MAX).reverse();
  if (!rows.length) return `<span class="dt-head">Doing</span><span class="dt-none">${esc(byDesk ? "No doing rows from this desk yet." : "No doing rows on this card yet.")}</span>`;
  const older = Math.max(0, (Number(got.entries) || rows.length) - rows.length);
  return `<span class="dt-head">Doing</span>` +
    (older ? `<span class="dt-more">${esc(older + " older not shown")}</span>` : "") +
    rows.map(function (e) {
      const how = e.ended_by ? String(e.ended_by) : (e.ended ? "ended" : "current");
      return `<span class="dt-row">` +
        `<span class="dt-at">${esc(e.at ? dt(e.at).slice(5, 16) : "")}</span> ` +
        (byDesk ? "" : `<b class="dt-desk">${esc(millName("desk", e.desk || ""))}</b> `) +
        `<span class="dt-text">${esc(e.doing || "")}</span>` +
        (byDesk && e.on ? ` <span class="dt-on">${esc("on " + e.on)}</span>` : "") +
        ` <span class="doing-ended" data-ended-by="${esc(e.ended_by || "")}">${esc(how)}</span>` +
        `</span>`;
    }).join("");
}
function wallDoingTrailFill(key) {
  const html = wallDoingTrailHtml(key);
  document.querySelectorAll("[data-doing-trail]").forEach(function (el) {
    if (el.getAttribute("data-doing-trail") === key && el.innerHTML !== html) el.innerHTML = html;
  });
}
function wallDoingTrail(only) {
  const st = window.WALL_DOING;
  const now = Date.now();
  if (st.historyAbsentAt && now - st.historyAbsentAt < WALL_DOING_ABSENT_MS) return Promise.resolve(null);
  /* The two routes land together: with no doing view, do not probe the history one too. */
  if (st.state === "absent" && now - st.at < WALL_DOING_ABSENT_MS) return Promise.resolve(null);
  const keys = {};
  if (only) keys[String(only)] = 1;
  else document.querySelectorAll("[data-doing-trail]").forEach(function (el) { keys[el.getAttribute("data-doing-trail") || ""] = 1; });
  const jobs = Object.keys(keys).filter(Boolean).map(function (key) {
    const url = wallDoingTrailUrl(key);
    if (!url) return null;
    const got = st.trails[key];
    if (got && got.inflight) return got.inflight;
    if (got && got.state === "ok" && now - got.at < WALL_DOING_TRAIL_TTL_MS) {
      wallDoingTrailFill(key);
      return null;
    }
    const slot = got || (st.trails[key] = { state: "unknown", rows: [], at: 0 });
    slot.inflight = fetch(url, { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (wallDoingMissing(r.status)) { st.historyAbsentAt = Date.now(); slot.state = "absent"; return null; }
        if (!r.ok) { slot.state = "down"; return null; }
        return r.json();
      })
      .then(function (json) {
        slot.at = Date.now();
        if (!json) { slot.rows = []; return; }
        if (!Array.isArray(json.history)) { slot.state = "down"; slot.rows = []; return; }
        slot.rows = json.history;
        slot.entries = (json.page && json.page.entries) || json.history.length;
        slot.state = "ok";
      })
      .catch(function () { slot.state = "down"; slot.rows = []; slot.at = Date.now(); })
      .then(function () { slot.inflight = null; wallDoingTrailFill(key); });
    return slot.inflight;
  }).filter(Boolean);
  return Promise.all(jobs);
}

/* A link to a letter or card opens it on its own pane. Read-only: tab, open, scroll. */
function wallDoingGo(item) {
  const m = WALL_DOING_ITEM.exec(String(item || ""));
  if (!m || !WALL_DOING_TAB[m[1]]) return false;
  const id = m[2];
  if (m[1] === "todo") {
    _todoDetailId = String(id);
    showTab("jobs");
    try { if (window._floor) { board(window._floor); paintPlan(window._floor); } } catch (eOpen) {}
    try { wallOpenTodoIfTrunc(id); } catch (eLean) {}
    try { wallDoingTrail(); } catch (eTrail) {}
  } else if (m[1] === "mail") {
    showTab("mail");
    try { wallOpenMailIfTrunc(id); } catch (eLeanMail) {}
  } else {
    showTab(WALL_DOING_TAB[m[1]]);
  }
  const sel = m[1] === "todo" ? `[data-todo-id="${id}"]` : (m[1] === "mail" ? `[data-mail-id="${id}"]` : "");
  if (sel) {
    setTimeout(function () {
      const el = document.querySelector(sel);
      if (!el) return;
      try { el.scrollIntoView({ block: "center" }); } catch (eScroll) {}
      el.classList.add("doing-flash");
      setTimeout(function () { el.classList.remove("doing-flash"); }, 1600);
    }, 80);
  }
  return true;
}
(function wallDoingWire() {
  if (document._wallDoingWired) return;
  document._wallDoingWired = true;
  document.addEventListener("click", function (ev) {
    const a = ev.target && ev.target.closest ? ev.target.closest("a[data-doing-go]") : null;
    if (!a) return;
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
    if (wallDoingGo(a.getAttribute("data-doing-go"))) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  }, true);
  /* One popover open at a time. */
  document.addEventListener("toggle", function (ev) {
    const t = ev.target;
    if (!t || !t.classList || !t.classList.contains("doing-wait") || !t.open) return;
    document.querySelectorAll("details.doing-wait[open]").forEach(function (o) { if (o !== t) o.open = false; });
  }, true);
})();
var WALL_UI_DEFAULT_DOING_PAINT = "WALL_UI_DEFAULT_DOING_PAINT";
