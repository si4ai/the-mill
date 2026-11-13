/* WALL_UI_DEFAULT_DOING_PAINT - each desk's live doings (tw runs)
 * (#818 PR C; card 1207: doing is only tw runs, a desk may run many, no desk-written text).
 * Marker: WALL_UI_DEFAULT_DOING_PAINT
 * Loads through lib/lazy.js (MODULES.doingPaint) after the first CONNECTED paint. Classic
 * script on purpose: it shares boot.js globals, and its function declarations replace the
 * boot.js stubs (wallDoingSync, wallDoingTrail).
 *
 * Two GET reads, the server's own views (humans are read-only; nothing here writes):
 *   /api/v1/doing?all=1                        the `mill connected` desk views
 *   /api/v1/doing/history?desk=D | ?on=ITEM    the `mill connected --history` page (ended_by)
 * The Wall shows what they say and computes nothing. If a route is not there (404), the
 * Wall shows no doing, with no error and no made-up field, and asks again every 10 minutes.
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
/* Age of an ISO UTC stamp, as the server's views used to say it (12s, 5m, 3h, 2d). */
function wallDoingAge(iso) {
  const t = Date.parse(String(iso || ""));
  if (!Number.isFinite(t)) return "";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return sec + "s";
  if (sec < 3600) return Math.floor(sec / 60) + "m";
  if (sec < 86400) return Math.floor(sec / 3600) + "h";
  return Math.floor(sec / 86400) + "d";
}
/* The text in the row button: the newest doing's text, or "N doings", or idle. Plain text (it sits in a button). */
function wallDoingRowHtml(owner) {
  const v = wallDoingView(owner);
  if (!v) return "";
  const cur = wallDoingText(owner);
  if (cur) return `<span class="here-doing">${esc(cur)}</span>`;
  return `<span class="here-doing is-idle${wallDoingStale(v) ? " is-stale" : ""}">idle</span>`;
}
/* Beside the row button: the newest doing's age (from its created) and its card link. */
function wallDoingMetaHtml(owner) {
  const v = wallDoingView(owner);
  if (!v) return "";
  const top = wallDoingText(owner) ? wallDoingNewest(v) : null;
  return `<span class="doing-meta">` +
    (top && top.card != null ? wallDoingItemHtml("todo-" + top.card) : "") +
    `<span class="doing-age" title="newest doing started">${esc(top ? wallDoingAge(top.created) : "")}</span>` +
    `</span>`;
}

/* wall-scores Phase A: live doing rows (tw runs) + once-per-desk doing.task.* leaves. */
function wallDoingTaskList(owner) {
  const v = wallDoingView(owner);
  const raw = (v && Array.isArray(v.doings)) ? v.doings : [];
  if (typeof scoreDoingTaskLiveRows === "function") return scoreDoingTaskLiveRows(raw);
  return raw.filter(function (t) {
    const st = String((t && t.state) || "").trim().toLowerCase();
    return st !== "finished" && st !== "failed";
  }).slice(0, 8);
}
function wallDoingTaskRowHtml(row) {
  if (!row) return "";
  const actBit = (typeof wallActLabel === "function") ? wallActLabel("task") : "tasked";
  const state = String(row.state || "").trim();
  const text = String(row.text || "").trim();
  const card = row.card == null ? "" : String(row.card).trim();
  const cardBit = card
    ? (` ` + (typeof wallDoingItemHtml === "function" ? wallDoingItemHtml(card.indexOf("-") >= 0 ? card : ("todo-" + card)) : `<span class="doing-on">${esc(card)}</span>`))
    : "";
  return `<span class="doing-task-row" data-state="${esc(state)}" data-id="${esc(row.id == null ? "" : row.id)}">` +
    `<span class="dt-act">${esc(actBit)}</span>` +
    (state ? ` <span class="dt-state" title="${esc(row.state_at || "")}">${esc(state)}</span>` : "") +
    (text ? ` <span class="dt-text">${esc(text)}</span>` : "") +
    ` <span class="dt-ago">${esc(wallDoingAge(row.created))}</span>` +
    cardBit +
    `</span>`;
}
function wallDoingTaskLastDoneHtml(row) {
  if (!row) return "";
  const actBit = (typeof wallActLabel === "function") ? wallActLabel("task") : "tasked";
  const bits = [];
  bits.push(`<span class="dt-act">${esc(actBit)}</span>`);
  bits.push(`<span class="dt-last-done">last done</span>`);
  const keys = (typeof DOING_TASK_LAST_DONE_KEYS !== "undefined")
    ? DOING_TASK_LAST_DONE_KEYS
    : ["end_reason", "dwell_active_ms", "dwell_idle_ms"];
  keys.forEach(function (key) {
    if (!Object.prototype.hasOwnProperty.call(row, key)) return;
    const shown = (typeof scoreDoingTaskFormatLeaf === "function")
      ? scoreDoingTaskFormatLeaf(key, row[key])
      : String(row[key]);
    if (!shown) return;
    const label = (typeof scoreKpiLabel === "function") ? scoreKpiLabel("doing.task." + key) : key;
    bits.push(`<span class="doing-task-kpi" data-kpi="${esc("doing.task." + key)}"><b>${esc(label)}</b> ${esc(shown)}</span>`);
  });
  if (row.ago) bits.push(`<span class="dt-ago">${esc(row.ago)}</span>`);
  return `<span class="doing-task-row is-last-done" data-act="task" data-state="last-done" data-live="false">` +
    bits.join(" ") + `</span>`;
}
function wallDoingTaskRowsHtml(owner) {
  /* Live doings[] win. If none, last-done tail from doing.task.* scores. */
  const rows = wallDoingTaskList(owner);
  if (rows.length) {
    return `<div class="doing-tasks" data-slot="tasks">` +
      `<span class="dt-head">Tasks</span>` +
      rows.map(wallDoingTaskRowHtml).join("") +
      `</div>`;
  }
  const kpis = (window._officeScores && window._officeScores.kpis) || [];
  const last = (typeof scoreDoingTaskLastDoneFromScores === "function")
    ? scoreDoingTaskLastDoneFromScores(kpis, owner)
    : null;
  if (!last) return "";
  return `<div class="doing-tasks" data-slot="tasks">` +
    `<span class="dt-head">Tasks</span>` +
    wallDoingTaskLastDoneHtml(last) +
    `</div>`;
}
function wallDoingTaskScoresHtml(owner) {
  /* Once per desk (Session + Scorecards), never repeated on each task row. */
  const desk = String(owner || "").trim();
  if (!desk) return "";
  const kpis = (window._officeScores && window._officeScores.kpis) || [];
  if (!kpis.length || typeof scoreDoingTaskLeavesByDesk !== "function") return "";
  const by = scoreDoingTaskLeavesByDesk(kpis);
  const row = by[desk];
  if (!row) return "";
  const leaves = scoreDoingTaskDeskRollup(row);
  const bits = [];
  (typeof DOING_TASK_LEAF_KEYS !== "undefined" ? DOING_TASK_LEAF_KEYS : Object.keys(leaves)).forEach(function (key) {
    if (!Object.prototype.hasOwnProperty.call(leaves, key)) return;
    const shown = scoreDoingTaskFormatLeaf(key, leaves[key]);
    if (!shown) return;
    const label = (typeof scoreKpiLabel === "function")
      ? scoreKpiLabel("doing.task." + key)
      : key;
    bits.push(`<span class="doing-task-kpi" data-kpi="${esc("doing.task." + key)}"><b>${esc(label)}</b> ${esc(shown)}</span>`);
  });
  if (!bits.length) return "";
  return `<div class="doing-task-scores" data-slot="doing.task" title="doing.task.* latest upsert for this desk">` +
    `<span class="dt-head">Task scores</span>` + bits.join(" ") + `</div>`;
}

/* The desk panel and the COLLAB desk detail: the whole view, with links. */
function wallDoingDeskHtml(owner) {
  const v = wallDoingView(owner);
  const tasksHtml = wallDoingTaskRowsHtml(owner);
  const scoresHtml = wallDoingTaskScoresHtml(owner);
  if (!v) {
    /* No /api/v1/doing view yet: still paint Phase A task rows/scores when present. */
    if (!tasksHtml && !scoresHtml) return "";
    const head = `<div class="here-doing-now is-idle">${esc("-")}</div>`;
    return `<div class="here-doing doing-view">${head}${tasksHtml}${scoresHtml}</div>`;
  }
  const cur = wallDoingText(owner);
  const head = cur
    ? `<div class="here-doing-now">${esc(cur)}</div><div class="doing-facts"><span class="doing-age">${esc(wallDoingNewest(v) ? "newest " + wallDoingAge(wallDoingNewest(v).created) : "")}</span></div>`
    : `<div class="here-doing-now is-idle${wallDoingStale(v) ? " is-stale" : ""}">idle</div>`;
  return `<div class="here-doing doing-view">${head}` +
    tasksHtml +
    scoresHtml +
    `</div>`;
}

/* Trails: a card's tw runs and moves (on=todo-N) or a desk's tw runs (desk=D), oldest first. */
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
  if (!rows.length) return `<span class="dt-head">Doing</span><span class="dt-none">${esc(byDesk ? "No tw runs from this desk yet." : "No tw runs or moves on this card yet.")}</span>`;
  const older = Math.max(0, (Number(got.entries) || rows.length) - rows.length);
  return `<span class="dt-head">Doing</span>` +
    (byDesk ? "" : wallDoingCardEvidenceHtml(key)) +
    (older ? `<span class="dt-more">${esc(older + " older not shown")}</span>` : "") +
    rows.map(function (e) {
      /* Card 1207: src doing is a tw run (current until its terminal transition); src transition is a
         move on the item's trail, painted by its act (#899). */
      const isRun = String(e.src || "doing") !== "transition";
      const act = isRun ? "" : String(e.act || "").trim();
      const actBit = act ? (typeof wallActLabel === "function" ? wallActLabel(act) : act) : "";
      let how;
      if (!isRun) how = actBit || "move";
      else if (e.ended_by) how = String(e.ended_by);
      else if (e.ended) how = "ended";
      else how = "current";
      const ev = e.evidence != null && String(e.evidence) ? String(e.evidence) : "";
      return `<span class="dt-row${isRun ? "" : " dt-move"}" data-act="${esc(act)}">` +
        `<span class="dt-at">${esc(e.at ? dt(e.at).slice(5, 16) : "")}</span> ` +
        (byDesk ? "" : `<b class="dt-desk">${esc(millName("desk", e.desk || ""))}</b> `) +
        (actBit ? `<span class="dt-act">${esc(actBit)}</span> ` : "") +
        `<span class="dt-text">${esc(e.text || (isRun ? "tw run" : ""))}</span>` +
        (byDesk && e.on ? ` <span class="dt-on">${esc("on " + e.on)}</span>` : "") +
        (ev ? ` <span class="dt-evidence">${esc(ev)}</span>` : "") +
        ` <span class="doing-ended" data-ended-by="${esc(isRun ? (e.ended_by || "") : "")}">${esc(how)}</span>` +
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
})();
var WALL_UI_DEFAULT_DOING_PAINT = "WALL_UI_DEFAULT_DOING_PAINT";

/* #898 rule-card-evidence: newest ship/done evidence on a card trail; back clears it. */
function wallDoingCardEvidence(item) {
  const key = String(item || "");
  const got = window.WALL_DOING && window.WALL_DOING.trails && window.WALL_DOING.trails[key];
  if (!got || got.state !== "ok") return "";
  /* History is newest first; the rule reads oldest first. */
  if (typeof wallCardEvidenceFromTrail === "function") return wallCardEvidenceFromTrail((got.rows || []).slice().reverse());
  return "";
}
/* The card's evidence slot at the head of its trail; blank once back clears it. */
function wallDoingCardEvidenceHtml(item) {
  const ev = wallDoingCardEvidence(item);
  return `<span class="dt-card-evidence" data-slot="card_evidence">${ev ? `<span class="dt-head">evidence</span> <span class="dt-text">${esc(ev)}</span>` : ""}</span>`;
}
