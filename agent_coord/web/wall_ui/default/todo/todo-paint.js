/* WALL_UI_DEFAULT_TODO_PAINT - TODO paint code, split out of boot.js (#710).
 * Marker: WALL_UI_DEFAULT_TODO_PAINT
 * Loads with the pane through lib/lazy.js (MODULES.todoPaint); boot.js keeps a stub
 * for each entry. Classic script on purpose: it shares boot.js globals (let/const
 * state and functions), and its function declarations replace boot.js stubs.
 */
    function millNestEntry(nodes, node) {
      /* { idx, e } when the index is good and still matches this row; else null (caller scans). */
      if (!node) return null;
      let idx = millNestIndex(nodes);
      let e = idx.bad ? null : idx.at.get(node);
      if (e && (e.lft !== Number(node.lft) || e.rgt !== Number(node.rgt))) {
        idx = millNestIndex(nodes, true);
        e = idx.bad ? null : idx.at.get(node);
      }
      return e ? { idx: idx, e: e } : null;
    }
    function millNestKids(idx, n) {
      /* Direct kids in list order. */
      if (!idx.kidsBuilt) {
        idx.kidsBuilt = true;
        idx.at.forEach(e => {
          if (!e.parent) return;
          const p = idx.at.get(e.parent);
          (p.kids || (p.kids = [])).push(e.node);
        });
      }
      const e = idx.at.get(n);
      return (e && e.kids) || [];
    }
    function millTreeDepthScan(nodes, node, lft, rgt) {
      let n = 0;
      (nodes || []).forEach(o => {
        if (!o || o === node) return;
        const a = Number(o.lft);
        const b = Number(o.rgt);
        if (Number.isFinite(a) && Number.isFinite(b) && a < lft && b > rgt) n += 1;
      });
      return n;
    }
    function millTreeDepth(nodes, node) {
      if (node && node.depth != null && node.depth !== "") {
        const d = Number(node.depth);
        if (Number.isFinite(d) && d >= 0) return d;
      }
      const lft = Number(node && node.lft);
      const rgt = Number(node && node.rgt);
      if (!Number.isFinite(lft) || !Number.isFinite(rgt)) return 0;
      const hit = millNestEntry(nodes, node);
      if (hit) return hit.e.depth;
      return millTreeDepthScan(nodes, node, lft, rgt);
    }
    function millOutlineKidsOf(nodes, n) {
      const hit = millNestEntry(nodes, n);
      if (hit && !hit.idx.explicit) return millNestKids(hit.idx, n).slice();
      const lft = Number(n && n.lft);
      const rgt = Number(n && n.rgt);
      const d = millTreeDepth(nodes, n);
      return (nodes || []).filter(o => {
        if (!o || o === n) return false;
        if (millTreeDepth(nodes, o) !== d + 1) return false;
        return Number(o.lft) > lft && Number(o.rgt) < rgt;
      });
    }
    function millTreesCollapseMap() {
      try {
        const raw = JSON.parse(localStorage.getItem(TREES_COLLAPSE_KEY) || "{}");
        return raw && typeof raw === "object" ? raw : {};
      } catch (e) { return {}; }
    }
    function millTreesCollapseSave(map) {
      try { localStorage.setItem(TREES_COLLAPSE_KEY, JSON.stringify(map || {})); } catch (e) {}
    }
    function millTreesCollapseKey(planId, type, id) {
      if (type == null || type === "") return "plan:" + String(planId || "");
      return String(planId || "") + "|" + String(type || "").toLowerCase() + ":" + String(id || "");
    }
    function millTreesQ() {
      const el = document.getElementById("trees-q");
      if (el && el.value != null) return String(el.value || "").trim().toLowerCase();
      try { return String(localStorage.getItem(TREES_Q_KEY) || "").trim().toLowerCase(); } catch (e) { return ""; }
    }
    function millTreesNodeMatch(p, q) {
      if (!q) return true;
      const hay = [p.title, p.status, p.who, p.type].map(x => String(x || "").toLowerCase()).join(" ");
      return hay.indexOf(q) >= 0;
    }
    function millTreesVisibleSet(nodes, d, q) {
      const keep = {};
      if (!q) {
        (nodes || []).forEach((_, i) => { keep[i] = 1; });
        return keep;
      }
      (nodes || []).forEach((n, i) => {
        const p = millTreePayload(d, n);
        if (!millTreesNodeMatch(p, q)) return;
        keep[i] = 2; /* hit */
        millOutlineAncestors(nodes, n).forEach(a => {
          const j = nodes.indexOf(a);
          if (j >= 0 && !keep[j]) keep[j] = 1; /* spine */
        });
      });
      return keep;
    }
    function millOutlineRowHtml(d, nodes, node, opts) {
      opts = opts || {};
      const depth = millTreeDepth(nodes, node);
      const p = millTreePayload(d, node);
      const kind = p.type || "name";
      const cue = kind === "todo" ? (p.status || "todo") : kind;
      const cls = ["mill-outline-row", "ty-" + kind];
      if (kind === "todo" && p.status) cls.push("st-" + p.status);
      if (p.unread) cls.push("is-unread");
      if (opts.hit) cls.push("is-hit");
      if (opts.spine) cls.push("is-spine");
      if (opts.collapsed) cls.push("is-collapsed");
      const who = p.who ? `<span class="who">${esc(millName("desk", p.who) || p.who)}</span>` : "";
      const unread = p.unread ? `<span class="leaf-unread" title="unread">unread</span>` : "";
      const kids = millOutlineKidsOf(nodes, node);
      const hasKidsHint = !!(node && (node.has_children === true || node.has_children === 1 || node.has_children === "1"));
      const needsExpand = hasKidsHint && kids.length === 0;
      const canCollapse = kids.length > 0 || needsExpand;
      if (needsExpand) cls.push("needs-expand");
      const twistCollapsed = opts.collapsed || needsExpand;
      const twist = canCollapse
        ? `<button type="button" class="trees-twist" data-trees-twist="1" data-trees-needs-expand="${needsExpand ? "1" : "0"}" aria-expanded="${twistCollapsed ? "false" : "true"}" title="${needsExpand ? "Load children" : (twistCollapsed ? "Expand branch" : "Collapse branch")}">${twistCollapsed ? "+" : "-"}</button>`
        : `<span class="trees-twist-gap"></span>`;
      return `<div class="${cls.join(" ")}" style="--d:${depth}" data-depth="${depth}" data-type="${esc(kind)}" data-id="${esc(String(node && node.id || ""))}" data-plan="${esc(String(opts.planId || ""))}" data-has-children="${hasKidsHint ? "1" : "0"}">` +
        twist +
        `<span class="st">${esc(cue)}</span>` +
        `<div class="ttl"><b>${esc(p.title)}</b>${millWatchBadge(kind, node && node.id)}${unread}${who}</div>` +
        `</div>`;
    }
    function millTodoNodesOf(nodes) {
      return (nodes || []).filter(n => String((n && n.type) || "").toLowerCase() === "todo");
    }
    function millTodoParentOfScan(todos, n) {
      const lft = Number(n && n.lft);
      const rgt = Number(n && n.rgt);
      if (!Number.isFinite(lft) || !Number.isFinite(rgt)) return null;
      let best = null;
      (todos || []).forEach(o => {
        if (!o || o === n) return;
        const a = Number(o.lft);
        const b = Number(o.rgt);
        if (!Number.isFinite(a) || !Number.isFinite(b) || !(a < lft && b > rgt)) return;
        if (!best || a > Number(best.lft)) best = o;
      });
      return best;
    }
    function millTodoParentOf(todos, n) {
      const hit = millNestEntry(todos, n);
      return hit ? hit.e.parent : millTodoParentOfScan(todos, n);
    }
    function millTodoByLft(a, b) {
      return (Number(a.lft) || 0) - (Number(b.lft) || 0);
    }
    function millTodoKidsOf(todos, n) {
      const hit = millNestEntry(todos, n);
      if (hit) {
        if (!hit.e.kidsLft) hit.e.kidsLft = millNestKids(hit.idx, n).slice().sort(millTodoByLft);
        return hit.e.kidsLft.slice();
      }
      const lft = Number(n && n.lft);
      const rgt = Number(n && n.rgt);
      if (!Number.isFinite(lft) || !Number.isFinite(rgt)) return [];
      return (todos || []).filter(o => {
        if (!o || o === n) return false;
        if (!(Number(o.lft) > lft && Number(o.rgt) < rgt)) return false;
        return millTodoParentOf(todos, o) === n;
      }).sort(millTodoByLft);
    }
    function millTodoRootsOf(todos) {
      return (todos || []).filter(n => !millTodoParentOf(todos, n)).sort(millTodoByLft);
    }
    function todoTreeCardKey(n) {
      return "todo:" + String(n && n.id || "");
    }
    function todoTreeHasKidsHint(n) {
      return !!(n && (n.has_children === true || n.has_children === 1 || n.has_children === "1"));
    }
    function todoTreeMatch(d, n, q) {
      if (!q) return true;
      return millTreesNodeMatch(millTreePayload(d, n), q);
    }
    function todoTreeOnSpine(todos, n, d, q) {
      if (!q) return true;
      if (todoTreeMatch(d, n, q)) return true;
      const hit = millNestEntry(todos, n);
      if (hit) {
        /* Rows with a matching row somewhere under them, one pass per (todos, d, q). */
        const idx = hit.idx;
        if (!idx.spine || idx.spine.d !== d || idx.spine.q !== q) {
          const under = new Set();
          for (let i = idx.order.length - 1; i >= 0; i--) {
            const e = idx.at.get(idx.order[i]);
            if (!e.parent) continue;
            if (under.has(e.node) || todoTreeMatch(d, e.node, q)) under.add(e.parent);
          }
          idx.spine = { d: d, q: q, under: under };
        }
        return idx.spine.under.has(n);
      }
      const lft = Number(n && n.lft);
      const rgt = Number(n && n.rgt);
      return (todos || []).some(o => o && o !== n && Number(o.lft) > lft && Number(o.rgt) < rgt && todoTreeMatch(d, o, q));
    }
    function todoTreePathSet(todos, selected) {
      const set = {};
      let cur = selected;
      const guard = {};
      while (cur && !guard[todoTreeCardKey(cur)]) {
        guard[todoTreeCardKey(cur)] = 1;
        set[todoTreeCardKey(cur)] = 1;
        cur = millTodoParentOf(todos, cur);
      }
      return set;
    }
    function todoTreeFindNode(d, planId, id) {
      const trees = (d && d.trees) || [];
      for (let ti = 0; ti < trees.length; ti++) {
        const t = trees[ti];
        const pid = String((t && (t.name || t.id)) || "");
        if (planId && pid !== planId) continue;
        const todos = millTodoNodesOf((t && t.nodes) || []);
        for (let i = 0; i < todos.length; i++) {
          if (String(todos[i].id) === String(id)) return { todos: todos, node: todos[i] };
        }
      }
      return null;
    }
    function todoTreeDesk(name) {
      const raw = String(name || "").trim();
      if (!raw) return "";
      try {
        const n = (typeof millName === "function") ? millName("desk", raw) : "";
        return n || raw;
      } catch (e) { return raw; }
    }
    function todoTreeCardRow(d, node) {
      const id = String(node && node.id || "");
      return millTodoCardLookup(d, id) || null;
    }
    function todoTreeEnsureKids(node) {
      if (!node || !todoTreeHasKidsHint(node)) return;
      const key = todoTreeCardKey(node);
      if (_todoTreeExpandTried[key]) return;
      _todoTreeExpandTried[key] = 1;
      try { wallFetchTreeExpand("todo", String(node.id || ""), { kind: wallActiveTreeKind() || "tree-todo" }); } catch (eExp) {}
    }
    function paintPlan(d) {
      const prevScope = _millPaintScope;
      _millPaintScope = { d: d, cards: null };
      try { return paintPlanInner(d); } finally { _millPaintScope = prevScope; }
    }
    function paintPlanInner(d) {
      if (_todoChartPanning) {
        _todoChartPaintWait = true;
        return;
      }
      const el = document.getElementById("jobs-outline");
      if (!el) return;
      const trees = d && d.trees;
      if (!Array.isArray(trees)) {
        el.innerHTML = `<div class="idle">Plans are not on this floor yet.</div>`;
        return;
      }
      const q = millTreesQ();
      const qEl = document.getElementById("trees-q");
      if (qEl && !qEl._treesWired) {
        try {
          const saved = localStorage.getItem(TREES_Q_KEY) || "";
          if (!qEl.value && saved) qEl.value = saved;
        } catch (e) {}
      }
      const forests = [];
      trees.forEach((t, ti) => {
        const nodes = (t && Array.isArray(t.nodes) ? t.nodes.slice() : []).sort((a, b) =>
          (Number(a && a.lft) || 0) - (Number(b && b.lft) || 0));
        const todos = millTodoNodesOf(nodes);
        if (!todos.length) return;
        if (q && !todos.some(n => todoTreeMatch(d, n, q))) return;
        const planId = String((t && (t.name || t.id)) || ("t" + ti));
        forests.push({ planId: planId, label: millTreePlanLabel(t), todos: todos });
      });
      let hitN = 0;
      if (q) forests.forEach(f => { f.todos.forEach(n => { if (todoTreeMatch(d, n, q)) hitN += 1; }); });
      let forest = forests.find(f => f.planId === _todoTreePlan) || forests[0] || null;
      if (forest) _todoTreePlan = forest.planId;
      let selected = null;
      if (forest) {
        selected = forest.todos.find(n => todoTreeCardKey(n) === _todoTreeCard) || null;
        if (q && selected && !todoTreeOnSpine(forest.todos, selected, d, q)) selected = null;
        if (!selected) {
          selected = forest.todos.find(n => !q || todoTreeMatch(d, n, q)) || millTodoRootsOf(forest.todos)[0] || forest.todos[0] || null;
        }
        if (selected) _todoTreeCard = todoTreeCardKey(selected);
      }
      const sub = document.getElementById("jobs-view-sub") || document.getElementById("trees-view-sub");
      const pane = document.getElementById("pane-todo") || document.getElementById("pane-jobs");
      const nestOn = !pane || pane.classList.contains("jobs-view-nest") || !sub || sub.id !== "jobs-view-sub";
      if (sub && nestOn) {
        if (q) sub.textContent = hitN ? (`filter "${q}" | ${hitN} hit` + (hitN === 1 ? "" : "s")) : (`filter "${q}" | no hits`);
        else sub.textContent = "plans | chart left to right";
      }
      if (!forests.length) {
        el.innerHTML = q
          ? `<div class="idle">No cards match that filter.</div>`
          : `<div class="idle">No plan yet. A card sits under another card, or it sits in none.</div>`;
        bindTreesChrome();
        return;
      }
      const path = forest ? todoTreePathSet(forest.todos, selected) : {};
      const roots = forest ? millTodoRootsOf(forest.todos).filter(n => todoTreeOnSpine(forest.todos, n, d, q)) : [];
      const forestRows = forests.map(f => {
        const root = millTodoRootsOf(f.todos)[0];
        const face = millPlanRowFace(f.label, root ? millTreePayload(d, root) : null, root);
        const on = forest && f.planId === forest.planId ? " on" : "";
        return { key: f.planId, html: `<button type="button" class="todo-tree-row${on}" data-plan="${esc(f.planId)}">` +
          `<b title="${esc(face.full)}">${esc(face.head)}</b>` +
          `<span class="todo-tree-n">${f.todos.length}</span>` +
          `<span class="todo-tree-line">${esc(face.line)}</span>` +
          `</button>` };
      });
      const forestHtml = forestRows.map(r => r.html).join("");
      /* One card: { key, html (its button), hasUl, kids }. Same markup as the old string build. */
      function todoPertNode(n, seen) {
        const key = todoTreeCardKey(n);
        if (seen[key]) return null;
        seen[key] = 1;
        const p = millTreePayload(d, n);
        const on = path[key] ? " on" : "";
        const st = p.status || "todo";
        const detailKey = "todo:" + String(_todoDetailId || "");
        const open = !!_todoDetailId && !!path[detailKey] && !!path[key];
        const shrunk = todoStatusCollapsed(st) && !open;
        const rowFace = todoTreeCardRow(d, n);
        /* #818: cards have no title; the body line is the card's detail. */
        const detailFull = rowFace ? String(rowFace.detail || "").trim() : "";
        const bodyLine = detailFull || p.title;
        const note = detailFull && detailFull !== bodyLine ? detailFull : "";
        const asker = rowFace ? todoTreeDesk(rowFace.creator || rowFace.asker || rowFace.src || "") : "";
        const holder = rowFace
          ? todoTreeDesk(rowFace.assigned || rowFace.volunteer || rowFace.owner || "")
          : todoTreeDesk(p.who);
        const nid = rowFace ? String(rowFace.need_id || "").trim() : "";
        const kids = _todoTreeChainOpen
          ? millTodoKidsOf(forest.todos, n).filter(k => todoTreeOnSpine(forest.todos, k, d, q))
          : [];
        const kidNodes = kids.map(k => todoPertNode(k, seen)).filter(Boolean);
        const face = shrunk
          ? `<span class="st">${esc(st)}</span>`
          : (open
            ? `<span class="st">${esc(st)}</span><b>${esc(bodyLine)}</b>` +
              (note ? `<span class="todo-card-note">${esc(note)}</span>` : "") +
              (nid ? `<span class="todo-tree-id"><code>${esc(nid)}</code></span>` : "") +
              (asker ? `<span class="todo-tree-field"><span>asker</span> <b>${esc(asker)}</b></span>` : "") +
              (holder ? `<span class="todo-tree-field"><span>holder</span> <b>${esc(holder)}</b></span>` : "") +
              (rowFace ? wallClaimedSlot(rowFace) : "") +
              (n.id ? wallDoingTrailSlot("todo-" + String(n.id)) : "")
            : `<span class="st">${esc(st)}</span><b>${esc(p.title)}</b>`);
        const html = `<button type="button" class="todo-tree-card st-${esc(st)}${on}${shrunk ? " is-collapsed" : ""}${open ? " is-open" : ""}" data-plan="${esc(forest.planId)}" data-type="todo" data-id="${esc(String(n.id || ""))}" data-has-children="${todoTreeHasKidsHint(n) ? "1" : "0"}" title="${esc(open ? bodyLine : p.title)}">` +
          face + `</button>`;
        return { key: key, html: html, hasUl: kids.length > 0, kids: kidNodes };
      }
      const chainNodes = roots.map(n => todoPertNode(n, {})).filter(Boolean);
      let wrap = el.firstElementChild;
      let forestBox = wrap && wrap._wallPert ? wrap.querySelector(".todo-tree-forests .todo-tree-scroll") : null;
      let pertUl = wrap && wrap._wallPert ? wrap.querySelector(".todo-tree-chain > ul.pert") : null;
      if (forestBox && pertUl) {
        /* Refresh: keep the shell and every unchanged card; scroll stays where it was. */
        while (el.firstChild && el.firstChild !== wrap) el.removeChild(el.firstChild);
        while (el.lastChild && el.lastChild !== wrap) el.removeChild(el.lastChild);
        wallKeyedSync(forestBox, forestRows);
        todoPertSync(pertUl, chainNodes);
      } else {
        const chainHtml = `<ul class="pert">${chainNodes.map(todoPertLiHtml).join("")}</ul>`;
        const prevChain = el.querySelector(".todo-tree-chain");
        const keepLeft = prevChain ? prevChain.scrollLeft : 0;
        const keepTop = prevChain ? prevChain.scrollTop : 0;
        el.innerHTML = `<div class="todo-tree" data-todo-tree="forests-chain">` +
          `<aside class="todo-tree-col todo-tree-forests" aria-label="plans"><div class="rail-h">PLANS</div><div class="todo-tree-scroll">${forestHtml}</div></aside>` +
          `<div class="todo-tree-col todo-tree-chain-col" aria-label="chart"><div class="todo-tree-chain">${chainHtml}</div></div>` +
          `</div>`;
        wrap = el.firstElementChild;
        if (wrap) {
          wrap._wallPert = true;
          forestBox = wrap.querySelector(".todo-tree-forests .todo-tree-scroll");
          pertUl = wrap.querySelector(".todo-tree-chain > ul.pert");
          if (forestBox) wallKeyedTag(forestBox, forestRows);
          if (pertUl) todoPertTagList(pertUl, chainNodes);
        }
        const freshChain = el.querySelector(".todo-tree-chain");
        if (freshChain) {
          if (keepLeft) freshChain.scrollLeft = keepLeft;
          if (keepTop) freshChain.scrollTop = keepTop;
        }
      }
      const nextChain = el.querySelector(".todo-tree-chain");
      if (nextChain) alignPlanSpine(nextChain);
      if (_todoTreeChainOpen && forest) {
        (forest.todos || []).filter(n =>
          todoTreeHasKidsHint(n) && !millTodoKidsOf(forest.todos, n).length
        ).slice(0, 4).forEach(todoTreeEnsureKids);
      }
      bindTreesChrome();
    }
    /* #33 keyed reuse for the plan chart: a row keeps its DOM node while its markup is unchanged. */
    function wallKeyedEl(html) {
      const tpl = document.createElement("template");
      tpl.innerHTML = html;
      return tpl.content.firstElementChild;
    }
    function wallKeyedTag(box, rows) {
      for (let i = 0; i < rows.length; i++) {
        const node = box.children[i];
        if (!node) break;
        node._wallKey = rows[i].key;
        node._wallSig = rows[i].html;
      }
    }
    function wallKeyedSync(box, rows) {
      const have = new Map();
      Array.prototype.forEach.call(box.children, c => { if (c._wallKey != null && !have.has(c._wallKey)) have.set(c._wallKey, c); });
      let cursor = box.firstElementChild;
      rows.forEach(r => {
        let node = have.get(r.key);
        if (node) have.delete(r.key);
        if (!node || node._wallSig !== r.html) {
          const made = wallKeyedEl(r.html);
          made._wallKey = r.key;
          made._wallSig = r.html;
          if (node) {
            if (node === cursor) cursor = made;
            box.replaceChild(made, node);
          }
          node = made;
        }
        if (node === cursor) cursor = cursor.nextElementSibling;
        else box.insertBefore(node, cursor);
      });
      while (cursor) { const nx = cursor.nextElementSibling; cursor.remove(); cursor = nx; }
    }
    function todoPertLiHtml(n) {
      return `<li>${n.html}${n.hasUl ? `<ul>${n.kids.map(todoPertLiHtml).join("")}</ul>` : ""}</li>`;
    }
    function todoPertTag(li, n) {
      li._wallKey = n.key;
      const btn = li.firstElementChild;
      if (btn) btn._wallSig = n.html;
      if (n.hasUl && li.children[1]) todoPertTagList(li.children[1], n.kids);
    }
    function todoPertTagList(ul, list) {
      for (let i = 0; i < list.length; i++) {
        const li = ul.children[i];
        if (!li) break;
        todoPertTag(li, list[i]);
      }
    }
    function todoPertSync(ul, list) {
      const have = new Map();
      Array.prototype.forEach.call(ul.children, li => { if (li._wallKey != null && !have.has(li._wallKey)) have.set(li._wallKey, li); });
      let cursor = ul.firstElementChild;
      list.forEach(n => {
        let li = have.get(n.key);
        if (li) {
          have.delete(n.key);
          let btn = li.firstElementChild;
          if (!btn || btn.tagName !== "BUTTON" || btn._wallSig !== n.html) {
            const made = wallKeyedEl(n.html);
            made._wallSig = n.html;
            if (btn && btn.tagName === "BUTTON") li.replaceChild(made, btn);
            else li.insertBefore(made, li.firstChild);
            btn = made;
          }
          let sub = btn.nextElementSibling;
          while (sub && sub.nextElementSibling) sub.nextElementSibling.remove();
          if (sub && sub.tagName !== "UL") { sub.remove(); sub = null; }
          if (n.hasUl) {
            if (!sub) { sub = document.createElement("ul"); li.appendChild(sub); }
            todoPertSync(sub, n.kids);
          } else if (sub) {
            sub.remove();
          }
        } else {
          li = wallKeyedEl(todoPertLiHtml(n));
          todoPertTag(li, n);
        }
        if (li === cursor) cursor = cursor.nextElementSibling;
        else ul.insertBefore(li, cursor);
      });
      while (cursor) { const nx = cursor.nextElementSibling; cursor.remove(); cursor = nx; }
    }
    /* Parents of the selected card drop onto its row. Siblings stay stacked. */
    function alignPlanSpine(chain) {
      if (!chain) return;
      chain.querySelectorAll("button.todo-tree-card").forEach(btn => { btn.style.marginTop = ""; });
      chain.querySelectorAll(".pert li").forEach(li => {
        li.classList.remove("is-spine");
        li.style.removeProperty("--stub-y");
      });
      chain.querySelectorAll(".pert ul").forEach(ul => ul.style.removeProperty("--link-y"));
      const ons = [...chain.querySelectorAll("button.todo-tree-card.on")];
      const selected = ons.find(btn => {
        const li = btn.parentElement;
        return li && !ons.some(other => other !== btn && li.contains(other));
      });
      if (!selected) return;
      const steps = [];
      let childBtn = selected;
      while (childBtn) {
        const childLi = childBtn.parentElement;
        const ul = childLi && childLi.parentElement;
        const parentLi = ul && ul.parentElement;
        if (!ul || !parentLi || parentLi.tagName !== "LI") break;
        const parentBtn = parentLi.querySelector(":scope > button.todo-tree-card");
        if (!parentBtn) break;
        parentLi.classList.add("is-spine");
        steps.push({ parentLi: parentLi, ul: ul, parentBtn: parentBtn, childBtn: childBtn });
        childBtn = parentBtn;
      }
      steps.forEach(step => {
        const c = step.childBtn.getBoundingClientRect();
        const p = step.parentBtn.getBoundingClientRect();
        const delta = (c.top + c.height / 2) - (p.top + p.height / 2);
        step.parentBtn.style.marginTop = (Math.abs(delta) > 0.5 ? delta : 0) + "px";
      });
      steps.forEach(step => {
        const p = step.parentBtn.getBoundingClientRect();
        const mid = p.top + p.height / 2;
        const liBox = step.parentLi.getBoundingClientRect();
        const ulBox = step.ul.getBoundingClientRect();
        step.parentLi.style.setProperty("--stub-y", (mid - liBox.top) + "px");
        step.ul.style.setProperty("--link-y", (mid - ulBox.top) + "px");
      });
    }
    function bindTreesChrome() {
      const root = document.getElementById("pane-todo") || document.getElementById("pane-trees") || document;
      if (!root || root._treesChrome) return;
      root._treesChrome = true;
      window.addEventListener("resize", () => {
        const chain = document.querySelector("#jobs-outline .todo-tree-chain");
        if (chain) alignPlanSpine(chain);
      });
      const qEl = document.getElementById("trees-q");
      if (qEl) {
        qEl._treesWired = true;
        qEl.addEventListener("input", () => {
          try { localStorage.setItem(TREES_Q_KEY, qEl.value || ""); } catch (e) {}
          if (window._floor) paintPlan(window._floor);
        });
      }
      let chartPan = null;
      function chartPanEnd(ev) {
        if (!chartPan || ev.pointerId !== chartPan.id) return;
        const moved = chartPan.moved;
        const card = chartPan.card;
        chartPan.chain.classList.remove("is-panning");
        chartPan = null;
        _todoChartPanning = false;
        if (!moved && card && card.isConnected) {
          _todoChartPaintWait = false;
          card.click();
          return;
        }
        if (moved) {
          const stop = evClick => {
            evClick.preventDefault();
            evClick.stopPropagation();
            root.removeEventListener("click", stop, true);
          };
          root.addEventListener("click", stop, true);
          setTimeout(() => root.removeEventListener("click", stop, true), 0);
        }
        if (_todoChartPaintWait) {
          _todoChartPaintWait = false;
          if (window._floor) paintPlan(window._floor);
        }
      }
      root.addEventListener("pointerdown", ev => {
        if (ev.button !== 0) return;
        const chain = ev.target && ev.target.closest ? ev.target.closest(".todo-tree-chain") : null;
        if (!chain) return;
        const active = document.activeElement;
        if (active && chain.contains(active) && active.blur) {
          try { active.blur(); } catch (eBl) {}
        }
        if (ev.cancelable) ev.preventDefault();
        const card = ev.target && ev.target.closest ? ev.target.closest("button.todo-tree-card") : null;
        _todoChartPanning = true;
        chartPan = { chain: chain, id: ev.pointerId, x: ev.clientX, left: chain.scrollLeft, moved: false, card: card };
        try { chain.setPointerCapture(ev.pointerId); } catch (eCap0) {}
      });
      root.addEventListener("pointermove", ev => {
        if (!chartPan || ev.pointerId !== chartPan.id) return;
        const dx = ev.clientX - chartPan.x;
        if (!chartPan.moved) {
          if (Math.abs(dx) < 5) return;
          chartPan.moved = true;
          chartPan.chain.classList.add("is-panning");
          try { chartPan.chain.setPointerCapture(ev.pointerId); } catch (eCap) {}
        }
        chartPan.chain.scrollLeft = chartPan.left - dx;
        ev.preventDefault();
      });
      root.addEventListener("pointerup", chartPanEnd);
      root.addEventListener("pointercancel", chartPanEnd);
      root.addEventListener("click", ev => {
        const allBtn = ev.target && ev.target.closest ? ev.target.closest("[data-trees-collapse]") : null;
        if (allBtn) {
          _todoTreeChainOpen = allBtn.getAttribute("data-trees-collapse") !== "collapse";
          if (window._floor) paintPlan(window._floor);
          return;
        }
        const t = ev.target && ev.target.closest ? ev.target : null;
        if (!t) return;
        const forest = t.closest("button.todo-tree-row");
        if (forest) {
          _todoTreePlan = forest.getAttribute("data-plan") || "";
          _todoTreeCard = "";
          _todoTreeChainOpen = true;
          if (window._floor) paintPlan(window._floor);
          return;
        }
        const card = t.closest("button.todo-tree-card");
        if (!card) return;
        const planId = card.getAttribute("data-plan") || "";
        const id = card.getAttribute("data-id") || "";
        _todoTreePlan = planId;
        _todoTreeCard = "todo:" + id;
        _todoDetailId = String(id || "");
        _todoTreeChainOpen = true;
        const has = card.getAttribute("data-has-children") === "1";
        if (window._floor) paintPlan(window._floor);
        try { wallDoingTrail(); } catch (eTrail) {}
        const found = todoTreeFindNode(window._floor, planId, id);
        let cur = found && found.node;
        const seenOpen = {};
        while (cur && !seenOpen[todoTreeCardKey(cur)]) {
          seenOpen[todoTreeCardKey(cur)] = 1;
          try { wallOpenTodoIfTrunc(cur.id); } catch (eLeanPlan) {}
          cur = millTodoParentOf(found.todos, cur);
        }
        if (!found) {
          try { wallOpenTodoIfTrunc(id); } catch (eLeanPlan) {}
        }
        if (!has) return;
        const localKids = found ? millTodoKidsOf(found.todos, found.node).length : 0;
        if (localKids) return;
        delete _todoTreeExpandTried["todo:" + id];
        try { wallFetchTreeExpand("todo", id, { kind: wallActiveTreeKind() || "tree-todo" }); } catch (eExp) {}
      });
    }

    function paintWatchers(d) {
      const el = document.getElementById("watchers");
      if (!el) return;
      const rows = d && d.watchers;
      if (!Array.isArray(rows)) {
        el.innerHTML = `<div class="idle">Watchers are not on this floor yet.</div>`;
        return;
      }
      if (!rows.length) {
        el.innerHTML = `<div class="idle">No watchers. When a desk subscribes to a card or a note, they show up here. Empty means nobody is subscribed.</div>`;
        return;
      }
      const groups = [];
      const index = {};
      rows.forEach(r => {
        const key = String(r.type || "") + ":" + String(r.id || "");
        const desks = Array.isArray(r.desks) ? r.desks : [{ desk: r.desk, hint: r.hint }];
        if (!index[key]) {
          index[key] = { type: r.type, id: r.id, title: r.title, status: r.status, desks: [] };
          groups.push(index[key]);
        }
        desks.forEach(item => index[key].desks.push(item));
        if (!index[key].title && r.title) index[key].title = r.title;
      });
      el.innerHTML = groups.map(g => {
        const who = g.desks.map(r => {
          const name = millName("desk", r.desk || r) || r.desk || r || "?";
          const flag = r.hint === "custom" ? "custom" : "default";
          return esc(name) + " | " + esc(flag);
        }).join("<br>");
        const node = { type: g.type, id: g.id, title: g.title, status: g.status };
        const p = millTreePayload(d, node);
        const cue = p.type === "todo" ? (p.status || "todo") : (p.type || "watch");
        return `<div class="mill-outline-row ty-${esc(p.type)}">` +
          `<span class="st">${esc(cue)}</span>` +
          `<div class="ttl"><b>${esc(p.title)}</b><span class="who">${who}</span></div>` +
          `</div>`;
      }).join("");
    }
    function planNormStatus(st) {
      const s = String(st || "").toLowerCase().trim();
      if (s === "done" || s === "shipped") return "done";
      if (s === "doing" || s === "claimed" || s === "open") return "doing";
      return "todo";
    }
    function planLabelFilter() {
      return String((document.getElementById("plan-label") || {}).value || "").trim().toLowerCase();
    }
    function fillPlanCuts(all) {
      const el = document.getElementById("plan-cut");
      if (!el) return;
      const want = el.dataset.want != null ? el.dataset.want : el.value;
      const cuts = [];
      const seen = {};
      (all || []).forEach(r => {
        const c = String(r.cut || "").trim();
        if (c && !seen[c]) { seen[c] = 1; cuts.push(c); }
      });
      cuts.sort((a, b) => a.localeCompare(b));
      const cur = want != null ? want : "";
      el.innerHTML = `<option value="">this cut</option>` +
        cuts.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
      if (cur && !seen[cur]) {
        const opt = document.createElement("option");
        opt.value = cur; opt.textContent = cur; el.appendChild(opt);
      }
      el.value = cur;
      delete el.dataset.want;
    }
    function boardRowPass(r) {
      const q = String((document.getElementById("board-search") || {}).value || "").trim().toLowerCase();
      if (q) {
        const hay = (String(r.title || "") + " " + String(r.detail || "") + " " +
          String(r.label || "") + " " + String(r.cut || "")).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      const lf = planLabelFilter();
      if (lf && String(r.label || "").toLowerCase().indexOf(lf) < 0) return false;
      const st = planNormStatus(r.status);
      const cut = String(r.cut || "");
      const sel = planCut();
      const hist = planHist();
      if (hist === "this") {
        if (st === "done") return false;
        if (sel) return cut === sel;
        // empty selector = current unnamed cut + items with empty cut
        return !cut || cut === sel;
      }
      if (hist === "prior") {
        if (st === "done") return true;
        if (sel) return cut && cut !== sel;
        return !!cut;
      }
      return true; // all
    }
    function issueCard(r) {
      const st = planNormStatus(r.status);
      const label = r.label || "";
      const cut = r.cut || "";
      const by = r.who || r.src || "";
      const when = r.updated_at || r.created_at || "";
      const pulled = (r.pulled_need_id || "").trim();
      const snip = r.detail ? `<div class="note">${esc(r.detail)}</div>` : "";
      const cls = esc(st) + (pulled ? " pulled" : "");
      return `<div class="plan-card ${cls}" data-id="${esc(String(r.id))}" data-sort="${esc(String(r.sort_order || 0))}">` +
        `<div class="plan-title">${esc(r.title || "")}</div>` +
        `<div class="plan-meta">` +
          (label ? `<span>label <b>${esc(label)}</b></span>` : "") +
          (cut ? `<span>cut <b>${esc(cut)}</b></span>` : `<span>cut <b>this</b></span>`) +
          `<span>${esc(st)}</span>` +
          (pulled ? `<span>pulled <b>${esc(pulled)}</b></span>` : "") +
          (by ? `<span>by <b>${esc(by)}</b></span>` : "") +
          (when ? `<span>${esc(dt(when))}</span>` : "") +
        `</div>${snip}</div>`;
    }
    function issues(d) {
      const listEl = document.getElementById("issue-list");
      if (!listEl) return;
      const all = d.issues || [];
      fillPlanCuts(all);
      let rows = all.filter(boardRowPass);
      rows = rows.slice().sort((a, b) => {
        const sa = Number(a.sort_order || 0), sb = Number(b.sort_order || 0);
        if (sa !== sb) return sa - sb;
        return Number(a.id || 0) - Number(b.id || 0);
      });
      const sub = document.getElementById("plan-sub");
      const hist = planHist();
      const sel = planCut();
      if (sub) {
        sub.textContent = hist === "this"
          ? (sel ? (`cut "${sel}" - parked + upcoming`) : "this cut - parked + upcoming")
          : (hist === "prior" ? "prior cuts / finished" : "all Plan items");
      }
      paintPlanView();
      if (!rows.length) {
        const empty = !all.length
          ? "No parked cards."
          : "No parked cards match this filter.";
        listEl.innerHTML = `<div class="idle">${empty}</div>`;
        return;
      }
      listEl.innerHTML = rows.map(issueCard).join("");
    }

    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function millPlanRowFace(label, rootPayload, root) {
      const p = rootPayload || {};
      const title = String(p.title || "").replace(/\s+/g, " ").trim();
      const name = String(label || "").trim();
      if (name) return { head: name, line: title, full: name };
      if (title) {
        const bits = [String(p.status || "").trim(), String(p.who || "").trim()].filter(Boolean);
        /* The plans column is narrow: keep the head to about two lines. */
        const head = title.length > 64 ? (title.slice(0, 63).replace(/\s+\S*$/, "") + "\u2026") : title;
        return { head: head, line: bits.join(" | "), full: title };
      }
      const id = root && root.id != null && String(root.id) !== "" ? String(root.id) : "";
      const head = id ? ("card " + id) : "plan";
      return { head: head, line: String(p.status || "").trim(), full: head };
    }
    function wallFindTodoRow(id) {
      const d = window._floor || {};
      const want = String(id);
      const pools = [d.needs, d.issues, d.on_it];
      for (let p = 0; p < pools.length; p++) {
        const arr = pools[p];
        if (!Array.isArray(arr)) continue;
        for (let i = 0; i < arr.length; i++) {
          if (String(arr[i] && arr[i].id) === want) return arr[i];
        }
      }
      return null;
    }
    function wallMergeTodoDetail(full) {
      if (!full || full.id == null) return false;
      const d = window._floor;
      if (!d) return false;
      const want = String(full.id);
      const keys = ["needs", "issues", "on_it"];
      let hit = false;
      for (let p = 0; p < keys.length; p++) {
        const arr = d[keys[p]];
        if (!Array.isArray(arr)) continue;
        for (let i = 0; i < arr.length; i++) {
          if (String(arr[i] && arr[i].id) !== want) continue;
          const merged = Object.assign({}, arr[i], full);
          delete merged.detail_trunc;
          arr[i] = merged;
          hit = true;
        }
      }
      if (!hit) {
        if (!Array.isArray(d.needs)) d.needs = [];
        const row = Object.assign({}, full);
        delete row.detail_trunc;
        d.needs.push(row);
      }
      return true;
    }
    async function wallOpenTodoIfTrunc(id) {
      const tid = String(id || "").trim();
      if (!tid) return false;
      const row = wallFindTodoRow(tid);
      if (row && !wallTodoIsTrunc(row)) return false;
      const key = "todo:" + tid;
      if (_wallLeanDetailInflight[key]) return _wallLeanDetailInflight[key];
      const p = (async function () {
        try {
          const r = await fetch("/api/v1/todo/" + encodeURIComponent(tid), { cache: "no-store" });
          if (!r.ok) return false;
          const json = await r.json();
          const full = json && json.todo;
          if (!full) return false;
          if (!wallMergeTodoDetail(full)) return false;
          try { board(window._floor); } catch (ePaint) {}
          try { paintPlan(window._floor); } catch (ePlan) {}
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

var WALL_UI_DEFAULT_TODO_PAINT = "WALL_UI_DEFAULT_TODO_PAINT";
