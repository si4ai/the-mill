/* WALL_UI_DEFAULT_MAIL_PAINT - MAIL paint code, split out of boot.js (#710).
 * Marker: WALL_UI_DEFAULT_MAIL_PAINT
 * Loads with the pane through lib/lazy.js (MODULES.mailPaint); boot.js keeps a stub
 * for each entry. Classic script on purpose: it shares boot.js globals (let/const
 * state and functions), and its function declarations replace boot.js stubs.
 */
    /* WALL_UI_DEFAULT_MAIL: mailDst from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailIsFloor from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailDstKey from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailReadMatchesDst from domain module */
    /** Primary Wall unread = agent-unread for dst desk (party=agent). Human open alone does not clear. */
    /* WALL_UI_DEFAULT_MAIL: mailDstAgentRead from domain module */
    /** Soft cue: human opened on Wall (party=human). Optional - not primary unread. */
    /* WALL_UI_DEFAULT_MAIL: mailDstHumanOpened from domain module */
    /** @deprecated name kept: primary read = agent read */
    /* WALL_UI_DEFAULT_MAIL: mailDstRead from domain module */
    function mailReadChips(m) {
      const reads = m.reads || [];
      if (reads.length) {
        return reads.map(r => {
          const who = String((r && r.who) || "").trim();
          if (!who) return "";
          const party = String((r && r.party) || "").toLowerCase();
          const cls = party === "human" ? "mail-chip human" : (party === "agent" ? "mail-chip agent" : "mail-chip");
          return `<span class="${cls}" title="${esc(who)}">${esc(who)}</span>`;
        }).filter(Boolean);
      }
      return (m.readers || []).map(r => {
        const s = String(r || "").trim();
        if (!s) return "";
        const cls = s.indexOf(":human") >= 0 ? "mail-chip human" : (s.indexOf(":agent") >= 0 ? "mail-chip agent" : "mail-chip");
        return `<span class="${cls}" title="${esc(s)}">${esc(s)}</span>`;
      }).filter(Boolean);
    }
    function mailGuessEta(d, m) {
      if (mailIsFloor(m)) return { kind: "unknown" };
      const dst = mailDst(m);
      const pid = String(millGid(m) || "");
      const name = x => String(x || "").trim() === dst;
      const agents = (d.agents || []).filter(a => a.alive && name(a.owner));
      const sess = agents.find(a => millGid(a) === pid) || agents[0];
      if (!sess) return { kind: "offline" };
      const millCard = r => {
        const nid = String(r.need_id || "");
        if (!nid || nid === "leftover" || nid.indexOf("idle-") === 0) return false;
        if (r.holder_dead) return false;
        const st = r.status || "";
        if (st !== "claimed" && st !== "current") return false;
        if (!name(r.volunteer) && !name(r.owner)) return false;
        if (pid && millGid(r) && String(millGid(r)) !== pid) return false;
        return true;
      };
      const pool = [].concat(d.on_it || [], d.needs || []);
      const cards = pool.filter(millCard);
      const card = cards.find(r => r.eta) || cards[0];
      if (card) {
        const eta = { kind: "card" };
        if (card.eta) eta.at = card.eta;
        if (card.need_id) eta.need_id = card.need_id;
        return eta;
      }
      const doing = wallDoingText(sess.owner, sess.doing);
      const idleNid = r => {
        const nid = String(r.need_id || "");
        return nid === "leftover" || nid.indexOf("idle-") === 0;
      };
      const idleCard = pool.find(r => idleNid(r) && (name(r.volunteer) || name(r.owner)));
      const idleDoing = !doing || /^idle\b/i.test(doing) || doing === "here";
      if (idleCard || idleDoing) {
        const eta = { kind: "idle" };
        const at = (idleCard && idleCard.eta) || sess.heartbeat || "";
        if (at) eta.at = at;
        if (idleCard && idleCard.need_id) eta.need_id = idleCard.need_id;
        return eta;
      }
      return { kind: "unknown" };
    }
    function mailReadEta(d, m) {
      const given = m.read_eta;
      if (given && ["offline", "card", "idle", "unknown"].indexOf(given.kind) >= 0) return given;
      return mailGuessEta(d, m);
    }
    function mailEtaText(unread, eta) {
      if (!unread) return "-";
      const kind = (eta && eta.kind) || "unknown";
      if (kind === "offline") return "offline";
      if (kind === "card") return eta.at ? t(eta.at) : "-";
      if (kind === "idle") return eta.at ? t(eta.at) : "idle";
      return "-";
    }
    /* WALL_UI_DEFAULT_MAIL: mailBareDst from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailIsBareHumanMailbox from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailActiveRows from domain module */
    /* MAIL_BOOT_FIX: paint Mail on enter / when pane visible - same family as Floor cold load */
    function ensureMailPaint(opts) {
      /* Wave 3: one paint path. opts.chromeOnly skips mail() when tick already painted. */
      try {
        const browser = document.querySelector(".mail-browser, .mail-split");
        if (browser) browser.setAttribute("data-mail-view", mailView || "rooms");
        document.querySelectorAll(".mail-view-toggle button").forEach(b => {
          b.classList.toggle("on", b.dataset.mailView === (mailView || "rooms"));
        });
      } catch (e) {}
      if (opts && opts.chromeOnly) return;
      if (!window._floor) return;
      try { mail(window._floor); } catch (e) {}
    }
    function setMailView(which) {
      mailView = (which === "letters") ? "letters" : "rooms";
      _mailViewChosen = true;
      if (mailView !== "rooms") {
        _mailRoomsRailSig = "";
        _mailRoomsNestSig = "";
      }
      document.querySelectorAll(".mail-view-toggle button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailView === mailView);
      });
      const browser = document.querySelector(".mail-browser, .mail-split");
      if (browser) browser.setAttribute("data-mail-view", mailView);
      try { syncMailRoomsFiltersVisible(); } catch (eRoomsWin) {}
      /* bump gen + overlay; stale ticks must not blank; keep theme. */
      const mailGen = wallBumpSwitchGen();
      try { wallRestoreActivePaneFromFloor({ force: true }); } catch (eRestMail) {}
      try { wallShowPaneOverlay("pane-mail", "Checking\u2026"); } catch (eOvMail) {}
            /* Checking overlay; reuse in-flight if same parts, else tick after fp decide. */
      if (typeof wallReuseInflightForReturn === "function" && wallReuseInflightForReturn()) {
        /* keep Checking until in-flight settle */
      } else if (typeof tick === "function") {
        try { tick(true); } catch (eTick) {
          if (wallSwitchGenAlive(mailGen) && window._floor) {
            try { mail(window._floor); } catch (eMail) {}
          }
          if (wallSwitchGenAlive(mailGen)) {
            try { wallClearPaneOverlay("pane-mail"); } catch (eClr) {}
          }
        }
      } else if (wallSwitchGenAlive(mailGen) && window._floor) {
        try { mail(window._floor); } catch (eMail2) {}
        try { wallClearPaneOverlay("pane-mail"); } catch (eClr2) {}
      }
    }
    function setMailRoom(roomId) {
      mailSelectedRoom = String(roomId || "").trim();
      try { localStorage.setItem(MAIL_ROOM_KEY, mailSelectedRoom); } catch (e) {}
      if (window._floor) mail(window._floor);
    }
    function setMailRoomsQ(q) {
      mailRoomsQ = String(q || "").trim();
      try { localStorage.setItem(MAIL_ROOMS_Q_KEY, mailRoomsQ); } catch (e) {}
      if (window._floor) mail(window._floor);
    }
    function setMailMode(which) {
      mailMode = (which === "all" || which === "recent") ? which : "attention";
      try { localStorage.setItem(MAIL_MODE_KEY, mailMode); } catch (e) {}
      document.querySelectorAll(".mail-mode-toggle button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailMode === mailMode);
      });
      if (window._floor) mail(window._floor);
    }
    function setMailDestClass(which) {
      const ok = { all: 1, desk: 1, roster: 1, star: 1 };
      mailDestClassFilter = ok[which] ? which : "all";
      try { localStorage.setItem(MAIL_CLASS_KEY, mailDestClassFilter); } catch (e) {}
      document.querySelectorAll(".mail-dest-class button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailClass === mailDestClassFilter);
      });
      if (window._floor) mail(window._floor);
    }
    function setMailDesk(desk) {
      setMailDst(desk);
    }
    function setMailDst(dst) {
      mailSelectedDst = String(dst || "").trim();
      mailSelectedDesk = mailSelectedDst;
      mailSelectedSrc = "";
      try {
        localStorage.setItem(MAIL_TO_KEY, mailSelectedDst);
        localStorage.setItem(MAIL_DESK_KEY, mailSelectedDesk);
        localStorage.setItem(MAIL_SRC_KEY, "");
      } catch (e) {}
      if (window._floor) mail(window._floor);
    }
    function setMailSrc(src) {
      mailSelectedSrc = String(src || "").trim();
      try { localStorage.setItem(MAIL_SRC_KEY, mailSelectedSrc); } catch (e) {}
      if (window._floor) mail(window._floor);
    }
    /* WALL_UI_DEFAULT_MAIL: mailMsgHumanRequiredOpen from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailMsgAgentUnread from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailMsgNeedsAttention from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailDeskMatches from domain module */
    function mailKnownDesks(d, rows) {
      /* also used as mailKnownDsts - desks + rosters + * */
      const roles = new Set(wallRoleNames());
      const unreadMap = d.desk_unread || {};
      const hrMap = d.desk_human_required || {};
      const attnMap = d.desk_attention || {};
      const byId = new Map();
      const proj = wallProjectName() || String((d.wall && d.wall[0]) || ((d.groups || d.projects) && (d.groups || d.projects)[0]) || "").trim();
      const add = (id, kind) => {
        const o = String(id || "").trim();
        if (!o || mailIsBareHumanMailbox(o)) return;
        const key = (typeof mailDstKey === "function") ? mailDstKey(o) : String(o || "").trim();
        if (!key || mailIsBareHumanMailbox(key)) return;
        const cls = kind || (typeof mailDestClass === "function" ? mailDestClass(key, proj) : "desk");
        const prev = byId.get(key) || { id: key, kind: cls, agentUnread: 0, humanCue: 0, humanRequired: 0 };
        if (cls && cls !== "desk") prev.kind = cls;
        byId.set(key, prev);
      };
      (d.agents || []).forEach(a => add(a.owner, "desk"));
      ((d.office_glance && d.office_glance.desks) || []).forEach(x => add(x.owner, "desk"));
      Object.keys(unreadMap).forEach(k => add(k, "desk"));
      Object.keys(hrMap).forEach(k => add(k, "desk"));
      Object.keys(attnMap).forEach(k => add(k, "desk"));
      roles.forEach(r => add(r, "roster"));
      if (proj) add(proj, "roster");
      add("*", "star");
      (rows || []).forEach(m => {
        const desks = (typeof mailDstDesks === "function") ? mailDstDesks(m) : [mailDst(m)];
        desks.forEach(raw0 => {
          const raw = String(raw0 || "").trim();
          if (!raw || mailIsBareHumanMailbox(raw)) return;
          add(raw, typeof mailDestClass === "function" ? mailDestClass(raw, proj) : "desk");
        });
      });
      byId.forEach((rec, key) => {
        let agentUnread = 0, humanCue = 0, humanRequired = 0;
        (rows || []).forEach(m => {
          if (!mailDeskMatches(m, key)) return;
          if (key === "*") {
            if ((typeof mailStarWallUnread === "function") ? mailStarWallUnread(m) : false) agentUnread += 1;
          } else if (mailMsgAgentUnread(m)) agentUnread += 1;
          else if (!mailDstHumanOpened(m)) humanCue += 1;
          if (mailMsgHumanRequiredOpen(m)) humanRequired += 1;
        });
        if (key !== "*" && unreadMap[key] != null && Number(unreadMap[key]) >= 0) {
          rec.agentUnread = Math.max(0, Number(unreadMap[key]) | 0);
        } else {
          rec.agentUnread = agentUnread;
        }
        if (hrMap[key] != null && Number(hrMap[key]) >= 0) {
          rec.humanRequired = Math.max(0, Number(hrMap[key]) | 0);
        } else {
          rec.humanRequired = humanRequired;
        }
        rec.humanCue = humanCue;
        const attn = attnMap[key];
        if (attn && typeof attn === "object" && "needs_attention" in attn) {
          rec.needsAttention = !!attn.needs_attention;
          if (attn.agent_unread != null) rec.agentUnread = Math.max(0, Number(attn.agent_unread) | 0);
          if (attn.human_required != null) rec.humanRequired = Math.max(0, Number(attn.human_required) | 0);
        } else if (key === "*") {
          rec.needsAttention = rec.humanRequired > 0;
        } else {
          rec.needsAttention = rec.agentUnread > 0 || rec.humanRequired > 0;
        }
      });
      return [...byId.values()].sort((a, b) => {
        if (a.needsAttention !== b.needsAttention) return a.needsAttention ? -1 : 1;
        if (b.agentUnread !== a.agentUnread) return b.agentUnread - a.agentUnread;
        if (b.humanRequired !== a.humanRequired) return b.humanRequired - a.humanRequired;
        const rank = { star: 0, project: 1, role: 2, desk: 3 };
        const ra = rank[a.kind] != null ? rank[a.kind] : 9;
        const rb = rank[b.kind] != null ? rank[b.kind] : 9;
        if (ra !== rb) return ra - rb;
        return String(a.id).localeCompare(String(b.id));
      });
    }
    function mailDeskRailHtml(desks, mode, selected) {
      return mailDstColHtml(desks, mode, selected);
    }
    function mailDstColHtml(dsts, mode, selected) {
      const show = mode === "attention" ? dsts.filter(x => x.needsAttention) : dsts;
      if (mode === "attention" && !show.length) {
        return `<div class="rail-h">Dst</div><div class="col-empty">All clear - none need attention</div>`;
      }
      if (!show.length) {
        return `<div class="rail-h">Dst</div><div class="col-empty">no destinations</div>`;
      }
      const rows = show.map(x => {
        const on = selected === x.id ? " on" : "";
        const n = x.agentUnread | 0;
        const badge = `<span class="desk-badge" data-n="${n}" title="${n} agent-unread">${n > 99 ? "99+" : n}</span>`;
        const hr = x.humanRequired > 0 ? `<span class="hr-cue" title="open human_required">HR</span>` : "";
        const soft = (n === 0 && x.humanCue > 0)
          ? `<span class="human-cue" title="human not opened on some">|</span>` : "";
        let kindLabel = "";
        if (x.kind === "roster") kindLabel = "roster";
        else if (x.kind === "star") kindLabel = "star";
        const kind = kindLabel ? `<span class="desk-kind">${kindLabel}</span>` : "";
        const label = x.id === "*" ? "*" : x.id;
        return `<button type="button" class="desk-row${on}" data-mail-dst="${esc(x.id)}" data-mail-desk="${esc(x.id)}" title="${esc(x.id)}">` +
          `<span class="desk-id">${esc(label)}</span>${kind}${hr}${soft}${badge}</button>`;
      }).join("");
      return `<div class="rail-h">Dst</div>${rows}`;
    }
    /* WALL_UI_DEFAULT_MAIL: mailSrcsForDst from domain module */
    function mailSrcColHtml(srcs, selected, hasDst) {
      if (!hasDst) {
        return `<div class="rail-h">Src</div><div class="col-empty">pick a dst</div>`;
      }
      if (!srcs.length) {
        return `<div class="rail-h">Src</div><div class="col-empty">no senders for this dst</div>`;
      }
      const rows = srcs.map(x => {
        const on = selected === x.id ? " on" : "";
        const n = x.agentUnread | 0;
        const badge = `<span class="desk-badge" data-n="${n}" title="${n} agent-unread">${n > 99 ? "99+" : n}</span>`;
        const hr = x.humanRequired > 0 ? `<span class="hr-cue" title="open human_required">HR</span>` : "";
        return `<button type="button" class="src-row${on}" data-mail-src="${esc(x.id)}" title="${esc(x.id)}">` +
          `<span class="src-id">${esc(x.id)}</span>${hr}${badge}</button>`;
      }).join("");
      return `<div class="rail-h">Src</div>${rows}`;
    }
    function mailRowsAllRecent(rows, mode) {
      /* recent-first (mode may slice/filter attention); LIST uses via mailRowsForListDst */
      let out = (rows || []).slice();
      if (mode === "attention") {
        out = out.filter(m => mailMsgAgentUnread(m) || mailMsgHumanRequiredOpen(m));
      }
      out.sort((a, b) => {
        const aa = (typeof mailAt === "function") ? mailAt(a) : (a.at || a.created || "");
        const bb = (typeof mailAt === "function") ? mailAt(b) : (b.at || b.created || "");
        return String(bb).localeCompare(String(aa));
      });
      if (mode === "recent") out = out.slice(0, 80);
      return out;
    }
    /* WALL_UI_DEFAULT_MAIL: mailRowsForListDst from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailRowsForDesk from domain module */
    /* WALL_UI_DEFAULT_MAIL: mailRowsForDstSrc from domain module */
    function mailListHtml(d, rows) {
      return `<table data-table="mail"><thead><tr>` +
        `<th>sent</th><th>read</th><th>line</th><th>src</th><th>dst</th><th>kind</th><th>body</th><th></th><th>eta</th>` +
        `</tr></thead><tbody>` +
        rows.map(m => {
          const floor = mailIsFloor(m);
          const agentRead = mailDstAgentRead(m);
          const humanOpen = mailDstHumanOpened(m);
          const unread = (typeof mailWallUnread === "function") ? mailWallUnread(m) : (!floor && !agentRead);
          const hr = mailMsgHumanRequiredOpen(m);
          const eta = mailReadEta(d, m);
          m.read_eta = eta;
          const soft = (!floor && agentRead && !humanOpen) ? " human-unopened" : "";
          const hrCls = hr ? " human-required" : "";
          const cls = `${unread ? "unread" : (agentRead ? "fading" : "")}${soft}${hrCls}${m.fading ? " fading" : ""}${m.kind === "instruct" ? " desk" : ""}`;
          const chipList = mailReadChips(m);
          const readers = chipList.length ? " " + chipList.join(" ") : "";
          const hrChip = hr ? `<span class="mail-chip needs-human mail-hr-chip" title="Needs human (human_required)">Needs human</span>` : "";
          const mid = String(m.id || "");
          const st = (mailDst(m) === "*") ? (unread ? "star-unread" : "star-read") : (floor ? "floor" : (unread ? "agent-unread" : (humanOpen ? "read" : "agent-read")));
          const guess = mailEtaText(unread, eta);
          const atVal = (typeof mailAt === "function") ? mailAt(m) : (m.at || m.created || "");
          const srcVal = (typeof mailSenderDesk === "function") ? mailSenderDesk(m) : (m.src || "");
          const dstVal = mailDst(m);
          const cast = (typeof mailRoomCast === "function") ? mailRoomCast(m) : [];
          const dstShow = (cast.length > 2)
            ? (dstVal + " +" + (cast.length - 1))
            : (cast.length > 1 ? cast.map(c => c.deskId).filter(d => d !== srcVal).join(",") || dstVal : dstVal);
          const sent = dt(atVal);
          const readAt = (!floor && m.read_at) ? dt(m.read_at) : "-";
          const deskKey = mailDstKey(dstVal);
          const bodyTrunc = (m.body_trunc === true) ? "1" : "0";
          return `<tr class="${cls}" data-mail-id="${esc(mid)}" data-mail-dst="${esc(deskKey)}" data-mail-project="${esc(millGid(m) || "")}" data-body-trunc="${bodyTrunc}">` +
          `<td data-sort="${esc(atVal)}">${esc(sent)}</td>` +
          `<td data-sort="${esc(m.read_at || "")}">${esc(readAt)}</td>` +
          `<td>${esc(millGid(m))}</td>` +
          `<td>${esc(srcVal)}</td><td title="${esc(cast.map(c => c.deskId).join(", "))}">${esc(dstShow)}</td>` +
          `<td>${esc(m.kind || "note")}</td>` +
          `<td class="body">${esc(m.body)}${millWatchBadge("mail", m.id)}${hrChip}</td>` +
          `<td class="note">${st}${readers}</td>` +
          `<td class="note" data-sort="${esc((eta && (eta.at || eta.kind)) || "")}">${esc(guess)}</td></tr>`;
        }).join("") +
        `</tbody></table>`;
    }
    function mailGraphHtml(rows) {
      const edges = rows.filter(m => {
        const src = (typeof mailSenderDesk === "function") ? mailSenderDesk(m) : String(m.src || "").trim();
        const dst = mailDst(m);
        return !mailIsFloor(m) && src && dst;
      });
      if (!edges.length) {
        return '<div class="mail-graph"><div class="idle">no mail edges for this filter (floor-only or empty)</div></div>';
      }
      const bySrc = {};
      edges.forEach(m => {
        const src = (typeof mailSenderDesk === "function") ? mailSenderDesk(m) : String(m.src || "").trim();
        (bySrc[src] ??= []).push(m);
      });
      Object.keys(bySrc).forEach(k => {
        bySrc[k].sort((a, b) => {
          const aa = (typeof mailAt === "function") ? mailAt(a) : (a.at || a.created || "");
          const bb = (typeof mailAt === "function") ? mailAt(b) : (b.at || b.created || "");
          return String(bb).localeCompare(String(aa));
        });
      });
      const srcs = Object.keys(bySrc).sort((a, b) => {
        const ta = (typeof mailAt === "function") ? mailAt(bySrc[a][0]) : ((bySrc[a][0] && bySrc[a][0].at) || "");
        const tb = (typeof mailAt === "function") ? mailAt(bySrc[b][0]) : ((bySrc[b][0] && bySrc[b][0].at) || "");
        return String(tb).localeCompare(String(ta));
      });
      const tree = srcs.map(src => {
        const kids = bySrc[src].map(m => {
          const agentRead = mailDstAgentRead(m);
          const humanOpen = mailDstHumanOpened(m);
          const unread = (typeof mailWallUnread === "function") ? mailWallUnread(m) : !agentRead;
          const hr = mailMsgHumanRequiredOpen(m);
          const snip = String(m.body || "").slice(0, 72);
          const cue = unread
            ? ' | <span class="unread-dot" title="agent-unread">unread</span>'
            : (hr ? "" : (humanOpen ? " | read" : ' | read <span class="human-cue" title="human not opened">|</span>'));
          const hrBit = hr ? ' | <span class="mail-chip needs-human mail-hr-chip" title="Needs human (receipt)">Needs human</span>' : "";
          const dstShow = mailDst(m);
          const atShow = (typeof mailAt === "function") ? mailAt(m) : (m.at || m.created || "");
          return `<li>` +
            `<span class="whom">${esc(dstShow)}</span>` +
            ` <span class="meta">${esc(dt(atShow))} | ${esc(m.kind || "note")}` +
            `${cue}${hrBit}</span>` +
            (snip ? `<div class="body-snip">${esc(snip)}</div>` : "") +
            `</li>`;
        }).join("");
        return `<li><span class="who">${esc(src)}</span> <span class="meta">-> ${bySrc[src].length}</span><ul>${kids}</ul></li>`;
      }).join("");
      return `<div class="mail-graph">` +
        `<p class="note">Coordination tree from mailbox src->dst (project-scoped). Not Wire mill events.</p>` +
        `<ul class="tree">${tree}</ul></div>`;
    }

    function mailTreesWithMail(d) {
      /* Client-side Rooms root SELECT: keep trees whose root is type=mail AND lft=1 (no GROUP BY).
       * Sort most-recent-first by latest mail activity in the name_id forest
       * (lean cast ``created`` / legacy ``at`` via mailAt; crumbs have no clock). */
      const trees = (d && Array.isArray(d.trees) ? d.trees : []);
      const mailbox = (d && Array.isArray(d.mailbox) ? d.mailbox : []);
      if (typeof mailRoomsSortedByLatest === "function") return mailRoomsSortedByLatest(trees, mailbox);
      let rooms = (typeof mailRoomsFromTrees === "function")
        ? mailRoomsFromTrees(trees)
        : trees.filter(function (t) {
            return !!(typeof mailTreeRoot === "function" ? mailTreeRoot((t && t.nodes) || []) : null);
          });
      const latestOf = (typeof mailRoomLatestAt === "function")
        ? function (t) { return mailRoomLatestAt(t, mailbox) || ""; }
        : function (t) {
            let latest = "";
            const nodes = (t && t.nodes) || [];
            const byId = {};
            mailbox.forEach(function (m) {
              if (m && m.id != null && m.id !== "") byId[String(m.id)] = m;
            });
            for (let i = 0; i < nodes.length; i++) {
              const n = nodes[i];
              if (!n || String(n.type || "").toLowerCase() !== "mail") continue;
              const m = byId[String(n.id)];
              if (!m) continue;
              const ts = (typeof mailAt === "function") ? mailAt(m) : String(m.at || m.created || "").trim();
              if (ts && ts > latest) latest = ts;
            }
            return latest;
          };
      return rooms.slice().sort(function (a, b) {
        const aa = latestOf(a);
        const bb = latestOf(b);
        if (aa !== bb) return bb < aa ? -1 : 1;
        /* tie-break higher max mail node id before label. */
        const ia = (typeof mailRoomMaxMailId === "function") ? mailRoomMaxMailId(a) : 0;
        const ib = (typeof mailRoomMaxMailId === "function") ? mailRoomMaxMailId(b) : 0;
        if (ia !== ib) return ib - ia;
        return 0;
      });
    }
    function mailRoomsTreesSig(trees) {
      /* Wave 3: left-rail skip key = tree structure only (name + type/id/lft/rgt).
       * Mailbox badge churn alone must not rebuild Rooms rail DOM. */
      return (Array.isArray(trees) ? trees : []).map(function (t) {
        const id = String((t && (t.name || t.id)) || "");
        const nodes = (t && Array.isArray(t.nodes) ? t.nodes : []);
        const bits = nodes.map(function (n) {
          return [n && n.type, n && n.id, n && n.lft, n && n.rgt].join(":");
        }).join(",");
        return id + "{" + bits + "}";
      }).join("|");
    }
    function mailRoomPlanId(t, ti) {
      /* Room identity is the plan name (t.name). */
      return String((t && (t.name || t.id)) || ("mail-room-" + ti));
    }
    function mailRoomTreeRoot(t) {
      /* Rooms root: type==='mail' AND lft===1 for THIS forest (mill_tree_create; no GROUP BY). */
      const nodes = (t && Array.isArray(t.nodes) ? t.nodes : []).filter(Boolean);
      if (!nodes.length) return null;
      if (typeof mailTreeRoot === "function") return mailTreeRoot(nodes);
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        if ((Number(n.lft) || 0) !== 1) continue;
        if (String((n && n.type) || "").toLowerCase() !== "mail") continue;
        return n;
      }
      return null;
    }
    function mailRoomMailNodes(t) {
      const nodes = (t && Array.isArray(t.nodes) ? t.nodes.slice() : []).sort(function (a, b) {
        return (Number(a && a.lft) || 0) - (Number(b && b.lft) || 0);
      });
      return nodes.filter(function (n) { return String((n && n.type) || "").toLowerCase() === "mail"; });
    }
    function mailRoomRootLabel(d, t) {
      const root = mailRoomTreeRoot(t);
      const plan = (typeof millTreePlanLabel === "function") ? millTreePlanLabel(t) : "";
      if (!root) return plan || "mail room";
      const p = millTreePayload(d, root);
      let title = String((p && p.title) || "").trim();
      if (!title || (typeof millTreeHexName === "function" && millTreeHexName(title))) {
        if (plan) return plan;
        const typ = String((root && root.type) || "").toLowerCase() || "mail";
        title = typ + " #" + String(root.id || "");
      }
      return title;
    }
    function mailRoomMailbox(d, node) {
      const id = node && node.id;
      return ((d && d.mailbox) || []).find(function (x) { return String(x.id) === String(id); }) || null;
    }
    function mailRoomCues(d, t) {
      let agentUnread = 0, humanRequired = 0, n = 0;
      mailRoomMailNodes(t).forEach(function (node) {
        n += 1;
        const m = mailRoomMailbox(d, node);
        if (m) {
          if (typeof mailMsgAgentUnread === "function" && mailMsgAgentUnread(m)) agentUnread += 1;
          if (typeof mailMsgHumanRequiredOpen === "function" && mailMsgHumanRequiredOpen(m)) humanRequired += 1;
        } else {
          const p = millTreePayload(d, node);
          if (p && p.unread) agentUnread += 1;
        }
      });
      return {
        n: n,
        agentUnread: agentUnread,
        humanRequired: humanRequired,
        needsAttention: agentUnread > 0 || humanRequired > 0
      };
    }
    function mailRoomMatchesQ(d, t, q) {
      if (!q) return true;
      const needle = String(q || "").toLowerCase();
      if (mailRoomRootLabel(d, t).toLowerCase().indexOf(needle) >= 0) return true;
      /* Identity is the plan name. */
      const nameId = String((t && t.name) || "").toLowerCase();
      if (nameId && nameId.indexOf(needle) >= 0) return true;
      const nodes = mailRoomMailNodes(t);
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const p = millTreePayload(d, n);
        const m = mailRoomMailbox(d, n);
        const hay = [
          p && p.title, p && p.who, p && p.type,
          m && m.body, m && m.subject,
          m && ((typeof mailSenderDesk === "function") ? mailSenderDesk(m) : m.src),
          m && mailDst(m), m && m.kind,
          m && ((typeof mailRoomCast === "function") ? mailRoomCast(m).map(function (c) { return c.deskId; }).join(" ") : ""),
          n && n.title, n && n.body, n && n.who
        ].map(function (x) { return String(x || "").toLowerCase(); }).join(" ");
        if (hay.indexOf(needle) >= 0) return true;
      }
      return false;
    }
    function mailRoomsNestVisible(d, allNodes, mailNodes, q) {
      const keep = {};
      if (!q) {
        mailNodes.forEach(function (_, i) { keep[i] = 1; });
        return keep;
      }
      const needle = String(q || "").toLowerCase();
      mailNodes.forEach(function (n, i) {
        const p = millTreePayload(d, n);
        const m = mailRoomMailbox(d, n);
        const hay = [
          p && p.title, p && p.who, p && p.type,
          m && m.body, m && m.subject,
          m && ((typeof mailSenderDesk === "function") ? mailSenderDesk(m) : m.src),
          m && mailDst(m),
          m && ((typeof mailRoomCast === "function") ? mailRoomCast(m).map(function (c) { return c.deskId; }).join(" ") : "")
        ].map(function (x) { return String(x || "").toLowerCase(); }).join(" ");
        if (hay.indexOf(needle) < 0) return;
        keep[i] = 2;
        millOutlineAncestors(allNodes, n).forEach(function (a) {
          if (String((a && a.type) || "").toLowerCase() !== "mail") return;
          const j = mailNodes.indexOf(a);
          if (j >= 0 && !keep[j]) keep[j] = 1;
        });
      });
      return keep;
    }
    function mailRoomsColHtml(rooms, selected) {
      const qVal = String(mailRoomsQ || "");
      const head = `<div class="rail-h">Rooms</div>` +
        `<input type="search" class="mail-rooms-q" id="mail-rooms-q" placeholder="title / body / src / dst" autocomplete="off" spellcheck="false" value="${esc(qVal)}" title="Filter rooms by title, body, src, or dst. Nest keeps ancestor spine.">`;
      if (!rooms.length) {
        return head + `<div class="col-empty">${qVal ? "no rooms match" : "no mail-tree rooms"}</div>`;
      }
      const rows = rooms.map(function (r) {
        const on = selected === r.id ? " on" : "";
        const unreadCls = r.needsAttention ? " is-unread" : "";
        const n = r.agentUnread | 0;
        const badge = `<span class="desk-badge" data-n="${n}" title="${n} agent-unread">${n > 99 ? "99+" : n}</span>`;
        const hr = r.humanRequired > 0 ? `<span class="hr-cue" title="open human_required">HR</span>` : "";
        const castN = r.castN | 0;
        const castBit = castN ? (" / cast " + castN) : "";
        /* short recency hint when latestAt is a real clock (not id-fallback). */
        let whenBit = "";
        const lat = String(r.latestAt || "").trim();
        if (lat && !/^\d{16}$/.test(lat)) {
          const m = lat.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
          whenBit = m ? (" | " + m[1] + " " + m[2]) : (lat.length > 16 ? (" | " + lat.slice(0, 16)) : (" | " + lat));
        }
        const frac = (r.partyN | 0) >= 0 ? ("-/-/" + (r.partyN | 0)) : "";
        const meta = `${frac ? frac + " " : ""}${r.n} letter${r.n === 1 ? "" : "s"}${whenBit}`;
        const tip = r.castTip ? `${r.label} | ${r.castTip}` : r.label;
        return `<button type="button" class="mail-rooms-row${on}${unreadCls}" data-mail-room="${esc(r.id)}" title="${esc(tip)}">` +
          `<span class="room-ttl">${esc(r.label)}</span>${hr}${badge}` +
          `<span class="room-meta">${esc(meta)}</span></button>`;
      }).join("");
      return head + rows;
    }
    function mailRoomsNestSig(d, t, q, roomId) {
      const allNodes = (t && Array.isArray(t.nodes) ? t.nodes : []).slice();
      const mailNodes = allNodes.filter(function (n) {
        return String((n && n.type) || "").toLowerCase() === "mail";
      });
      const bits = mailNodes.map(function (n) {
        const p = millTreePayload(d, n);
        const m = mailRoomMailbox(d, n);
        const unread = !!(p && p.unread) || (m && typeof mailWallUnread === "function" && mailWallUnread(m));
        const hr = m && typeof mailMsgHumanRequiredOpen === "function" && mailMsgHumanRequiredOpen(m);
        const castN = (m && typeof mailCastCount === "function") ? mailCastCount(m) : 0;
        const body = String((m && (m.body || m.subject)) || (p && p.title) || "").trim();
        const who = (m && typeof mailSenderDesk === "function") ? mailSenderDesk(m) : (p && p.who) || "";
        return [n.id, n.lft, n.rgt, body, unread ? 1 : 0, hr ? 1 : 0, castN, who].join("\t");
      });
      return String(roomId || "") + "|" + String(q || "") + "|" + bits.join("||");
    }
    function mailRoomsNestHtml(d, t, q) {
      /* Nest under the first letter (type mail, lft 1). Indent counts mail cards only. */
      const allNodes = (t && Array.isArray(t.nodes) ? t.nodes.slice() : []).sort(function (a, b) {
        return (Number(a && a.lft) || 0) - (Number(b && b.lft) || 0);
      });
      const mailNodes = allNodes.filter(function (n) {
        return String((n && n.type) || "").toLowerCase() === "mail";
      });
      if (!mailNodes.length) {
        return `<div class="col-empty">no mail in this room</div>`;
      }
      const visible = mailRoomsNestVisible(d, allNodes, mailNodes, q);
      const rows = mailNodes.map(function (n, i) {
        if (q && !visible[i]) return "";
        const lft = Number(n && n.lft) || 0;
        const rgt = Number(n && n.rgt) || 0;
        let depth = 0;
        mailNodes.forEach(function (o) {
          if (!o || o === n) return;
          if ((Number(o.lft) || 0) < lft && (Number(o.rgt) || 0) > rgt) depth += 1;
        });
        const p = millTreePayload(d, n);
        const m = mailRoomMailbox(d, n);
        const unread = !!(p && p.unread) || (m && typeof mailWallUnread === "function" && mailWallUnread(m));
        const hr = m && typeof mailMsgHumanRequiredOpen === "function" && mailMsgHumanRequiredOpen(m);
        const cls = ["mail-room-msg"];
        if (unread) cls.push("is-unread");
        if (visible[i] === 2) cls.push("is-hit");
        if (visible[i] === 1) cls.push("is-spine");
        const whoDesk = (m && typeof mailSenderDesk === "function") ? mailSenderDesk(m) : (p.who || "");
        const who = whoDesk ? `<span class="who">${esc(millName("desk", whoDesk) || whoDesk)}</span>` : "";
        const castN = (m && typeof mailCastCount === "function") ? mailCastCount(m) : 0;
        const castTip = (m && typeof mailCastTip === "function") ? mailCastTip(m) : "";
        const cast = (m && typeof mailRoomCast === "function") ? mailRoomCast(m) : [];
        const castIds = cast.map(function (c) { return c.deskId; }).filter(Boolean);
        const dstLabel = castIds.length
          ? castIds.join(", ")
          : (m && mailDst(m) ? mailDst(m) : "");
        /* Cast count = 1 (sender) + len(mail_tos); tip lists sender + each mail_to. */
        const dst = castN
          ? `<span class="dst cast-n" title="${esc(castTip || ("cast " + castN))}">cast ${castN}</span>`
          : (dstLabel ? `<span class="dst" title="room cast = sender U mail_tos">cast ${esc(dstLabel)}</span>` : "");
        const unreadBit = unread ? `<span class="leaf-unread" title="attention">attention</span>` : "";
        const hrBit = hr ? ` <span class="mail-chip needs-human mail-hr-chip" title="Needs human (receipt)">Needs human</span>` : "";
        const body = String((m && (m.body || m.subject)) || (p && p.title) || "").trim();
        const bodyTrunc = (m && m.body_trunc === true) ? "1" : "0";
        return `<div class="${cls.join(" ")}" data-depth="${depth}" data-mail-id="${esc(String(n.id || ""))}" data-body-trunc="${bodyTrunc}">` +
          `<span class="st">mail</span>` +
          `<div class="ttl"><b>${esc(body)}</b>${unreadBit}${hrBit}${who}${dst}</div>` +
          `</div>`;
      }).filter(Boolean).join("");
      if (!rows) {
        return `<div class="col-empty">${q ? "no messages match filter" : "empty room"}</div>`;
      }
      return `<div class="mail-rooms-nest">${rows}</div>`;
    }
    function paintMailRooms(d, opts) {
      const railOnly = !!(opts && opts.railOnly);
      const structureOnly = !!(opts && opts.structureOnly);
      const el = document.getElementById("mail");
      const dstCol = document.getElementById("mail-dst-col") || document.getElementById("mail-desk-rail");
      const srcCol = document.getElementById("mail-src-col");
      const note = document.getElementById("mail-view-note");
      if (note) {
        note.textContent = "Rooms, thread, and party. told/pushed/total. A dash means that count is not on this glance. Pushed is still queued. Told has left the queue.";
      }
      document.querySelectorAll(".mail-mode-toggle, .mail-dest-class").forEach(function (g) {
        g.hidden = true;
      });
      if (!Array.isArray(d && d.trees)) {
        _mailRoomsRailSig = ""; _mailRoomsNestSig = "";
        if (dstCol) dstCol.innerHTML = `<div class="rail-h">Rooms</div>` + wallLoadingHtml("Loading rooms\u2026");
        if (el) wallShowLoading(el, "Loading nest\u2026");
        return;
      }
      const trees = mailConversationTrees(d);
      const q = String(mailRoomsQ || "").trim().toLowerCase();
      let rooms = trees.map(function (t, ti) {
        const id = mailRoomPlanId(t, ti);
        const cues = mailRoomCues(d, t);
        const root = mailRoomFirstLetter(t);
        const rootM = root ? mailRoomMailbox(d, root) : null;
        const castN = (rootM && typeof mailCastCount === "function") ? mailCastCount(rootM) : 0;
        const castTip = (rootM && typeof mailCastTip === "function") ? mailCastTip(rootM) : "";
        /* latestAt = mailbox created/at (mailAt); else max mail id padded. */
        const latestAt = (typeof mailRoomLatestAt === "function")
          ? (mailRoomLatestAt(t, (d && d.mailbox) || []) || "")
          : "";
        const maxMailId = (typeof mailRoomMaxMailId === "function")
          ? mailRoomMaxMailId(t)
          : 0;
        return {
          id: id,
          tree: t,
          label: mailRoomLetterLabel(d, t),
          n: cues.n,
          agentUnread: cues.agentUnread,
          humanRequired: cues.humanRequired,
          needsAttention: cues.needsAttention,
          castN: castN,
          castTip: castTip,
          partyN: (rootM && typeof mailTos === "function") ? mailTos(rootM).length : 0,
          latestAt: latestAt,
          maxMailId: maxMailId
        };
      });
      rooms = rooms.filter(function (r) { return (r.n | 0) > 1; });
      if (q) rooms = rooms.filter(function (r) { return mailRoomMatchesQ(d, r.tree, q); });
      /* Left pane most-recent-first. latestAt = mailbox created/at else max id;
       * tie-break higher maxMailId before label (hex rooms without mb still rise). */
      rooms.sort(function (a, b) {
        const aa = String(a.latestAt || "");
        const bb = String(b.latestAt || "");
        if (aa !== bb) return bb.localeCompare(aa);
        const ia = a.maxMailId | 0;
        const ib = b.maxMailId | 0;
        if (ia !== ib) return ib - ia;
        return String(a.label).localeCompare(String(b.label));
      });
      if (mailSelectedRoom && !rooms.some(function (r) { return r.id === mailSelectedRoom; })) {
        mailSelectedRoom = rooms.length ? rooms[0].id : "";
        try { localStorage.setItem(MAIL_ROOM_KEY, mailSelectedRoom); } catch (e0) {}
      }
      if (!mailSelectedRoom && rooms.length) {
        mailSelectedRoom = rooms[0].id;
        try { localStorage.setItem(MAIL_ROOM_KEY, mailSelectedRoom); } catch (e1) {}
      }
      /* Trees fingerprint + mode/q/selection - skip full left-rail innerHTML when unchanged. */
      /* mb0 = trees only (phase 1); mb1 = mailbox landed (phase 2 re-sort/badges/cast).
       * Wave 3 still skips rebuild on later badge-only churn (mb1 stays mb1). */
      const mailboxReady = Array.isArray(d && d.mailbox) ? "mb1" : "mb0";
      const railSig = [mailMode || "", q || "", mailSelectedRoom || "", mailRoomsTreesSig(trees), mailboxReady].join("|");
      if (dstCol) {
        const roomsChrome = !!(dstCol.querySelector("#mail-rooms-q") || dstCol.querySelector(".mail-rooms-row") || dstCol.querySelector(".col-empty"));
        if (railSig !== _mailRoomsRailSig || !roomsChrome) {
          const prevQ = document.getElementById("mail-rooms-q");
          const keepFocus = prevQ && document.activeElement === prevQ;
          const selStart = keepFocus ? prevQ.selectionStart : null;
          const selEnd = keepFocus ? prevQ.selectionEnd : null;
          dstCol.innerHTML = mailRoomsColHtml(rooms, mailSelectedRoom);
          if (typeof wallPerfFirst === "function") {
            wallPerfFirst("mail_rooms_rail");
            if (mailboxReady === "mb1") wallPerfFirst("mail_rooms_rail_mb");
          }
          _mailRoomsRailSig = railSig;
          if (!dstCol._roomsDeleg) {
            dstCol._roomsDeleg = true;
            dstCol.addEventListener("input", function (ev) {
              if (ev.target && ev.target.id === "mail-rooms-q") setMailRoomsQ(ev.target.value || "");
            });
            dstCol.addEventListener("click", function (ev) {
              const btn = ev.target.closest("button.mail-rooms-row");
              if (btn) setMailRoom(btn.dataset.mailRoom || "");
            });
          }
          const qEl = document.getElementById("mail-rooms-q");
          if (qEl && keepFocus) {
            qEl.focus();
            try {
              if (selStart != null) qEl.setSelectionRange(selStart, selEnd != null ? selEnd : selStart);
            } catch (eSel) {}
          }
        }
      }
      if (railOnly) {
        /* Left rail only; nest shows spinner until structure/mailbox phase. */
        const nestEl = document.getElementById("mail");
        if (nestEl && !wallHasRealContent(nestEl)) wallShowLoading(nestEl, "Loading nest\u2026");
        return;
      }
      if (structureOnly) {
        /* Nest structure from trees; badge that mailbox enrich is still inbound. */
        if (!rooms.length) {
          _mailRoomsNestSig = "";
          const nestEl = document.getElementById("mail");
          if (nestEl) {
            nestEl.innerHTML = !trees.length
              ? wallLoadingHtml("Loading rooms\u2026")
              : wallLoadingHtml("Loading mailbox\u2026");
          }
          return;
        }
        if (!mailSelectedRoom && rooms.length) {
          mailSelectedRoom = rooms[0].id;
          try { localStorage.setItem(MAIL_ROOM_KEY, mailSelectedRoom); } catch (eSel0) {}
        }
        const picked0 = rooms.find(function (r) { return r.id === mailSelectedRoom; }) || rooms[0];
        const nestEl = document.getElementById("mail");
        if (nestEl && picked0) {
          /* paint structure alone (no loading marker sibling that blanked on re-enter).
             Opaque pane overlay covers confirm; keep struct as last-good paint. */
          const struct = mailRoomsNestHtml(d, picked0.tree, q);
          nestEl.innerHTML = struct;
          try { wallShowPaneOverlay("pane-mail", "Loading mailbox\u2026"); } catch (eOvSt) {}
          if (typeof wallPerfFirst === "function") wallPerfFirst("mail_rooms_structure");
          _mailRoomsNestSig = "struct|" + (mailSelectedRoom || "");
        } else if (nestEl && !wallHasRealContent(nestEl)) {
          wallShowLoading(nestEl, "Loading nest\u2026");
        }
        return;
      }
      if (!rooms.length) {
        _mailRoomsNestSig = "";
        if (el) {
          el.innerHTML = !trees.length
            ? `<div class="idle">No conversations yet.</div>`
            : (q
              ? `<div class="col-empty">no rooms match filter</div>`
              : `<div class="idle">No conversations yet.</div>`);
        }
        try { paintMailPartyCol(d, null); } catch (eParty0) {}
        return;
      }
      if (!mailSelectedRoom) {
        _mailRoomsNestSig = "";
        if (el) el.innerHTML = `<div class="col-empty">pick a room</div>`;
        return;
      }
      const picked = rooms.find(function (r) { return r.id === mailSelectedRoom; });
      if (!picked) {
        _mailRoomsNestSig = "";
        if (el) el.innerHTML = `<div class="col-empty">pick a room</div>`;
        return;
      }
      if (el) {
        const nestSig = mailRoomsNestSig(d, picked.tree, q, mailSelectedRoom);
        const nestChrome = !!(el.querySelector(".mail-rooms-nest") || el.querySelector(".col-empty") || el.querySelector(".idle"));
        if (nestSig !== _mailRoomsNestSig || !nestChrome) {
          el.innerHTML = mailRoomsNestHtml(d, picked.tree, q);
          try { paintMailPartyCol(d, picked.tree); } catch (eParty) {}
          if (typeof wallPerfFirst === "function") wallPerfFirst("mail_rooms_body");
          _mailRoomsNestSig = nestSig;
        }
      }
    }

    function mailConversationTrees(d) {
      /* A room has at least two mail letters. The plan root may be another activity. */
      const trees = ((d && d.trees) || []).filter(function (t) {
        return mailRoomMailNodes(t).length > 1;
      });
      return trees.slice().sort(function (a, b) {
        return (mailRoomMaxMailId(b) | 0) - (mailRoomMaxMailId(a) | 0);
      });
    }
    function mailRoomFirstLetter(t) {
      const nodes = mailRoomMailNodes(t);
      return nodes.length ? nodes[0] : null;
    }
    function mailRoomLetterLabel(d, t) {
      const node = mailRoomFirstLetter(t);
      const m = node ? mailRoomMailbox(d, node) : null;
      const body = String((m && (m.body || m.subject)) || "").replace(/\s+/g, " ").trim();
      if (body) return body.slice(0, 72);
      const p = node && typeof millTreePayload === "function" ? millTreePayload(d, node) : null;
      const title = String((p && p.title) || "").trim();
      if (title) return title.slice(0, 72);
      return (node && node.id != null) ? ("letter " + node.id) : "conversation";
    }
    function mailPartyFraction(m) {
      let n = (m && typeof mailTos === "function") ? mailTos(m).length : 0;
      if (!n && m && Array.isArray(m.mail_tos)) n = m.mail_tos.length;
      return "-/-/" + n;
    }
    function paintMailPartyCol(d, tree) {
      const srcCol = document.getElementById("mail-src-col");
      if (!srcCol || mailView !== "rooms") return;
      if (!tree) {
        srcCol.innerHTML = `<div class="rail-h">Party</div><div class="col-empty">Pick a room.</div>`;
        return;
      }
      const root = mailRoomFirstLetter(tree);
      const m = root ? mailRoomMailbox(d, root) : null;
      const tos = (m && typeof mailTos === "function") ? mailTos(m) : [];
      const head = `<div class="rail-h">Party</div><div class="mail-party-frac" title="told/pushed/total. told and pushed wait on the queue.">${esc(mailPartyFraction(m))} told/pushed/total</div>`;
      if (!m) {
        srcCol.innerHTML = head + `<div class="col-empty">Party waits on the letter list.</div>`;
        return;
      }
      if (!tos.length) {
        srcCol.innerHTML = head + `<div class="col-empty">No one was addressed.</div>`;
        return;
      }
      srcCol.innerHTML = head + tos.map(function (t) {
        const id = String(t.deskId || "");
        const name = (typeof millName === "function" && millName("desk", id)) || id;
        return `<div class="mail-party-row"><span class="desk-id">${esc(name)}</span><span class="desk-kind">addressed</span></div>`;
      }).join("");
    }
    function mailLetterMs(m) {
      const raw = (typeof mailAt === "function") ? mailAt(m) : String((m && (m.at || m.created)) || "");
      if (!raw || typeof floorParseTs !== "function") return NaN;
      const t = floorParseTs(raw);
      return (typeof t === "number" && !isNaN(t)) ? t : NaN;
    }
    function paintMailLetters(d) {
      const el = document.getElementById("mail");
      const note = document.getElementById("mail-view-note");
      const browser = document.querySelector(".mail-browser, .mail-split");
      if (browser) browser.setAttribute("data-mail-view", "letters");
      if (note) note.textContent = "Every letter in this cut, newest first.";
      if (!el) return;
      if (!d || !Array.isArray(d.mailbox)) {
        wallShowLoading(el, "Loading letters\u2026");
        return;
      }
      if (!MAIL_LETTER_SPANS.some(function (s) { return s[0] === mailLetterSpan; })) mailLetterSpan = "all";
      const span = MAIL_LETTER_SPANS.find(function (s) { return s[0] === mailLetterSpan; }) || MAIL_LETTER_SPANS[4];
      const picks = `<div class="mail-desk-picks" role="group" aria-label="letter window">` +
        MAIL_LETTER_SPANS.map(function (s) {
          const on = s[0] === mailLetterSpan ? " on" : "";
          return `<button type="button" data-mail-letter-span="${s[0]}" class="${on.trim()}">${s[1]}</button>`;
        }).join("") + `</div>`;
      const now = Date.now();
      const windowMs = span[2];
      let rows = (d.mailbox || []).filter(function (m) { return m && m.id != null && m.id !== ""; });
      rows = rows.filter(function (m) {
        if (windowMs == null) return true;
        const t = mailLetterMs(m);
        if (isNaN(t)) return false;
        return t >= now - windowMs;
      });
      rows.sort(function (a, b) {
        const ta = mailLetterMs(a);
        const tb = mailLetterMs(b);
        const aOk = !isNaN(ta);
        const bOk = !isNaN(tb);
        if (aOk && bOk && tb !== ta) return tb - ta;
        if (aOk !== bOk) return aOk ? -1 : 1;
        return (Number(b.id) || 0) - (Number(a.id) || 0);
      });
      const lines = rows.map(function (m) {
        const when = (typeof mailAt === "function" && mailAt(m))
          ? String(mailAt(m))
          : String((m && (m.at || m.created)) || "");
        const clock = when ? when.slice(5, 16) : "";
        let src = (typeof mailSenderDesk === "function") ? String(mailSenderDesk(m) || "") : "";
        if (!src && m && m.sender && typeof m.sender === "object") src = String(m.sender.deskId || m.sender.desk || "");
        if (!src) src = String((m && (m.src || m.desk)) || "");
        const srcName = (src && typeof millName === "function" && millName("desk", src)) || src || "desk";
        const tos = (typeof mailTos === "function" && mailTos(m).length)
          ? mailTos(m)
          : ((m && Array.isArray(m.mail_tos)) ? m.mail_tos : []);
        const toNames = tos.map(function (t) {
          const id = String(t.deskId || "");
          return (typeof millName === "function" && millName("desk", id)) || id;
        }).filter(Boolean).join(", ");
        const body = String(m.body || m.subject || "").replace(/\s+/g, " ").trim().slice(0, 96);
        return `<div class="mail-letter"><span class="ln"><span class="meta">${esc(clock)}</span><span class="meta">${esc(srcName)}${toNames ? " \u2192 " + esc(toNames) : ""}</span><span class="meta">${esc(mailPartyFraction(m))}</span></span><span class="ln">${esc(body)}</span></div>`;
      }).join("");
      el.innerHTML = picks + (lines || `<div class="col-empty">${esc(span[3])}</div>`);
      el.querySelectorAll("[data-mail-letter-span]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          mailLetterSpan = String(btn.getAttribute("data-mail-letter-span") || "all");
          paintMailLetters(d);
        });
      });
    }
    function mail(d) {
      /* Rooms is the only other live view. list and graph stay off this glass. */
      if (mailView !== "rooms") {
        mailView = "letters";
        try { paintMailLetters(d || {}); } catch (eLetters) {}
        return;
      }
      const raw = d.mailbox || [];
      const rows = mailActiveRows(raw);
      const el = document.getElementById("mail");
      const dstCol = document.getElementById("mail-dst-col") || document.getElementById("mail-desk-rail");
      const srcCol = document.getElementById("mail-src-col");
      document.querySelectorAll(".mail-view-toggle button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailView === mailView);
      });
      document.querySelectorAll(".mail-mode-toggle button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailMode === mailMode);
      });
      document.querySelectorAll(".mail-dest-class button").forEach(b => {
        b.classList.toggle("on", b.dataset.mailClass === mailDestClassFilter);
      });
      document.querySelectorAll(".mail-mode-toggle, .mail-dest-class").forEach(function (g) {
        g.hidden = (mailView === "rooms");
      });
      const note = document.getElementById("mail-view-note");
      if (note) {
        if (raw.length !== rows.length) note.dataset.humanArchive = String(raw.length - rows.length);
        note.textContent = mailView === "rooms"
          ? "Rooms, thread, and party. told/pushed/total. A dash means that count is not on this glance. Pushed is still queued. Told has left the queue."
          : (mailView === "graph"
          ? (mailMode === "attention"
            ? "GRAPH 3-col: pick dst -> src -> messages (src->dst only). Needs attention dsts."
            : (mailMode === "recent"
              ? "GRAPH: recent - pick dst | src | messages."
              : "GRAPH: all dsts - pick src then messages."))
          : (mailMode === "attention"
            ? "LIST 2-col: selected dst messages recent-first. Wrap<->nowrap. No h-scroll."
            : (mailMode === "recent"
              ? "LIST: selected dst | recent. Wrap<->nowrap."
              : "LIST 2-col: selected dst messages. Wrap<->nowrap.")));
      }
      /* MAIL_ROOMS early: skip dst|src rails */
      if (mailView === "rooms") {
        const browserEarly = document.querySelector(".mail-browser, .mail-split");
        if (browserEarly) browserEarly.setAttribute("data-mail-view", "rooms");
        document.querySelectorAll(".mail-view-toggle button").forEach(b => {
          b.classList.toggle("on", b.dataset.mailView === "rooms");
        });
        paintMailRooms(d || {});
        return;
      }
      if (!mailSelectedDst && mailSelectedDesk) mailSelectedDst = mailSelectedDesk;
      const dstsAll = mailKnownDesks(d || {}, rows);
      const destKinds = new Set(dstsAll.map(x => x.kind));
      document.querySelectorAll(".mail-dest-class button").forEach(b => {
        const k = b.dataset.mailClass;
        if (k === "all") {
          b.hidden = !dstsAll.length;
          return;
        }
        b.hidden = !destKinds.has(k) && k !== mailDestClassFilter;
      });
      const dsts = mailDestClassFilter === "all"
        ? dstsAll
        : dstsAll.filter(x => x.kind === mailDestClassFilter);
      const attentionDsts = dsts.filter(x => x.needsAttention);
      /* Always paint three peer columns - empty states OK */
      if (mailMode === "attention") {
        if (attentionDsts.length && !attentionDsts.some(x => x.id === mailSelectedDst)) {
          mailSelectedDst = attentionDsts[0].id;
          mailSelectedDesk = mailSelectedDst;
          mailSelectedSrc = "";
          try {
            localStorage.setItem(MAIL_TO_KEY, mailSelectedDst);
            localStorage.setItem(MAIL_DESK_KEY, mailSelectedDesk);
            localStorage.setItem(MAIL_SRC_KEY, "");
          } catch (e) {}
        }
      } else if (!mailSelectedDst && dsts.length) {
        /* do not force-select in All - empty src/msg OK */
      }
      if (dstCol) {
        dstCol.innerHTML = mailDstColHtml(dsts, mailMode, mailSelectedDst);
        dstCol.querySelectorAll("button.desk-row").forEach(btn => {
          btn.addEventListener("click", () => setMailDst(btn.dataset.mailDst || btn.dataset.mailDesk));
        });
      }
      const browser = document.querySelector(".mail-browser, .mail-split");
      if (browser) browser.setAttribute("data-mail-view", mailView);

      /* MAIL_LIST_TO_FILTER: LIST = 2-col dst | messages for selected dst only */
      if (mailView === "list") {
        /* MAIL_LIST_AUTOSELECT_DST: if no dst + rail has entries, pick first viable (attention: first Needs-attention; else first rail dst). Persist like setMailDst. GRAPH: no auto-pick src. */
        /* MAIL_BOOT_FIX: Needs attention preferred; if none, fall back to all dsts so LIST is not blank */
        const listRail = (mailMode === "attention" && attentionDsts.length) ? attentionDsts : dsts;
        if (!mailSelectedDst && listRail.length) {
          mailSelectedDst = listRail[0].id;
          mailSelectedDesk = mailSelectedDst;
          try {
            localStorage.setItem(MAIL_TO_KEY, mailSelectedDst);
            localStorage.setItem(MAIL_DESK_KEY, mailSelectedDesk);
          } catch (e) {}
        }
        if (srcCol) srcCol.innerHTML = "";
        if (dstCol) {
          dstCol.innerHTML = mailDstColHtml(dsts, mailMode, mailSelectedDst);
          dstCol.querySelectorAll("button.desk-row").forEach(btn => {
            btn.addEventListener("click", () => setMailDst(btn.dataset.mailDst || btn.dataset.mailDesk));
          });
        }
        if (!mailSelectedDst) {
          el.innerHTML = (mailMode === "attention" && !attentionDsts.length)
            ? '<div class="mail-all-clear"><b>All clear.</b> No destinations need attention.</div>'
            : '<div class="col-empty">pick a dst</div>';
          return;
        }
        const listRows = mailRowsForListDst(rows, mailSelectedDst, mailMode);
        if (!listRows.length) {
          el.innerHTML = (mailMode === "attention")
            ? `<div class="col-empty">no attention mail for ${esc(mailSelectedDst)}</div>`
            : `<div class="col-empty">no mail for ${esc(mailSelectedDst)}</div>`;
          return;
        }
        el.innerHTML = mailListHtml(d, listRows);
        if (typeof wallPerfFirst === "function") wallPerfFirst("mailbox_body");
        enhanceTables(el);
        return;
      }

      /* GRAPH = 3-col dst|src|messages; col3 = selected src->dst only */
      const srcs = mailSelectedDst ? mailSrcsForDst(rows, mailSelectedDst) : [];
      /* MAIL_COL3_SRC_FILTER: never auto-pick src - col3 idle until user selects src */
      if (!mailSelectedDst) {
        mailSelectedSrc = "";
        try { localStorage.setItem(MAIL_SRC_KEY, ""); } catch (e) {}
      } else if (mailSelectedSrc && !srcs.some(x => x.id === mailSelectedSrc)) {
        mailSelectedSrc = "";
        try { localStorage.setItem(MAIL_SRC_KEY, ""); } catch (e) {}
      }
      if (srcCol) {
        srcCol.innerHTML = mailSrcColHtml(srcs, mailSelectedSrc, !!mailSelectedDst);
        srcCol.querySelectorAll("button.src-row").forEach(btn => {
          btn.addEventListener("click", () => setMailSrc(btn.dataset.mailSrc));
        });
      }
      if (!mailSelectedDst) {
        el.innerHTML = (mailMode === "attention" && !attentionDsts.length)
          ? '<div class="mail-all-clear"><b>All clear.</b> No destinations need attention.</div>'
          : '<div class="col-empty">pick a dst</div>';
        return;
      }
      if (!mailSelectedSrc) {
        el.innerHTML = '<div class="col-empty">pick a src</div>';
        return;
      }
      const deskRows = mailRowsForDstSrc(rows, mailSelectedDst, mailSelectedSrc, mailMode);
      if (!deskRows.length) {
        el.innerHTML = `<div class="col-empty">no mail from ${esc(mailSelectedSrc)} -> ${esc(mailSelectedDst)}</div>`;
        return;
      }
      el.innerHTML = mailListHtml(d, deskRows);
      if (typeof wallPerfFirst === "function") wallPerfFirst("mailbox_body");
      enhanceTables(el);
    }

    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function wallProjectName() {
      const picked = (currentFilter().projects || []).filter(Boolean);
      if (picked.length) return String(picked[0]).trim();
      const floor = window._floor || {};
      const fromFloor = (floor.wall && floor.wall[0]) || ((floor.groups || floor.projects) && (floor.groups || floor.projects)[0]) || "";
      return String(fromFloor || "").trim();
    }
    function wallRoleNames() {
      return Array.from(document.querySelectorAll("#rail-roster .rail-row"))
        .map(el => String(el.getAttribute("data-id") || "").trim())
        .filter(Boolean);
    }
    function wallFindMailRow(id) {
      const box = (window._floor && window._floor.mailbox) || [];
      const want = String(id);
      for (let i = 0; i < box.length; i++) {
        if (String(box[i] && box[i].id) === want) return box[i];
      }
      return null;
    }
    function wallMergeMailDetail(full) {
      if (!full || full.id == null) return false;
      const d = window._floor;
      if (!d) return false;
      if (!Array.isArray(d.mailbox)) d.mailbox = [];
      const want = String(full.id);
      const next = Object.assign({}, full);
      delete next.body_trunc;
      let i = -1;
      for (let k = 0; k < d.mailbox.length; k++) {
        if (String(d.mailbox[k] && d.mailbox[k].id) === want) { i = k; break; }
      }
      if (i < 0) {
        d.mailbox.push(next);
      } else {
        d.mailbox[i] = Object.assign({}, d.mailbox[i], next);
        delete d.mailbox[i].body_trunc;
      }
      return true;
    }
    async function wallOpenMailIfTrunc(id) {
      const mid = String(id || "").trim();
      if (!mid) return false;
      const row = wallFindMailRow(mid);
      if (!wallMailIsTrunc(row)) return false;
      const key = "mail:" + mid;
      if (_wallLeanDetailInflight[key]) return _wallLeanDetailInflight[key];
      const p = (async function () {
        try {
          const r = await fetch("/api/v1/mail/" + encodeURIComponent(mid), { cache: "no-store" });
          if (!r.ok) return false;
          const json = await r.json();
          const full = json && json.mail;
          if (!full) return false;
          if (!wallMergeMailDetail(full)) return false;
          try { mail(window._floor); } catch (ePaint) {}
          return true;
        } catch (eFetch) {
          return false;
        } finally {
          delete _wallLeanDetailInflight[key];
        }
      })();
      _wallLeanDetailInflight[key] = p;
      return p;
    }

var WALL_UI_DEFAULT_MAIL_PAINT = "WALL_UI_DEFAULT_MAIL_PAINT";
