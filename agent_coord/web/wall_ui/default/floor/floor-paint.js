/* WALL_UI_DEFAULT_FLOOR_PAINT - COLLAB paint code, split out of boot.js (#710).
 * Marker: WALL_UI_DEFAULT_FLOOR_PAINT
 * Loads with the pane through lib/lazy.js (MODULES.floorPaint); boot.js keeps a stub
 * for each entry. Classic script on purpose: it shares boot.js globals (let/const
 * state and functions), and its function declarations replace boot.js stubs.
 */
    function setFloorAgg(mode) {
      if (mode !== "desk" && mode !== "workstation") return;
      floorAgg = mode;
      try { localStorage.setItem(FLOOR_AGG_KEY, mode); } catch (e) {}
      paintFloorAgg();
      if (floorGlanceCache) paintFloorView(floorGlanceCache);
      else loadFloorGlance(true);
    }
    /* WALL_UI_LIB_GRAPH + WALL_UI_DEFAULT_FLOOR: floorHostOf from lib or domain module */
    /* WALL_UI_DEFAULT_FLOOR: floorStateRank from domain module */
    function aggregateFloorGlance(g) {
      /* Map-only rollup. Timeline stays per-desk. Desk default = identity. */
      if (!g || floorAgg !== "workstation") return g;
      const dFloor = window._floor || {};
      const hostByOwner = {};
      (dFloor.agents || []).forEach(a => {
        const o = String(a.owner || "").trim();
        if (!o) return;
        const h = String(a.owner_host || a.host || "").trim();
        if (h) hostByOwner[o] = h;
      });
      const desksIn = (g.desks || []).slice();
      desksIn.forEach(d => {
        if (!d.owner_host) d.owner_host = hostByOwner[d.owner] || "";
      });
      const byHost = {};
      desksIn.forEach(d => {
        const host = floorHostOf(d, hostByOwner);
        let box = byHost[host];
        if (!box) {
          box = byHost[host] = {
            owner: host,
            kind: "workstation",
            owner_host: host,
            desks: [],
            unread: 0, tokens: 0, usd: 0, jobs_done: 0,
            alive: false, stale: false, doing: "", role: "",
            _state: "idle"
          };
        }
        box.desks.push(d.owner);
        box.unread += Number(d.unread || 0);
        box.tokens += Number(d.tokens || 0);
        box.usd += Number(d.usd || 0);
        box.jobs_done += Number(d.jobs_done || 0);
        box.alive = box.alive || !!d.alive;
        box.stale = box.stale || !!d.stale;
        const agent = (dFloor.agents || []).find(a => a.owner === d.owner && a.alive)
          || (dFloor.agents || []).find(a => a.owner === d.owner)
          || { owner: d.owner, doing: d.doing || "", waiting_on: d.waiting_on || "", stale: d.stale };
        let st = "idle";
        try { st = (hereGlance(dFloor, agent).state) || (d.stale ? "stale" : "idle"); } catch (e) { st = d.stale ? "stale" : "idle"; }
        if (floorStateRank(st) > floorStateRank(box._state)) box._state = st;
        if (!box.doing) box.doing = d.doing || "";
      });
      const desks = Object.keys(byHost).sort().map(h => {
        const box = byHost[h];
        box.usd = Math.round(Number(box.usd || 0) * 10000) / 10000;
        if (box.desks.length > 1) {
          box.doing = box.desks.length + " desks" + (box.doing ? (" | " + box.doing) : "");
        }
        box.rollup_state = box._state;
        delete box._state;
        return box;
      });
      const ownerToHost = {};
      desksIn.forEach(d => { ownerToHost[d.owner] = floorHostOf(d, hostByOwner); });
      const pair = {};
      ((g.edges) || []).forEach(e => {
        const a0 = String(e.a || "");
        const b0 = String(e.b || "");
        const a = ownerToHost[a0] || a0;
        const b = ownerToHost[b0] || b0;
        if (!a || !b || a === b) return;
        const lo = a <= b ? a : b, hi = a <= b ? b : a;
        const key = lo + "\0" + hi;
        let p = pair[key];
        if (!p) p = pair[key] = { a: lo, b: hi, count: 0, a_to_b: 0, b_to_a: 0, back_and_forth: false, kinds: { mail: 0, todo: 0, hold: 0 } };
        p.count += Number(e.count || 0);
        const ek = e.kinds || {};
        p.kinds.mail += Number(ek.mail || 0);
        p.kinds.todo += Number(ek.todo || 0);
        p.kinds.hold += Number(ek.hold || 0);
        /* direction approx: if original a maps to lo */
        const aIsLo = (ownerToHost[a0] || a0) === lo;
        if (aIsLo) { p.a_to_b += Number(e.a_to_b || 0); p.b_to_a += Number(e.b_to_a || 0); }
        else { p.a_to_b += Number(e.b_to_a || 0); p.b_to_a += Number(e.a_to_b || 0); }
        p.back_and_forth = p.back_and_forth || !!e.back_and_forth || (p.a_to_b > 0 && p.b_to_a > 0);
      });
      const edges = Object.values(pair).sort((x, y) => Number(y.count || 0) - Number(x.count || 0));
      return Object.assign({}, g, { desks: desks, edges: edges, _agg: "workstation" });
    }
    function floorSpanLabel(span) {
      const s = normalizeFloorSpan(span || floorSpan || "daily") || "daily";
      if (s === "min") return "Activity";
      if (s === "hourly") return "Hour";
      return "Day";
    }
    function setFloorSpan(span) {
      span = normalizeFloorSpan(span);
      if (!span) return;
      floorSpan = span;
      try { localStorage.setItem(FLOOR_SPAN_KEY, span); } catch (e) {}
      paintFloorSpan();
      loadPresenceBuckets().then(() => {
        loadFloorGlance(true);
        if (window._floor) paintSessionWire(window._floor);
      });
    }
    function floorCountBit(n, one, many) {
      n = Number(n || 0);
      if (!n) return "";
      return n + " " + (n === 1 ? one : many);
    }
    function floorEdgeLabel(e) {
      const k = (e && e.kinds) || {};
      const bits = [
        floorCountBit(k.mail, "letter", "letters"),
        floorCountBit(k.todo, "card", "cards"),
        floorCountBit(k.hold, "promise", "promises")
      ].filter(Boolean);
      if (bits.length) return bits.join(", ");
      return floorCountBit((e && e.count) || 0, "shared row", "shared rows") || "0 shared";
    }
    function ensureFloorPaint() {
      try { paintFloorMode(); } catch (e) {}
      let g = null;
      try { g = floorGlanceCache || floorGlanceFromFloor(window._floor) || null; } catch (e) { g = floorGlanceFromFloor(window._floor); }
      if (g) {
        try { paintFloorView(g, { force: true }); } catch (e) {}
        /* second paint after layout - #floor cold load often has 0-size flex until shown */
        try {
          requestAnimationFrame(function() {
            try { paintFloorView(g, { force: true }); } catch (e2) {}
          });
        } catch (e) {}
      } else {
        try { loadFloorGlance(true); } catch (e) {}
      }
    }
    function setFloorMode(mode) {
      if (mode !== "map" && mode !== "timeline") return;
      floorMode = mode;
      try { localStorage.setItem(FLOOR_MODE_KEY, mode); } catch (e) {}
      paintFloorMode();
      try { wallBumpSwitchGen(); } catch (eGenF) {}
      try { wallRestoreActivePaneFromFloor({ force: true }); } catch (eRestF) {}
      try { wallShowPaneOverlay("pane-floor", "Checking\u2026"); } catch (eOvF) {}
      if (typeof wallReuseInflightForReturn === "function" && wallReuseInflightForReturn()) {
        /* reuse in-flight */
      } else {
        tick(true);
      }
    }
    function loadFloorGlance() {
      const g = floorGlanceFromFloor(window._floor);
      if (!g) return;
      floorGlanceCache = g;
      paintFloorView(g);
    }
    /* WALL_UI_DEFAULT_FLOOR: floorLayout from domain module */
    function wallBindMapDeps() {
      try {
        window.__wallMapDeps = {
          paintFloorSpan: paintFloorSpan,
          paintFloorAgg: paintFloorAgg,
          aggregateFloorGlance: aggregateFloorGlance,
          floorLayout: floorLayout,
          floorEdgeLabel: floorEdgeLabel,
          esc: esc,
          hereGlance: hereGlance,
          wallDoingText: wallDoingText,
          millNameBare: millNameBare,
          floorSpanLabel: floorSpanLabel,
          showFloorEdge: showFloorEdge,
          showFloorDesk: showFloorDesk,
          getFloorAgg: function () { return floorAgg; },
          getFloorSpan: function () { return floorSpan; }
        };
      } catch (eMapDep) {}
    }
    function wallEnsureFloorMap() {
      wallBindMapDeps();
      if (typeof wallEnsureModule === "function") return wallEnsureModule("floorMap");
      if (typeof wallLoadScript === "function") return wallLoadScript("/floor/map-paint.js?v=wow280");
      return Promise.resolve();
    }
    function paintFloorMap(g) {
      wallBindMapDeps();
      if (window.WallFloorMap && typeof window.WallFloorMap.paint === "function") {
        return window.WallFloorMap.paint(g);
      }
      wallEnsureFloorMap().then(function () {
        wallBindMapDeps();
        if (window.WallFloorMap) window.WallFloorMap.paint(g);
      });
    }
    function presenceEventsInWindow(d, span) {
      const spec = floorWindowSpec(span || floorSpan);
      const now = Date.now();
      const since = now - spec.ms;
      return ((d && d.events) || []).filter(e => {
        const ts = floorParseTs(e.at || e.updated);
        return Number.isFinite(ts) && ts >= since && ts <= now + 1000;
      });
    }
    function floorTlSvg(namedSeries, ymax, spec, since, nB) {
      const W = 640, H = 88, padL = 28, padB = 16, padT = 8, padR = 8;
      const innerW = W - padL - padR, innerH = H - padT - padB;
      const xAt = i => padL + (nB <= 1 ? 0 : (i / (nB - 1)) * innerW);
      const yAt = v => padT + innerH - (v / ymax) * innerH;
      const grid = [0, 0.5, 1].map(f => {
        const y = yAt(ymax * f);
        return `<line class="floor-tl-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>` +
          `<text class="floor-tl-axis" x="${padL - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end">${esc(String(Math.round(ymax * f)))}</text>`;
      }).join("");
      const xLabels = [];
      const step = nB <= 8 ? 1 : Math.ceil(nB / 8);
      for (let i = 0; i < nB; i += step) {
        const t = new Date(since + i * spec.bucket);
        let lab = "";
        if (spec.unit === "hour") lab = String(t.getHours()).padStart(2, "0") + "h";
        else if (spec.unit === "day") lab = (t.getMonth() + 1) + "/" + t.getDate();
        else lab = String(t.getMinutes()).padStart(2, "0") + "m";
        xLabels.push(`<text class="floor-tl-axis" x="${xAt(i).toFixed(1)}" y="${H - 2}" text-anchor="middle">${esc(lab)}</text>`);
      }
      const lines = namedSeries.map(s => {
        const pts = s.values.map((v, i) => xAt(i).toFixed(1) + "," + yAt(v).toFixed(1)).join(" ");
        return `<polyline fill="none" stroke="${s.color}" stroke-width="${s.thick || 1.6}" points="${pts}"/>`;
      }).join("");
      return `<svg viewBox="0 0 ${W} ${H}" role="img">${grid}${xLabels.join("")}${lines}</svg>`;
    }
    function evidenceCount(row) {
      const v = row && row.value;
      if (v && typeof v === "object" && v.n != null) return Number(v.n) || 0;
      return 0;
    }
    function paintEvidenceTimeline(tlEl, rows) {
      const span = normalizeFloorSpan(floorSpan) || "daily";
      const byDesk = floorTlSplit !== "type";
      const owners = [];
      (rows || []).forEach(function (row) {
        const o = String((row && row.owner) || "");
        if (o && owners.indexOf(o) < 0) owners.push(o);
      });
      const note = span === "hourly"
        ? `<p class="floor-tl-note">Hour rollup. Each point is that desk's command count.</p>`
        : `<p class="floor-tl-note">Day rollup, 30 midnights. Each point is that desk's command count.</p>`;
      if (!owners.length) {
        const empty = span === "hourly"
          ? "No hour rollup for these desks."
          : "No day rollup for these desks.";
        tlEl.innerHTML = note + `<div class="idle">${empty}</div>`;
        return;
      }
      let spec, since, nB, indexOf;
      if (span === "hourly") {
        const start = new Date();
        start.setHours(0, 0, 0, 0);
        spec = { bucket: 3600000, unit: "hour" };
        since = start.getTime();
        nB = 24;
        indexOf = evidenceHour;
      } else {
        const start = new Date();
        start.setHours(0, 0, 0, 0);
        start.setDate(start.getDate() - 29);
        spec = { bucket: 86400000, unit: "day" };
        since = start.getTime();
        nB = 30;
        const keys = [];
        for (let i = 0; i < nB; i++) {
          const d = new Date(since + i * spec.bucket);
          keys.push(d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"));
        }
        indexOf = function (row) {
          return keys.indexOf(evidenceDay(row));
        };
      }
      const perDesk = {};
      owners.forEach(function (owner) { perDesk[owner] = new Array(nB).fill(0); });
      (rows || []).forEach(function (row) {
        const owner = String((row && row.owner) || "");
        const i = indexOf(row);
        if (!perDesk[owner] || i < 0 || i >= nB) return;
        perDesk[owner][i] = evidenceCount(row);
      });
      const commandColor = "#5ec8d8";
      let legend = "";
      let charts = "";
      if (byDesk) {
        legend = `<div class="floor-tl-legend"><span><i style="background:${commandColor}"></i>commands</span></div>`;
        charts = owners.map(function (owner) {
          const values = perDesk[owner];
          let ymax = 1;
          values.forEach(function (v) { if (v > ymax) ymax = v; });
          return `<div class="floor-tl-chart" data-owner="${esc(owner)}" role="button" tabindex="0">` +
            `<div class="floor-tl-name">${esc(owner)}</div>` +
            floorTlSvg([{ values: values, color: commandColor, thick: 1.6 }], ymax, spec, since, nB) + `</div>`;
        }).join("");
      } else {
        legend = `<div class="floor-tl-legend">` + owners.map(function (o, i) {
          return `<span><i style="background:${DESK_PALETTE[i % DESK_PALETTE.length]}"></i>${esc(o)}</span>`;
        }).join("") + `</div>`;
        const named = owners.map(function (owner, i) {
          return { values: perDesk[owner], color: DESK_PALETTE[i % DESK_PALETTE.length], thick: 1.6 };
        });
        let ymax = 1;
        named.forEach(function (s) { s.values.forEach(function (v) { if (v > ymax) ymax = v; }); });
        charts = `<div class="floor-tl-chart"><div class="floor-tl-name">commands</div>` +
          floorTlSvg(named, ymax, spec, since, nB) + `</div>`;
      }
      tlEl.innerHTML = `<div class="floor-tl-stick">${note}${legend}</div>` + charts;
      tlEl.onclick = function (ev) {
        const lane = ev.target.closest(".floor-tl-chart");
        if (!lane) return;
        tlEl.querySelectorAll(".floor-tl-chart").forEach(function (el) { el.classList.toggle("on", el === lane); });
        const owner = lane.getAttribute("data-owner");
        if (owner) showFloorDesk(owner);
      };
    }
    function paintFloorTimeline(g) {
      const tlEl = document.getElementById("floor-timeline");
      if (!tlEl) return;
      const q = activitySpanQuery();
      if (_presenceMiss && _presenceKey === q.key) {
        tlEl.innerHTML = '<div class="idle">This office has no activity span yet.</div>';
        return;
      }
      const span = q.window;
      if (span === "hourly" || span === "daily") {
        const rows = _presenceKey === q.key ? _presenceRows : [];
        paintEvidenceTimeline(tlEl, rows);
        return;
      }
      const spec = floorWindowSpec(span);
      const now = Date.now();
      const since = now - spec.ms;
      const nB = Math.max(1, Math.round(spec.ms / spec.bucket));
      const ev = presenceRowsForUi();
      const owners = [];
      ((g && g.desks) || []).forEach(function (d) {
        const o = String((d && d.owner) || "");
        if (o && owners.indexOf(o) < 0) owners.push(o);
      });
      ev.forEach(function (e) {
        const o = String(e.owner || "");
        if (o && owners.indexOf(o) < 0) owners.push(o);
      });
      const byDesk = floorTlSplit !== "type";
      const note = byDesk
        ? `<p class="floor-tl-note">By desk: mail, todo, and hold. Last 15 minutes.</p>`
        : `<p class="floor-tl-note">By type: one row per kind. Each line is a desk. Last 15 minutes.</p>`;
      if (!owners.length) {
        tlEl.innerHTML = note + '<div class="idle">No activity in the last 15 minutes.</div>';
        return;
      }
      function bucketIdx(ts) {
        return Math.max(0, Math.min(nB - 1, Math.floor((ts - since) / spec.bucket)));
      }
      const perDesk = {};
      owners.forEach(owner => {
        const series = {};
        PRESENCE_SERIES.forEach(p => { series[p[0]] = new Array(nB).fill(0); });
        ev.filter(e => floorDeskKey(e.owner) === owner || String(e.owner || "") === owner).forEach(e => {
          const ts = floorParseTs(e.at || e.updated);
          if (!Number.isFinite(ts)) return;
          const i = bucketIdx(ts);
          const n = Number(e.n != null ? e.n : 1) || 1;
          const k = String(e.kind || e.type || "");
          if (series[k]) series[k][i] += n;
        });
        perDesk[owner] = { series };
      });
      let charts = "";
      let legend = "";
      if (byDesk) {
        legend = `<div class="floor-tl-legend">` +
          PRESENCE_SERIES.map(p => `<span><i style="background:${p[1]}"></i>${esc(p[0])}</span>`).join("") +
          `</div>`;
        charts = owners.map(owner => {
          const series = perDesk[owner].series;
          let ymax = 1;
          PRESENCE_SERIES.forEach(p => series[p[0]].forEach(v => { if (v > ymax) ymax = v; }));
          const named = PRESENCE_SERIES.map(p => ({ values: series[p[0]], color: p[1], thick: 1.6 }));
          return `<div class="floor-tl-chart" data-owner="${esc(owner)}" role="button" tabindex="0">` +
            `<div class="floor-tl-name">${esc(owner)}</div>` +
            floorTlSvg(named, ymax, spec, since, nB) + `</div>`;
        }).join("");
      } else {
        legend = `<div class="floor-tl-legend">` + owners.map((o, i) =>
          `<span><i style="background:${DESK_PALETTE[i % DESK_PALETTE.length]}"></i>${esc(o)}</span>`
        ).join("") + `</div>`;
        const typeRows = PRESENCE_SERIES.map(p => [p[0], p[0]]);
        charts = typeRows.map(tr => {
          const key = tr[0];
          const named = owners.map((owner, i) => {
            const d = perDesk[owner];
            return { values: d.series[key], color: DESK_PALETTE[i % DESK_PALETTE.length], thick: 1.6 };
          });
          let ymax = 1;
          named.forEach(s => s.values.forEach(v => { if (v > ymax) ymax = v; }));
          return `<div class="floor-tl-chart" data-type="${esc(key)}">` +
            `<div class="floor-tl-name">${esc(tr[1])}</div>` +
            floorTlSvg(named, ymax, spec, since, nB) + `</div>`;
        }).join("");
      }
      tlEl.innerHTML = `<div class="floor-tl-stick">${note}${legend}</div>` + charts;
      tlEl.onclick = (ev) => {
        const lane = ev.target.closest(".floor-tl-chart");
        if (!lane) return;
        tlEl.querySelectorAll(".floor-tl-chart").forEach(el => el.classList.toggle("on", el === lane));
        showFloorDesk(lane.getAttribute("data-owner"));
      };
    }
    function showFloorDesk(owner, kind) {
      const detail = document.getElementById("floor-pop") || document.getElementById("floor-detail");
      if (!detail) return;
      detail.hidden = false;
      const gRaw = floorGlanceCache || floorGlanceFromFloor(window._floor) || {};
      const gMap = (kind === "workstation" || floorAgg === "workstation") ? (aggregateFloorGlance(gRaw) || gRaw) : gRaw;
      const g = gRaw;
      const desk = ((gMap.desks || []).find(d => d.owner === owner)) || ((g.desks || []).find(d => d.owner === owner)) || { owner };
      const isWs = (kind === "workstation") || desk.kind === "workstation";
      if (isWs) {
        const members = desk.desks || [];
        const pills = members.map(m => {
          const unreadM = Math.max(0, Number(((g.desks || []).find(x => x.owner === m) || {}).unread || ((window._floor || {}).desk_unread || {})[m] || 0) | 0);
          const badgeM = unreadM > 0 ? `<span class="fd-unread" data-n="${unreadM}">${unreadM > 99 ? "99+" : unreadM}</span>` : "";
          return `<span class="chip">${esc(m)}${badgeM}</span>`;
        }).join(" ");
        detail.innerHTML = `<div class="floor-detail-head"><h3>WORKSTATION | ${esc(owner)}</h3></div>` +
          `<span class="chip">${esc(desk.rollup_state || "")}</span>` +
          `<span class="chip">tok ${esc(desk.tokens || 0)}</span>` +
          `<span class="chip">usd ${esc(desk.usd || 0)}</span>` +
          `<span class="chip">done ${esc(floorSpanLabel(g.window || floorSpan))} ${esc(desk.jobs_done || 0)}</span>` +
          `<div style="margin-top:.35rem">desks: ${pills || esc("(none)")}</div>` +
          `<div class="here-doing"><div class="here-doing-now">${esc(String(desk.doing || "").trim() || "-")}</div></div>`;
        floorDetailSel = { type: "workstation", owner };
        return;
      }
      const lane = ((((g.timeline || {}).lanes) || []).find(L => L.owner === owner)) || null;
      const d = window._floor || {};
      const agent = (d.agents || []).find(a => a.owner === owner && a.alive) || {};
      const glance = agent.owner ? hereGlance(d, agent) : { state: (lane && lane.now_state) || "?", doing: String(desk.doing || "").trim() };
      const unread = Math.max(0, Number(desk.unread != null ? desk.unread : ((d.desk_unread || {})[owner] || 0)) | 0);
      const badge = unread > 0
        ? `<span class="fd-unread" data-n="${unread}" title="${unread} agent-unread">${unread > 99 ? "99+" : unread}</span>`
        : `<span class="fd-unread mute" data-n="0" hidden></span>`;
      const tok = desk.tokens != null ? desk.tokens : (lane ? lane.tokens : 0);
      const done = desk.jobs_done != null ? desk.jobs_done : (lane ? lane.jobs_done : 0);
      detail.innerHTML = `<div class="floor-detail-head"><h3>DESK | ${esc(owner)}</h3>${badge}</div>` +
        `<span class="chip">${esc(glance.state || (lane && lane.now_state) || "")}</span>` +
        `<span class="chip">tok ${esc(tok || 0)}</span>` +
        `<span class="chip">usd ${esc(desk.usd || (lane && lane.usd) || 0)}</span>` +
        `<span class="chip">done ${esc(floorSpanLabel(g.window || floorSpan))} ${esc(done || 0)}</span>` +
        wallDoingBlock(owner, glance.doing || desk.doing || "(no doing)");
      floorDetailSel = { type: "desk", owner };
    }
    function showFloorEdge(a, b) {
      const detail = document.getElementById("floor-pop") || document.getElementById("floor-detail");
      if (!detail) return;
      detail.hidden = false;
      const d = window._floor || {};
      const ak = floorDeskKey(a);
      const bk = floorDeskKey(b);
      const letters = (d.mailbox || []).filter(m => {
        const s = floorDeskKey(floorMailSender(m));
        const dests = floorMailDests(m).map(floorDeskKey);
        return (s === ak && dests.indexOf(bk) >= 0) || (s === bk && dests.indexOf(ak) >= 0);
      });
      let cards = [];
      try { cards = millTodoCards(d) || []; } catch (eCards) { cards = []; }
      cards = cards.filter(function (r) {
        const asker = floorDeskKey(r && (r.creator || r.asker || ""));
        const holder = floorDeskKey(r && (r.assigned || r.volunteer || ""));
        return (asker === ak && holder === bk) || (asker === bk && holder === ak);
      });
      const promises = (d.locks || []).filter(function (row) {
        const names = [row && row.owner, row && row.holder, row && row.desk, row && row.volunteer]
          .map(floorDeskKey).filter(Boolean);
        return names.indexOf(ak) >= 0 && names.indexOf(bk) >= 0;
      });
      const g = floorGlanceCache || {};
      const edge = ((g.edges || []).find(e => (e.a === a && e.b === b) || (e.a === b && e.b === a)));
      const counts = edge ? floorEdgeLabel(edge) : [
        floorCountBit(letters.length, "letter", "letters"),
        floorCountBit(cards.length, "card", "cards"),
        floorCountBit(promises.length, "promise", "promises")
      ].filter(Boolean).join(", ");
      function listOf(title, rows, line) {
        if (!rows.length) return "";
        const shown = rows.slice(0, 8);
        const more = rows.length > shown.length ? `<div class="meta">${rows.length - shown.length} more</div>` : "";
        return `<div style="margin-top:.45rem"><b>${esc(title)}</b><ul style="margin:.2rem 0 0 1rem;padding:0">` +
          shown.map(line).join("") + `</ul>${more}</div>`;
      }
      const letterList = listOf("Letters", letters, function (m) {
        const who = floorMailSender(m) || "";
        const to = floorMailDests(m).filter(Boolean).join(", ");
        return `<li><b>${esc(who)}</b> to ${esc(to)} <span class="meta">${esc(dt(m.at || m.created))}</span> - ${esc(String(m.body || "").slice(0, 100))}</li>`;
      });
      const cardList = listOf("Cards", cards, function (r) {
        const title = String(r.detail || r.need_id || "card").replace(/\s+/g, " ").trim().slice(0, 80);
        const asker = r.creator || r.asker || "";
        const holder = r.assigned || r.volunteer || "";
        return `<li><b>${esc(asker)}</b> to ${esc(holder)} - ${esc(title)}</li>`;
      });
      const promiseList = listOf("Promises", promises, function (row) {
        const file = String(row.resource || row.path || "a file").split(/[/\\]/).pop();
        return `<li>${esc(file || "a file")}</li>`;
      });
      const body = letterList + cardList + promiseList ||
        `<div class="idle">No rows for this pair in the current book.</div>`;
      detail.innerHTML = `<h3>${esc(a)} &lt;-&gt; ${esc(b)}</h3>` +
        `<div class="note">${esc(counts || "0 shared")}</div>${body}`;
      floorDetailSel = { type: "edge", a, b };
    }
var WALL_UI_DEFAULT_FLOOR_PAINT = "WALL_UI_DEFAULT_FLOOR_PAINT";
