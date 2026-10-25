/* WALL_UI_DEFAULT_MAIL - thin pure-rule module for default pack (fungible cut 5).
 * Path A extract from board.html mail helpers. Packs may override this file.
 * SoR Python: agent_coord.web.wall_logic.mail (WALL_LOGIC_MAIL_SOR).
 * Lean adapters (Loop-3): sender + mail_tos + receipt; no opened on cast.
 * Marker: WALL_UI_DEFAULT_MAIL
 */
(function (global) {
  "use strict";

  var BARE_HUMAN_MAILBOX = { "setter-upper": 1, human: 1, "dead-letter": 1 };

  function mailNameType(value) {
    if (!value || typeof value !== "object") return "";
    var kind = String(value.type || "").trim().toLowerCase();
    if (kind === "proj") return "project";
    if (kind === "file" || kind === "resource") return "res";
    if (kind) return kind;
    if (value.deskId && typeof value.deskId === "object") return mailNameType(value.deskId);
    if (value.desk && typeof value.desk === "object") return mailNameType(value.desk);
    return "";
  }
  function mailNameText(value) {
    if (value && typeof value === "object") {
      if (value.name != null && value.name !== "") return String(value.name).trim();
      if (value.str != null && value.str !== "") return String(value.str).trim();
      if (value.deskId != null && value.deskId !== "") return mailNameText(value.deskId);
      if (value.desk != null && value.desk !== "") return mailNameText(value.desk);
      return "";
    }
    return String(value || "").trim();
  }
  function mailSameName(a, b) {
    var left = mailNameText(a);
    var right = mailNameText(b);
    if (!left || left !== right) return false;
    var leftType = mailNameType(a);
    var rightType = mailNameType(b);
    if (leftType && rightType && leftType !== rightType) return false;
    return true;
  }
  function mailIsLean(m) {
    return !!(m && (("mail_tos" in m) || (m.sender && typeof m.sender === "object")));
  }
  function mailSenderDesk(m) {
    if (!m) return "";
    var sender = m.sender;
    if (sender && typeof sender === "object") {
      if (sender.deskId != null && sender.deskId !== "") return mailNameText(sender.deskId);
      if (sender.desk != null && sender.desk !== "") return mailNameText(sender.desk);
      return mailNameText(sender);
    }
    if (sender != null && sender !== "") return mailNameText(sender);
    return mailNameText(m.src || m.desk || "");
  }
  function mailTos(m) {
    if (!m) return [];
    var raw = m.mail_tos;
    if (Array.isArray(raw) && raw.length) {
      return raw.filter(function (t) { return t && typeof t === "object"; }).map(function (t) {
        var desk = mailNameText((t.deskId != null && t.deskId !== "") ? t.deskId : t.desk);
        return {
          deskId: desk,
          roster: (t.roster == null || t.roster === "") ? null : t.roster,
          receipt: (t.receipt | 0)
        };
      }).filter(function (t) { return !!t.deskId; });
    }
    var rawDst = m.dst;
    if (typeof rawDst === "string" && rawDst.indexOf(",") >= 0) {
      return rawDst.split(",").map(function (part) {
        var d = String(part || "").trim();
        return d ? { deskId: d, roster: null, receipt: 0 } : null;
      }).filter(Boolean);
    }
    var dst = mailNameText(rawDst);
    if (!dst || dst === "*") return [];
    return [{ deskId: dst, roster: null, receipt: 0 }];
  }
  function mailTreeRoot(nodes) {
    /* Rooms root lock: WHERE type='mail' AND lft=1 (no GROUP BY).
     * Root per forest is lft=1 (mill_tree_create). One name_id forest.
     * Depth-0 helper (mailTreeDepth0) is crumbs-only inside one name_id. */
    var rows = (nodes || []).filter(function (n) { return !!n; });
    for (var i = 0; i < rows.length; i++) {
      var n = rows[i];
      if ((Number(n.lft) || 0) !== 1) continue;
      if (String(n.type || "").toLowerCase() !== "mail") continue;
      return n;
    }
    return null;
  }
  function mailRoomsFromTrees(trees) {
    /* Client-side Rooms root SELECT: keep trees whose root is type=mail AND lft=1. */
    return (trees || []).filter(function (t) {
      return !!mailTreeRoot((t && t.nodes) || []);
    });
  }
  function mailRoomMaxMailId(tree) {
    /* Max numeric mail node id in the forest (activity proxy when mailbox thin). */
    var nodes = (tree && tree.nodes) || [];
    var max = 0;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n || String(n.type || "").toLowerCase() !== "mail") continue;
      if (n.id == null || n.id === "") continue;
      var num = Number(n.id);
      if (!isFinite(num) || num < 0) continue;
      if (num > max) max = num;
    }
    return max;
  }
  function mailRoomLatestAt(tree, mailbox) {
    /* Latest activity in one name_id forest (newest mail at/under the tree).
     * Timestamp: lean MAIL cast ``created``; legacy ``at`` (via mailAt). Crumbs have no clock.
     * when mailbox thin/empty (mb0), fall back to max mail node id as
     * zero-padded 16-digit string so localeCompare still orders by recency. */
    var nodes = (tree && tree.nodes) || [];
    var byId = {};
    (mailbox || []).forEach(function (m) {
      if (m && m.id != null && m.id !== "") byId[String(m.id)] = m;
    });
    var latest = "";
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n || String(n.type || "").toLowerCase() !== "mail") continue;
      if (n.id == null || n.id === "") continue;
      var m = byId[String(n.id)];
      if (!m) continue;
      var ts = mailAt(m);
      if (ts && ts > latest) latest = ts;
    }
    if (latest) return latest;
    var maxId = mailRoomMaxMailId(tree);
    if (maxId > 0) {
      var s = String(Math.floor(maxId));
      while (s.length < 16) s = "0" + s;
      return s;
    }
    return "";
  }
  function mailRoomsSortedByLatest(trees, mailbox) {
    /* MAIL rooms sorted most-recent-first by mailRoomLatestAt (created/at / id).
     * tie-break higher max mail node id before label. */
    return mailRoomsFromTrees(trees).slice().sort(function (a, b) {
      var aa = mailRoomLatestAt(a, mailbox) || "";
      var bb = mailRoomLatestAt(b, mailbox) || "";
      if (aa !== bb) return bb < aa ? -1 : 1;
      var ia = mailRoomMaxMailId(a);
      var ib = mailRoomMaxMailId(b);
      if (ia !== ib) return ib - ia;
      return 0;
    });
  }
  function mailTreeDepth0(nodes) {
    /* Crumbs-only inside one name_id: packed depth===0 or no strict ancestor. */
    var rows = (nodes || []).filter(function (n) { return !!n; });
    if (!rows.length) return null;
    var i, j, n, o, lft, rgt, d, depth0 = [], roots = [];
    for (i = 0; i < rows.length; i++) {
      d = rows[i].depth;
      if (d === 0 || d === "0") depth0.push(rows[i]);
    }
    if (depth0.length) {
      depth0.sort(function (a, b) { return (Number(a.lft) || 0) - (Number(b.lft) || 0); });
      return depth0[0];
    }
    for (i = 0; i < rows.length; i++) {
      n = rows[i];
      lft = Number(n.lft) || 0;
      rgt = Number(n.rgt) || 0;
      var hasAnc = false;
      for (j = 0; j < rows.length; j++) {
        if (j === i) continue;
        o = rows[j];
        if ((Number(o.lft) || 0) < lft && (Number(o.rgt) || 0) > rgt) { hasAnc = true; break; }
      }
      if (!hasAnc) roots.push(n);
    }
    if (!roots.length) roots = rows.slice();
    roots.sort(function (a, b) { return (Number(a.lft) || 0) - (Number(b.lft) || 0); });
    return roots[0] || null;
  }
  function mailRoomCast(m) {
    var out = [];
    var seen = {};
    var src = mailSenderDesk(m);
    if (src) {
      var aff = null;
      if (m && m.sender && typeof m.sender === "object") aff = m.sender.roster || null;
      seen[src] = 1;
      out.push({ deskId: src, roster: aff });
    }
    mailTos(m).forEach(function (t) {
      var d = String(t.deskId || "").trim();
      if (!d || seen[d]) return;
      seen[d] = 1;
      out.push({ deskId: d, roster: t.roster || null });
    });
    return out;
  }
  function mailLeanTosLen(m) {
    /* Lean mail_tos length only; do not invent from legacy dst. */
    if (!m || !Array.isArray(m.mail_tos)) return 0;
    return m.mail_tos.length;
  }
  function mailCastCount(m) {
    /* Cast size = 1 (sender) + len(mail_tos). Lean only. */
    if (!mailIsLean(m)) return 0;
    return 1 + mailLeanTosLen(m);
  }
  function mailCastTip(m) {
    /* Hover: sender + each mail_to desk/roster. */
    if (!m) return "";
    var parts = [];
    var desk = mailSenderDesk(m);
    var aff = null;
    if (m.sender && typeof m.sender === "object") {
      aff = (m.sender.roster == null || m.sender.roster === "") ? null : m.sender.roster;
    }
    if (desk) parts.push(aff ? ("from " + desk + " (" + aff + ")") : ("from " + desk));
    var raw = Array.isArray(m.mail_tos) ? m.mail_tos : [];
    for (var i = 0; i < raw.length; i++) {
      var t = raw[i];
      if (!t || typeof t !== "object") continue;
      var d = mailNameText((t.deskId != null && t.deskId !== "") ? t.deskId : t.desk);
      if (!d) continue;
      var a = (t.roster == null || t.roster === "") ? null : t.roster;
      parts.push(a ? ("to " + d + " (" + a + ")") : ("to " + d));
    }
    return parts.join("; ");
  }
  function mailDstDesks(m) {
    var tos = mailTos(m);
    if (tos.length) return tos.map(function (t) { return String(t.deskId); });
    var dst = mailNameText(m && m.dst);
    if (!dst || dst === "*") return dst === "*" ? ["*"] : [];
    return [dst];
  }
  function mailAt(m) {
    if (!m) return "";
    return String(m.at || m.created || "").trim();
  }
  function mailDst(m) {
    if (!m) return "";
    var raw = mailNameText(m.dst);
    if (raw) return raw;
    var tos = mailTos(m);
    if (!tos.length) return "";
    return String(tos[0].deskId || "").trim();
  }
  function mailIsFloor(m) {
    var dst = mailDst(m);
    if (mailIsLean(m) && !mailTos(m).length && !mailNameText(m && m.dst)) return true;
    return !dst || dst === "*";
  }
  function mailDestClass(dst, projectId) {
    var raw = mailNameText(dst);
    var key = mailDstKey(dst);
    if (!key || key === "*") return "star";
    /* 0.7.0: one roster kind. A roster is the picked roster or any row in the rail Roster list. */
    var proj = String(projectId || "").trim();
    if (proj && (key === proj || raw === proj)) return "roster";
    var rows = (typeof document !== "undefined") ? document.querySelectorAll("#rail-roster .rail-row") : [];
    for (var i = 0; i < rows.length; i++) {
      if (String(rows[i].getAttribute("data-id") || "").trim() === key) return "roster";
    }
    return "desk";
  }
  function mailDstKey(dst) {
    return mailNameText(dst);
  }
  function mailBareDst(dst) {
    return mailNameText(dst).toLowerCase();
  }
  function mailIsBareHumanMailbox(dst) {
    var d = mailBareDst(dst);
    return !d || !!BARE_HUMAN_MAILBOX[d];
  }
  function mailActiveRows(rows) {
    return (rows || []).filter(function (m) { return !mailIsBareHumanMailbox(mailDst(m)); });
  }
  function mailReadMatchesDst(r, dst) {
    var reader = mailNameText(r && (r.desk != null && r.desk !== "" ? r.desk : r.reader));
    if (!reader) return false;
    return reader === mailNameText(dst);
  }
  function mailDstAgentRead(m) {
    if (mailIsFloor(m)) return false;
    if (m && m.read_agent === true) return true;
    var dst = mailDst(m);
    var reads = (m && m.reads) || [];
    if (reads.length) {
      return reads.some(function (r) {
        return mailReadMatchesDst(r, dst) && String((r && r.party) || "").toLowerCase() === "agent";
      });
    }
    var key = mailDstKey(dst);
    return ((m && m.readers) || []).some(function (r) {
      var s = String(r || "").trim();
      return s === key + ":agent" || s.indexOf(key + ":agent:") === 0
        || s === dst + ":agent" || s.indexOf(String(dst) + ":agent:") === 0;
    });
  }
  function mailDstHumanOpened(m) {
    /* Soft cue only when reads/readers present. Lean cast has no opened. */
    if (mailIsFloor(m)) return false;
    var dst = mailDst(m);
    var reads = (m && m.reads) || [];
    if (reads.length) {
      return reads.some(function (r) {
        return mailReadMatchesDst(r, dst) && String((r && r.party) || "").toLowerCase() === "human";
      });
    }
    var key = mailDstKey(dst);
    return ((m && m.readers) || []).some(function (r) {
      var s = String(r || "").trim();
      return s === key + ":human" || s === dst + ":human";
    });
  }
  function mailDstRead(m) {
    return mailDstAgentRead(m);
  }
  function mailStarAnyAgentRead(m) {
    if (!m || mailDst(m) !== "*") return false;
    if (m.read_star_any_agent === true) return true;
    var reads = m.reads || [];
    if (reads.length) {
      return reads.some(function (r) {
        return String((r && r.party) || "").toLowerCase() === "agent";
      });
    }
    return (m.readers || []).some(function (r) {
      return String(r || "").indexOf(":agent") >= 0;
    });
  }
  function mailStarWallUnread(m) {
    return !!(m && mailDst(m) === "*" && !mailStarAnyAgentRead(m));
  }
  function mailWallUnread(m) {
    if (!m) return false;
    if (mailDst(m) === "*") return mailStarWallUnread(m);
    return mailMsgAgentUnread(m);
  }
  function mailMsgHumanRequiredOpen(m) {
    if (!m) return false;
    if (m.human_required_cleared || m.human_acked || m.human_required_done) return false;
    var st = String(m.human_required_status || "").toLowerCase();
    if (st === "cleared" || st === "acked" || st === "done") return false;
    if (!!(m.human_required || m.needs_human)) return true;
    return mailTos(m).some(function (t) { return (t.receipt | 0) === 1; });
  }
  function mailMsgAgentUnread(m) {
    if (!m || mailIsFloor(m)) return false;
    if (mailDst(m) === "*") return mailStarWallUnread(m);
    /* Lean: no opened on cast - do not invent unread. HR via receipt; rails via floor.desk_unread. */
    if (mailIsLean(m) && m.read_agent !== true && !(m.reads && m.reads.length) && !(m.readers && m.readers.length)) {
      return false;
    }
    return !mailDstAgentRead(m);
  }
  function mailMsgNeedsAttention(m) {
    return mailMsgAgentUnread(m) || mailMsgHumanRequiredOpen(m);
  }
  function mailDeskMatches(m, desk) {
    var want = mailNameText(desk);
    if (!want) return false;
    var desks = mailDstDesks(m);
    if (want === "*") return desks.indexOf("*") >= 0 || mailDst(m) === "*";
    var sawType = false;
    var rawTos = (m && Array.isArray(m.mail_tos)) ? m.mail_tos : [];
    for (var i = 0; i < rawTos.length; i++) {
      var t = rawTos[i];
      if (!t || typeof t !== "object") continue;
      var ident = (t.deskId != null && t.deskId !== "") ? t.deskId : t.desk;
      if (mailNameType(ident)) sawType = true;
      if (mailSameName(ident, desk)) return true;
    }
    if (m && m.dst != null && m.dst !== "") {
      if (mailNameType(m.dst)) sawType = true;
      if (mailSameName(m.dst, desk)) return true;
    }
    if (sawType) return false;
    for (var j = 0; j < desks.length; j++) {
      if (mailSameName(desks[j], desk)) return true;
    }
    return false;
  }
  function mailRowsAllRecent(rows, mode) {
    var out = (rows || []).slice();
    if (mode === "attention") out = out.filter(mailMsgNeedsAttention);
    out.sort(function (a, b) { return String(mailAt(b)).localeCompare(String(mailAt(a))); });
    if (mode === "recent") out = out.slice(0, 80);
    return out;
  }
  function mailRowsForListDst(rows, dst, mode) {
    var want = String(dst || "").trim();
    if (!want) return [];
    var scoped = (rows || []).filter(function (m) { return mailDeskMatches(m, want); });
    return mailRowsAllRecent(scoped, mode || "attention");
  }
  function mailRowsForDstSrc(rows, dst, src, mode) {
    var want = String(dst || "").trim();
    if (!want) return [];
    var out = (rows || []).filter(function (m) { return mailDeskMatches(m, want); });
    var wantSrc = String(src || "").trim();
    if (wantSrc) out = out.filter(function (m) { return mailSenderDesk(m) === wantSrc; });
    mode = mode || "attention";
    if (mode === "recent") {
      return out.sort(function (a, b) { return String(mailAt(b)).localeCompare(String(mailAt(a))); }).slice(0, 80);
    }
    return out.sort(function (a, b) {
      var au = mailMsgAgentUnread(a) ? 1 : 0, bu = mailMsgAgentUnread(b) ? 1 : 0;
      if (au !== bu) return bu - au;
      var ah = mailMsgHumanRequiredOpen(a) ? 1 : 0, bh = mailMsgHumanRequiredOpen(b) ? 1 : 0;
      if (ah !== bh) return bh - ah;
      return String(mailAt(b)).localeCompare(String(mailAt(a)));
    });
  }
  function mailRowsForDesk(rows, desk, mode) {
    return mailRowsForDstSrc(rows, desk, "", mode);
  }
  function mailSrcsForDst(rows, dst) {
    var want = String(dst || "").trim();
    if (!want) return [];
    var by = {};
    (rows || []).forEach(function (m) {
      /* Floor (no dest) never has senders for a dst. Star dst=* is a real dest on cast
       * but mailIsFloor treats legacy dst="*" as floor - still allow srcs when want is *. */
      if (!mailDeskMatches(m, want)) return;
      if (mailIsFloor(m) && want !== "*") return;
      var src = mailSenderDesk(m);
      if (!src) return;
      var prev = by[src] || { id: src, agentUnread: 0, humanRequired: 0, n: 0 };
      prev.n += 1;
      if (mailMsgAgentUnread(m)) prev.agentUnread += 1;
      if (mailMsgHumanRequiredOpen(m)) prev.humanRequired += 1;
      by[src] = prev;
    });
    return Object.keys(by).map(function (k) { return by[k]; }).sort(function (a, b) {
      if (a.agentUnread !== b.agentUnread) return b.agentUnread - a.agentUnread;
      if (a.humanRequired !== b.humanRequired) return b.humanRequired - a.humanRequired;
      return String(a.id).localeCompare(String(b.id));
    });
  }
  function mailAttentionDsts(dsts) {
    return (dsts || []).filter(function (x) { return x && x.needsAttention; });
  }
  function mailResolveListDst(dsts, opts) {
    opts = opts || {};
    var sel = String(opts.selected || "").trim();
    var view = opts.view || "list";
    var mode = opts.mode || "attention";
    if (view !== "list") return sel;
    var rail = dsts || [];
    var attention = mailAttentionDsts(rail);
    if (mode === "attention" && attention.length) {
      if (sel && attention.some(function (x) { return String(x.id || "").trim() === sel; })) return sel;
      return String(attention[0].id || "").trim();
    }
    if (sel) return sel;
    if (!rail.length) return "";
    return String(rail[0].id || "").trim();
  }

  var api = {
    mailIsLean: mailIsLean,
    mailSenderDesk: mailSenderDesk,
    mailTos: mailTos,
    mailTreeRoot: mailTreeRoot,
    mailRoomsFromTrees: mailRoomsFromTrees,
    mailRoomMaxMailId: mailRoomMaxMailId,
    mailRoomLatestAt: mailRoomLatestAt,
    mailRoomsSortedByLatest: mailRoomsSortedByLatest,
    mailTreeDepth0: mailTreeDepth0,
    mailRoomCast: mailRoomCast,
    mailLeanTosLen: mailLeanTosLen,
    mailCastCount: mailCastCount,
    mailCastTip: mailCastTip,
    mailDstDesks: mailDstDesks,
    mailAt: mailAt,
    mailDst: mailDst,
    mailIsFloor: mailIsFloor,
    mailDestClass: mailDestClass,
    mailDstKey: mailDstKey,
    mailBareDst: mailBareDst,
    mailIsBareHumanMailbox: mailIsBareHumanMailbox,
    mailActiveRows: mailActiveRows,
    mailReadMatchesDst: mailReadMatchesDst,
    mailDstAgentRead: mailDstAgentRead,
    mailDstHumanOpened: mailDstHumanOpened,
    mailDstRead: mailDstRead,
    mailStarAnyAgentRead: mailStarAnyAgentRead,
    mailStarWallUnread: mailStarWallUnread,
    mailWallUnread: mailWallUnread,
    mailMsgHumanRequiredOpen: mailMsgHumanRequiredOpen,
    mailMsgAgentUnread: mailMsgAgentUnread,
    mailMsgNeedsAttention: mailMsgNeedsAttention,
    mailDeskMatches: mailDeskMatches,
    mailRowsAllRecent: mailRowsAllRecent,
    mailRowsForListDst: mailRowsForListDst,
    mailRowsForDstSrc: mailRowsForDstSrc,
    mailRowsForDesk: mailRowsForDesk,
    mailSrcsForDst: mailSrcsForDst,
    mailAttentionDsts: mailAttentionDsts,
    mailResolveListDst: mailResolveListDst,
    mailListAutoselectDst: mailResolveListDst
  };
  Object.keys(api).forEach(function (k) { global[k] = api[k]; });
  global.WallMail = api;
  global.WALL_UI_DEFAULT_MAIL = "WALL_UI_DEFAULT_MAIL";
  global.BARE_HUMAN_MAILBOX = BARE_HUMAN_MAILBOX;
})(typeof window !== "undefined" ? window : globalThis);
