/* WALL_UI_DEFAULT_SCORE_PAINT - SCORE paint code, split out of boot.js (#710).
 * Marker: WALL_UI_DEFAULT_SCORE_PAINT
 * Loads with the pane through lib/lazy.js (MODULES.scorePaint); boot.js keeps a stub
 * for each entry. Classic script on purpose: it shares boot.js globals (let/const
 * state and functions), and its function declarations replace boot.js stubs.
 */

    /* WALL_UI_DEFAULT_SCORE: scoreParseAt from domain module */
    /* WALL_UI_DEFAULT_SCORE: scoreWindowMs from domain module */
    /* WALL_UI_DEFAULT_SCORE: scoreInWindow from domain module */
    function scoreParseProgress(raw) {
      const s = String(raw || "").trim();
      if (!s) return null;
      let m = s.match(/^(\d+)\s*\/\s*(\d+)/);
      if (m) {
        const n = Number(m[1]), of = Number(m[2]);
        if (of > 0) return { pct: Math.max(0, Math.min(100, (n / of) * 100)), label: n + "/" + of, known: true };
      }
      m = s.match(/(\d+)\s*%/);
      if (m) {
        const pct = Math.max(0, Math.min(100, Number(m[1])));
        return { pct: pct, label: pct + "%", known: true };
      }
      return { pct: 0, label: s.slice(0, 24), known: false };
    }
    function scoreBarHtml(pct, known) {
      const p = known ? Math.max(0, Math.min(100, Number(pct) || 0)) : 0;
      const cls = known ? "" : " unknown";
      const empty = (!known || p <= 0) ? " empty" : "";
      return `<div class="score-bar${cls}${empty}" title="${known ? (Math.round(p) + "%") : "unknown"}"><i style="width:${p}%"></i></div>`;
    }
    function scoreSpendPulse(d, span) {
      /* SCORECARDS_TOKEN_DETAIL / TOKENS_EST / WALL_HONEST_EMPTY_VS_DOWN: exact LLM vs est vs mill bytes; never fake LLM 0 */
      const now = Date.now();
      const lines = (d.spend_lines && d.spend_lines.length) ? d.spend_lines : (d.spend || []);
      let exact = null, est = null, millBytes = 0, millRows = 0, cmds = 0, llmRows = 0;
      lines.forEach(r => {
        const at = r.at || "";
        if (at && !scoreInWindow(at, span, now)) return;
        const src = String(r.source || "mill");
        if (src === "mill") {
          millRows += 1;
          millBytes += Number(r.bytes_out || r.bytes || 0) || 0;
          if (r.cmds) cmds += Number(r.cmds || 0) || 0;
          else cmds += 1;
          return;
        }
        llmRows += 1;
        cmds += 1;
        if (r.tokens != null && r.tokens !== "") {
          const tok = Number(r.tokens);
          if (Number.isFinite(tok)) {
            if (exact == null) exact = 0;
            exact += tok;
            return;
          }
        }
        if (r.tokens_est != null && r.tokens_est !== "") {
          const e = Number(r.tokens_est);
          if (Number.isFinite(e)) {
            if (est == null) est = 0;
            est += e;
          }
        }
      });
      return {
        tokens: exact,
        tokens_est: est,
        millBytes: millRows ? millBytes : null,
        millRows: millRows,
        cmds: cmds,
        llmRows: llmRows,
        exact: exact != null
      };
    }
    function scoreSpendByDesk(d, span) {
      const now = Date.now();
      const out = {};
      const lines = (d.spend_lines && d.spend_lines.length) ? d.spend_lines : (d.spend || []);
      lines.forEach(r => {
        const at = r.at || "";
        if (at && !scoreInWindow(at, span, now)) return;
        const desk = String(r.owner || r.desk || "").trim();
        if (!desk) return;
        const src = String(r.source || "");
        if (src === "mill") return;
        if (!out[desk]) out[desk] = { tokens: null, tokens_est: null, exact: false };
        if (r.tokens != null && r.tokens !== "") {
          const tok = Number(r.tokens);
          if (Number.isFinite(tok)) {
            if (out[desk].tokens == null) out[desk].tokens = 0;
            out[desk].tokens += tok;
            out[desk].exact = true;
            return;
          }
        }
        if (r.tokens_est != null && r.tokens_est !== "") {
          const e = Number(r.tokens_est);
          if (Number.isFinite(e)) {
            if (out[desk].tokens_est == null) out[desk].tokens_est = 0;
            out[desk].tokens_est += e;
          }
        }
      });
      return out;
    }
    function scoreWaiting(d) {
      let n = 0;
      (d.agents || d.live_agents || []).forEach(a => {
        if (a && String(a.waiting_on || "").trim()) n++;
      });
      return n;
    }
    function scoreStalledNeeds(d) {
      const rows = [];
      (d.needs || []).forEach(n => {
        if (!n) return;
        const st = String(n.status || "").toLowerCase();
        if (st === "done") return;
        const stale = !!n.stale || !!n.holder_dead;
        const leftover = String(n.need_id || "") === "leftover" && (n.paused || (d.leftover && d.leftover.paused));
        if (stale || leftover) rows.push(n);
      });
      return rows;
    }
    function scoreBottlenecks(d) {
      const out = [];
      const now = Date.now();
      (d.agents || d.live_agents || []).forEach(a => {
        if (!a) return;
        const wo = String(a.waiting_on || "").trim();
        if (!wo) return;
        const desk = String(a.owner || a.desk || "").trim() || "(desk)";
        const prog = scoreParseProgress(a.progress || "");
        const hb = scoreParseAt(a.heartbeat || a.updated_at);
        const age = hb == null ? "-" : Math.max(0, Math.round((now - hb) / 60000)) + "m";
        out.push({
          kind: "waiting_on",
          desk: desk,
          target: wo,
          age: age,
          progress: prog,
          job: wallDoingText(a.owner, a.doing).slice(0, 48),
        });
      });
      scoreStalledNeeds(d).forEach(n => {
        const desk = String(n.volunteer || n.asker || "").trim() || "(unclaimed)";
        const prog = scoreParseProgress(n.progress || "");
        const start = scoreParseAt(n.started_at || n.updated_at || n.asked_at);
        const age = start == null ? "-" : Math.max(0, Math.round((now - start) / 60000)) + "m";
        out.push({
          kind: n.stale ? "stale card" : "stalled",
          desk: desk,
          target: String(n.need_id || ""),
          age: age,
          progress: prog,
          job: String(n.detail || n.need_id || "").slice(0, 48),
        });
      });
      return out;
    }
    function scoreDeskProgressRows(d) {
      const tokensBy = scoreSpendByDesk(d, scoreSpan);
      const by = {};
      function ensure(desk) {
        const tb = tokensBy[desk] || null;
        if (!by[desk]) by[desk] = {
          desk: desk, open: 0, done: 0, progress: null,
          tokens: tb && tb.exact ? tb.tokens : null,
          tokens_est: tb ? tb.tokens_est : null,
          exact: !!(tb && tb.exact)
        };
        return by[desk];
      }
      (d.agents || d.live_agents || []).forEach(a => {
        if (!a) return;
        const desk = String(a.owner || "").trim();
        if (!desk) return;
        const row = ensure(desk);
        const p = scoreParseProgress(a.progress || "");
        if (p && p.known) row.progress = p;
      });
      (d.needs || []).forEach(n => {
        if (!n) return;
        const desk = String(n.volunteer || n.asker || "").trim();
        if (!desk) return;
        const row = ensure(desk);
        const st = String(n.status || "").toLowerCase();
        if (st === "done") row.done += 1;
        else row.open += 1;
        const p = scoreParseProgress(n.progress || "");
        if (p && p.known) row.progress = p;
      });
      Object.keys(tokensBy).forEach(desk => {
        const row = ensure(desk);
        const tb = tokensBy[desk];
        row.exact = !!(tb && tb.exact);
        row.tokens = tb && tb.exact ? tb.tokens : null;
        row.tokens_est = tb ? tb.tokens_est : null;
      });
      return Object.keys(by).sort().map(k => {
        const row = by[k];
        const total = row.open + row.done;
        if (!row.progress || !row.progress.known) {
          if (total > 0) {
            row.progress = { pct: (row.done / total) * 100, label: row.done + "/" + total, known: true };
          } else {
            row.progress = { pct: 0, label: "-", known: false };
          }
        }
        if (row.tokens == null) row.tokens = null;
        return row;
      });
    }
    function scoreTrend(rows) {
      const hot = rows.filter(r => r.hot).length;
      const total = rows.length || 1;
      if (!rows.length) return { word: "flat", cls: "" };
      if (hot === 0) return { word: "better", cls: "better" };
      if (hot / total >= 0.5) return { word: "worse", cls: "worse" };
      return { word: "flat", cls: "" };
    }
    function paintScoreChrome() {
      document.querySelectorAll("#score-span button[data-score-span]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-score-span") === scoreSpan);
      });
      document.querySelectorAll("button[data-score-mode]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-score-mode") === scoreMode);
      });
      const core = document.getElementById("score-core");
      const spend = document.getElementById("score-spend-view");
      const kpi = document.getElementById("score-kpi-detail");
      if (core) core.hidden = scoreMode === "spend";
      if (spend) spend.hidden = scoreMode !== "spend";
      if (kpi) kpi.hidden = true;
      const span = document.getElementById("score-span");
      if (span) span.hidden = scoreMode === "spend";
      const note = document.getElementById("score-note");
      if (note) note.hidden = scoreMode === "spend";
      const show = document.getElementById("score-show");
      if (show) show.hidden = scoreMode === "spend";
    }
    function paintScorePulse(d, rows) {
      const el = document.getElementById("score-pulse");
      if (!el) return;
      const sp = scoreSpendPulse(d, scoreSpan);
      const waiting = scoreWaiting(d);
      const stalled = scoreStalledNeeds(d).length;
      const waitStall = waiting + stalled;
      const staleN = rows.filter(r => r.stale).length;
      const trend = scoreTrend(rows);
      const staleWarn = (staleN || stalled) ? " warn" : "";
      const exact = sp.exact && sp.tokens != null;
      const estOnly = (!exact) && sp.tokens_est != null;
      const tok = (typeof wallHonestLlmDisplay === "function")
        ? wallHonestLlmDisplay(exact ? sp.tokens : null, estOnly ? sp.tokens_est : null)
        : (exact ? sp.tokens : (estOnly ? sp.tokens_est : "-"));
      const llmLabel = exact ? ("LLM " + scoreSpan) : (estOnly ? ("LLM est " + scoreSpan) : ("LLM " + scoreSpan));
      const llmCls = estOnly ? "sp-item est" : "sp-item";
      const llmTitle = exact
        ? "Exact model tokens from spend --tokens (wins over tokens_est)"
        : (estOnly
          ? "Estimated tokens_est=(chars_in+chars_out)//4; source=est_chars4; not mill bytes"
          : "Model tokens from spend --tokens; or tokens_est when vendor tokens missing; empty is - not 0");
      const bytes = (typeof wallHonestMillBytesDisplay === "function")
        ? wallHonestMillBytesDisplay(sp.millBytes, sp.millRows || 0)
        : ((sp.millRows && (sp.millBytes || sp.millBytes === 0)) ? sp.millBytes : "-");
      const filed = scoreFiledList(d);
      const offT = filed.filter(function (k) {
        return typeof kpiMiss === "function" && kpiMiss(k.value, k.target);
      }).length;
      const onT = Math.max(0, filed.length - offT);
      el.innerHTML =
        `<span class="sp-item">On target<b>${esc(String(onT))}</b></span>` +
        `<span class="sp-item${offT ? " warn" : ""}">Off target<b>${esc(String(offT))}</b></span>` +
        `<span class="sp-item${waitStall ? " warn" : ""}">Waiting<b>${esc(waitStall)}</b></span>` +
        `<span class="sp-trend ${offT ? "worse" : trend.cls}">${esc(offT ? "needs eyes" : "ok")}</span>`;
    }
    function paintScoreBottlenecks(d) {
      const el = document.getElementById("score-bottlenecks");
      if (!el) return;
      const rows = scoreBottlenecks(d);
      if (!rows.length) {
        el.innerHTML = `<h3>BOTTLENECKS</h3><div class="idle">None - no one waiting, no stalled cards.</div>`;
        return;
      }
      el.innerHTML = `<h3>BOTTLENECKS</h3>` + rows.map(r => {
        const prog = r.progress || { pct: 0, known: false, label: "-" };
        return `<div class="score-bn-row">` +
          `<div class="who" title="${esc(r.job || "")}">${esc(r.desk)} | ${esc(r.target)}</div>` +
          `<div class="meta">${esc(r.kind)} | age ${esc(r.age)}</div>` +
          `<div class="meta">${esc(prog.label || "-")}</div>` +
          scoreBarHtml(prog.pct, prog.known) +
          `</div>`;
      }).join("");
    }
    function paintScoreDeskProgress(d) {
      const el = document.getElementById("score-desk-progress");
      if (!el) return;
      const rows = scoreDeskProgressRows(d);
      if (!rows.length) {
        el.innerHTML = `<h3>PROGRESS + TOKENS BY DESK</h3><div class="idle">Honest empty - no desks/needs/spend yet.</div>`;
        return;
      }
      el.innerHTML = `<h3>PROGRESS + TOKENS BY DESK</h3>` + rows.map(r => {
        const exact = !!r.exact && r.tokens != null;
        const estOnly = (!exact) && r.tokens_est != null;
        const tok = exact ? r.tokens : (estOnly ? r.tokens_est : "-");
        const llmLab = exact ? "LLM" : (estOnly ? "LLM est" : "LLM");
        const llmDim = estOnly ? "opacity:.72" : "";
        const prog = r.progress || { pct: 0, known: false, label: "-" };
        return `<div class="score-desk-row">` +
          `<div class="who">${esc(r.desk)}</div>` +
          scoreBarHtml(prog.pct, prog.known) +
          `<div class="meta">${esc(prog.label || "-")}</div>` +
          `<div class="meta" style="${llmDim}" title="${exact ? "Exact spend --tokens" : (estOnly ? "tokens_est chars//4" : "LLM tokens")}">${esc(llmLab)} ${esc(tok)}</div>` +
          `</div>`;
      }).join("");
    }
    function paintScoreHot(rows) {
      const el = document.getElementById("score-hot");
      if (!el) return;
      const list = scoreFilter === "all" ? rows : rows.filter(r => r.hot);
      if (!list.length) {
        el.innerHTML = rows.length
          ? `<div class="idle">${scoreFilter === "needs" ? "No desks need attention." : "No desks."}</div>`
          : `<div class="idle">no agent_kpi in the records</div>`;
        return;
      }
      el.innerHTML = `<div class="note" style="margin:0 0 .35rem">Hot / Needs attention</div>` + list.map(r => {
        const sel = r.desk === scoreSelectedDesk ? " sel" : "";
        const miss = r.miss ? " miss" : "";
        return `<div class="hot-card${miss}${sel}" data-score-desk="${esc(r.desk)}">` +
          `<div class="who">${esc(r.desk)}</div>` +
          `<div class="note">${esc((typeof scoreKpiLabel === "function" ? scoreKpiLabel(r.kpi) : r.kpi) || r.kpi)} | last ${esc(r.last)} | target ${esc(r.target)}</div>` +
          `<div class="note">${esc((r.reasons || []).join(" | ") || "ok")}</div>` +
          `</div>`;
      }).join("");
    }
    function paintScoreDetail(row) {
      const el = document.getElementById("score-detail");
      if (!el) return;
      if (!row) {
        el.innerHTML = `<h3>DETAIL</h3><div class="idle">Pick a desk.</div>`;
        return;
      }
      const rows = (row.kpis || []).map(k => {
        const miss = kpiMiss(k.value, k.target) ? " class=\"kpi-miss\"" : "";
        const kn = (typeof scoreKpiLabel === "function") ? scoreKpiLabel(k) : (k.kpi || "");
        return `<tr${miss}><td title="${esc(k.kpi || "")}">${esc(kn)}</td><td>${esc(k.value)}</td><td>${esc(k.target)}</td>` +
          `<td>${esc(k.note || "")}</td><td>${esc(dt(k.updated_at))}</td></tr>`;
      }).join("");
      el.innerHTML = `<h3>DETAIL | ${esc(row.desk)}</h3>` +
        `<div class="note">Last vs Target | agent_kpi | ${esc(millGid(row))}</div>` +
        `<div class="note">published ${esc(dt(row.published))} | ${esc((row.reasons || []).join(" | ") || "ok")}</div>` +
        (rows
          ? `<table data-table="score-detail"><thead><tr><th>kpi</th><th>last</th><th>target</th><th>note</th><th>published</th></tr></thead><tbody>${rows}</tbody></table>`
          : `<div class="idle">no KPIs for this desk</div>`);
    }
    function scoreRowFor(name, d) {
      const want = String(name || "").trim();
      let hit = null;
      const books = [];
      if (_officeScores && Array.isArray(_officeScores.kpis)) books.push(_officeScores.kpis);
      if (d && Array.isArray(d.kpis)) books.push(d.kpis);
      books.forEach(function (list) {
        list.forEach(function (k) {
          if (hereKpiName(k) !== want) return;
          if (!hit) { hit = k; return; }
          if (String(k.owner || "") === "Admin" && String(hit.owner || "") !== "Admin") hit = k;
        });
      });
      return hit;
    }
    function paintScoreOfficeTotals(d) {
      const lbl = (n) => scoreShowLabel(n);
      const names = scoreCatalog(d);
      const product = names.filter(n => scoreKpiBucket(n) === "product" && scoreShown(n));
      const office = names.filter(n => scoreKpiBucket(n) === "office" && scoreShown(n));
      const totals = typeof scoreOfficeTotals === "function" ? scoreOfficeTotals(d) : {};
      const chip = (n, fromHost) => {
        const k = fromHost ? (totals[n] || scoreRowFor(n, d)) : scoreRowFor(n, d);
        return `<span class="score-office-kpi"><span class="k">${esc(lbl(n))}</span>${scoreKpiCell(k)}</span>`;
      };
      const chips = product.map(n => chip(n, true)).join("");
      const officeChips = office.map(n => chip(n, false)).join("");
      if (!chips && !officeChips) return "";
      return `<div class="score-office" aria-label="Scores on this page">` +
        (chips ? `<div class="score-office-h">the-mill</div>${chips}` : "") +
        (officeChips ? `<div class="score-office-h">Office</div>${officeChips}` : "") +
        `</div>`;
    }
    function scoreEvidenceUrl(windowName) {
      const b = scoreEvidenceBase();
      let url = "/api/activity?scope=" + encodeURIComponent(b.kind) +
        "&id=" + encodeURIComponent(b.id) +
        "&window=" + encodeURIComponent(windowName) +
        "&limit=50";
      if (b.kind === "project") url += "&project=" + encodeURIComponent(b.id);
      return url;
    }
    function scoreRowDesk(row) {
      if (!row) return "";
      return scoreOwnerKey(row.owner || row.desk || "");
    }
    function scoreSameDesk(row, desk) {
      const want = scoreOwnerKey(desk).toLowerCase();
      if (!want) return false;
      return scoreRowDesk(row).toLowerCase() === want;
    }
    function evidenceCommandN(row, command) {
      const v = row && row.value;
      if (!v || typeof v !== "object") return 0;
      if (!command || command === "all") return Number(v.n) || 0;
      const slot = v[command];
      if (!slot || typeof slot !== "object") return 0;
      return Number(slot.n) || 0;
    }
    function scoreLatestDoc(rows, desk) {
      let best = null;
      let bestKey = "";
      (rows || []).forEach(function (row) {
        if (!scoreSameDesk(row, desk)) return;
        const key = String((row && (row.timestamp || row.taken)) || "");
        if (!best || key > bestKey) { best = row; bestKey = key; }
      });
      return best;
    }
    function scoreCommandNames(row) {
      const v = row && row.value;
      if (!v || typeof v !== "object") return [];
      return Object.keys(v).filter(function (k) {
        if (k === "n" || k === "bytes") return false;
        return !!(v[k] && typeof v[k] === "object");
      }).sort(function (a, b) { return a.localeCompare(b); });
    }
    function scoreDocStats(row, command) {
      const v = row && row.value;
      if (!v || typeof v !== "object") return { n: null, ms: null };
      if (!command || command === "all") {
        let ms = 0;
        let any = false;
        Object.keys(v).forEach(function (k) {
          if (k === "n" || k === "bytes") return;
          const slot = v[k];
          if (slot && typeof slot === "object" && slot.ms != null) {
            ms += Number(slot.ms) || 0;
            any = true;
          }
        });
        return { n: v.n != null ? Number(v.n) : null, ms: any ? ms : null };
      }
      const slot = v[command];
      if (!slot || typeof slot !== "object") return { n: null, ms: null };
      return {
        n: slot.n != null ? Number(slot.n) : null,
        ms: slot.ms != null ? Number(slot.ms) : null
      };
    }
    function scoreCountText(n) {
      if (n == null || !Number.isFinite(Number(n))) return "-";
      const x = Number(n);
      if (Math.abs(x - Math.round(x)) < 0.05) return String(Math.round(x));
      return String(Math.round(x * 10) / 10);
    }
    function scoreCommandDetail(stats) {
      const n = stats && stats.n;
      const ms = stats && stats.ms;
      if (n == null && ms == null) return "No count for this command today.";
      const bits = [];
      if (n != null) bits.push(scoreCountText(n) + (Number(n) === 1 ? " time" : " times"));
      if (ms != null) bits.push(scoreCountText(ms) + " ms");
      return bits.join(", ");
    }
    function scoreTotal(values) {
      let n = 0;
      (values || []).forEach(function (v) { n += Number(v) || 0; });
      return n;
    }
    function scoreBars(values, labels, name) {
      const series = values || [];
      const n = Math.max(series.length, 1);
      const W = 320, H = 78, padL = 4, padR = 4, padT = 4, padB = 16;
      let ymax = 0;
      series.forEach(function (v) {
        const x = Number(v) || 0;
        if (x > ymax) ymax = x;
      });
      if (ymax < 1) ymax = 1;
      const innerW = W - padL - padR;
      const innerH = H - padT - padB;
      const slot = innerW / n;
      const bw = Math.max(0.8, slot * (n > 16 ? 0.72 : 0.62));
      const bars = series.map(function (v, i) {
        const val = Number(v) || 0;
        const h = (val / ymax) * innerH;
        const x = padL + i * slot + (slot - bw) / 2;
        const y = padT + innerH - h;
        const hh = val > 0 ? Math.max(1.2, h) : 0;
        const track = `<rect class="score-bar-track" x="${x.toFixed(1)}" y="${padT}" width="${bw.toFixed(1)}" height="${innerH.toFixed(1)}"/>`;
        return track + `<rect class="score-bar-col" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${hh.toFixed(1)}"><title>${esc(String(val))}</title></rect>`;
      }).join("");
      const baseY = (padT + innerH).toFixed(1);
      const base = `<line class="score-bar-base" x1="${padL}" y1="${baseY}" x2="${W - padR}" y2="${baseY}"/>`;
      const labs = labels || [];
      const axis = labs.map(function (lab, i) {
        const count = labs.length;
        const x = padL + (count <= 1 ? innerW / 2 : (i / (count - 1)) * innerW);
        const anchor = i === 0 ? "start" : (i === count - 1 ? "end" : "middle");
        return `<text x="${x.toFixed(1)}" y="${H - 3}" text-anchor="${anchor}">${esc(lab)}</text>`;
      }).join("");
      return `<svg class="score-spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)}">${base}${bars}${axis}</svg>`;
    }
    function scoreSeriesActivity(desk) {
      const step = 60 * 1000;
      const nB = 15;
      const start = Math.floor(Date.now() / step) * step - (nB - 1) * step;
      const values = new Array(nB).fill(0);
      (_scoreEv.min || []).forEach(function (row) {
        if (!scoreSameDesk(row, desk)) return;
        const ts = floorParseTs(row.updated || row.at || row.timestamp);
        if (!Number.isFinite(ts)) return;
        const i = Math.floor((ts - start) / step);
        if (i < 0 || i >= nB) return;
        values[i] += Number(row.n) || 0;
      });
      const lab = function (ms) {
        const d = new Date(ms);
        return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
      };
      return { values: values, labels: [lab(start), lab(start + (nB - 1) * step)] };
    }
    function scoreSeriesHour(desk, command) {
      const values = new Array(24).fill(0);
      (_scoreEv.hourly || []).forEach(function (row) {
        if (!scoreSameDesk(row, desk)) return;
        const i = evidenceHour(row);
        if (i < 0 || i >= 24) return;
        values[i] = evidenceCommandN(row, command);
      });
      return { values: values, labels: ["0h", "12h", "23h"] };
    }
    function scoreSeriesDay(desk, command) {
      const nB = 30;
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      start.setDate(start.getDate() - (nB - 1));
      const keys = [];
      for (let i = 0; i < nB; i++) {
        const d = new Date(start.getTime() + i * 86400000);
        keys.push(d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"));
      }
      const values = new Array(nB).fill(0);
      (_scoreEv.daily || []).forEach(function (row) {
        if (!scoreSameDesk(row, desk)) return;
        const i = keys.indexOf(evidenceDay(row));
        if (i < 0) return;
        values[i] = evidenceCommandN(row, command);
      });
      const lab = function (k) {
        const m = String(k || "").match(/-(\d{2})-(\d{2})$/);
        return m ? (Number(m[1]) + "/" + Number(m[2])) : k;
      };
      return { values: values, labels: [lab(keys[0]), lab(keys[14]), lab(keys[29])] };
    }
    function scoreGraphBlock(title, count, note, body) {
      return `<div class="score-block"><h3>${esc(title)} <b>${esc(scoreCountText(count))}</b></h3><div class="note">${esc(note)}</div>${body}</div>`;
    }
    function scoreWindowBody(miss, seriesHtml) {
      if (miss) return `<div class="idle">This office has no activity span yet.</div>`;
      return seriesHtml;
    }
    async function loadScoreEvidence() {
      const key = scoreEvidenceBase().key;
      if (_scoreEvBusy) return;
      if (_scoreEv.key === key && (Date.now() - _scoreEvAt) < 15000) return;
      _scoreEvBusy = key;
      async function pull(windowName) {
        const rows = [];
        let url = scoreEvidenceUrl(windowName);
        try {
          for (let guard = 0; url && guard < 8; guard++) {
            const r = await fetch(url, { cache: "no-store" });
            if (!r.ok) return { rows: [], miss: true };
            const j = await r.json();
            (j.rows || []).forEach(function (row) { rows.push(row); });
            if (!j.next) return { rows: rows, miss: false };
            url = scoreEvidenceUrl(windowName) + "&cursor=" + encodeURIComponent(j.next);
          }
          return { rows: rows, miss: false };
        } catch (ePull) {
          return { rows: [], miss: true };
        }
      }
      let min, hourly, daily;
      try {
        const got = await Promise.all([pull("min"), pull("hourly"), pull("daily")]);
        min = got[0];
        hourly = got[1];
        daily = got[2];
      } catch (eEv) {
        min = { rows: [], miss: true };
        hourly = { rows: [], miss: true };
        daily = { rows: [], miss: true };
      }
      if (_scoreEvBusy !== key) {
        _scoreEvBusy = "";
        return;
      }
      _scoreEvBusy = "";
      if (scoreEvidenceBase().key !== key) {
        loadScoreEvidence();
        return;
      }
      _scoreEv = {
        key: key,
        min: min.rows,
        hourly: hourly.rows,
        daily: daily.rows,
        missMin: !!min.miss,
        missHour: !!hourly.miss,
        missDay: !!daily.miss
      };
      _scoreEvAt = Date.now();
      try { paintScoreDeskTable(scoreDeskRows(window._floor || {})); } catch (ePaintEv) {}
    }
    function wallSetScoreScroll(box, top) {
      _scoreGlanceLock = true;
      box.scrollTop = top;
      _scoreGlanceLock = false;
    }
    function paintScoreCommands(commandsEl, graphsEl, desk, evReady, scoreOn) {
      if (!commandsEl || !graphsEl) return;
      if (!desk) {
        commandsEl.innerHTML = `<div class="idle">Pick a desk.</div>`;
        graphsEl.innerHTML = `<div class="idle">Pick a command.</div>`;
        return;
      }
      if (!evReady) {
        const msg = (scoreOn || _scoreEvBusy) ? "Loading rollups..." : "Rollups load on this tab.";
        commandsEl.innerHTML = `<div class="score-office-h">Commands</div><div class="idle" style="padding:.45rem">${esc(msg)}</div>`;
        graphsEl.innerHTML = `<div class="idle">${esc(msg)}</div>`;
        return;
      }
      const doc = scoreLatestDoc(_scoreEv.daily, desk) || scoreLatestDoc(_scoreEv.hourly, desk);
      const names = scoreCommandNames(doc);
      const ids = ["all"].concat(names);
      if (ids.indexOf(scoreSelectedCommand) < 0) scoreSelectedCommand = names[0] || "all";
      const command = scoreSelectedCommand || "all";
      let maxN = 1;
      ids.forEach(function (id) {
        const n = Number(scoreDocStats(doc, id).n) || 0;
        if (n > maxN) maxN = n;
      });
      const rows = ids.map(function (id) {
        const stats = scoreDocStats(doc, id);
        const sel = id === command ? " sel" : "";
        const label = id === "all" ? "all commands" : id;
        const pct = Math.max(0, Math.min(100, Math.round(((Number(stats.n) || 0) / maxN) * 100)));
        return `<tr class="${sel}" data-score-verb="${esc(id)}">` +
          `<td><span class="score-verb-bar" aria-hidden="true"><i style="width:${pct}%"></i></span>${esc(label)}</td>` +
          `<td>${esc(scoreCountText(stats.n))}</td><td>${esc(scoreCountText(stats.ms))}</td></tr>`;
      }).join("");
      commandsEl.innerHTML = `<div class="score-office-h">Commands</div>` +
        `<table data-table="score-verbs"><thead><tr><th>command</th><th>n</th><th>ms</th></tr></thead><tbody>${rows}</tbody></table>`;
      const stats = scoreDocStats(doc, command);
      const commandLabel = command === "all" ? "all commands" : command;
      const activitySeries = scoreSeriesActivity(desk);
      const hourSeries = scoreSeriesHour(desk, command);
      const daySeries = scoreSeriesDay(desk, command);
      const activityN = scoreTotal(activitySeries.values);
      const hourN = scoreTotal(hourSeries.values);
      const dayN = scoreTotal(daySeries.values);
      const activity = scoreWindowBody(
        _scoreEv.missMin,
        scoreBars(activitySeries.values, activitySeries.labels, "Activity, last 15 minutes, total " + scoreCountText(activityN))
      );
      const hour = scoreWindowBody(
        _scoreEv.missHour,
        scoreBars(hourSeries.values, hourSeries.labels, "Hour, 24 slots, " + commandLabel + ", total " + scoreCountText(hourN))
      );
      const day = scoreWindowBody(
        _scoreEv.missDay,
        scoreBars(daySeries.values, daySeries.labels, "Day, 30 midnights, " + commandLabel + ", total " + scoreCountText(dayN))
      );
      const detail = scoreCommandDetail(stats);
      const detailLine = (stats.n == null && stats.ms == null)
        ? detail
        : (commandLabel + " today: " + detail);
      graphsEl.innerHTML =
        `<div class="note">${esc(detailLine)}</div>` +
        `<div class="score-charts">` +
        scoreGraphBlock("Activity", activityN, "15 minutes", activity) +
        scoreGraphBlock("Hour", hourN, "24 hours, this command", hour) +
        scoreGraphBlock("Day", dayN, "30 days, this command", day) +
        `</div>`;
    }
    function selectScoreDesk(desk, rows) {
      scoreSelectedDesk = desk || "";
      try { localStorage.setItem("factory-score-desk", scoreSelectedDesk); } catch (e) {}
      const row = rows.find(r => r.desk === scoreSelectedDesk) || null;
      paintScoreHot(rows);
      paintScoreDeskTable(rows);
      paintScoreDetail(row);
    }

    function cards(d) {
      const rows = scoreDeskRows(d);
      paintScoreChrome();
      try { paintScoreShow(d); } catch (eShowCards) {}
      paintScorePulse(d, rows);
      paintScoreBottlenecks(d);
      paintScoreDeskProgress(d);
      const spendBlock = millSpend(d);
      const spendView = document.getElementById("score-spend-view");
      if (spendView) spendView.innerHTML = spendBlock || `<div class="idle">No mill spend in this window.</div>`;
      const legacy = document.getElementById("cards");
      if (legacy) {
        legacy.innerHTML = "";
        legacy.hidden = true;
      }
      if (!scoreSelectedDesk && rows.length) {
        const prefer = rows.find(r => r.hot) || rows[0];
        scoreSelectedDesk = prefer.desk;
      }
      if (scoreSelectedDesk && !rows.some(r => r.desk === scoreSelectedDesk)) {
        scoreSelectedDesk = rows[0] ? rows[0].desk : "";
      }
      selectScoreDesk(scoreSelectedDesk, rows);
      if (!rows.length && scoreMode === "kpi") {
        const hot = document.getElementById("score-hot");
        const detail = document.getElementById("score-detail");
        if (hot) hot.innerHTML = `<div class="idle">no agent_kpi in the records</div>`;
        if (detail) detail.innerHTML = `<h3>DETAIL</h3><div class="idle">Honest empty - nothing to measure yet.</div>`;
      }
    }
    /* SCORE_BOOT_FIX: mirror ensureFloorPaint / ensureMailPaint */
    function ensureScorePaint() {
      if (!window._floor) return;
      try { cards(window._floor); } catch (e) {}
      try {
        requestAnimationFrame(function() {
          try { if (window._floor) cards(window._floor); } catch (e2) {}
        });
      } catch (e) {}
    }

    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function spendWhatRows(d) {
      const lines = d.spend_lines || [];
      let rows = lines.length ? lines : (d.spend || []);
      if (spendWindow === "today") {
        const now = new Date();
        const ymd = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
        rows = rows.filter(r => rowDay(r) === ymd);
      }
      if (spendOwner) {
        const want = spendOwner.toLowerCase();
        rows = rows.filter(r => String(r.owner || "").toLowerCase() === want);
      }
      return rows;
    }
    function presenceSpendLines(d) {
      return (d.events || []).map(e => ({
        at: e.at || e.updated || "",
        owner: e.owner || "",
        source: "presence",
        kind: e.kind || e.type || "",
        tokens: Number(e.n || 0) * Number(e.weight == null ? 1 : e.weight),
        usd: 0,
        detail: (e.kind || e.type || "") + " n*weight",
      }));
    }
    function millSpend(d) {
      if (!(d.spend_lines && d.spend_lines.length) && !(d.spend && d.spend.length)) {
        d = Object.assign({}, d, { spend_lines: presenceSpendLines(d) });
      }
      const allLines = (d.spend_lines && d.spend_lines.length) ? d.spend_lines : (d.spend || []);
      const rows = spendWhatRows(d);
      const tokens = rows.reduce((a, r) => a + Number(r.tokens || 0), 0);
      const usd = rows.reduce((a, r) => a + Number(r.usd || 0), 0).toFixed(4);
      const spendEl = document.getElementById("score-spend");
      if (spendEl) spendEl.innerHTML = `MILL SPEND<b>${esc(tokens)}</b> | est USD<b>${esc(usd)}</b>`;
      const owners = [...new Set(allLines.map(r => r.owner).filter(Boolean))].sort();
      const ownerOpts = `<option value="">owner</option>` + owners.map(o =>
        `<option value="${esc(o)}"${o === spendOwner ? " selected" : ""}>${esc(o)}</option>`
      ).join("");
      const ownerSel = owners.length > 1
        ? `<select id="spend-owner">${ownerOpts}</select>`
        : "";
      const cut = allLines.length
        ? (`<span class="wall-filter spend-cut">` +
          `<button type="button" data-spend-window="today" class="${spendWindow === "today" ? "on" : ""}">today</button>` +
          `<button type="button" data-spend-window="all" class="${spendWindow === "all" ? "on" : ""}">all</button>` +
          `</span>` + ownerSel)
        : "";
      const byOwner = {};
      rows.forEach(r => {
        const o = String(r.owner || "-");
        (byOwner[o] = byOwner[o] || []).push(r);
      });
      const groups = Object.keys(byOwner).sort((a, b) => {
        const ta = byOwner[a].reduce((s, r) => s + Number(r.tokens || 0), 0);
        const tb = byOwner[b].reduce((s, r) => s + Number(r.tokens || 0), 0);
        return tb - ta || a.localeCompare(b);
      }).map(owner => {
        const list = byOwner[owner].slice().sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
        const tok = list.reduce((s, r) => s + Number(r.tokens || 0), 0);
        const u = list.reduce((s, r) => s + Number(r.usd || 0), 0);
        const lines = list.map(r => {
          const kind = String(r.kind || r.source || "mill");
          const kcls = kind.toLowerCase().replace(/[^a-z0-9]+/g, "");
          const what = r.detail || r.note || (millGid(r) ? (String(millGid(r)) + (r.cmds ? " cmds " + r.cmds : "")) : "");
          return `<div class="spend-row kind-${esc(kcls)}">` +
            `<span class="when">${esc(dt(r.at))}</span>` +
            `<span class="k">${esc(kind)}</span>` +
            `<span class="tok" title="tokens">${esc(r.tokens == null ? "-" : r.tokens)}</span>` +
            `<span class="usd" title="est USD">${esc(r.usd == null || r.usd === 0 ? "" : ("$" + r.usd))}</span>` +
            `<span class="what">${esc(what)}</span>` +
          `</div>`;
        }).join("");
        return `<div class="spend-group">` +
          `<h3>${esc(owner)} <span>${esc(String(tok))} tok` + (u ? ` | $${esc(u.toFixed(4))}` : "") + `</span></h3>` +
          lines +
        `</div>`;
      }).join("");
      const body = rows.length
        ? groups
        : '<div class="idle">nothing in this window yet</div>';
      return `<div class="spend-chrome">${cut}</div>` +
        `<div class="spend-summary">` +
          `<span class="sp-item">Tokens<b>${esc(tokens)}</b></span>` +
          `<span class="sp-item">est USD<b>${esc(usd)}</b></span>` +
          `<span class="sp-item">Lines<b>${esc(String(rows.length))}</b></span>` +
        `</div>` +
        `<div class="spend-body">${body}</div>`;
    }
    function scoreKpiCell(k) {
      if (!k) return `<span class="score-lt dim">-</span>`;
      const last = (k.value == null || k.value === "") ? "-" : String(k.value);
      const tgt = (k.target == null || k.target === "") ? "-" : String(k.target);
      const quiet = typeof scoreMintQuiet === "function" && scoreMintQuiet(k.value, k.target);
      const miss = !quiet && typeof kpiMiss === "function" && kpiMiss(k.value, k.target);
      return `<span class="score-lt${miss ? " miss" : ""}${quiet ? " mint" : ""}">` +
        `<b>${esc(last)}</b><span class="tgt"> / ${esc(tgt)}</span></span>`;
    }
    function scoreCatalog(d) {
      const names = [];
      const seen = {};
      function add(n) {
        n = String(n || "").trim();
        if (!n || seen[n]) return;
        seen[n] = 1;
        names.push(n);
      }
      add("system");
      const books = [];
      if (_officeScores && Array.isArray(_officeScores.kpis)) books.push(_officeScores.kpis);
      if (d && Array.isArray(d.kpis)) books.push(d.kpis);
      books.forEach(function (list) {
        list.forEach(function (k) { add(hereKpiName(k)); });
      });
      const office = names.filter(function (n) { return n !== "system"; });
      office.sort(function (a, b) { return a.localeCompare(b); });
      return ["system"].concat(office);
    }
    function scoreShowLabel(name) {
      const raw = String(name || "").trim();
      if (raw === "system") return "commands";
      const mapped = (typeof scoreKpiLabel === "function") ? scoreKpiLabel(raw) : raw;
      if (mapped && mapped !== raw) return mapped;
      return raw.replace(/[._]+/g, " ");
    }
    function scoreFiledFamily(name) {
      const raw = String(name || "").trim();
      const dot = raw.indexOf(".");
      if (dot <= 0) return "";
      return raw.slice(0, dot).replace(/[-_]+/g, " ");
    }
    function scoreFiledRank(k) {
      if (typeof kpiMiss === "function" && kpiMiss(k.value, k.target)) return 0;
      const last = (k && k.value == null) ? "" : String(k.value).trim();
      if (last && last !== "-" && last !== "0") return 1;
      return 2;
    }
    function paintScoreShow(d) {
      const box = document.getElementById("score-show");
      if (!box) return;
      const names = scoreCatalog(d);
      const sig = names.join("|");
      function sync() {
        box.querySelectorAll("input[data-score-kpi]").forEach(function (inp) {
          inp.checked = !_scoreShowOff[inp.getAttribute("data-score-kpi") || ""];
        });
        box.querySelectorAll("input[data-score-group]").forEach(function (inp) {
          const g = inp.getAttribute("data-score-group") || "";
          inp.checked = !_scoreGroupOff[g];
          const set = inp.closest(".score-show-set");
          if (set) set.classList.toggle("is-off", !!_scoreGroupOff[g]);
        });
      }
      if (box.getAttribute("data-sig") === sig) { sync(); return; }
      function group(id, title, list) {
        const items = list.map(function (n) {
          const on = !_scoreShowOff[n] ? " checked" : "";
          return `<label class="score-show-item"><input type="checkbox" data-score-kpi="${esc(n)}"${on}> ${esc(scoreShowLabel(n))}</label>`;
        }).join("");
        const gOn = !_scoreGroupOff[id] ? " checked" : "";
        const off = _scoreGroupOff[id] ? " is-off" : "";
        return `<fieldset class="score-show-set${off}"><legend><label><input type="checkbox" data-score-group="${id}"${gOn}> ${esc(title)}</label></legend>${items}</fieldset>`;
      }
      const platform = names.filter(function (n) { return scoreKpiBucket(n) === "platform"; });
      const office = names.filter(function (n) { return scoreKpiBucket(n) === "office"; });
      box.innerHTML = group("platform", "Platform", platform) + group("office", "Filed", office);
      box.setAttribute("data-sig", sig);
    }
    function scoreEvidenceBase() {
      const q = activitySpanQuery();
      return { key: q.kind + ":" + q.id, kind: q.kind, id: q.id };
    }
    function paintScoreDeskTable(rows) {
      void rows;
      const el = document.getElementById("score-desk-table");
      const commandsEl = document.getElementById("score-verbs");
      const graphsEl = document.getElementById("score-graphs");
      const humanEl = document.getElementById("score-human");
      const productEl = document.getElementById("score-product");
      if (!el) return;
      const d = window._floor || window._floorRaw || {};
      try { paintScoreShow(d); } catch (eShowPaint) {}
      function deskOf(k) {
        if (typeof scoreDeskSlug === "function") return scoreOwnerKey(scoreDeskSlug(k));
        return scoreOwnerKey(k && k.owner);
      }
      function deskLabel(desk) {
        return millName ? millName("desk", desk) : desk;
      }
      const books = [];
      if (_officeScores && Array.isArray(_officeScores.kpis)) books.push(_officeScores.kpis);
      if (d && Array.isArray(d.kpis)) books.push(d.kpis);
      const showPlatform = !!scoreShown("system");
      const showFiled = !_scoreGroupOff.office;
      if (productEl) productEl.hidden = !showPlatform;
      if (!showPlatform && !showFiled) {
        if (humanEl) {
          humanEl.hidden = false;
          humanEl.innerHTML = `<div class="idle" style="padding:.45rem">No scores selected.</div>`;
        }
        return;
      }
      if (showPlatform) {
        const byDesk = {};
        books.forEach(function (list) {
          list.forEach(function (k) {
            if (hereKpiName(k) !== "system") return;
            const desk = deskOf(k);
            if (!desk || desk === "(unknown)") return;
            const id = desk.toLowerCase();
            if (!byDesk[id]) byDesk[id] = { desk: desk, kpi: k };
          });
        });
        ((d.agents || []).filter(function (a) { return a && a.alive !== false; })).forEach(function (a) {
          const desk = scoreOwnerKey(a.owner);
          if (!desk) return;
          const id = desk.toLowerCase();
          if (!byDesk[id]) byDesk[id] = { desk: desk, kpi: null };
        });
        const desks = Object.keys(byDesk).map(function (id) { return byDesk[id]; });
        desks.sort(function (a, b) { return deskLabel(a.desk).localeCompare(deskLabel(b.desk)); });
        let selected = scoreOwnerKey(scoreSelectedDesk);
        const found = desks.find(function (item) { return item.desk.toLowerCase() === selected.toLowerCase(); });
        if (found) selected = found.desk;
        else selected = desks.length ? desks[0].desk : "";
        if (selected !== scoreSelectedDesk) {
          scoreSelectedDesk = selected;
          scoreSelectedCommand = "";
          try { localStorage.setItem("factory-score-desk", scoreSelectedDesk); } catch (eDesk) {}
        }
        if (!desks.length) {
          el.innerHTML = `<div class="score-office-h">Desks</div><div class="idle" style="padding:.45rem">No desk command scores yet.</div>`;
          if (commandsEl) commandsEl.innerHTML = `<div class="idle">Pick a desk.</div>`;
          if (graphsEl) graphsEl.innerHTML = `<div class="idle">Pick a command.</div>`;
        } else {
          const body = desks.map(function (item) {
            const k = item.kpi;
            const last = (!k || k.value == null || k.value === "") ? "-" : String(k.value);
            const sel = item.desk === scoreSelectedDesk ? " sel" : "";
            return `<tr class="${sel}" data-score-desk="${esc(item.desk)}"><td>${esc(deskLabel(item.desk))}</td><td>${esc(last)}</td></tr>`;
          }).join("");
          el.innerHTML = `<div class="score-office-h">Desks</div>` +
            `<table data-table="score-platform"><thead><tr><th>desk</th><th>today</th></tr></thead><tbody>${body}</tbody></table>`;
          const pane = document.getElementById("pane-score");
          const scoreOn = !!(pane && pane.classList.contains("on"));
          const evKey = scoreEvidenceBase().key;
          const evReady = _scoreEv.key === evKey;
          if (scoreOn && (!evReady || (Date.now() - _scoreEvAt) >= 15000)) loadScoreEvidence();
          paintScoreCommands(commandsEl, graphsEl, scoreSelectedDesk, evReady, scoreOn);
        }
      }
      if (!humanEl) return;
      if (!showFiled) {
        humanEl.hidden = true;
        humanEl.innerHTML = "";
        return;
      }
      humanEl.hidden = false;
      const officeRows = scoreFiledList(d);
      if (!officeRows.length) {
        humanEl.innerHTML = `<div class="score-office-h">Filed</div><div class="idle" style="padding:.45rem">No filed scores yet. Ask your agent to file one.</div>`;
        return;
      }
      const buckets = {};
      const famOrder = [];
      officeRows.forEach(function (k) {
        const fam = scoreFiledFamily(hereKpiName(k));
        if (!buckets[fam]) {
          buckets[fam] = [];
          famOrder.push(fam);
        }
        buckets[fam].push(k);
      });
      function famBest(fam) {
        let n = 3;
        buckets[fam].forEach(function (k) {
          const r = scoreFiledRank(k);
          if (r < n) n = r;
        });
        return n;
      }
      famOrder.sort(function (a, b) {
        const d = famBest(a) - famBest(b);
        if (d) return d;
        return a.localeCompare(b);
      });
      famOrder.forEach(function (fam) {
        buckets[fam].sort(function (a, b) {
          const d = scoreFiledRank(a) - scoreFiledRank(b);
          if (d) return d;
          return scoreFiledFace(hereKpiName(a)).localeCompare(scoreFiledFace(hereKpiName(b)))
            || deskOf(a).localeCompare(deskOf(b));
        });
      });
      const filed = [];
      famOrder.forEach(function (fam) {
        if (fam) filed.push(`<tr class="score-family"><th colspan="3">${esc(fam)}</th></tr>`);
        buckets[fam].forEach(function (k) {
          const name = hereKpiName(k);
          const desk = deskOf(k);
          const miss = typeof kpiMiss === "function" && kpiMiss(k.value, k.target);
          filed.push(
            `<tr class="${miss ? "hot" : ""}">` +
            `<td title="${esc(name)}">${esc(scoreFiledFace(name))}</td>` +
            `<td>${esc(deskLabel(desk))}</td><td>${scoreKpiCell(k)}</td></tr>`
          );
        });
      });
      if (_scoreGlanceUser) _scoreGlanceScroll = humanEl.scrollTop;
      humanEl.innerHTML = `<div class="score-office-h">Filed</div>` +
        `<table data-table="score-filed"><thead><tr><th>score</th><th>desk</th><th>Last / target</th></tr></thead><tbody>${filed.join("")}</tbody></table>`;
      wallWireScoreGlance();
      wallQueueScoreGlance();
    }
    function wallWireScoreGlance() {
      const box = document.getElementById("score-human");
      if (!box || box._glanceWired) return;
      box._glanceWired = true;
      function markUser() { _scoreGlanceUser = true; }
      box.addEventListener("wheel", markUser, { passive: true });
      box.addEventListener("pointerdown", markUser);
      box.addEventListener("touchstart", markUser, { passive: true });
      box.addEventListener("scroll", function () {
        if (_scoreGlanceLock || !_scoreGlanceUser) return;
        _scoreGlanceScroll = box.scrollTop;
      }, { passive: true });
    }
    function wallCenterScoreGlance() {}
    function wallQueueScoreGlance() {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          try { wallCenterScoreGlance(); } catch (eGlance) {}
          try { if (window.markOverflow) window.markOverflow(); } catch (eMore) {}
        });
      });
    }

var WALL_UI_DEFAULT_SCORE_PAINT = "WALL_UI_DEFAULT_SCORE_PAINT";
