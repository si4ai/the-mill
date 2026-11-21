/* WALL_UI_DEFAULT_DOING_PAINT - each desk's live doings (tw runs)
 * (#818 PR C; card 1207: doing is only tw runs, a desk may run many, no desk-written text).
 * Marker: WALL_UI_DEFAULT_DOING_PAINT
 * Loads through lib/lazy.js (MODULES.doingPaint) after the first CONNECTED paint. Classic
 * script on purpose: it shares boot.js globals, and its function declarations replace the
 * boot.js stubs (wallDoingSync, wallDoingTrail).
 *
 * Three GET reads, the server's own views (humans are read-only; nothing here writes):
 *   /api/v1/doing?all=1                        the `mill connected` desk views
 *   /api/v1/doing/history?desk=D | ?on=ITEM    the `mill connected --history` page (ended_by)
 *   /api/v1/doing?run=WATCH_ID&desk=D          one tw run and the runs nested under it (card 1240)
 * The Wall shows what they say and computes nothing. If a route is not there (404), the
 * Wall shows no doing, with no error and no made-up field, and asks again every 10 minutes.
 */
var WALL_DOING_URL = "/api/v1/doing?all=1";
var WALL_DOING_HISTORY_URL = "/api/v1/doing/history";
var WALL_DOING_RUN_URL = "/api/v1/doing?run=";
var WALL_DOING_TTL_MS = 15000;
var WALL_DOING_TRAIL_TTL_MS = 30000;
var WALL_DOING_ABSENT_MS = 600000;
var WALL_DOING_TRAIL_MAX = 12;
var WALL_DOING_ITEM = /^(mail|todo|hold|score)-(\d+)$/;
var WALL_DOING_TAB = { mail: "mail", todo: "jobs", score: "score" };
window.WALL_DOING = window.WALL_DOING || { state: "unknown", byOwner: null, at: 0, sig: "", inflight: null, trails: {}, historyAbsentAt: 0 };
window.WALL_DOING.runs = window.WALL_DOING.runs || {};

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
      try { wallDoingRunRefresh(); } catch (eRun) {}
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
  if (typeof scoreDoingTaskLiveRows === "function") return wallDoingRunIds(scoreDoingTaskLiveRows(raw), raw);
  return raw.filter(function (t) {
    const st = String((t && t.state) || "").trim().toLowerCase();
    return st !== "finished" && st !== "failed";
  }).slice(0, typeof WALL_DOINGS_CAP === "number" ? WALL_DOINGS_CAP : 20);
}
/* Card 1240: the row cleaner keeps only the card 1207 fields; put back watch_id and
   parent_watch_id from the server's row when it sent them (an older server sends neither). */
function wallDoingRunIds(rows, raw) {
  const byId = {};
  raw.forEach(function (t) { if (t && t.id != null) byId[String(t.id)] = t; });
  return rows.map(function (row) {
    const src = row && byId[String(row.id)];
    if (!src || !Object.prototype.hasOwnProperty.call(src, "watch_id")) return row;
    return Object.assign({}, row, {
      watch_id: src.watch_id == null ? "" : String(src.watch_id),
      parent_watch_id: src.parent_watch_id == null ? "" : String(src.parent_watch_id)
    });
  });
}
function wallDoingTaskRowHtml(row, owner, childOf) {
  if (!row) return "";
  const watch = String(row.watch_id || "");
  const actBit = (typeof wallActLabel === "function") ? wallActLabel("task") : "tasked";
  const state = String(row.state || "").trim();
  const text = String(row.text || "").trim();
  const card = row.card == null ? "" : String(row.card).trim();
  const cardBit = card
    ? (` ` + (typeof wallDoingItemHtml === "function" ? wallDoingItemHtml(card.indexOf("-") >= 0 ? card : ("todo-" + card)) : `<span class="doing-on">${esc(card)}</span>`))
    : "";
  return `<span class="doing-task-row" data-state="${esc(state)}" data-id="${esc(row.id == null ? "" : row.id)}"${watch ? ` data-watch="${esc(watch)}"` : ""}>` +
    `<span class="dt-act">${esc(actBit)}</span>` +
    (state ? ` <span class="dt-state" title="${esc(row.state_at || "")}">${esc(state)}</span>` : "") +
    (text ? ` <span class="dt-text">${esc(text)}</span>` : "") +
    (watch ? ` <span class="dt-join" title="watch id">${esc(watch)}</span>` : "") +
    ` <span class="dt-ago">${esc(wallDoingAge(row.created))}</span>` +
    cardBit +
    (childOf ? ` <span class="dt-child-of" title="its parent run is not live">${esc("child of " + childOf)}</span>` : "") +
    (watch && owner ? ` ${wallDoingRunButton(owner, watch)}` : "") +
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
    const forest = wallDoingRunForest(rows, owner);
    return `<div class="doing-tasks" data-slot="tasks">` +
      `<span class="dt-head">Tasks</span>` +
      (forest == null ? rows.map(function (row) { return wallDoingTaskRowHtml(row); }).join("") : forest) +
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

/* Card 1240 (display contract, letter 6456): the tw-run tree.
 * Live list: a row nests under its parent when the parent is live on the same desk view.
 * A child whose parent is not in the view (ended, or never seen) stays at the top, marked
 * "child of PARENT". Tops keep the server's newest-first order; children read oldest first,
 * as the run tree does. Rows with no watch_id field at all (an older server) return null and
 * the caller paints today's flat list: no tree is invented. */
function wallDoingRunForest(rows, owner) {
  if (!rows.some(function (r) { return r && Object.prototype.hasOwnProperty.call(r, "watch_id"); })) return null;
  const live = {};
  rows.forEach(function (r) { if (r && r.watch_id) live[r.watch_id] = r; });
  const kids = {};
  const tops = [];
  rows.forEach(function (r) {
    if (!r) return;
    const p = r.parent_watch_id;
    if (p && p !== r.watch_id && live[p]) (kids[p] = kids[p] || []).push(r);
    else tops.push(r);
  });
  Object.keys(kids).forEach(function (p) {
    kids[p].sort(function (a, b) {
      return String(a.created || "").localeCompare(String(b.created || "")) || String(a.watch_id).localeCompare(String(b.watch_id));
    });
  });
  const seen = {};
  function node(r) {
    seen[r.watch_id || ("id-" + r.id)] = 1;
    const p = r.parent_watch_id;
    const childOf = p && p !== r.watch_id && !live[p] ? p : "";
    const mine = (r.watch_id && kids[r.watch_id] || []).filter(function (k) { return !seen[k.watch_id]; });
    return `<div class="doing-run"${r.watch_id ? ` data-watch="${esc(r.watch_id)}"` : ""}>` +
      wallDoingTaskRowHtml(r, owner, childOf) +
      (r.watch_id ? wallDoingRunSlot(owner, r.watch_id) : "") +
      (mine.length ? `<div class="doing-run-kids">${mine.map(node).join("")}</div>` : "") +
      `</div>`;
  }
  let html = tops.map(node).join("");
  /* A parent loop (a under b under a) has no top: paint what is left flat, never drop a run. */
  rows.forEach(function (r) { if (r && !seen[r.watch_id || ("id-" + r.id)]) html += node(r); });
  return html;
}
function wallDoingRunKey(owner, watch) {
  return String(owner || "") + "|" + String(watch || "");
}
function wallDoingRunButton(owner, watch) {
  const got = window.WALL_DOING.runs[wallDoingRunKey(owner, watch)];
  const open = !!(got && got.open);
  return `<button type="button" class="dt-tree" data-doing-run="${esc(watch)}" data-doing-desk="${esc(owner)}" aria-expanded="${open ? "true" : "false"}" title="${esc("Run tree for " + watch)}">${open ? "hide runs" : "runs"}</button>`;
}
function wallDoingRunSlot(owner, watch) {
  const key = wallDoingRunKey(owner, watch);
  return `<div class="doing-run-tree" data-doing-run-tree="${esc(key)}">${wallDoingRunTreeHtml(key)}</div>`;
}
/* Run detail: GET /api/v1/doing?run=WATCH_ID&desk=DESK -> {runs, n}. runs is flat, the asked run
   first and its descendants depth-first; nest them by parent_watch_id. Each run: state, start,
   end and how, exit_code, and its forwarded mill calls (verb, ok, err). */
function wallDoingRunTreeHtml(key) {
  const got = window.WALL_DOING.runs[key];
  if (!got || !got.open) return "";
  if (got.state === "unknown" || got.state === "loading") return `<span class="dt-none">Loading run tree.</span>`;
  if (got.state === "absent") return `<span class="dt-none">This server sends no run tree.</span>`;
  if (got.state === "missing") return `<span class="dt-none">${esc(got.error || "No such tw run on this desk.")}</span>`;
  if (got.state !== "ok") return `<span class="dt-none">Run tree did not load.</span>`;
  const runs = got.runs;
  const ids = {};
  runs.forEach(function (r) { ids[r.watch_id] = 1; });
  const kids = {};
  const tops = [];
  runs.forEach(function (r, i) {
    const p = r.parent_watch_id;
    if (i > 0 && p && p !== r.watch_id && ids[p]) (kids[p] = kids[p] || []).push(r);
    else tops.push(r);
  });
  const seen = {};
  function node(r, top) {
    seen[r.watch_id] = 1;
    const mine = (kids[r.watch_id] || []).filter(function (k) { return !seen[k.watch_id]; });
    return wallDoingRunHtml(r, top) +
      (mine.length ? `<div class="doing-run-kids">${mine.map(function (k) { return node(k, false); }).join("")}</div>` : "");
  }
  return `<span class="dt-head">${esc("Run tree: " + runs.length + " run" + (runs.length === 1 ? "" : "s"))}</span>` +
    tops.map(function (r) { return node(r, true); }).join("");
}
function wallDoingRunHtml(r, top) {
  const how = r.ended_by ? String(r.ended_by) : (r.end ? "ended" : "live");
  const calls = Array.isArray(r.calls) ? r.calls : [];
  const callsN = Number(r.calls_n);
  const older = Number.isFinite(callsN) ? Math.max(0, callsN - calls.length) : 0;
  const counts = Number.isFinite(callsN)
    ? `${callsN} call${callsN === 1 ? "" : "s"}` + (r.ok_n != null ? `, ${Number(r.ok_n) || 0} ok` : "") + (r.failed_n != null ? `, ${Number(r.failed_n) || 0} failed` : "")
    : "";
  const parent = r.parent_watch_id ? String(r.parent_watch_id) : "";
  return `<div class="rt-run" data-watch="${esc(r.watch_id)}" data-state="${esc(r.state || "")}" data-ended-by="${esc(r.ended_by || "")}">` +
    `<span class="rt-head">` +
    `<span class="rt-id">${esc(r.watch_id)}</span>` +
    (r.state ? ` <span class="dt-state">${esc(r.state)}</span>` : "") +
    ` <span class="dt-at" title="${esc(r.start || "")}">${esc(r.start ? dt(r.start).slice(5, 16) : "")}</span>` +
    (r.end ? ` <span class="dt-at" title="${esc(r.end)}">${esc("to " + dt(r.end).slice(5, 16))}</span>` : "") +
    ` <span class="doing-ended" data-ended-by="${esc(r.ended_by || "")}">${esc(how)}</span>` +
    (r.exit_code != null ? ` <span class="rt-exit">${esc("exit " + r.exit_code)}</span>` : "") +
    (top && parent ? ` <span class="dt-child-of">${esc("child of " + parent)}</span>` : "") +
    (counts ? ` <span class="rt-counts">${esc(counts)}</span>` : "") +
    `</span>` +
    `<span class="rt-calls">` +
    (older ? `<span class="dt-more">${esc(older + " older not shown")}</span>` : "") +
    (calls.length
      ? calls.map(function (c) {
          const ok = c && c.ok === true;
          return `<span class="rt-call" data-ok="${ok ? "true" : "false"}">` +
            `<span class="dt-at" title="${esc((c && c.at) || "")}">${esc(c && c.at ? dt(c.at).slice(11, 19) : "")}</span> ` +
            `<span class="rt-verb">${esc((c && c.verb) || "")}</span> ` +
            `<span class="rt-ok">${esc(ok ? "ok" : ((c && c.err) || "error"))}</span>` +
            `</span>`;
        }).join("")
      : `<span class="dt-none">No mill calls on this run.</span>`) +
    `</span>` +
    `</div>`;
}
function wallDoingRunFill(key) {
  const html = wallDoingRunTreeHtml(key);
  document.querySelectorAll("[data-doing-run-tree]").forEach(function (el) {
    if (el.getAttribute("data-doing-run-tree") === key && el.innerHTML !== html) el.innerHTML = html;
  });
  const got = window.WALL_DOING.runs[key];
  const open = !!(got && got.open);
  document.querySelectorAll("button[data-doing-run]").forEach(function (b) {
    if (wallDoingRunKey(b.getAttribute("data-doing-desk"), b.getAttribute("data-doing-run")) !== key) return;
    b.setAttribute("aria-expanded", open ? "true" : "false");
    b.textContent = open ? "hide runs" : "runs";
  });
}
function wallDoingRunUrl(owner, watch) {
  return WALL_DOING_RUN_URL + encodeURIComponent(watch) + "&desk=" + encodeURIComponent(owner);
}
function wallDoingRunRead(owner, watch) {
  const key = wallDoingRunKey(owner, watch);
  const slot = window.WALL_DOING.runs[key] || (window.WALL_DOING.runs[key] = { open: false, state: "unknown", runs: [], at: 0 });
  if (slot.inflight) return slot.inflight;
  if (slot.state !== "ok") slot.state = "loading";
  slot.inflight = fetch(wallDoingRunUrl(owner, watch), { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (r) {
      if (wallDoingMissing(r.status)) { slot.state = "absent"; return null; }
      if (r.status === 400) {
        slot.state = "missing";
        return r.json().then(function (j) { slot.error = String((j && j.error) || ""); return null; }, function () { return null; });
      }
      if (!r.ok) { slot.state = "down"; return null; }
      return r.json();
    })
    .then(function (json) {
      slot.at = Date.now();
      if (!json) return;
      /* An older server ignores run= and sends the desk list: that is not a tree. */
      const runs = json && Array.isArray(json.runs) ? json.runs.filter(function (r) { return r && r.watch_id; }) : null;
      if (!runs || !runs.length) { slot.state = "absent"; slot.runs = []; return; }
      slot.runs = runs;
      slot.state = "ok";
    })
    .catch(function () { slot.state = "down"; slot.at = Date.now(); })
    .then(function () { slot.inflight = null; wallDoingRunFill(key); });
  return slot.inflight;
}
function wallDoingRunToggle(owner, watch) {
  const key = wallDoingRunKey(owner, watch);
  const slot = window.WALL_DOING.runs[key] || (window.WALL_DOING.runs[key] = { open: false, state: "unknown", runs: [], at: 0 });
  slot.open = !slot.open;
  wallDoingRunFill(key);
  if (slot.open && (slot.state !== "ok" || Date.now() - slot.at >= WALL_DOING_TTL_MS)) return wallDoingRunRead(owner, watch);
  return Promise.resolve(slot);
}
/* Open trees follow the live list: read again when it is read, at most once per TTL. */
function wallDoingRunRefresh() {
  const runs = window.WALL_DOING.runs;
  const now = Date.now();
  return Promise.all(Object.keys(runs).map(function (key) {
    const slot = runs[key];
    if (!slot.open || slot.state === "absent" || now - slot.at < WALL_DOING_TTL_MS) return null;
    const cut = key.indexOf("|");
    return wallDoingRunRead(key.slice(0, cut), key.slice(cut + 1));
  }).filter(Boolean));
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
    const b = ev.target && ev.target.closest ? ev.target.closest("button[data-doing-run]") : null;
    if (b) {
      ev.preventDefault();
      ev.stopPropagation();
      wallDoingRunToggle(b.getAttribute("data-doing-desk") || "", b.getAttribute("data-doing-run") || "");
      return;
    }
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
