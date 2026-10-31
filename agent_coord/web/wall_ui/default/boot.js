/* WALL_UI_DEFAULT_BOOT - extracted from board.html Path A breakup.
 * Marker: WALL_HONEST_EMPTY_VS_DOWN
 * Marker: MAINTENANCE_DRAIN
 * Marker: WALL_HUMAN_READONLY
 * Marker: WALL_WELCOME_SHOW_BEFORE_MINT_WOW172
 * Marker: WALL_UI_PERF (opt-in; hooks no-op unless lib/perf.js loaded)
 * SoR: wall-contract (tests/wall)
 * Marker: WALL_UI_DEFAULT_BOOT
 * Loads after lib/* + gutter + floor; MAIL/TODO/SCORE lazy via wallEnsureDomain (Wave 2).
 * Keys wired via wallKeysBind if present.
 */
    let showDead = false;

    /* WALL_HUMAN_READONLY: humans only read on the Wall; agents write with mill send / mill reply.
     * #770: the glass carries no human write path, so there is no escape to turn it off.
     */
    function wallHumanReadonly() {
      return true;
    }
    function wallApplyHumanReadonly() {
      try {
        document.documentElement.classList.add("wall-human-readonly");
        document.documentElement.setAttribute("data-wall-human-readonly", "1");
      } catch (eOn) {}
      const ids = [
        "admin-mint", "admin-lan-on", "admin-lan-off"
      ];
      for (let i = 0; i < ids.length; i++) {
        const el = document.getElementById(ids[i]);
        if (!el) continue;
        try { el.setAttribute("inert", ""); } catch (eInert) {}
        try { el.setAttribute("aria-hidden", "true"); } catch (eAh) {}
        if (el.tagName === "BUTTON" || el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT") {
          try { el.disabled = true; } catch (eDis) {}
        }
        const btns = el.querySelectorAll ? el.querySelectorAll("button, input, textarea, select") : [];
        for (let j = 0; j < btns.length; j++) {
          try { btns[j].disabled = true; } catch (eBtn) {}
        }
      }
      return true;
    }
    try { wallApplyHumanReadonly(); } catch (eApplyRo) {}

    /* WALL_WELCOME_SHOW_BEFORE_MINT_WOW172: Nest popup show first; mint invite in background so hung mint never blocks Host. */
    /* WALL_WELCOME_DISMISS_ALWAYS_WOW173: Escape / backdrop / X / Dismiss always dismiss; never wait on mint. */
    /* WALL_WELCOME_PERSIST_DISMISS_WOW174: dismiss sets factory-welcome-hide=1; strip ?welcome=1 via replaceState. */
    /* WALL_WELCOME_INVITE_NEST_WOW175: Invite Agent strip opens Nest overlay only (never location=/welcome). */
    /* WALL_INVITE_STRIP_OFF: no INVITE chip in the strip while it is being redesigned. */
    /* WALL_INVITE_LOADING_HOURGLASS_WOW189: seat_count loading is ⏳; M/N replaces it on success, TBD is errors only. */
    /* WALL_STRIP_NAV_DELEGATE_WOW190: strip tab clicks via document delegation (innerHTML rebuilds drop per-chip handlers); INVITE excluded. */
    /* WALL_INVITE_SEAT_COUNT_WOW180: strip count POST seat_count -> M/N joined/invited; refresh after mint + on strip. */
    /* WALL_WELCOME_HUMAN_LABEL_WOW184: HUMAN ask is HTML heading/label; paste body is agent-only. */
    /* WALL_INVITE_MINT_UNIQUE_DESK_WOW185: mint_seat needs fresh desk; fixed agent collides -> 400 desk live. */
    /* WALL_INVITE_BARE_DESK_URL_WOW186: invite URL /welcome?desk=&seat= uses the stored desk name; desk name agent-<10digits> every mint. */
    /* WALL_INVITE_ASSIGN_NAME_WOW187: Assign name default agent+10digits (no hyphen); user edit as-is; regenerate only while auto/empty. */
/* WALL_DOMAIN_PINS_WOW182: mail/score/todo + lazy tip; root-absolute under Nest. */
/* WALL_WELCOME_LEAN_WOW181: Gardener 2-line wakeup + invite URL + Copy/Generate/Enter; no paste walls. */
    /* Seat form stays behind wallInviteGateOk, which stays false during the strip redesign. */
    const WALL_WELCOME_HIDE_KEY = "factory-welcome-hide";
    /* Human welcome. Close stays closed. A seat URL is created only from Generate. */
    let _wallWelcomeShownThisLoad = false;
    let _wallInviteUrl = "";
    let _wallInviteDesk = "";
    let _wallInviteSeat = "";
    let _wallInviteGateOk = false;

    function wallBaseOrigin() {
      try {
        const o = String((typeof location !== "undefined" && location.origin) || "").replace(/\/$/, "");
        if (o && o !== "null") return o;
      } catch (eO) {}
      return "https://<wall>";
    }
    function wallWelcomeQs() {
      try {
        return new URLSearchParams((typeof location !== "undefined" && location.search) || "");
      } catch (eQ) {
        return new URLSearchParams();
      }
    }
    function wallWelcomeParseSeat() {
      const q = wallWelcomeQs();
      let desk = String(q.get("desk") || "").trim();
      let seat = String(q.get("seat") || "").trim();
      /* legacy cold invite token -> seat once until Builder */
      if (!seat) {
        const inv = String(q.get("invite") || "").trim();
        if (inv) seat = inv;
      }
      return { desk, seat };
    }
    function wallInviteDeskBare(raw) {
      return String(raw || "").trim();
    }
    function wallRandom10Digits() {
      let n = "";
      try {
        const arr = new Uint8Array(10);
        (window.crypto || crypto).getRandomValues(arr);
        for (let i = 0; i < 10; i++) n += String(arr[i] % 10);
      } catch (eR) {
        n = String(Date.now()).replace(/\D/g, "").slice(-10);
        while (n.length < 10) n = "0" + n;
      }
      return n;
    }
    function wallIsAutoDefaultDesk(raw) {
      /* auto default is contiguous agent + exactly 10 digits (no hyphen). */
      return /^agent\d{10}$/i.test(String(raw || "").trim());
    }
    function wallFreshMintDesk(hint) {
      /* fresh auto desk = agent + 10 decimal digits (no hyphen). hint unused. */
      void hint;
      return "agent" + wallRandom10Digits();
    }
    function wallSeedAssignNameDefault() {
      const deskIn = document.getElementById("wall-welcome-desk");
      if (!deskIn) return;
      const cur = String(deskIn.value || "").trim();
      if (!cur || wallIsAutoDefaultDesk(cur)) {
        try { deskIn.value = wallFreshMintDesk(); } catch (eSeed) {}
      }
    }
    function wallBuildInviteUrl(desk, seat) {
      const base = wallBaseOrigin();
      const d = wallInviteDeskBare(desk) || "desk";
      const s = String(seat || "").trim() || "seat";
      return base + "/welcome?desk=" + encodeURIComponent(d) + "&seat=" + encodeURIComponent(s);
    }
    function wallWelcomeWakeupText(inviteUrl) {
      /* Brief for the agent. The install paste stays in docs/JOIN.md. */
      const url = String(inviteUrl || "").trim();
      if (!url) return "";
      return [
        "A seat on this office is ready for you.",
        "The human sees the wall: who is here, the cards, the letters, and last against target.",
        "The install steps stay in docs/JOIN.md. This URL is the seat.",
        "",
        url
      ].join("\n");
    }
    function wallWelcomeFillJoin() {
      const pre = document.getElementById("wall-welcome-join");
      const copyBtn = document.getElementById("wall-welcome-copy");
      const forAgent = document.getElementById("wall-welcome-for-agent");
      const desk = _wallInviteDesk || wallWelcomeParseSeat().desk || "";
      let url = _wallInviteUrl || "";
      if (!url && desk && _wallInviteSeat) url = wallBuildInviteUrl(desk, _wallInviteSeat);
      const text = wallWelcomeWakeupText(url);
      const show = !!text;
      if (pre) {
        pre.textContent = text;
        pre.hidden = !show;
      }
      if (copyBtn) copyBtn.hidden = !show;
      if (forAgent) forAgent.hidden = !show;
    }
    function wallWelcomeSetInvite(inviteUrl, desk, seat) {
      _wallInviteUrl = String(inviteUrl || "").trim();
      _wallInviteDesk = String(desk || "").trim();
      _wallInviteSeat = String(seat || "").trim();
      if (!_wallInviteUrl && _wallInviteDesk && _wallInviteSeat) {
        _wallInviteUrl = wallBuildInviteUrl(_wallInviteDesk, _wallInviteSeat);
      }
      const note = document.getElementById("wall-welcome-invite-note");
      const deskIn = document.getElementById("wall-welcome-desk");
      if (deskIn && _wallInviteDesk && !deskIn.value) deskIn.value = _wallInviteDesk;
      if (note) {
        note.textContent = _wallInviteUrl
          ? ("Ready. " + (_wallInviteDesk || "desk"))
          : "No URL yet";
      }
      wallWelcomeFillJoin();
    }
    function wallIsAdminChrome() {
      try {
        const btn = document.getElementById("admin-open");
        if (btn && !btn.hidden && btn.getAttribute("data-invite-admin") === "1") return true;
      } catch (eA) {}
      try {
        if (localStorage.getItem("factory-admin") === "1") return true;
      } catch (eB) {}
      try {
        const desk = String(wallResolveDeskId() || "").trim();
        const u = desk.toUpperCase();
        if (u === "ADMIN" || u.indexOf("ADMIN") >= 0) return true;
        const badge = JSON.parse(localStorage.getItem("factory-desk-badge") || "null");
        if (badge) {
          const role = String(badge.role || badge.roles || "").toUpperCase();
          if (role.indexOf("ADMIN") >= 0) return true;
        }
      } catch (eC) {}
      return false;
    }
    function wallInviteGateOk() {
      /* INVITE chip stays hidden while the strip is being redesigned.
       * High trust does not open it. */
      return false;
    }
    function wallApplyInviteGate() {
      _wallInviteGateOk = wallInviteGateOk();
      const sec = document.getElementById("wall-welcome-invite");
      const box = document.getElementById("wall-invite-box");
      const mint = document.getElementById("wall-welcome-mint");
      const open = document.getElementById("wall-invite-open");
      if (sec) sec.hidden = !_wallInviteGateOk;
      if (box) {
        box.hidden = !_wallInviteGateOk;
        /* gate via [hidden] only - do not toggle .on (that means selected strip tab) */
        try { box.classList.remove("on"); } catch (eOn) {}
        /* live seat_count M/N when gate on (same mint owner) */
        if (_wallInviteGateOk) {
          try { wallRefreshInviteCount(); } catch (eCnt) {}
        }
      }
      if (mint) {
        mint.disabled = !_wallInviteGateOk;
        try { mint.setAttribute("data-invite-ok", _wallInviteGateOk ? "1" : "0"); } catch (eM) {}
      }
      if (open) {
        try { open.setAttribute("data-invite-ok", _wallInviteGateOk ? "1" : "0"); } catch (eO) {}
      }
    }

    function wallInviteOwner() {
      let human = "";
      let owner = "";
      try {
        human = localStorage.getItem("factory-human") || "";
        owner = human || localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || "builder";
      } catch (eLs) {
        owner = "builder";
      }
      return { owner: owner };
    }
    let _wallInviteCountInflight = null;
    let _wallInviteCountLast = "";
    /* WALL_LOADING_CONSISTENCY_WOW189: keep last-good M/N under the same compact
       spinner used by strip tabs; first load has no last-good and shows only ⏳. */
    function wallInviteCountSpinnerHtml() {
      return `<span class="kpi-load" aria-hidden="true"><span class="wall-loading-spin"></span><span class="wall-loading-ico" title="loading">⏳</span></span>`;
    }
    function wallInviteCountSetLoading(countEl) {
      const raw = String(_wallInviteCountLast || countEl.getAttribute("data-invite-count") || "").trim();
      const prior = /^\d+\/\d+$/.test(raw) ? raw : "";
      if (prior) _wallInviteCountLast = prior;
      const box = document.getElementById("wall-invite-box");
      if (box) {
        box.classList.add("kpi-loading");
        box.setAttribute("data-wall-strip-loading", "1");
        if (!box.querySelector(".kpi-load")) {
          const tmp = document.createElement("span");
          tmp.innerHTML = wallInviteCountSpinnerHtml();
          if (tmp.firstChild) box.insertBefore(tmp.firstChild, countEl);
        }
      }
      countEl.setAttribute("data-invite-count", "loading");
      countEl.textContent = prior || "⏳";
      countEl.title = prior ? "Refreshing seat_count" : "Loading seat_count";
    }
    function wallInviteCountSetSettled(countEl, value, title) {
      const text = String(value || "");
      const known = /^\d+\/\d+$/.test(text);
      const box = document.getElementById("wall-invite-box");
      if (box) {
        box.classList.remove("kpi-loading");
        box.setAttribute("data-wall-strip-loading", "0");
        const spin = box.querySelector(".kpi-load");
        if (spin) try { spin.remove(); } catch (eSpin) {}
      }
      countEl.setAttribute("data-invite-count", known ? text : "tbd");
      countEl.textContent = text;
      countEl.title = title || "";
    }
    async function wallRefreshInviteCount() {
      /* POST /api/admin/invites {action:"seat_count", owner} -> {ok, invites:N, joined:M}; display M/N.
         The door session cookie rides this same-origin fetch. */
      const countEl = document.getElementById("wall-invite-count");
      if (!countEl) return null;
      if (!_wallInviteGateOk && !wallInviteGateOk()) return null;
      wallInviteCountSetLoading(countEl);
      if (_wallInviteCountInflight) return _wallInviteCountInflight;
      const ot = wallInviteOwner();
      const body = { action: "seat_count", owner: ot.owner };
      _wallInviteCountInflight = (async () => {
        try {
          const r = await fetch("/api/admin/invites", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Mill-Wall": "1" },
            body: JSON.stringify(body),
          });
          /* Hub recycle if 404 - surface TBD; Host recycles mill-wall. */
          if (r.status === 404) {
            wallInviteCountSetSettled(countEl, _wallInviteCountLast || "TBD", "seat_count 404 - recycle Hub (mill-wall)");
            return { ok: false, status: 404 };
          }
          let data = null;
          try { data = await r.json(); } catch (eJ) { data = null; }
          if (r.ok && data && data.ok !== false && !data.error && data.invites != null && data.joined != null) {
            const n = Number(data.invites) || 0;
            const m = Number(data.joined) || 0;
            _wallInviteCountLast = m + "/" + n;
            countEl.setAttribute("data-invite-joined", String(m));
            countEl.setAttribute("data-invite-invites", String(n));
            wallInviteCountSetSettled(countEl, _wallInviteCountLast, m + " joined / " + n + " invited");
            return { ok: true, invites: n, joined: m };
          }
          if (!countEl.getAttribute("data-invite-count") || countEl.getAttribute("data-invite-count") === "tbd" || countEl.getAttribute("data-invite-count") === "loading") {
            wallInviteCountSetSettled(countEl, _wallInviteCountLast || "TBD", (data && data.error) ? String(data.error) : ("seat_count HTTP " + r.status));
          }
          return { ok: false, status: r.status, error: data && data.error };
        } catch (eFetch) {
          if (!countEl.getAttribute("data-invite-count") || countEl.getAttribute("data-invite-count") === "tbd" || countEl.getAttribute("data-invite-count") === "loading") {
            wallInviteCountSetSettled(countEl, _wallInviteCountLast || "TBD", "seat_count network fail");
          }
          return { ok: false, error: String(eFetch && eFetch.message || eFetch) };
        } finally {
          _wallInviteCountInflight = null;
        }
      })();
      return _wallInviteCountInflight;
    }

    function wallMintInvite() { return wallLazyCall("adminMint", "wallMintInvite", wallMintInvite, arguments); }

    function wallWelcomeShouldShow() {
      try {
        if (localStorage.getItem(WALL_WELCOME_HIDE_KEY) === "1") return false;
      } catch (eH) {}
      return true;
    }
    function wallWelcomeStripForceQs() {
      /* ?welcome=1 force-opens every load; strip on dismiss so refresh stays closed. */
      try {
        const u = new URL(String((typeof location !== "undefined" && location.href) || ""));
        if (!u.searchParams.has("welcome")) return;
        u.searchParams.delete("welcome");
        const q = u.searchParams.toString();
        history.replaceState(null, "", u.pathname + (q ? "?" + q : "") + (u.hash || ""));
      } catch (eStrip) {}
    }
    function wallWelcomeHide(persist) {
      /* always dismiss Nest welcome; mint pending must never block close.
       * persist factory-welcome-hide so next document load skips auto-open. */
      const el = document.getElementById("wall-welcome");
      if (el) el.hidden = true;
      if (persist) {
        try { localStorage.setItem(WALL_WELCOME_HIDE_KEY, "1"); } catch (eP) {}
      }
      wallWelcomeStripForceQs();
    }
    function wallWelcomeVisible() {
      const el = document.getElementById("wall-welcome");
      return !!(el && !el.hidden);
    }
    function wallWelcomeDismiss(persist) {
      /* default persist=true (Dismiss / Escape / X / backdrop). */
      if (persist === undefined || persist === null) persist = true;
      wallWelcomeHide(!!persist);
    }
    function wallWelcomeShow(opts) {
      const el = document.getElementById("wall-welcome");
      if (!el) return;
      el.hidden = false;
      _wallWelcomeShownThisLoad = true;
      wallApplyInviteGate();
      try { wallSeedAssignNameDefault(); } catch (eSeedShow) {}
      wallWelcomeFillJoin();
      /* optional ?welcome=1 replaceState on current Nest path - never assign /welcome. */
      try {
        if (opts && opts.stampQs) {
          const u = new URL(String((typeof location !== "undefined" && location.href) || ""));
          const p = String(u.pathname || "");
          if (p === "/welcome" || p.indexOf("/welcome") === 0) {
            u.pathname = "/";
          }
          u.searchParams.set("welcome", "1");
          history.replaceState(null, "", u.pathname + (u.searchParams.toString() ? "?" + u.searchParams.toString() : "") + (u.hash || ""));
        }
      } catch (eStamp) {}
    }
    async function wallWelcomeBoot() {
      /* Auto-open once per document load unless factory-welcome-hide is set.
       * A seat URL is not minted here. Generate creates it.
       * /welcome serves the wall and opens this card, then replaceState back to /. */
      if (_wallWelcomeShownThisLoad) return;
      const parsed = wallWelcomeParseSeat();
      if (parsed.desk || parsed.seat) {
        wallWelcomeSetInvite(
          parsed.desk && parsed.seat ? wallBuildInviteUrl(parsed.desk, parsed.seat) : "",
          parsed.desk,
          parsed.seat
        );
      }
      wallApplyInviteGate();
      const forceWelcomePath = (() => {
        try {
          const p = String((location && location.pathname) || "");
          const q = wallWelcomeQs();
          const w = String(q.get("welcome") || "").trim().toLowerCase();
          if (w === "1" || w === "on" || w === "true" || w === "open") return true;
          return p === "/welcome" || p.indexOf("/welcome") >= 0;
        } catch (ePath) { return false; }
      })();
      if (!wallWelcomeShouldShow() && !forceWelcomePath) {
        /* still wire strip gate; hide skips auto-open only */
        return;
      }
      /* Nest URL feel: /welcome -> / (keep desk/seat query); Nest glass already loaded. */
      if (forceWelcomePath) {
        try {
          const p = String((location && location.pathname) || "");
          if (p === "/welcome" || p.indexOf("/welcome") >= 0) {
            const q = String((location && location.search) || "");
            history.replaceState(null, "", "/" + (q || ""));
          }
        } catch (eRep) {}
      }
      /* Show the card first. Generate is the only mint. A hung mint must not block the wall. */
      if (parsed.desk && parsed.seat) {
        wallWelcomeSetInvite(wallBuildInviteUrl(parsed.desk, parsed.seat), parsed.desk, parsed.seat);
      } else {
        wallWelcomeFillJoin();
      }
      wallWelcomeShow();
    }
    let _wallWelcomeWired = false;
    function wallWelcomeWire() {
      if (_wallWelcomeWired) return;
      _wallWelcomeWired = true;
      const xBtn = document.getElementById("wall-welcome-x");
      if (xBtn) xBtn.addEventListener("click", () => wallWelcomeDismiss(true));
      const backdrop = document.querySelector("#wall-welcome .ww-backdrop");
      if (backdrop) backdrop.addEventListener("click", () => wallWelcomeDismiss(true));
      document.addEventListener("keydown", ev => {
        if (ev.key !== "Escape") return;
        if (!wallWelcomeVisible()) return;
        ev.preventDefault();
        wallWelcomeDismiss(true);
      });
      const mintBtn = document.getElementById("wall-welcome-mint");
      if (mintBtn) mintBtn.addEventListener("click", async () => {
        if (!_wallInviteGateOk && !wallInviteGateOk()) return;
        _wallInviteGateOk = true;
        try { await wallMintInvite(); } catch (eM) {}
      });
      const copyBtn = document.getElementById("wall-welcome-copy");
      if (copyBtn) copyBtn.addEventListener("click", () => {
        const pre = document.getElementById("wall-welcome-join");
        copyText(pre ? pre.textContent : "");
      });
      function wallInviteOpenFromStrip(ev) {
        /* Strip always reopens full welcome kit; noshow only skips auto-open on new visits. Nest overlay only (never href=/welcome or location assign). */
        try { if (ev) { ev.preventDefault(); ev.stopPropagation(); } } catch (eEv) {}
        wallApplyInviteGate();
        try { wallRefreshInviteCount(); } catch (eStripCnt) {}
        wallWelcomeShow({ stampQs: true });
        const sec = document.getElementById("wall-welcome-invite");
        if (sec) {
          sec.hidden = !_wallInviteGateOk;
          try { sec.scrollIntoView({ block: "nearest" }); } catch (eS) {}
        }
      }
      const open = document.getElementById("wall-invite-open");
      if (open) open.addEventListener("click", wallInviteOpenFromStrip);
      /* Capture delegation: survives strip() innerHTML rebuilds; INVITE opens welcome only
       * (stopPropagation so it never falls through to strip-nav pane switching). */
      if (!document._wallInviteOpenDelegated) {
        document._wallInviteOpenDelegated = true;
        document.addEventListener("click", function (ev) {
          const t = ev.target;
          const chip = t && t.closest ? t.closest("#wall-invite-box") : null;
          if (!chip) return;
          wallInviteOpenFromStrip(ev);
        }, true);
      }
      try { window.wallInviteOpenFromStrip = wallInviteOpenFromStrip; } catch (eWinInv) {}
      /* trust re-gate hooked after wallRememberTrust (below) */
    }
    /* wallWelcomeWire+Boot scheduled after wallRememberTrust */

    let showReads = false;
    let wireDetails = false;
    let wireProto = "";
    const WIRE_QUIET = {sweep:1, read:1, observer:1, "wall-poll":1, poll:1};
    const WIRE_PROTO = [["","all"],["mail","mail"],["lock","stations"],["cards","todo"],["presence","presence"]];
    const WIRE_KIND = {send:"mail",kpi:"kpi",refuse:"refuse",acquire:"lock",release:"lock",steal:"lock",ask:"cards",volunteer:"cards",yield:"cards",done:"cards",progress:"cards",issue:"issues","issue-status":"issues",register:"presence",unregister:"presence",recover:"recover",drift:"recover"};
    function millGid(r) {
      return String((r && r.roster_id) || ""); /* #869 rule-roster-fields: roster_id only */
    }
    /* Display the stored name. Counts are not name ids. */
    function millNameBare(kind, raw) {
      return String(raw || "").trim();
    }
    function millName(kind, raw) {
      return millNameBare(kind, raw);
    }
    function millInc(map, key) {
      key = String(key || "").trim();
      if (!key) return;
      map[key] = (map[key] || 0) + 1;
    }
    function millPairs(map) {
      return Object.keys(map).sort((a, b) => a.localeCompare(b)).map(k => ({ name: k, n: map[k] }));
    }
    const HINT_KEY = "factory-howto";
    const POS_KEY = "factory-howto-pos";
    const hint = document.getElementById("howto-card");
    const hintBtn = document.getElementById("howto-toggle");
    function homeHint() {
      hint.style.left = "";
      hint.style.top = "";
      hint.style.right = "";
      try { localStorage.removeItem(POS_KEY); } catch (e) {}
    }
    function setHint(on) {
      hint.hidden = !on;
      hintBtn.setAttribute("aria-expanded", on ? "true" : "false");
      try { localStorage.setItem(HINT_KEY, on ? "on" : "off"); } catch (e) {}
    }
    hintBtn.addEventListener("click", () => {
      if (!hint.hidden) {
        homeHint();
        setHint(false);
      } else {
        setHint(true);
      }
    });
    (function wireHeaderMore() {
      const moreBtn = document.getElementById("header-more-btn");
      const moreMenu = document.getElementById("header-more-menu");
      if (!moreBtn || !moreMenu) return;
      moreBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const open = moreMenu.hidden;
        moreMenu.hidden = !open;
        moreBtn.setAttribute("aria-expanded", open ? "true" : "false");
      });
      document.addEventListener("click", (ev) => {
        if (moreMenu.hidden) return;
        if (ev.target.closest(".header-more")) return;
        moreMenu.hidden = true;
        moreBtn.setAttribute("aria-expanded", "false");
      });
    })();
    document.getElementById("howto-dismiss").addEventListener("click", () => {
      homeHint();
      setHint(false);
    });
    let hintOn = false;
    try { hintOn = localStorage.getItem(HINT_KEY) === "on"; } catch (e) {}
    setHint(hintOn);
    function clampHint(x, y) {
      const w = hint.offsetWidth || 280;
      const hgt = hint.offsetHeight || 200;
      const grip = 48;
      const minX = grip - w;
      const maxX = window.innerWidth - grip;
      const minY = grip - hgt;
      const maxY = window.innerHeight - grip;
      return {
        x: Math.min(maxX, Math.max(minX, x)),
        y: Math.min(maxY, Math.max(minY, y)),
      };
    }
    function placeHint(x, y) {
      const p = clampHint(x, y);
      hint.style.left = p.x + "px";
      hint.style.top = p.y + "px";
      hint.style.right = "auto";
    }
    function saveHintPos() {
      const r = hint.getBoundingClientRect();
      try { localStorage.setItem(POS_KEY, JSON.stringify({ x: r.left, y: r.top })); } catch (e) {}
    }
    try {
      const saved = JSON.parse(localStorage.getItem(POS_KEY) || "null");
      if (saved && typeof saved.x === "number" && typeof saved.y === "number") placeHint(saved.x, saved.y);
    } catch (e) {}
    (function dragHint() {
      let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
      hint.addEventListener("pointerdown", ev => {
        if (ev.target.closest(".dismiss, .jump")) return;
        dragging = true;
        hint.classList.add("dragging");
        hint.setPointerCapture(ev.pointerId);
        const r = hint.getBoundingClientRect();
        sx = ev.clientX; sy = ev.clientY; ox = r.left; oy = r.top;
        ev.preventDefault();
      });
      hint.addEventListener("pointermove", ev => {
        if (!dragging) return;
        placeHint(ox + ev.clientX - sx, oy + ev.clientY - sy);
      });
      const stop = () => {
        if (!dragging) return;
        dragging = false;
        hint.classList.remove("dragging");
        saveHintPos();
      };
      hint.addEventListener("pointerup", stop);
      hint.addEventListener("pointercancel", stop);
      window.addEventListener("resize", () => {
        const r = hint.getBoundingClientRect();
        placeHint(r.left, r.top);
      });
    })();

    let holdTick = false;
    let skipSortUntil = 0;
    const LAYOUT_KEY = "factory-layout";
    const ICON_LIST = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M2 4h12M2 8h12M2 12h12"/></svg>';
    const ICON_TILES = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z"/></svg>';
    function loadLayout() {
      try { return JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}"); } catch (e) { return {}; }
    }
    function layoutOf(id) {
      return loadLayout()[id] === "tiles" ? "tiles" : "list";
    }
    function saveLayout(id, mode) {
      const all = loadLayout();
      all[id] = mode === "tiles" ? "tiles" : "list";
      try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(all)); } catch (e) {}
    }
    function paintLayoutToggles() {
      document.querySelectorAll(".layout-toggle").forEach(box => {
        if (box.id === "board-view-toggle") return;
        const id = box.dataset.layoutId;
        const cur = layoutOf(id);
        if (!box.querySelector("button")) {
          box.innerHTML =
            `<button type="button" data-layout="list" title="list">${ICON_LIST}</button>` +
            `<button type="button" data-layout="tiles" title="tiles">${ICON_TILES}</button>`;
          box.querySelectorAll("button").forEach(btn => {
            btn.addEventListener("click", ev => {
              ev.preventDefault();
              ev.stopPropagation();
              saveLayout(id, btn.dataset.layout);
              paintLayoutToggles();
              if (window._floor) {
                const d = window._floor;
                paintHero(d); board(d); issues(d); wire(d); mail(d); stations(d); agents(d); cards(d);
                enhanceTables(document);
                markOverflow();
              }
            });
          });
        }
        box.querySelectorAll("button").forEach(btn => {
          btn.setAttribute("aria-pressed", btn.dataset.layout === cur ? "true" : "false");
        });
      });
    }
    const BOARD_VIEW_KEY = "factory-board-view";
    const PLAN_CHROME_KEY = "factory-plan-chrome";
    const ICON_KANBAN = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M2.5 2.5h3v11h-3zM6.5 2.5h3v11h-3zM10.5 2.5h3v11h-3z"/></svg>';
    function boardView() {
      try { return localStorage.getItem(BOARD_VIEW_KEY) === "kanban" ? "kanban" : "list"; } catch (e) { return "list"; }
    }
    function saveBoardView(mode) {
      try { localStorage.setItem(BOARD_VIEW_KEY, mode === "kanban" ? "kanban" : "list"); } catch (e) {}
    }
    function paintBoardViewToggle() {
      const box = document.getElementById("board-view-toggle");
      if (!box) return;
      const cur = boardView();
      if (!box.querySelector("button")) {
        box.innerHTML =
          `<button type="button" data-board-view="list" title="list">${ICON_LIST}</button>` +
          `<button type="button" data-board-view="kanban" title="kanban">${ICON_KANBAN}</button>`;
        box.querySelectorAll("button").forEach(btn => {
          btn.addEventListener("click", ev => {
            ev.preventDefault();
            ev.stopPropagation();
            saveBoardView(btn.dataset.boardView);
            paintBoardViewToggle();
            applyBoardView();
            if (window._floor) {
              issues(window._floor);
              enhanceTables(document.getElementById("pane-backlog"));
              markOverflow();
            }
          });
        });
      }
      box.querySelectorAll("button").forEach(btn => {
        btn.setAttribute("aria-pressed", btn.dataset.boardView === cur ? "true" : "false");
      });
    }
    function applyBoardView() {
      /* WALL_PLAN_TAB: list/cards only - no kanban */
      const pane = document.getElementById("pane-backlog");
      if (!pane) return;
      pane.classList.add("board-list");
    }
    function tileGrid(headers, rows) {
      return `<div class="tile-grid">` + rows.map(r => {
        const body = (r.cells || []).map((c, i) =>
          `<div class="tile-row"><span class="tile-k">${esc(headers[i] || "")}</span>` +
          `<span class="tile-v">${c}</span></div>`
        ).join("");
        return `<div class="tile ${r.className || ""}">${body}</div>`;
      }).join("") + `</div>`;
    }
    const COL_KEY = "factory-table-cols";
    const SORT_KEY = "factory-table-sort";
    const WRAP_KEY = "factory-table-wrap";
    const WRAP_ON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M2 3.5h12M2 8h8.5A2.5 2.5 0 0 1 11 13H7"/><path fill="none" stroke="currentColor" stroke-width="1.4" d="M8.2 11.2 6.5 13l1.7 1.8"/></svg>';
    const WRAP_OFF = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M2 4h12M2 8h12M2 12h8"/></svg>';
    function loadWrap() {
      try { return JSON.parse(localStorage.getItem(WRAP_KEY) || "{}"); } catch (e) { return {}; }
    }
    function saveWrap(id, on) {
      const all = loadWrap();
      all[id] = !!on;
      try { localStorage.setItem(WRAP_KEY, JSON.stringify(all)); } catch (e) {}
    }
    function fatColIndex(tbl) {
      const id = tbl.getAttribute("data-table") || "";
      if (id === "wire") return 4;
      if (id === "mail") return 6;
      const heads = tbl.tHead && tbl.tHead.rows[0] ? [...tbl.tHead.rows[0].cells] : [];
      const names = heads.map(h => (h.innerText || "").replace(/[\u25b2\u25bc]/g, "").trim().toLowerCase());
      const prefer = ["body", "detail", "details", "note", "doing", "last ping"];
      for (const p of prefer) {
        const i = names.indexOf(p);
        if (i >= 0) return i;
      }
      const marked = tbl.querySelector("tbody td.body, tbody td.detail, tbody td.fat");
      if (marked) return marked.cellIndex;
      return Math.max(0, heads.length - 1);
    }
    function layoutTableCols(tbl, wrap) {
      if (!tbl || !wrap) return;
      const cg = tbl.querySelector("colgroup");
      const on = wrap.classList.contains("cell-wrap");
      tbl.style.maxWidth = "100%";
      if (!on) {
        tbl.style.width = "100%";
        tbl.style.tableLayout = "auto";
        if (cg) [...cg.children].forEach(col => { col.style.width = ""; });
        return;
      }
      const fat = fatColIndex(tbl);
      tbl.style.width = "100%";
      tbl.style.tableLayout = "fixed";
      if (cg) [...cg.children].forEach((col, i) => {
        col.style.width = i === fat ? "70%" : "auto";
      });
      tbl.querySelectorAll("tbody td").forEach(td => {
        td.classList.toggle("fat", td.cellIndex === fat);
      });
    }
    function applyWrap(wrap, id, on) {
      wrap.classList.toggle("cell-wrap", on);
      const btn = wrap.querySelector(".tbl-wrap-btn");
      if (btn) {
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        btn.title = on ? "clip columns" : "wrap columns";
        btn.setAttribute("aria-label", btn.title);
        btn.innerHTML = on ? WRAP_OFF : WRAP_ON;
      }
      layoutTableCols(wrap.querySelector("table"), wrap);
    }
    function loadColWidths() {
      try { return JSON.parse(localStorage.getItem(COL_KEY) || "{}"); } catch (e) { return {}; }
    }
    function saveColWidths(id, widths) {
      const all = loadColWidths();
      all[id] = widths;
      try { localStorage.setItem(COL_KEY, JSON.stringify(all)); } catch (e) {}
    }
    function loadSort() {
      try { return JSON.parse(localStorage.getItem(SORT_KEY) || "{}"); } catch (e) { return {}; }
    }
    function saveSort(id, spec) {
      const all = loadSort();
      all[id] = spec;
      try { localStorage.setItem(SORT_KEY, JSON.stringify(all)); } catch (e) {}
    }
    function sortSpec(id) {
      const saved = loadSort()[id];
      if (saved && typeof saved.col === "number") return saved;
      if (id === "wire" || id === "mail" || (id && id.indexOf("score-loop-") === 0)) {
        return { col: 0, dir: "desc" };
      }
      return null;
    }
    function cellSortVal(cell) {
      if (!cell) return "";
      return (cell.getAttribute("data-sort") || cell.innerText || "").trim();
    }
    /* WALL_UI_LIB_TABLE: prefer wallSortTable when loaded */
    function sortTable(tbl, spec) {
      if (typeof wallSortTable === "function") { wallSortTable(tbl, spec); return; }
      const tbody = tbl.tBodies && tbl.tBodies[0];
      if (!tbody || !spec) return;
      const idx = spec.col;
      const dir = spec.dir === "asc" ? 1 : -1;
      const rows = [...tbody.rows];
      rows.sort((a, b) => {
        const sa = cellSortVal(a.cells[idx]);
        const sb = cellSortVal(b.cells[idx]);
        const na = Number(sa), nb = Number(sb);
        if (sa !== "" && sb !== "" && !isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
        return sa.localeCompare(sb, undefined, { numeric: true, sensitivity: "base" }) * dir;
      }).forEach(r => tbody.appendChild(r));
      const heads = tbl.tHead ? [...tbl.tHead.rows[0].cells] : [];
      heads.forEach((th, i) => {
        th.classList.toggle("sort-asc", spec.dir === "asc" && i === idx);
        th.classList.toggle("sort-desc", spec.dir === "desc" && i === idx);
      });
    }
    function toast(msg) {
      const el = document.getElementById("copy-toast");
      el.textContent = msg || "copied";
      el.hidden = false;
      clearTimeout(toast._t);
      toast._t = setTimeout(() => { el.hidden = true; }, 900);
    }
    function copyText(text) {
      const val = String(text ?? "").trim();
      if (!val) return;
      const go = () => toast("copied");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(val).then(go).catch(() => {
          const ta = document.createElement("textarea");
          ta.value = val;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
          go();
        });
      } else {
        const ta = document.createElement("textarea");
        ta.value = val;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        go();
      }
    }
    function tableTsv(tbl) {
      return [...tbl.rows].map(row =>
        [...row.cells].map(c => c.innerText.replace(/\s+/g, " ").trim()).join("\t")
      ).join("\n");
    }
    function rowsTsv(sel, root) {
      const host = root || document;
      return [...host.querySelectorAll(sel)].map(row =>
        [...row.children].map(c => c.innerText.replace(/\s+/g, " ").trim()).join("\t")
      ).join("\n");
    }
    function ensureCopyBtn(host, getText) {
      if (!host) return;
      let btn = host.querySelector(":scope > .tbl-copy");
      if (!btn) {
        btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tbl-copy";
        btn.textContent = "copy";
        btn.title = "Copy all columns to the clipboard";
        host.appendChild(btn);
        btn.addEventListener("click", ev => {
          ev.preventDefault();
          ev.stopPropagation();
          const val = typeof getText === "function" ? getText() : getText;
          copyText(val);
        });
      }
    }
    function visibleColumnsTsv() {
      const pane = document.querySelector(".pane.on");
      if (!pane) return "";
      const tables = [...pane.querySelectorAll(".pane-body table, table")].filter(t => t.offsetParent);
      if (tables.length) return tables.map(tableTsv).join("\n\n");
      const hist = pane.querySelector(".hist-row");
      if (hist) return rowsTsv(".hist-row", pane);
      const spend = pane.querySelector(".spend-row");
      if (spend) return rowsTsv(".spend-row", pane);
      const list = document.getElementById("jobs-list");
      if (list && !list.hidden && list.querySelector(".todo-list-row")) return rowsTsv(".todo-list-row", list);
      const cards = [...pane.querySelectorAll("#jobs-kanban .body > *")].filter(el => !el.classList.contains("jobs-col-gutter"));
      if (cards.length) return cards.map(el => el.innerText.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
      return "";
    }
    function wirePaneCopy() {
      document.querySelectorAll(".pane-filters").forEach(slot => {
        ensureCopyBtn(slot, visibleColumnsTsv);
      });
    }
    function enhanceTables(root) {
      (root || document).querySelectorAll("table").forEach(tbl => {
        if (tbl.closest("#howto-card")) return;
        let wrap = tbl.parentElement;
        if (!wrap || !wrap.classList.contains("tbl-wrap")) {
          wrap = document.createElement("div");
          wrap.className = "tbl-wrap";
          tbl.parentNode.insertBefore(wrap, tbl);
          wrap.appendChild(tbl);
        }
        if (!wrap.closest(".pane-body")) ensureCopyBtn(wrap, () => tableTsv(tbl));
        const n = (tbl.tHead && tbl.tHead.rows[0] ? tbl.tHead.rows[0].cells.length
          : (tbl.rows[0] ? tbl.rows[0].cells.length : 0));
        if (!n) return;
        let cg = tbl.querySelector("colgroup");
        if (!cg) {
          cg = document.createElement("colgroup");
          for (let i = 0; i < n; i++) cg.appendChild(document.createElement("col"));
          tbl.insertBefore(cg, tbl.firstChild);
        }
        const id = tbl.getAttribute("data-table") || "table";
        applyWrap(wrap, id, !!loadWrap()[id]);
        const heads = tbl.tHead ? [...tbl.tHead.rows[0].cells] : [];
        heads.forEach((th, i) => {
          if (th.querySelector(".col-resizer")) return;
          const grip = document.createElement("span");
          grip.className = "col-resizer";
          grip.title = "drag to resize";
          th.appendChild(grip);
          grip.addEventListener("pointerdown", ev => {
            ev.preventDefault();
            ev.stopPropagation();
            holdTick = true;
            const startX = ev.clientX;
            const startWidths = [...cg.children].map((c, j) => {
              const w = c.getBoundingClientRect().width
                || (heads[j] ? heads[j].getBoundingClientRect().width : 0);
              return Math.max(48, w);
            });
            const apply = widths => {
              [...cg.children].forEach((c, j) => { c.style.width = widths[j] + "px"; });
              tbl.style.width = "100%";
            };
            apply(startWidths);
            try { grip.setPointerCapture(ev.pointerId); } catch (e) {}
            let dragged = false;
            const move = e => {
              const dx = e.clientX - startX;
              if (Math.abs(dx) < 2 && !dragged) return;
              dragged = true;
              const next = startWidths.slice();
              next[i] = Math.max(48, startWidths[i] + dx);
              apply(next);
            };
            const up = () => {
              grip.removeEventListener("pointermove", move);
              grip.removeEventListener("pointerup", up);
              grip.removeEventListener("pointercancel", up);
              const widths = [...cg.children].map(c =>
                Math.max(48, Math.round(c.getBoundingClientRect().width || 48)));
              apply(widths);
              saveColWidths(id, widths);
              if (dragged) skipSortUntil = Date.now() + 400;
              holdTick = false;
            };
            grip.addEventListener("pointermove", move);
            grip.addEventListener("pointerup", up);
            grip.addEventListener("pointercancel", up);
          });
        });
        tbl.querySelectorAll("td").forEach(cell => {
          if (cell.dataset.copyBound) return;
          cell.dataset.copyBound = "1";
          cell.addEventListener("click", ev => {
            if (ev.target.closest(".col-resizer")) return;
            if (window.getSelection && String(window.getSelection())) {
              const sel = String(window.getSelection());
              if (sel.length > 0 && cell.contains(window.getSelection().anchorNode)) return;
            }
            copyText(cell.innerText);
            cell.classList.add("copied");
            setTimeout(() => cell.classList.remove("copied"), 600);
          });
        });
        heads.forEach((th, i) => {
          if (th.dataset.sortBound) return;
          th.dataset.sortBound = "1";
          th.title = (th.title ? th.title + " | " : "") + "click to sort";
          th.addEventListener("click", ev => {
            if (ev.target.closest(".col-resizer")) return;
            if (Date.now() < skipSortUntil) return;
            const cur = sortSpec(id) || { col: i, dir: "asc" };
            const next = (cur.col === i && cur.dir === "desc")
              ? { col: i, dir: "asc" }
              : { col: i, dir: "desc" };
            saveSort(id, next);
            sortTable(tbl, next);
          });
        });
        const spec = sortSpec(id);
        if (spec) sortTable(tbl, spec);
      });
    }
    function markOverflow() {
      document.querySelectorAll(".has-more").forEach(el => el.classList.remove("has-more"));
      const pairs = [];
      const add = (scroll, host) => { if (scroll) pairs.push({ scroll: scroll, host: host || scroll }); };
      document.querySelectorAll("#pane-todo .jobs-kanban-col .body").forEach(b => add(b, b.closest(".jobs-kanban-col")));
      add(document.getElementById("here"), document.getElementById("sec-here") || document.getElementById("here"));
      add(document.querySelector("#pane-session .session-wire"));
      add(document.querySelector("#pane-session #sec-leases .body"), document.getElementById("sec-leases"));
      add(document.getElementById("jobs-list"));
      add(document.getElementById("floor-timeline"));
      document.querySelectorAll(".mail-col").forEach(c => add(c));
      add(document.getElementById("score-desk-table"));
      add(document.getElementById("score-human"));
      add(document.querySelector("#score-spend-view .spend-body"));
      add(document.getElementById("guide-body"));
      pairs.forEach(({ scroll, host }) => {
        if (!scroll || scroll.hidden || (host && host.hidden)) return;
        const ch = scroll.clientHeight;
        if (ch < 16) return;
        const overflow = scroll.scrollHeight > ch + 8;
        const atEnd = scroll.scrollTop + ch >= scroll.scrollHeight - 6;
        const on = overflow && !atEnd;
        host.classList.toggle("has-more", on);
        if (!scroll._moreScroll) {
          scroll._moreScroll = true;
          scroll.addEventListener("scroll", () => {
            const c = scroll.clientHeight;
            const ov = scroll.scrollHeight > c + 8;
            const end = scroll.scrollTop + c >= scroll.scrollHeight - 6;
            host.classList.toggle("has-more", ov && !end);
            hideIdleControls(window._floor);
          }, { passive: true });
        }
      });
      hideIdleControls(window._floor);
    }
    window.markOverflow = markOverflow;
    try {
      const _markOverflowBase = markOverflow;
      window.markOverflow = function () {
        try { _markOverflowBase(); } catch (eBase) {}
        try { if (typeof wallWireListInfiniteScroll === "function") wallWireListInfiniteScroll(); } catch (eWire) {}
      };
      markOverflow = window.markOverflow;
    } catch (eWrapMore) {}
    function hideIdleControls(d) {
      const text = document.getElementById("text-mode");
      if (text) {
        const pane = document.querySelector(".pane.on");
        const overflowing = !!(pane && pane.querySelector(".has-more"));
        const mode = document.body.getAttribute("data-text-mode") || "clip";
        text.hidden = !overflowing && mode === "clip";
      }
      const doneSpan = document.getElementById("todo-done-span");
      if (doneSpan) {
        const cards = (typeof millTodoCards === "function" && d) ? millTodoCards(d) : [];
        doneSpan.hidden = !cards.some(r => r && r.status === "done");
      }
      const legend = document.getElementById("floor-legend");
      if (legend && d) {
        const desks = ((d.office_glance && d.office_glance.desks) || d.agents || []);
        const states = {};
        desks.forEach(a => {
          const named = String((a && (a.state || a.status)) || "");
          const st = (named || wallDoingText(a && a.owner, a && a.doing)).toLowerCase();
          if (st.indexOf("wait") >= 0) states.waiting = true;
          else if (st === "idle" || st === "here" || st === "gone") states.idle = true;
          else if (st) states.working = true;
        });
        const lg = (name) => legend.querySelector(".lg-" + name);
        const w = lg("working"); if (w) w.hidden = !states.working;
        const i = lg("idle"); if (i) i.hidden = !states.idle;
        const v = lg("waiting"); if (v) v.hidden = !states.waiting;
        legend.hidden = !states.working && !states.idle && !states.waiting;
      }
    }
    const kindClass = k => "k k-" + (k || "");
    const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
    const t = v => {
      if (!v) return "-";
      const s = String(v);
      return s.length > 19 ? s.slice(11, 19) : s;
    };
    const dt = v => {
      if (!v) return "-";
      const s = String(v).replace("T", " ");
      return s.length >= 19 ? s.slice(0, 19) : s;
    };
    let hiTimer = 0;
    function highlight(ids) {
      document.querySelectorAll(".hi").forEach(el => el.classList.remove("hi"));
      const list = (ids || "").split(",").map(s => s.trim()).filter(Boolean);
      const els = list.map(id => document.getElementById(id)).filter(Boolean);
      els.forEach(el => el.classList.add("hi"));
      if (els[0]) els[0].scrollIntoView({ block: "nearest", behavior: "smooth" });
      clearTimeout(hiTimer);
      hiTimer = setTimeout(() => {
        document.querySelectorAll(".hi").forEach(el => el.classList.remove("hi"));
      }, 3500);
    }
    /* Load opens the first subtab. A later pick lasts until refresh. */
    let todoView = "board";
    function setJobsView(view) {
      const pane = document.getElementById("pane-todo") || document.getElementById("pane-jobs");
      if (!pane) return;
      let v = String(view || "board");
      if (v === "plan" || v === "trees") v = "nest";
      if (v !== "list" && v !== "nest") v = "board";
      todoView = v;
      pane.classList.toggle("jobs-view-list", v === "list");
      pane.classList.toggle("jobs-view-nest", v === "nest");
      pane.classList.toggle("jobs-view-plan", v === "nest"); /* alias: old CSS / plan nest */
      const kanban = document.getElementById("jobs-kanban");
      const jl = document.getElementById("jobs-list");
      const outline = document.getElementById("jobs-outline");
      if (kanban) kanban.hidden = v !== "board";
      if (jl) jl.hidden = v !== "list";
      if (outline) outline.hidden = v !== "nest";
      const doneSpan = document.getElementById("todo-done-span");
      const nestFilters = document.getElementById("todo-nest-filters");
      if (doneSpan) doneSpan.hidden = v === "nest";
      if (nestFilters) nestFilters.hidden = v !== "nest";
      if (v === "nest") { try { paintTreesWindowChips(); } catch (eTw) {} }
      document.querySelectorAll("[data-todo-view]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-todo-view") === v);
      });

      const sub = document.getElementById("jobs-view-sub");
      if (sub) {
        if (v === "nest") sub.textContent = "plans | chart left to right";
        else sub.textContent = "one card | parked / open / claimed / shipped / done";
      }
      /* Picking Plan does not rename the address, so a refresh returns to Board. */
      const todoOn = pane.classList.contains("on");
      if (todoOn) {
        if (v === "nest") {
          if (window._floor) paintPlan(window._floor);
        } else if (location.hash === "#nest" || location.hash === "#trees" || location.hash === "#plan") {
          if (location.hash !== "#jobs") location.hash = "jobs";
        }
      } else if (v === "nest" && window._floor) {
        /* keep nest outline warm without changing strip tab */
        try { paintPlan(window._floor); } catch (eNest) {}
      }
      /* bump gen + overlay; never blank prior TODO DOM; keep theme. */
      if (todoOn) {
        try { wallBumpSwitchGen(); } catch (eGenJ) {}
        try { wallRestoreActivePaneFromFloor({ force: true }); } catch (eRestJ) {}
        try { wallShowPaneOverlay("pane-todo", "Checking\u2026"); } catch (eOv) {}
        if (typeof wallReuseInflightForReturn === "function" && wallReuseInflightForReturn()) {
          /* reuse in-flight */
        } else if (typeof tick === "function") {
          try { tick(true); } catch (eTickJobs) {}
        }
      }
    }
    function paintStripTab(name) {
      let key = String(name || "session");
      if (key === "leases" || key === "stations") key = "session";
      if (key === "jobs" || key === "todo") key = "jobs";
      if (key === "scorecards") key = "score";
      if (key === "trees" || key === "plan" || key === "nest") key = "jobs";
      const map = { session: "strip-here", floor: "strip-floor", jobs: "strip-todo", score: "strip-score", mail: "strip-mail" };
      const id = map[key] || "strip-here";
      document.querySelectorAll(".strip .kpi.strip-nav").forEach(el => {
        if (el.id === "wall-invite-box") {
          try { el.classList.remove("on"); } catch (eInvOn) {}
          return;
        }
        el.classList.toggle("on", el.id === id);
      });
    }
    function showSubnav(name) {
      let key = String(name || "session");
      if (key === "stations" || key === "leases") key = "session";
      if (key === "trees" || key === "plan" || key === "nest") key = "jobs";
      if (key === "backlog" || key === "board" || key === "issues" || key === "todo") key = "jobs";
      if (key === "scorecards") key = "score";
      document.querySelectorAll("#subnav .subnav-set").forEach(el => {
        el.hidden = el.getAttribute("data-for") !== key;
      });
    }

    const WALL_TAB_KEY = "factory-wall-tab";
    const WALL_TAB_OK = ["session", "jobs", "plan", "trees", "nest", "backlog", "board", "issues", "mail", "wire", "stations", "leases", "watch", "score", "guide", "glossary", "admin", "floor"];
    function loadWallTab() {
      try {
        const v = String(localStorage.getItem(WALL_TAB_KEY) || "").trim();
        if (v && WALL_TAB_OK.includes(v)) return v;
      } catch (e) {}
      return "session";
    }
    function saveWallTab(name) {
      const v = String(name || "").trim();
      if (!v || !WALL_TAB_OK.includes(v)) return;
      try { localStorage.setItem(WALL_TAB_KEY, v); } catch (e) {}
    }

    function wallSetOlderHidden(hidden) {
      /* CONNECTED keeps its subnav hidden. Promise, History, and Watch are not offered. */
      const sub = document.getElementById("subnav");
      if (sub) sub.classList.toggle("is-later", !!hidden);
    }
    function showTab(name) {
      if (name === "stations" || name === "leases" || name === "watch") {
        try { wallBumpSwitchGen(); } catch (eGenS) {}
        paintStripTab("session");
        showSubnav("session");
        document.querySelectorAll("nav.tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === "session"));
        document.querySelectorAll(".pane").forEach(p => p.classList.toggle("on", p.id === "pane-session"));
        const mode = name === "watch" ? "watch" : "leases";
        if (typeof window.setSessionMode === "function") window.setSessionMode(mode);
        wallSetOlderHidden(true);
        const wantHash = mode === "watch" ? "#watch" : "#leases";
        if (location.hash !== wantHash && !(mode === "leases" && location.hash === "#stations")) location.hash = wantHash.slice(1);
        saveWallTab(mode === "watch" ? "watch" : "leases");
        requestAnimationFrame(() => requestAnimationFrame(() => highlight(mode === "watch" ? "sec-watch" : "sec-leases")));
        return;
      }
      // Nest lives under TODO (Board | List | Nest). #trees/#plan/#nest open TODO+Nest.
      let nestAlias = null;
      if (name === "trees" || name === "plan" || name === "nest") {
        nestAlias = name;
        name = "jobs";
      }
      // backlog/board/issues hashes land on TODO
      let planAlias = null;
      if (name === "backlog" || name === "board" || name === "issues") {
        planAlias = name;
        name = "jobs";
      }
      const tabHighlight = name;
      paintStripTab(tabHighlight);
      showSubnav(tabHighlight);
      wallSetOlderHidden(name === "session");
      // OOTB_UX + WALL_UI_LOCK + ADMIN_CHROME_ORDER: Session|Floor|Jobs|Scorecards|Mail|Plan; Admin in top chrome (Admin|Debug|Guide)
      document.querySelectorAll("nav.tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tabHighlight));
      const paneId = name === "jobs" ? "pane-todo" : ("pane-" + name);
      document.querySelectorAll(".pane").forEach(p => p.classList.toggle("on", p.id === paneId || p.id === "pane-" + name));
      if (name === "jobs") {
        let v = todoView || "board";
        if (nestAlias) v = "nest";
        if (v === "plan" || v === "trees") v = "nest";
        setJobsView(v);
      }
      if (nestAlias) {
        const h = nestAlias === "nest" ? "nest" : nestAlias;
        if (location.hash !== "#" + h) location.hash = h;
      } else if (planAlias) {
        if (location.hash !== "#jobs" && location.hash !== "#plan") location.hash = "jobs";
        requestAnimationFrame(() => requestAnimationFrame(() => highlight("sec-parked")));
      } else if (location.hash !== "#" + name) {
        location.hash = name;
      }
      saveWallTab(nestAlias || planAlias || name);
      if (name === "score") _scoreGlanceUser = false;
      document.querySelectorAll(".ops-chrome").forEach(el => {
        const want = (name === "admin" || name === "wire" || location.hash === "#admin" || location.hash === "#wire");
        el.hidden = !want;
      });
      (function parkTextMode() {
        const text = document.getElementById("text-mode");
        const pane = document.querySelector(".pane.on");
        const slot = pane && pane.querySelector(".pane-filters");
        if (text && slot && text.parentElement !== slot) slot.appendChild(text);
        if (typeof wirePaneCopy === "function") wirePaneCopy();
      })();
      if (typeof window.syncTextModeForTab === "function") window.syncTextModeForTab(name);
      if (typeof window.markOverflow === "function") {
        requestAnimationFrame(() => { try { window.markOverflow(); } catch (e) {} });
      }
      if (name === "guide") loadGuide();
      if (name === "glossary") paintGlossary();
      /* translucent Checking overlay (last-good visible under); stays until fp confirms.
         Checking overlay; last-good stays until tick fp confirms refresh.
         gen guard; keep-prior restore only if empty. */
      const switchGen = wallBumpSwitchGen();
      try { wallRestoreActivePaneFromFloor({ force: true }); } catch (eRestShow) {}
      try {
        if (name === "mail") wallShowPaneOverlay("pane-mail", "Checking\u2026");
        else if (name === "jobs") wallShowPaneOverlay("pane-todo", "Checking\u2026");
        else if (name === "floor") wallShowPaneOverlay("pane-floor", "Checking\u2026");
        else if (name === "score" || name === "scorecards") wallShowPaneOverlay("pane-score", "Checking\u2026");
        else if (name === "session") wallShowPaneOverlay("pane-session", "Checking\u2026");
        else wallClearActivePaneOverlay();
      } catch (eOvS) {}
            /* no provisional body paint under Checking overlay.
         if same-pane in-flight fetch exists, reuse it (no second DB call). */
      if (typeof wallReuseInflightForReturn === "function" && wallReuseInflightForReturn()) {
        /* keep Checking until in-flight settle paints live */
      } else if (typeof tick === "function") {
        tick(true);
      }
      /* Wave 2: load domain CSS/JS only; tick paints after fp settle (no provisional ensure*Paint). */
      if (name === "jobs" && typeof wallEnsureDomain === "function") {
        wallEnsureDomain("todo").catch(function () {});
      }
      if (name === "mail" && typeof wallEnsureDomain === "function") {
        wallEnsureDomain("mail").catch(function () {});
      }
      if ((name === "score" || name === "scorecards") && typeof wallEnsureDomain === "function") {
        wallEnsureDomain("score").catch(function () {});
      }      /* #710: COLLAB paint code and its map load together on the tab. */
      if (name === "floor" && typeof wallEnsureModule === "function") {
        wallEnsureModule("floorPaint").catch(function () {});
      }
    }
    function mdLite(src) {
      const raw = String(src || "").replace(/\r\n/g, "\n");
      const blocks = raw.split(/\n{2,}/);
      return blocks.map(block => {
        const lines = block.split("\n");
        if (lines[0].startsWith("# ")) return `<h1>${inline(lines[0].slice(2))}</h1>`;
        if (lines[0].startsWith("## ")) return `<h2>${inline(lines[0].slice(3))}</h2>` + (lines.length > 1 ? `<p>${inline(lines.slice(1).join(" "))}</p>` : "");
        if (lines[0].startsWith("```")) {
          const body = lines.slice(1).filter(l => l !== "```").join("\n");
          return `<pre>${esc(body)}</pre>`;
        }
        if (lines[0].startsWith("|")) {
          const rows = lines.filter(l => l.startsWith("|") && !/^\|[\s:|-]+\|$/.test(l.trim()));
          const cells = rows.map(r => r.split("|").slice(1, -1).map(c => c.trim()));
          if (!cells.length) return "";
          const head = cells[0].map(c => `<th>${inline(c)}</th>`).join("");
          const body = cells.slice(1).map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("");
          return `<table data-table="guide"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
        }
        if (lines.every(l => l.startsWith("|") || l.startsWith("- ") || l.startsWith("* "))) {
          /* fall through */
        }
        if (lines[0].startsWith("- ") || lines[0].startsWith("* ")) {
          return `<ul>${lines.filter(l => l.startsWith("- ") || l.startsWith("* ")).map(l => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
        }
        return `<p>${lines.map(l => inline(l)).join("<br>")}</p>`;
      }).join("");
      function inline(s) {
        return esc(s)
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
      }
    }
    function loadGuide() {
      /* Wave 3 / #40: GUIDE prose lives in <template id="wall-lazy-guide"> until first open. */
      const guideHost = document.getElementById("guide-body");
      const guideTpl = document.getElementById("wall-lazy-guide");
      if (guideHost && guideHost.getAttribute("data-lazy-guide") === "1" && guideTpl && guideTpl.content) {
        guideHost.appendChild(guideTpl.content.cloneNode(true));
        guideHost.removeAttribute("data-lazy-guide");
      }
      const pane = document.getElementById("pane-guide");
      const jump = document.getElementById("guide-jump");
      if (!pane || (jump && jump.dataset.bound === "1")) return;
      if (jump) {
        jump.dataset.bound = "1";
        jump.addEventListener("click", ev => {
          const b = ev.target.closest("[data-guide-jump]");
          if (!b) return;
          const t = document.getElementById(b.getAttribute("data-guide-jump"));
          if (t) t.scrollIntoView({ block: "start", behavior: "smooth" });
        });
      }
      requestAnimationFrame(() => { try { markOverflow(); } catch (eMore) {} });
    }
    document.querySelectorAll("nav.tabs button").forEach(b => {
      b.addEventListener("click", () => showTab(b.dataset.tab));
    });
    document.querySelectorAll(".mail-view-toggle button").forEach(b => {
      b.addEventListener("click", () => setMailView(b.dataset.mailView));
    });
    document.querySelectorAll(".mail-mode-toggle button").forEach(b => {
      b.addEventListener("click", () => setMailMode(b.dataset.mailMode));
    });
    document.querySelectorAll(".mail-dest-class button").forEach(b => {
      b.addEventListener("click", () => setMailDestClass(b.dataset.mailClass));
    });
    hint.querySelectorAll(".jump").forEach(btn => {
      btn.addEventListener("click", () => {
        showTab(btn.dataset.tab);
        requestAnimationFrame(() => requestAnimationFrame(() => highlight(btn.dataset.hi)));
      });
    });
    function csvList(raw) {
      return String(raw || "").split(/[,+\s]+/).map(s => s.trim()).filter(Boolean);
    }
    function wallProjects() {
      return currentFilter().projects;
    }
    function floorProjectQuery() {
      const names = (currentFilter().projects || []).filter(Boolean);
      const list = names.length ? names : ["Office"];
      return "project=" + list.map(encodeURIComponent).join(",");
    }
    let _roleScopeHold = null;
    function floorScope() {
      const project = floorProjectQuery();
      const tabBtn = document.querySelector("nav.tabs button.on");
      const tab = (tabBtn && tabBtn.dataset.tab) || "session";
      /* TODO/Nest needs the project book; a left-rail LAN pick returns trees:[] and blanks Nest. */
      if ((tab === "jobs" || tab === "trees" || (tab === "mail" && typeof mailView !== "undefined" && mailView === "rooms")) && project) {
        return { key: "project:" + project, query: project };
      }
      if (railPick && railPick.kind === "role" && _roleScopeHold && _roleScopeHold.query) {
        return { key: _roleScopeHold.key, query: _roleScopeHold.query };
      }
      if (railPick && railPick.kind === "lan" && railPick.id) {
        return { key: "lan:" + railPick.id, query: "lan=" + encodeURIComponent(railPick.id) };
      }
      return { key: "project:" + project, query: project };
    }
    /* WALL_UI_LOADING: every pending region shows spinner/hourglass until inbound.
     * Empty must not look broken. Progressive paint fills regions as lean isolates land. */
    function wallLoadingHtml(label) {
      const lbl = (label == null || label === "") ? "Loading\u2026" : String(label);
      return `<div class="wall-loading" role="status" aria-live="polite" data-wall-loading="1">` +
        `<span class="wall-loading-spin" aria-hidden="true"></span>` +
        `<span class="wall-loading-ico" aria-hidden="true" title="loading">\u231B</span>` +
        `<span class="wall-loading-lbl">${esc(lbl)}</span></div>`;
    }
    function wallStripLoadHtml() {
      /* Compact spinner+hourglass for strip KPI tabs. */
      return `<span class="kpi-load" aria-hidden="true">` +
        `<span class="wall-loading-spin"></span>` +
        `<span class="wall-loading-ico" title="loading">\u231B</span></span>`;
    }
    /* Sticky strip-tab ready flags; declared early - wallMarkShellLoading may run before strip(). */
    const _stripReady = { session: false, floor: false, todo: false, score: false, mail: false };
    let _officeScoreSeen = false;
    function wallIsLoadingEl(el) {
      return !!(el && el.querySelector && el.querySelector("[data-wall-loading='1']"));
    }
    function wallLoadingOnly(el) {
      /* True when host is empty or only wall-loading / empty-text chrome - safe to fill. */
      if (!el) return true;
      const kids = el.children ? Array.prototype.slice.call(el.children) : [];
      if (!kids.length) {
        return !String(el.textContent || "").trim();
      }
      return kids.every(function (k) {
        return !!(k.getAttribute && k.getAttribute("data-wall-loading") === "1")
          || !!(k.classList && k.classList.contains("wall-loading"))
          || !!(k.classList && k.classList.contains("wall-pane-overlay"));
      });
    }
    function wallHasRealContent(el) {
      /* painted content counts even if a loading spinner/overlay coexists.
         Do NOT treat "has loading descendant" as empty - that blanked panes on re-enter. */
      if (!el) return false;
      if (!wallLoadingOnly(el)) return true;
      if (el.querySelector && el.querySelector("table, svg, .mail-rooms-nest, .mail-rooms-row, .need, .todo-list-group, .floor-node, .score-row, .desk-row, .mill-outline-row, .idle, .col-empty, .empty-session, .mail-all-clear")) return true;
      const t = String(el.textContent || "").trim();
      if (!t) return false;
      /* Pure loading label text alone is not "real" content. */
      if (wallIsLoadingEl(el) && wallLoadingOnly(el)) return false;
      return true;
    }
    function wallShowLoading(el, label) {
      /* NEVER blank prior paint. Only fill truly empty / loading-only hosts. */
      if (!el) return false;
      if (!wallLoadingOnly(el)) return false;
      if (wallHasRealContent(el)) return false;
      const html = wallLoadingHtml(label);
      if (el.innerHTML === html) return true;
      el.innerHTML = html;
      return true;
    }
    /* opaque subtab overlay - covers pane-body, does NOT blank prior content.
       Keep theme/chrome classes across leave->return for every strip family. */
    function wallPreserveThemeChrome() {
      try {
        const KEY = "factory-theme";
        let pref = "auto";
        try { pref = localStorage.getItem(KEY) || "auto"; } catch (e0) {}
        const p = (pref === "light" || pref === "dark") ? pref : "auto";
        let resolved = p;
        const root = document.documentElement;
        if (p === "auto") {
          const prevScheme = root.style.colorScheme;
          const prevTheme = root.getAttribute("data-theme");
          try {
            /* One allowed scheme makes Chrome report that scheme as the OS. */
            root.removeAttribute("data-theme");
            root.style.colorScheme = "light dark";
            void root.offsetWidth;
            resolved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
          } catch (eM) { resolved = "dark"; }
          if (prevTheme) root.setAttribute("data-theme", prevTheme);
          if (prevScheme) root.style.colorScheme = prevScheme;
          else root.style.removeProperty("color-scheme");
        }
        root.setAttribute("data-theme-pref", p);
        root.setAttribute("data-theme", resolved);
        if (p === "auto") root.style.colorScheme = "light dark";
        else root.style.removeProperty("color-scheme");
        document.querySelectorAll("#theme-pref button[data-theme-pref]").forEach(function (b) {
          b.classList.toggle("on", b.getAttribute("data-theme-pref") === p);
        });
      } catch (eTheme) {}
      try {
        const dens = localStorage.getItem("factory-density");
        if (dens === "compact" || dens === "comfortable") {
          document.body.classList.toggle("wall-density-compact", dens === "compact");
          document.body.classList.toggle("wall-density-comfortable", dens !== "compact");
        }
      } catch (eDens) {}
      try {
        const rail = localStorage.getItem("factory-rail");
        let railNarrow = rail === "narrow";
        if (rail !== "wide" && rail !== "narrow" && window.matchMedia("(max-width: 720px)").matches) {
          railNarrow = true;
        }
        if (rail === "narrow" || rail === "wide" || railNarrow) {
          document.body.classList.toggle("rail-narrow", railNarrow);
        }
      } catch (eRail) {}
      try {
        /* Domain CSS links (mail/todo/score) stay once loaded - never remove on tab leave. */
        document.querySelectorAll('link[data-wall-lazy]').forEach(function (lnk) {
          if (lnk && lnk.parentNode) { /* keep */ }
        });
      } catch (eLazy) {}
    }
    /* switch generation - only latest showTab/subtab may mutate panes / clear overlays.
       Stale tick/early-paint/domain-ensure callbacks must no-op without blanking. */
    let _wallSwitchGen = 0;
    function wallBumpSwitchGen() {
      _wallSwitchGen += 1;
      try { window._wallSwitchGen = _wallSwitchGen; } catch (eW) {}
      try { wallPreserveThemeChrome(); } catch (eT) {}
      return _wallSwitchGen;
    }
    function wallSwitchGen() {
      return _wallSwitchGen;
    }
    function wallSwitchGenAlive(gen) {
      return gen != null && Number(gen) === Number(_wallSwitchGen);
    }
    let _wallTickGen = 0;
    function wallBeginTickGen(gen) {
      _wallTickGen = gen != null ? Number(gen) : _wallSwitchGen;
      try { window._wallTickGen = _wallTickGen; } catch (eTg) {}
      return _wallTickGen;
    }
    function wallTickGenAlive(gen) {
      const g = gen != null ? gen : _wallTickGen;
      return wallSwitchGenAlive(g);
    }
    function wallPaneBodyHost(paneOrId) {
      let pane = paneOrId;
      if (typeof paneOrId === "string") pane = document.getElementById(paneOrId);
      if (!pane) return null;
      return pane.querySelector(".pane-body") || pane;
    }
    function wallShowPaneOverlay(paneOrId, label) {
      /* translucent when last-good exists; opaque when pane empty. */
      const host = wallPaneBodyHost(paneOrId);
      if (!host) return false;
      try {
        const cs = window.getComputedStyle(host);
        if (cs && cs.position === "static") host.style.position = "relative";
      } catch (ePos) {
        host.style.position = "relative";
      }
      let hasReal = false;
      try { hasReal = !!wallHasRealContent(host); } catch (eHas) { hasReal = false; }
      let ov = host.querySelector(":scope > .wall-pane-overlay");
      if (!ov) {
        ov = document.createElement("div");
        ov.setAttribute("data-wall-pane-overlay", "1");
        ov.setAttribute("role", "status");
        ov.setAttribute("aria-live", "polite");
        host.appendChild(ov);
      }
      ov.className = "wall-pane-overlay";
      if (hasReal) ov.classList.remove("is-opaque");
      else ov.classList.add("is-opaque");
      const lbl = (label == null || label === "") ? "Loading\u2026" : String(label);
      ov.innerHTML = wallLoadingHtml(lbl);
      ov.hidden = false;
      host.setAttribute("data-wall-overlay", "1");
      try { host.setAttribute("data-wall-overlay-mode", hasReal ? "translucent" : "opaque"); } catch (eMode) {}
      return true;
    }
    function wallClearPaneOverlay(paneOrId) {
      const host = wallPaneBodyHost(paneOrId);
      if (!host) return false;
      const ov = host.querySelector(":scope > .wall-pane-overlay");
      if (ov) {
        try { ov.remove(); } catch (eRm) { ov.hidden = true; }
      }
      host.removeAttribute("data-wall-overlay");
      try { host.removeAttribute("data-wall-overlay-mode"); } catch (eModeClr) {}
      return true;
    }
    function wallClearActivePaneOverlay() {
      try {
        document.querySelectorAll(".pane-body[data-wall-overlay='1'], .pane[data-wall-overlay='1']").forEach(function (el) {
          wallClearPaneOverlay(el.classList.contains("pane-body") ? el.closest(".pane") || el : el);
        });
      } catch (eAll) {}
    }
    function wallRestoreActivePaneFromFloor(opts) {
      /* repaint active pane from _floor last-good.
         force=true: show latest committed book on return even if DOM still has prior paint. */
      const d = window._floor;
      if (!d) return;
      const force = !!(opts && opts.force);
      try { wallPreserveThemeChrome(); } catch (eT) {}
      const mailOn = document.getElementById("pane-mail");
      if (mailOn && mailOn.classList.contains("on")) {
        const host = document.getElementById("mail") || document.getElementById("mail-dst-col");
        if (force || (host && !wallHasRealContent(host))) {
          try { mail(d); } catch (eM) {}
        }
        return;
      }
      const todoOn = document.getElementById("pane-todo");
      if (todoOn && todoOn.classList.contains("on")) {
        const host = document.getElementById("parked") || document.getElementById("jobs-list") || document.getElementById("jobs-outline");
        if (force || (host && !wallHasRealContent(host))) {
          try { board(d); } catch (eB) {}
          try { paintPlan(d); } catch (eP) {}
        }
        return;
      }
      const scoreOn = document.getElementById("pane-score");
      if (scoreOn && scoreOn.classList.contains("on")) {
        const host = document.getElementById("score-desk-table");
        if (force || (host && !wallHasRealContent(host))) {
          try { cards(d); } catch (eC) {}
        }
        return;
      }
      const floorOn = document.getElementById("pane-floor");
      if (floorOn && floorOn.classList.contains("on")) {
        const host = document.getElementById("floor-map") || document.getElementById("floor-timeline");
        if (force || (host && !wallHasRealContent(host))) {
          try { ensureFloorPaint(); } catch (eF) {}
        }
        return;
      }
      const sessOn = document.getElementById("pane-session");
      if (sessOn && sessOn.classList.contains("on")) {
        const host = document.getElementById("here");
        if (force || (host && !wallHasRealContent(host))) {
          try { board(d, { hereOnly: true }); } catch (eH) {}
          try { agents(d); } catch (eA) {}
          try { paintSessionWire(d); } catch (eW) {}
        }
      }
    }
    function wallCommitFloorBook(raw, opts) {
      /* commit late/stale payload into floor book + window._floor last-good (no live-pane requirement). */
      if (!raw || typeof raw !== "object") return null;
      const storedFp = (opts && opts.storedFp) || {};
      const projectKey = (opts && opts.projectKey) != null ? opts.projectKey : floorScope().key;
      const partsStr = (opts && opts.partsStr) != null ? opts.partsStr : "";
      try {
        if (raw.fp && typeof raw.fp === "object") floorFpRemember(projectKey, partsStr, raw.fp);
      } catch (eFp) {}
      const book = absorbFloorSlice(raw, { storedFp: storedFp });
      const d = String(projectKey || "").indexOf("project:") === 0 ? applyRailPick(cutFloor(book)) : book;
      window._floor = d;
      try {
        const glance = floorGlanceFromFloor(d);
        if (glance) floorGlanceCache = glance;
      } catch (eG) {}
      return d;
    }
    function wallPaintOffPaneLastGood(d, parts) {
      /* update OFF-SCREEN pane DOM from committed last-good; never touch active .on pane. */
      if (!d) return false;
      const sliceParts = Array.isArray(parts) ? parts : [];
      const has = function (n) { return !sliceParts.length || sliceParts.indexOf(n) >= 0; };
      const safe = (typeof wallPaintThrowSafe === "function")
        ? wallPaintThrowSafe
        : function (fn) { try { return fn(); } catch (e) {} };
      let did = false;
      try {
        const mailOn = document.getElementById("pane-mail");
        if ((!mailOn || !mailOn.classList.contains("on")) && (has("mail") || has("trees"))) {
          if (typeof mail === "function") { safe(function () { mail(d); }, "off-mail"); did = true; }
        }
      } catch (eM) {}
      try {
        const todoOn = document.getElementById("pane-todo");
        if ((!todoOn || !todoOn.classList.contains("on")) && (has("todos") || has("trees"))) {
          if (typeof board === "function") { safe(function () { board(d); }, "off-todo"); did = true; }
          if (typeof paintPlan === "function") { safe(function () { paintPlan(d); }, "off-plan"); did = true; }
        }
      } catch (eT) {}
      try {
        const scoreOn = document.getElementById("pane-score");
        if ((!scoreOn || !scoreOn.classList.contains("on")) && has("scores")) {
          if (typeof cards === "function") { safe(function () { cards(d); }, "off-score"); did = true; }
        }
      } catch (eS) {}
      try {
        const floorOn = document.getElementById("pane-floor");
        if ((!floorOn || !floorOn.classList.contains("on")) && (has("agents") || has("mail") || has("timeline") || has("events"))) {
          try {
            const glance = floorGlanceFromFloor(d);
            if (glance) {
              floorGlanceCache = glance;
              /* paintFloorView skips inactive unless force - pass force for off-pane last-good */
              paintFloorView(glance, { force: true });
              did = true;
            }
          } catch (eF) {}
        }
      } catch (eFloor) {}
      try {
        const sessOn = document.getElementById("pane-session");
        if ((!sessOn || !sessOn.classList.contains("on")) && (has("agents") || has("holds") || has("events") || has("watchers"))) {
          if (typeof agents === "function") { safe(function () { agents(d); }, "off-session"); did = true; }
          if (typeof board === "function") { safe(function () { board(d, { hereOnly: true }); }, "off-here"); did = true; }
          if (typeof paintSessionWire === "function") { safe(function () { paintSessionWire(d); }, "off-wire"); did = true; }
          if (has("watchers") && typeof paintWatchers === "function") {
            safe(function () { paintWatchers(d); }, "off-watch"); did = true;
          }
        }
      } catch (eSess) {}
      return did;
    }
    function wallAbsorbOffPaneResult(raw, opts) {
      /* late/stale settle - commit book + paint off-pane last-good; live .on pane untouched. */
      const d = wallCommitFloorBook(raw, opts);
      if (!d) return null;
      try {
        wallPaintOffPaneLastGood(d, (raw && raw.parts) || (opts && opts.parts) || []);
      } catch (eP) {}
      return d;
    }
    /* leave->return before in-flight fetch completes -- reuse same request (no second DB call). */
    let _tickInflightParts = "";
    let _tickInflightScope = "";
    let _wallReuseInflight = false;
    function wallTickInflight() {
      return _tickInflight;
    }
    function wallShouldReuseInflight() {
      if (!_tickInflight) return false;
      try {
        if (String(_tickInflightScope || "") !== String(floorScope().key || "")) return false;
        if (String(_tickInflightParts || "") !== String(wallParts() || "")) return false;
      } catch (e) { return false; }
      return true;
    }
    function wallReuseInflightForReturn() {
      /* Keep current fetch; Checking overlay on active pane; do not queue _tickAgain restart. */
      if (!wallShouldReuseInflight()) return false;
      _wallReuseInflight = true;
      _tickAgain = false;
      try { window._wallReuseInflight = true; } catch (eW) {}
      return true;
    }
    function wallClearReuseInflight() {
      _wallReuseInflight = false;
      try { window._wallReuseInflight = false; } catch (eW) {}
    }
    function wallMarkShellLoading() {
      try {
        ["rail-desks", "rail-roster"].forEach(function (id) {
          const el = document.getElementById(id);
          if (el && !wallHasRealContent(el)) wallShowLoading(el, "Loading\u2026");
        });
      } catch (eRail) {}
      try { wallMarkTabLoading(); } catch (eTab) {}
    }
    function wallPaneHasCheckOverlay(paneId) {
      try {
        const pane = document.getElementById(paneId);
        if (!pane) return false;
        const host = pane.querySelector(".pane-body") || pane;
        return !!(host && host.getAttribute("data-wall-overlay") === "1");
      } catch (e) { return false; }
    }
    function wallMarkTabLoading() {
      /* while opaque check overlay is up, do not mutate pane bodies - overlay IS the check. */
      try {
        const tabBtn0 = document.querySelector("nav.tabs button.on");
        const tab0 = (tabBtn0 && tabBtn0.dataset.tab) || "session";
        const paneId0 = tab0 === "jobs" ? "pane-todo" : ("pane-" + tab0);
        if (wallPaneHasCheckOverlay(paneId0)) {
          try { wallSyncStripTabLoading(); } catch (eStripOnly) {}
          return;
        }
      } catch (eOvSkip) {}
      try { wallSyncStripTabLoading(); } catch (eStrip0) {}
      const tabBtn = document.querySelector("nav.tabs button.on");
      const tab = (tabBtn && tabBtn.dataset.tab) || "session";
      if (tab === "mail") {
        const dst = document.getElementById("mail-dst-col") || document.getElementById("mail-desk-rail");
        const src = document.getElementById("mail-src-col");
        const msg = document.getElementById("mail");
        if (typeof mailView !== "undefined" && mailView === "rooms") {
          /* never blank src/dst/msg on leave/re-enter; spinner only if empty. */
          if (dst && !wallHasRealContent(dst)) wallShowLoading(dst, "Loading rooms\u2026");
          if (msg && !wallHasRealContent(msg)) wallShowLoading(msg, "Loading nest\u2026");
        } else {
          if (dst && !wallHasRealContent(dst)) wallShowLoading(dst, "Loading destinations\u2026");
          if (src && !wallHasRealContent(src)) wallShowLoading(src, "Loading senders\u2026");
          if (msg && !wallHasRealContent(msg)) wallShowLoading(msg, "Loading mail\u2026");
        }
        return;
      }
      if (tab === "jobs") {
        let v = todoView || "board";
        if (v === "plan" || v === "trees") v = "nest";
        if (v !== "list" && v !== "nest") v = "board";
        if (v === "nest") {
          const outline = document.getElementById("jobs-outline");
          if (outline && !wallHasRealContent(outline)) wallShowLoading(outline, "Loading nest\u2026");
        } else if (v === "list") {
          const jl = document.getElementById("jobs-list");
          if (jl && !wallHasRealContent(jl)) wallShowLoading(jl, "Loading todos\u2026");
        } else {
          const kanban = document.getElementById("jobs-kanban");
          if (kanban) {
            const bodies = kanban.querySelectorAll(".jobs-kanban-col .body");
            let any = false;
            bodies.forEach(function (b) { if (wallHasRealContent(b)) any = true; });
            if (!any) {
              if (bodies.length) bodies.forEach(function (b) { wallShowLoading(b, "Loading\u2026"); });
              else if (!wallHasRealContent(kanban)) wallShowLoading(kanban, "Loading board\u2026");
            }
          }
        }
        return;
      }
      if (tab === "score") {
        const table = document.getElementById("score-desk-table");
        const hot = document.getElementById("score-hot");
        const detail = document.getElementById("score-detail");
        if (table && !wallHasRealContent(table)) wallShowLoading(table, "Loading scores\u2026");
        if (hot && !wallHasRealContent(hot)) wallShowLoading(hot, "Loading\u2026");
        if (detail && !wallHasRealContent(detail)) wallShowLoading(detail, "Loading detail\u2026");
        return;
      }
      if (tab === "floor") {
        const map = document.getElementById("floor-map") || document.getElementById("floor-view") || document.getElementById("floor");
        const tl = document.getElementById("floor-timeline");
        if (map && !wallHasRealContent(map)) wallShowLoading(map, "Loading\u2026");
        if (tl && !wallHasRealContent(tl)) wallShowLoading(tl, "Loading timeline\u2026");
        return;
      }
      const here = document.getElementById("here");
      if (here && !wallHasRealContent(here)) wallShowLoading(here, "Loading session\u2026");
      try { wallSyncStripTabLoading(); } catch (eStrip) {}
    }

    function wallSyncStripTabLoading() {
      /* Keep strip KPI loading class in sync with pane paint even before strip() rebuilds. */
      const map = [
        ["strip-here", "session", "here"],
        ["strip-floor", "floor", "floor-map"],
        ["strip-todo", "todo", "parked"],
        ["strip-score", "score", "score-desk-table"],
        ["strip-mail", "mail", "mail"],
      ];
      map.forEach(function (row) {
        const el = document.getElementById(row[0]);
        if (!el) return;
        const key = row[1];
        /* Ready only when this scope's payload carried the part (strip()). A painted
           pane is no proof: it can still hold the previous roster's rows (#715). */
        const ready = key === "score" ? !!_officeScoreSeen : !!_stripReady[key];
        if (ready) {
          el.classList.remove("kpi-loading");
          el.setAttribute("data-wall-strip-loading", "0");
          const spin = el.querySelector(".kpi-load");
          if (spin) try { spin.remove(); } catch (eR) {}
        } else {
          el.classList.add("kpi-loading");
          el.setAttribute("data-wall-strip-loading", "1");
          if (!el.querySelector(".kpi-load")) {
            const bNow = el.querySelector("b");
            const tmp = document.createElement("span");
            tmp.innerHTML = wallStripLoadHtml();
            const node = tmp.firstChild;
            if (node) el.insertBefore(node, bNow || null);
          }
          /* Not loaded is not zero: drop the count and cue left from the last scope. */
          const b = el.querySelector("b");
          if (b) b.textContent = key === "mail" ? "\u2014" : "...";
          const cue = el.querySelector(".kpi-cue");
          if (cue) try { cue.remove(); } catch (eCue) {}
        }
      });
    }

    function wallParts() {
      /* Tab-scoped floor slice only. Strip KPI chips keep last counts via _stripLast
         when a part is absent - do NOT re-append agents/mail/scores/todos every poll
         (that re-shipped the whole todo book ~400KB and stalled commands). */
      const tabBtn = document.querySelector("nav.tabs button.on");
      const tab = (tabBtn && tabBtn.dataset.tab) || "session";
      let core = "agents";
      if (tab === "mail") core = (typeof mailView !== "undefined" && mailView === "rooms") ? "mail,trees" : "mail";
      if (tab === "mail" && typeof mailView !== "undefined" && mailView === "letters") core = "mail,trees";
      else if (tab === "jobs") {
        /* Nest/List/Board need trees; parts=todos alone returns trees:[]. */
        core = "todos,trees";
      } else if (tab === "score") core = "scores";
      else if (tab === "glossary") core = "names";
      else if (tab === "floor") {
        const mode = (document.querySelector("[data-floor-mode].on") || {}).getAttribute
          ? document.querySelector("[data-floor-mode].on").getAttribute("data-floor-mode")
          : "map";
        if (mode === "timeline" && railPick && railPick.kind === "lan") core = "agents,events";
        else core = mode === "timeline" ? "agents,timeline" : "agents,mail";
      } else {
        const session = (document.querySelector("[data-session-mode].on") || {}).getAttribute
          ? document.querySelector("[data-session-mode].on").getAttribute("data-session-mode")
          : "now";
        if (session === "leases") core = "holds";
        else if (session === "watch") core = "watchers";
        else if (session === "history") core = "events";
        else core = "agents";
      }
      return core;
    }


    /* Floor v1 part isolates (Wall contract card rule-routes: mill todo wall-contract rule-routes) + progressive paint.
     * MAIL Rooms -> /api/v1/rooms + mailbox + tree-mail
     *   Fetch stagger (Loop-3 cold-SQL): phase A rooms+tree-mail parallel; phase B mailbox after A.
     *   Phase 1 paint: tree-mail (or rooms) paints left rail + nest structure; do NOT wait mailbox.
     *   Phase 2 paint: mailbox re-sorts (mailRoomLatestAt), badges, cast, search haystack, nest bodies.
     *   Rooms isolate kept in the trio (tree-mail not proven to always superset lean roots).
     * MAIL nest/list -> mailbox; spinner until isolate lands.
     * Lean list+detail: paint body/doing/detail snippets; on open if *_trunc,
     *   GET /api/v1/mail/{id} or /api/v1/todo/{id}, merge into local row, re-paint.
     * Limit+cursor scroll: first mailbox/todos GET ?limit=50; near-bottom appends
     *   via ?cursor= next; opaque subtab overlay until tick confirms (never blank on leave; keep prior+theme).
     * TODO Nest/List/Board -> /api/v1/todos + tree-todo; paint each isolate as it lands.
     * tree-mail/tree-todo progressive (limit=50 depth=1 cursor parent_id has_children);
     *   outline near-bottom appends; twist expand fetches direct children.
     * FLOOR Map/Timeline hybrids -> joined /api/v1/map + /api/v1/timeline (one RTT).
     *   Do NOT Promise.all agents+mailbox.
     * SCORE chip mill-office.activities -> activities/h; empty target never red.
     * history: hybrids briefly on floor until Builder joined Claim (now).
     * Pending regions ALWAYS show wall-loading (spinner/hourglass); never blank.
     * A failed part read paints the wall down. Project, role, and station use the same routes.
     * progressive trees - tree-mail/tree-todo ?limit=50&depth=1 + cursor next;
     *   expand ?parent_id=type:id.
     *   Prefer progressive expand over fat full-tree loads. GET-only (human-readonly).
     * nest window chips All|1d|1w|30d on MAIL Rooms + TODO Nest; pass ?window=
     *   on tree-mail/tree-todo progressive fetches (limit/cursor/depth/parent_id unchanged).
     *   Sticky: floor parts=trees has no window yet -> All-only (omit window; full trees).
     * trust browse vs membership on MAIL Rooms GET /api/v1/rooms.
     *   Read trust from any v1/floor envelope; limited => ?desk=<seated>&scope=membership;
     *   high => omit desk (browse book). Admin bypass is server-side. Seated desk =
     *   wallResolveDeskId (URL ?desk/?for, factory-desk-badge, factory-desk). GET-only.
     * MAIL Rooms scroll (grid min-height:0 + thin scrollbars) + sort by recency
     *   (mailbox created/at via mailAt; else max mail node id zero-padded).
     * welcome opening surface (beat1 + JOIN paste with minted invite_url +
     *   Invite Agent mint/copy). New document visits only; Do not show again -> localStorage.
     * split paste - Workstation once (pip+skill) vs This agent (join+connect);
     *   Generate new URL remints mint_seat (one seat per agent).
     * show welcome before mint (hung mint must not block Host); Nest popup overlay.
     *   ALWAYS auto-open on new window/tab document load unless Do not show again.
     *   /welcome serves Nest + opens popup (replaceState to /).
     * Escape / backdrop / X / Dismiss always dismiss overlay (mint pending never blocks).
     * dismiss persists factory-welcome-hide=1; strip ?welcome=1 via replaceState so refresh
     *   does not reopen. Host: click Dismiss/X/Escape/backdrop OR localStorage.setItem("factory-welcome-hide","1").
     * Invite Agent strip -> wallWelcomeShow on Nest (replaceState ?welcome=1 ok); never location=/welcome.
     *   board.css?v=wow179 + critical inline overlay so Host cache is not stuck on opaque full-page.
     *   Cache-bust. */
    let _wallTrust = null; /* high|limited from v1 envelope (mill trust) */
    window._wallTrust = null;
    function wallRememberTrust(src) {
      if (!src || typeof src !== "object") return;
      const t = String(src.trust || "").trim().toLowerCase();
      if (t === "high" || t === "limited") {
        _wallTrust = t;
        window._wallTrust = t;
      }
      try { wallApplyInviteGate(); } catch (eInviteGate) {}
    }
    function wallTrust() {
      return _wallTrust;
    }
    function wallRoomsMembershipQuery() {
      /* Wall contract card rule-rooms-and-trust: mill todo wall-contract rule-rooms-and-trust.
       * Every trust level reads every room; the server accepts and ignores ?desk= and
       * ?scope=membership, so these args no longer filter anything. Kept as sent today
       * (limited: desk + scope, unknown: desk, high: none) until a glass cleanup drops them. */
      const t = wallTrust();
      if (t === "high") return "";
      let desk = "";
      try { desk = String(wallResolveDeskId() || "").trim(); } catch (eDesk) { desk = ""; }
      if (!desk) return "";
      if (t === "limited") {
        return "&desk=" + encodeURIComponent(desk) + "&scope=membership";
      }
      return "&desk=" + encodeURIComponent(desk);
    }
    function wallV1Routes(scope) {
      /* project=, role=, or lan=. The part name is the path. */
      if (!scope || !String(scope.query || "").trim()) return null;
      const tabBtn = document.querySelector("nav.tabs button.on");
      const tab = (tabBtn && tabBtn.dataset.tab) || "session";
      if (tab === "mail") {
        if (typeof mailView !== "undefined" && (mailView === "rooms" || mailView === "letters")) {
          return [
            { path: "/api/v1/mailbox", kind: "mailbox" },
            { path: "/api/v1/rooms", kind: "rooms" },
            { path: "/api/v1/tree-mail", kind: "tree-mail" },
          ];
        }
        /* nest/list (list/graph): mailbox isolate; trees not requested by wallParts. */
        return [{ path: "/api/v1/mailbox", kind: "mailbox" }];
      }
      if (tab === "jobs") {
        return [
          { path: "/api/v1/todos", kind: "todos" },
          { path: "/api/v1/tree-todo", kind: "tree-todo" },
        ];
      }
      /* single-part + FLOOR joined map/timeline -> v1. */
      if (tab === "score") {
        return [{ path: "/api/v1/scores", kind: "scores" }];
      }
      if (tab === "glossary") {
        return [{ path: "/api/v1/names", kind: "names" }];
      }
      if (tab === "session" || tab === "floor") {
        const parts = (typeof wallParts === "function") ? String(wallParts() || "") : "";
        if (parts === "agents") {
          if (tab === "session") {
            const sessionEl = document.querySelector("[data-session-mode].on");
            const session = (sessionEl && sessionEl.getAttribute)
              ? sessionEl.getAttribute("data-session-mode")
              : "now";
            if (session && session !== "now") return null;
          }
          return [{ path: "/api/v1/agents", kind: "agents" }];
        }
        /* SESSION leases/watch/history (single-part). */
        if (tab === "session") {
          if (parts === "holds") return [{ path: "/api/v1/holds", kind: "holds" }];
          if (parts === "watchers") return [{ path: "/api/v1/watchers", kind: "watchers" }];
          if (parts === "events") return [{ path: "/api/v1/events", kind: "events" }];
        }
        /* joined isolates (one RTT each) - not Promise.all agents+mailbox. */
        if (tab === "floor") {
          if (parts === "agents,mail") {
            /* Map is the joined picture. Between is /api/activity, not a window on /api/v1/map. */
            const between = activityBetweenQuery();
            return [
              { path: "/api/v1/map", kind: "map", fpParts: "agents,mail" },
              { path: between.url, kind: "between", absolute: true },
            ];
          }
          if (parts === "agents,events") {
            return [{ path: "/api/v1/timeline", kind: "timeline", fpParts: "agents,events" }];
          }
          if (parts === "agents,timeline") {
            return [{
              path: "/api/v1/timeline",
              kind: "timeline",
              fpParts: "agents,timeline",
              queryParts: "agents,timeline"
            }];
          }
        }
      }
      return null;
    }
    function wallMergeV1Isolates(rows) {
      /* Merge v1 JSON isolates into one floor-shaped slice (contract field keys). */
      const out = { parts: [] };
      let treesRooms = null;
      let treesTyped = null;
      const fp = {};
      const partSeen = {};
      function addPart(p) {
        if (!p || partSeen[p]) return;
        partSeen[p] = true;
        out.parts.push(p);
      }
      (rows || []).forEach(function (row) {
        const json = row && row.json;
        const kind = row && row.kind;
        if (!json || typeof json !== "object") return;
        ["mill", "at", "node", "version", "trust"].forEach(function (k) {
          if (json[k] !== undefined) out[k] = json[k];
        });
        try { wallRememberTrust(json); } catch (eTrust) {}
        if (json.fp && typeof json.fp === "object") {
          Object.keys(json.fp).forEach(function (k) {
            if (json.fp[k] != null && json.fp[k] !== "") fp[k] = json.fp[k];
          });
        }
        if (kind === "rooms") {
          /* Lean mail roots in trees; absorb as trees part. Prefer tree-mail when both. */
          addPart("trees");
          if (Array.isArray(json.trees)) treesRooms = json.trees;
        } else if (kind === "tree-mail" || kind === "tree-todo") {
          addPart("trees");
          if (Array.isArray(json.trees)) treesTyped = json.trees;
          if (json.next !== undefined) out.next_trees = json.next;
        } else if (kind === "mailbox") {
          addPart("mail");
          if (json.mailbox !== undefined) out.mailbox = json.mailbox;
          if (json.desk_unread !== undefined) out.desk_unread = json.desk_unread;
          if (json.next !== undefined) out.next_mailbox = json.next;
        } else if (kind === "todos") {
          addPart("todos");
          if (json.needs !== undefined) out.needs = json.needs;
          if (json.issues !== undefined) out.issues = json.issues;
          if (json.next !== undefined) out.next_todos = json.next;
        } else if (kind === "agents") {
          addPart("agents");
          if (json.agents !== undefined) out.agents = json.agents;
          if (json.next !== undefined) out.next_agents = json.next;
        } else if (kind === "scores") {
          addPart("scores");
          if (json.kpis !== undefined) out.kpis = json.kpis;
          if (json.next !== undefined) out.next_scores = json.next;
        } else if (kind === "holds") {
          addPart("holds");
          if (json.locks !== undefined) out.locks = json.locks;
          if (json.next !== undefined) out.next_holds = json.next;
        } else if (kind === "watchers") {
          addPart("watchers");
          if (json.watchers !== undefined) out.watchers = json.watchers;
          if (json.next !== undefined) out.next_watchers = json.next;
        } else if (kind === "events") {
          addPart("events");
          if (json.events !== undefined) out.events = json.events;
          if (json.next !== undefined) out.next_events = json.next;
        } else if (kind === "map" || kind === "timeline") {
          /* Joined FLOOR hybrid: payload already floor-shaped. */
          if (Array.isArray(json.parts)) {
            json.parts.forEach(addPart);
          } else if (kind === "map") {
            addPart("agents");
            addPart("mail");
          } else {
            addPart("agents");
            if (json.timeline !== undefined) addPart("timeline");
            else addPart("events");
          }
          if (json.agents !== undefined) out.agents = json.agents;
          if (json.mailbox !== undefined) out.mailbox = json.mailbox;
          if (json.desk_unread !== undefined) out.desk_unread = json.desk_unread;
          if (json.events !== undefined) out.events = json.events;
          if (json.timeline !== undefined) out.timeline = json.timeline;
          if (json.next !== undefined) out.next = json.next;
          if (json.timings !== undefined) out.timings = json.timings;
        } else if (kind === "between") {
          if (Array.isArray(json.rows)) out.between = json.rows;
        } else if (kind === "names") {
          addPart("names");
          if (json.catalog !== undefined) out.catalog = json.catalog;
          if (json.next !== undefined) out.next_names = json.next;
        }
      });
      if (treesTyped) out.trees = treesTyped;
      else if (treesRooms) out.trees = treesRooms;
      if (Object.keys(fp).length) out.fp = fp;
      return out;
    }
    async function wallFetchFloorV1(scope, routes, onRow) {
      /* GET isolates. First-paint stagger: MAIL Rooms paints mailbox first, then
       * tree-mail/rooms; Jobs paints todos before tree-todo. Shared pane overlay stays
       * translucent over last-good (opaque only when empty). onRow absorbs; paint after fp.
       * mailbox+todos first page always ?limit=50; trees ?limit=50&depth=1. */
      const q = String(scope.query || "");
      async function fetchOne(route) {
        const pageKinds = {
          mailbox: 1, todos: 1, agents: 1,
          scores: 1, holds: 1, watchers: 1, events: 1, names: 1,
          map: 1, timeline: 1,
          "tree-mail": 1, "tree-todo": 1
        };
        const fpKinds = {
          agents: "agents", scores: "scores", holds: "holds",
          watchers: "watchers", events: "events", names: "names",
          mailbox: "mail"
        };
        let url = route.absolute ? String(route.path || "") : (route.path + "?" + q);
        if (!route.absolute && pageKinds[route.kind]) {
          url += (q ? "&" : "") + "limit=50";
        }
        /* first-paint depth-cap on progressive trees (omit = server default 1).
         * ?window=1d|1w|30d when chip set; All omits window. */
        if (route.kind === "tree-mail" || route.kind === "tree-todo") {
          url += "&depth=1";
          url += wallTreesWindowQuery();
        }
        /* MAIL Rooms membership when trust=limited + seated desk. */
        if (route.kind === "rooms") {
          url += wallRoomsMembershipQuery();
        }
        if (route.queryParts) {
          url += "&parts=" + encodeURIComponent(route.queryParts);
        }
        const fpPart = route.fpParts || fpKinds[route.kind];
        if (fpPart) {
          /* empty-on-match fp; mailbox=mail; map/timeline use fpParts. */
          const fpA = floorFpQuery(scope.key, fpPart);
          if (fpA) url += fpA;
        }
        const r = await fetch(url, { cache: "no-store" });
        if (r.status === 404) return { down: true, status: 404, kind: route.kind };
        const ct = (r.headers.get("content-type") || "").toLowerCase();
        if (!r.ok || ct.indexOf("json") < 0) {
          return { down: true, status: r.status, kind: route.kind };
        }
        const json = await r.json();
        if (pageKinds[route.kind]) {
          try { wallRememberListNext(route.kind, json); } catch (eNext) {}
        }
        const row = { down: false, kind: route.kind, path: route.path, json: json };
        if (typeof onRow === "function") {
          try { onRow(row); } catch (eOn) {}
        }
        return row;
      }
      const list = routes || [];
      const hasMailbox = list.some(function (r) { return r.kind === "mailbox"; });
      const hasMailTree = list.some(function (r) {
        return r.kind === "rooms" || r.kind === "tree-mail";
      });
      const hasTodos = list.some(function (r) { return r.kind === "todos"; });
      const hasTodoTree = list.some(function (r) { return r.kind === "tree-todo"; });
      let settled;
      if (hasMailbox && hasMailTree) {
        /* Mail Rooms: mailbox first paint, then tree-mail/rooms. */
        const phaseA = list.filter(function (r) { return r.kind === "mailbox"; });
        const phaseB = list.filter(function (r) { return r.kind !== "mailbox"; });
        const aRows = await Promise.all(phaseA.map(fetchOne));
        for (let i = 0; i < aRows.length; i++) {
          if (aRows[i] && aRows[i].down) {
            return { down: true, status: aRows[i].status };
          }
        }
        const bRows = await Promise.all(phaseB.map(fetchOne));
        settled = aRows.concat(bRows);
      } else if (hasTodos && hasTodoTree) {
        /* Jobs: todos first paint, then tree-todo. */
        const phaseA = list.filter(function (r) { return r.kind === "todos"; });
        const phaseB = list.filter(function (r) { return r.kind !== "todos"; });
        const aRows = await Promise.all(phaseA.map(fetchOne));
        for (let i = 0; i < aRows.length; i++) {
          if (aRows[i] && aRows[i].down) {
            return { down: true, status: aRows[i].status };
          }
        }
        const bRows = await Promise.all(phaseB.map(fetchOne));
        settled = aRows.concat(bRows);
      } else {
        settled = await Promise.all(list.map(fetchOne));
      }
      for (let i = 0; i < settled.length; i++) {
        if (settled[i] && settled[i].down) {
          return { down: true, status: settled[i].status };
        }
      }
      return { down: false, raw: wallMergeV1Isolates(settled) };
    }
    function wallMailRoomsWantEarlyRail() {
      /* Phase-1 left rail: MAIL Rooms pane only. */
      if (typeof mailView === "undefined" || mailView !== "rooms") return false;
      try {
        const mailOn = document.getElementById("pane-mail");
        if (mailOn && !mailOn.classList.contains("on")) return false;
      } catch (ePane) {}
      return true;
    }
    function wallPaintMailRoomsEarly(merged) {
      /* absorb-only; still commit when gen stale / pane off (off-pane last-good).
       * mailbox may land before trees; absorb mailbox-only slices too. */
      if (!merged) return false;
      if (!Array.isArray(merged.trees) && !Array.isArray(merged.mailbox)) return false;
      const book = absorbFloorSlice(merged);
      const scopeNow = floorScope();
      const d = (scopeNow.key.indexOf("project:") === 0)
        ? applyRailPick(cutFloor(book))
        : book;
      window._floor = d;
      if (!wallTickGenAlive()) return true; /* late result kept for next visit */
      if (!wallMailRoomsWantEarlyRail()) return true;
      return true;
    }
    function wallTodosWantEarlyPaint() {
      try {
        const todoOn = document.getElementById("pane-todo");
        if (todoOn && !todoOn.classList.contains("on")) return false;
      } catch (ePane) {}
      const tabBtn = document.querySelector("nav.tabs button.on");
      const tab = (tabBtn && tabBtn.dataset.tab) || "";
      return tab === "jobs";
    }
    function wallPaintTodosEarly(merged) {
      /* absorb-only; still commit when gen stale / pane off. */
      if (!merged) return false;
      const book = absorbFloorSlice(merged);
      const scopeNow = floorScope();
      const d = (scopeNow.key.indexOf("project:") === 0)
        ? applyRailPick(cutFloor(book))
        : book;
      window._floor = d;
      if (!wallTickGenAlive()) return true; /* late result kept */
      if (!wallTodosWantEarlyPaint()) return true;
      return true;
    }
    function wallPaintFloorPartEarly(slice) {
      /* Progressive absorb. no live DOM until fp settle. commit even if gen stale. */
      if (!slice || typeof slice !== "object") return false;
      const book = absorbFloorSlice(slice);
      const scopeNow = floorScope();
      const d = (scopeNow.key.indexOf("project:") === 0)
        ? applyRailPick(cutFloor(book))
        : book;
      /* Merge into prior floor so multi-part progressive keeps earlier parts. */
      const prev = window._floor || {};
      const merged = Object.assign({}, prev, d);
      if (Array.isArray(prev.parts) || Array.isArray(d.parts)) {
        const seen = {};
        merged.parts = [];
        (prev.parts || []).concat(d.parts || []).forEach(function (p) {
          if (!p || seen[p]) return;
          seen[p] = true;
          merged.parts.push(p);
        });
      }
      window._floor = merged;
      try {
        const glance = floorGlanceFromFloor(merged);
        if (glance) floorGlanceCache = glance;
      } catch (eFloor) {}
      if (!wallTickGenAlive()) {
        /* Late part: paint off-pane last-good only (live .on untouched). */
        try { wallPaintOffPaneLastGood(merged, slice.parts || []); } catch (eOff) {}
        return true;
      }
      return true;
    }
    async function wallFetchFloorParts(scope, partsStr, onPart) {
      /* One versioned part per GET. Strip counts use this for todos and mail. */
      const parts = String(partsStr || "").split(",").map(function (p) { return p.trim(); }).filter(Boolean);
      const partPath = {
        mail: "/api/v1/mailbox",
        todos: "/api/v1/todos",
        agents: "/api/v1/agents",
        scores: "/api/v1/scores",
        holds: "/api/v1/holds",
        watchers: "/api/v1/watchers",
        events: "/api/v1/events",
        names: "/api/v1/names"
      };
      async function one(partList) {
        const ps = Array.isArray(partList) ? partList.join(",") : String(partList || "agents");
        const q = String(scope.query || "");
        const fpQ = floorFpQuery(scope.key, ps);
        /* pageable parts first page ?limit=50 (incl. events). */
        const pageable = { agents: 1, scores: 1, holds: 1, watchers: 1, events: 1, mail: 1, todos: 1, names: 1 };
        let path = partPath[ps];
        if (ps === "trees") {
          path = (typeof wallActiveTreeKind === "function" && wallActiveTreeKind() === "tree-mail")
            ? "/api/v1/tree-mail"
            : "/api/v1/tree-todo";
        }
        if (!path) return { down: true, status: 404 };
        let url = path + "?" + q + fpQ;
        if (pageable[ps]) url += "&limit=50";
        if (ps === "trees") {
          url += "&limit=50&depth=1";
          try { url += wallTreesWindowQuery(); } catch (eWin) {}
        }
        const r = await fetch(url, { cache: "no-store" });
        const ct = (r.headers.get("content-type") || "").toLowerCase();
        if (!r.ok || ct.indexOf("json") < 0) return { down: true, status: r.status };
        const json = await r.json();
        if (pageable[ps] && typeof wallRememberListNext === "function") {
          try { wallRememberListNext(ps === "mail" ? "mailbox" : (ps === "todos" ? "todos" : ps), json); } catch (eNext) {}
        }
        if (typeof onPart === "function") {
          try { onPart(json); } catch (eOn) {}
        }
        return { down: false, raw: json, part: ps };
      }
      if (parts.length <= 1) return one(partsStr || "agents");
      const settled = await Promise.all(parts.map(function (p) { return one(p); }));
      for (let i = 0; i < settled.length; i++) {
        if (settled[i] && settled[i].down) return { down: true, status: settled[i].status };
      }
      const out = { parts: [] };
      const partSeen = {};
      settled.forEach(function (row) {
        const json = row && row.raw;
        if (!json || typeof json !== "object") return;
        Object.keys(json).forEach(function (k) {
          if (k === "parts") return;
          if (k === "fp" && json.fp && typeof json.fp === "object") {
            out.fp = out.fp || {};
            Object.keys(json.fp).forEach(function (fk) {
              if (json.fp[fk] != null && json.fp[fk] !== "") out.fp[fk] = json.fp[fk];
            });
            return;
          }
          if (json[k] !== undefined) out[k] = json[k];
        });
        (Array.isArray(json.parts) ? json.parts : String(row.part || "").split(",")).forEach(function (p) {
          p = String(p || "").trim();
          if (!p || partSeen[p]) return;
          partSeen[p] = true;
          out.parts.push(p);
        });
      });
      return { down: false, raw: out };
    }




    /* WALL_NEST_PATH_WOW175: Nest URL paths /project|/station|/role (+slug).
     * Floor API still uses lan= via floorScope. Query ?projects= / ?stations=|?lan= /
     * ?roles=|?role= -> replaceState path (keep hash + other query). Station ids:
     * encodeURIComponent (IPv4 dots stay literal; IPv6 colons %3A).
     * NEST_PATH_WRITE=true. Writers emit /project|station|role/<slug>. */
    var NEST_PATH_WRITE = true; /* Hub SPA fallthrough live */
    function nestEncodeSlug(id) {
      return encodeURIComponent(String(id == null ? "" : id).trim());
    }
    function nestDecodeSlug(raw) {
      try { return decodeURIComponent(String(raw || "").trim()); }
      catch (eDec) { return String(raw || "").trim(); }
    }
    function nestProjectsFromSlug(slug) {
      return String(slug || "").split(",").map(nestDecodeSlug).map(function (s) {
        return String(s || "").trim();
      }).filter(Boolean);
    }
    function parseNestPath(pathname) {
      const m = String(pathname || "").match(/^\/(project|station|role)(?:\/([^/]*))?\/?$/);
      if (!m) return null;
      return { family: m[1], slug: nestDecodeSlug(m[2] || "") };
    }
    function nestFamilyForKind(kind) {
      if (kind === "project") return "project";
      if (kind === "lan") return "station";
      if (kind === "role") return "role";
      return "";
    }
    function applyNestPathToUrl(u, family, slug) {
      const pathSlug = String(slug || "");
      if (family && pathSlug) u.pathname = "/" + family + "/" + pathSlug;
      else u.pathname = "/";
      return u;
    }
    function stripNestQueryKeys(u) {
      ["projects", "stations", "lan", "roles", "role"].forEach(function (k) {
        u.searchParams.delete(k);
      });
      return u;
    }
    function compatNestQueryToPath() {
      if (!NEST_PATH_WRITE) return false; /* write gate */
      try {
        const u = new URL(String(location.href || ""));
        const q = u.searchParams;
        const cur = parseNestPath(u.pathname);
        let family = "";
        let slugPath = "";
        if (cur && cur.slug) {
          family = cur.family;
          slugPath = family === "project"
            ? nestProjectsFromSlug(cur.slug).map(nestEncodeSlug).join(",")
            : nestEncodeSlug(cur.slug);
        } else {
          const proj = String(q.get("projects") || "").trim();
          const st = String(q.get("stations") || q.get("lan") || "").trim();
          const role = String(q.get("roles") || q.get("role") || "").trim();
          if (proj) {
            family = "project";
            slugPath = csvList(proj).map(nestEncodeSlug).join(",");
          } else if (st) {
            family = "station";
            slugPath = nestEncodeSlug(st);
          } else if (role) {
            family = "role";
            slugPath = nestEncodeSlug(role);
          }
        }
        if (!family || !slugPath) return false;
        stripNestQueryKeys(u);
        applyNestPathToUrl(u, family, slugPath);
        const next = u.pathname + (u.searchParams.toString() ? "?" + u.searchParams.toString() : "") + (u.hash || "");
        const now = String(location.pathname || "") + String(location.search || "") + String(location.hash || "");
        if (next === now) return false;
        history.replaceState(null, "", next);
        return true;
      } catch (eCompat) { return false; }
    }
    function nestPickFromPath() {
      const cur = parseNestPath(typeof location !== "undefined" ? location.pathname : "");
      if (!cur || !cur.slug) return null;
      if (cur.family === "station") return { kind: "lan", id: cur.slug };
      if (cur.family === "role") return { kind: "role", id: cur.slug };
      if (cur.family === "project") {
        const first = nestProjectsFromSlug(cur.slug)[0];
        return first ? { kind: "project", id: first } : null;
      }
      return null;
    }

    const DEFAULT_FILTER = { projects: [], owner: "", kind: "", status: "", from: "", to: "" };
    function currentFilter() {
      const q = new URLSearchParams(location.search);
      const nest = parseNestPath(location.pathname);
      let projects = csvList(q.get("projects") || "");
      if (!projects.length && nest && nest.family === "project" && nest.slug) {
        projects = nestProjectsFromSlug(nest.slug);
      }
      return {
        projects: projects,
        owner: (q.get("owner") || "").trim(),
        kind: (q.get("kind") || "").trim().toLowerCase(),
        status: (q.get("status") || "").trim().toLowerCase(),
        from: (q.get("from") || "").trim(),
        to: (q.get("to") || "").trim(),
      };
    }
    function urlHasFilter() {
      const q = new URLSearchParams(location.search);
      if (["projects", "owner", "kind", "status", "from", "to", "stations", "lan", "roles", "role"].some(k => q.has(k))) return true;
      const nest = parseNestPath(location.pathname);
      return !!(nest && nest.slug);
    }
    function filterActive(f) {
      return !!(f.projects.length || f.owner || f.kind || f.status || f.from || f.to);
    }
    function filterKey(f) {
      return [
        (f.projects || []).slice().sort().join(","),
        f.owner || "", f.kind || "", f.status || "", f.from || "", f.to || "",
      ].join("|");
    }
    function rowDay(row) {
      const raw = row.at || row.created_at || row.updated_at || row.asked_at || "";
      return String(raw).replace("T", " ").slice(0, 10);
    }
    function rowOwners(row) {
      return [row.owner, row.who, row.src, row.dst, row.asker, row.volunteer, row.creator, row.assigned]
        .map(x => String(x || "").toLowerCase()).filter(Boolean);
    }
    function inWall(pid, allow) {
      if (!allow.length) return true;
      return allow.indexOf(String(pid || "")) >= 0;
    }
    function rowPasses(row, f) {
      if (!inWall(millGid(row), f.projects || [])) return false;
      if (f.owner) {
        const want = f.owner.toLowerCase();
        if (rowOwners(row).indexOf(want) < 0) return false;
      }
      const day = rowDay(row);
      if (f.from && day && day < f.from) return false;
      if (f.to && day && day > f.to) return false;
      return true;
    }
    function issuePasses(row, f) {
      if (!rowPasses(row, f)) return false;
      if (f.kind && String(row.kind || "").toLowerCase() !== f.kind) return false;
      if (f.status && String(row.status || "").toLowerCase() !== f.status) return false;
      return true;
    }
    function seatPasses(row, f) {
      /* The scope query already limited the book and kept seats with no roster. */
      return rowPasses(row, Object.assign({}, f, { projects: [] }));
    }
    /* Loop-3 floor part fingerprints (Wall contract card rule-fingerprints: mill todo wall-contract rule-fingerprints).
     * Store only server-echoed fps, keyed by floorScope().key + parts=.
     * Empty part + unchanged fp => keep prior slice keys; skip paint for that part.
     * Empty part + new fp => real empty (trees wipe allowed).
     * No fp map (old servers) => do not paint-skip on empty alone (trees keep
     * remains as pre-fp lan-scope nest safeguard until hosts apply SQL). */
    const FLOOR_PART_KEYS = {
      agents: ["agents"],
      mail: ["mailbox", "desk_unread"],
      todos: ["needs", "issues"],
      events: ["events"],
      holds: ["locks"],
      scores: ["kpis"],
      trees: ["trees"],
      watchers: ["watchers"],
      timeline: ["timeline"],
      names: ["catalog"],
    };
    let _floorFpByScope = {};
    window._floorFpByScope = _floorFpByScope;
    function floorFpScopeKey(scopeKey, partsStr) {
      return String(scopeKey || "") + "|" + String(partsStr || "");
    }
    function floorFpStored(scopeKey, partsStr) {
      return _floorFpByScope[floorFpScopeKey(scopeKey, partsStr)] || {};
    }
    function floorFpRemember(scopeKey, partsStr, echoed) {
      if (!echoed || typeof echoed !== "object") return;
      const k = floorFpScopeKey(scopeKey, partsStr);
      const next = Object.assign({}, _floorFpByScope[k] || {});
      Object.keys(echoed).forEach(function (part) {
        const v = echoed[part];
        if (v == null || v === "") return;
        next[part] = String(v);
      });
      _floorFpByScope[k] = next;
      window._floorFpByScope = _floorFpByScope;
    }
    function floorFpForgetScope(scopeKey) {
      /* Next fetch for this cut must include desks. A stored fp comes back empty and skips #here. */
      const prefix = String(scopeKey || "") + "|";
      if (!scopeKey) return;
      Object.keys(_floorFpByScope).forEach(function (k) {
        if (k.indexOf(prefix) === 0) delete _floorFpByScope[k];
      });
      window._floorFpByScope = _floorFpByScope;
    }
    function floorFpQuery(scopeKey, partsStr) {
      const stored = floorFpStored(scopeKey, partsStr);
      const parts = String(partsStr || "").split(",").map(function (p) {
        return p.trim();
      }).filter(Boolean);
      const pairs = [];
      parts.forEach(function (part) {
        if (stored[part]) pairs.push(part + ":" + stored[part]);
      });
      if (!pairs.length) return "";
      return "&fp=" + encodeURIComponent(pairs.join(","));
    }
    function floorPartPayloadEmpty(slice, part) {
      const keys = FLOOR_PART_KEYS[part] || [];
      if (!keys.length || !slice) return false;
      let seen = false;
      for (let i = 0; i < keys.length; i++) {
        const key = keys[i];
        if (slice[key] === undefined) continue;
        seen = true;
        const v = slice[key];
        if (Array.isArray(v)) {
          if (v.length) return false;
        } else if (v && typeof v === "object") {
          if (Object.keys(v).length) return false;
        } else if (v != null && v !== "") {
          return false;
        }
      }
      return seen;
    }
    function floorPartFpHit(slice, part, storedFp) {
      /* Empty + echoed fp equals stored => keep prior; skip paint. */
      if (!slice || !slice.fp || typeof slice.fp !== "object") return false;
      if (storedFp == null || storedFp === "") return false;
      const echoed = slice.fp[part];
      if (echoed == null || echoed === "") return false;
      if (String(echoed) !== String(storedFp)) return false;
      return floorPartPayloadEmpty(slice, part);
    }
    function mergeFloorSlice(prev, slice, opts) {
      const parts = (slice && slice.parts) || [];
      if (!parts.length) return slice || prev || {};
      const base = Object.assign({}, prev || {});
      const storedFp = (opts && opts.storedFp) || {};
      const hasFpMap = !!(slice && slice.fp && typeof slice.fp === "object");
      parts.forEach(function (part) {
        (FLOOR_PART_KEYS[part] || []).forEach(function (key) {
          if (slice[key] === undefined) return;
          if (hasFpMap && floorPartFpHit(slice, part, storedFp[part])) return;
          /* Old servers (no fp): keep prior trees if slice empties (lan nest wipe). */
          if (!hasFpMap && key === "trees" && Array.isArray(slice[key]) && !slice[key].length && Array.isArray(base[key]) && base[key].length) return;
          /* A depth-1 poll repeats the first page. Keep cards already loaded under those nodes. */
          if (key === "trees" && Array.isArray(base[key]) && base[key].length && Array.isArray(slice[key]) && slice[key].length) {
            base[key] = wallMergeTreesForests(base[key], slice[key]);
            return;
          }
          base[key] = slice[key];
        });
      });
      ["at", "node", "version", "office", "office_id", "mill", "trust"].forEach(function (key) {
        if (slice[key] !== undefined) base[key] = slice[key];
      });
      /* Between rows are not a v1 part. Keep them only on the slice that fetched them. */
      if (Array.isArray(slice.between)) base.between = slice.between;
      else delete base.between;
      try { wallRememberTrust(slice); } catch (eTrust2) {}
      if (hasFpMap) base.fp = slice.fp;
      if ((parts.indexOf("agents") >= 0 || parts.indexOf("mail") >= 0) && slice.office_glance) {
        base.office_glance = slice.office_glance;
      }
      const seen = {};
      (base.parts || []).forEach(function (part) { seen[part] = true; });
      parts.forEach(function (part) { seen[part] = true; });
      base.parts = Object.keys(seen);
      return base;
    }
    function cutFloor(d) {
      const f = currentFilter();
      const out = Object.assign({}, d);
      if (!filterActive(f)) {
        return out;
      }
      const keep = rows => (rows || []).filter(r => rowPasses(r, f));
      const keepIss = rows => (rows || []).filter(r => issuePasses(r, f));
      out.events = keep(d.events);
      /* Lean letters omit roster_id. The mailbox fetch is already this cut. */
      out.mailbox = (d.mailbox || []).filter(function (r) {
        if (!r) return false;
        if (!millGid(r)) return rowPasses(r, Object.assign({}, f, { projects: [] }));
        return rowPasses(r, f);
      });
      out.locks = keep(d.locks);
      out.agents = (d.agents || []).filter(r => seatPasses(r, f));
      out.kpis = keep(d.kpis);
      out.needs = keep(d.needs);
      out.wanted = keep(d.wanted);
      out.spend = keep(d.spend);
      out.spend_lines = keep(d.spend_lines);
      out.issues = keepIss(d.issues);
      out.watchers = keep(d.watchers);
      if (Array.isArray(d.trees)) {
        out.trees = d.trees.map(t => {
          const nodes = (t && t.nodes) || [];
          const pass = [];
          nodes.forEach((n, i) => { if (rowPasses(n, f)) pass.push(i); });
          if (!pass.length) return null;
          const keepI = {};
          pass.forEach(i => {
            keepI[i] = 1;
            const lft = Number(nodes[i].lft);
            const rgt = Number(nodes[i].rgt);
            nodes.forEach((a, j) => {
              if (Number(a.lft) < lft && Number(a.rgt) > rgt) keepI[j] = 1;
            });
          });
          return Object.assign({}, t, { nodes: nodes.filter((_, j) => keepI[j]) });
        }).filter(Boolean);
      }
      out.on_it = keep(d.on_it);
      out.projects = (d.groups || d.projects || []).filter(p => inWall(p, f.projects));
      out.scorecards = {};
      Object.keys(d.scorecards || {}).forEach(k => {
        if (inWall(k, f.projects)) out.scorecards[k] = d.scorecards[k];
      });
      out.live_agents = (out.agents || []).filter(a => a.alive).length;
      out.live_locks = (out.locks || []).length;
      out.dead_holders = (out.locks || []).filter(r => r.holder_dead).length;
      out.open_needs = (out.needs || []).filter(n => n.status === "open").length;
      out.claimed_needs = (out.needs || []).filter(n => n.status === "claimed").length;
      out.open_issues = (out.issues || []).length;
      /* OFFICE_GLANCE: keep aggregates; filter desk_unread to visible live owners when filter on */
      out.desk_unread = d.desk_unread || {};
      out.office_glance = d.office_glance || null;
      if (filterActive(f) && out.desk_unread) {
        const liveOwners = new Set((out.agents || []).filter(a => a.alive).map(a => String(a.owner || "").trim()));
        const slim = {};
        Object.keys(out.desk_unread).forEach(k => { if (liveOwners.has(k)) slim[k] = out.desk_unread[k]; });
        out.desk_unread = slim;
      }
      out.wall = f.projects;
      return out;
    }
    const FILTERS_KEY = "mill-filters";
    function savedFilters() {
      try {
        const raw = JSON.parse(localStorage.getItem(FILTERS_KEY) || localStorage.getItem("factory-walls") || "[]");
        if (!Array.isArray(raw)) return [];
        return raw.map(item => {
          if (typeof item === "string") {
            return { label: item, projects: csvList(item), owner: "", kind: "", status: "", from: "", to: "" };
          }
          return {
            label: item.label || "filter",
            projects: csvList(Array.isArray(item.projects) ? item.projects.join(",") : (item.projects || "")),
            owner: item.owner || "", kind: item.kind || "", status: item.status || "",
            from: item.from || "", to: item.to || "",
          };
        });
      } catch (e) { return []; }
    }
    function writeFilters(list) {
      try { localStorage.setItem(FILTERS_KEY, JSON.stringify((list || []).slice(0, 16))); } catch (e) {}
    }
    function rememberFilter(f, label) {
      if (!filterActive(f)) return;
      const key = filterKey(f);
      const all = savedFilters().filter(x => filterKey(x) !== key);
      all.push({
        label: (label || f.kind || f.owner || (f.projects || []).join(",") || "filter").slice(0, 64),
        projects: f.projects, owner: f.owner, kind: f.kind, status: f.status, from: f.from, to: f.to,
      });
      writeFilters(all);
    }
    function forgetFilter(key) {
      writeFilters(savedFilters().filter(x => filterKey(x) !== key));
      if (filterKey(currentFilter()) === key) goFilter({});
      else paintWallNav();
    }
    function applyFilterToUrl(f) {
      const u = new URL(location.href);
      ["projects", "owner", "kind", "status", "from", "to"].forEach(k => u.searchParams.delete(k));
      stripNestQueryKeys(u);
      if (f.owner) u.searchParams.set("owner", f.owner);
      if (f.kind) u.searchParams.set("kind", f.kind);
      if (f.status) u.searchParams.set("status", f.status);
      if (f.from) u.searchParams.set("from", f.from);
      if (f.to) u.searchParams.set("to", f.to);
      if (NEST_PATH_WRITE) {
        /* Projects live under /project/<slug>. */
        if (f.projects && f.projects.length) {
          applyNestPathToUrl(u, "project", f.projects.map(nestEncodeSlug).join(","));
        } else {
          const cur = parseNestPath(u.pathname);
          /* Filter write owns projects family; empty projects clears any nest path
           * (stations/roles use applyRailNestUrl / selectRail instead). */
          if (cur) applyNestPathToUrl(u, "", "");
        }
      } else {
        /* fallback: keep ?projects= when NEST_PATH_WRITE false; clear stray nest path. */
        if (f.projects && f.projects.length) {
          u.searchParams.set("projects", f.projects.join(","));
        }
        const cur = parseNestPath(u.pathname);
        if (cur) applyNestPathToUrl(u, "", "");
      }
      return u;
    }
    function applyRailNestUrl(kind, id) {
      const u = new URL(location.href);
      if (!NEST_PATH_WRITE) {
        const cur = parseNestPath(u.pathname);
        if (cur) applyNestPathToUrl(u, "", "");
        stripNestQueryKeys(u);
        if (kind === "project" && id) u.searchParams.set("projects", String(id));
        return u;
      }
      stripNestQueryKeys(u);
      ["projects", "owner", "kind", "status", "from", "to"].forEach(function (k) {
        /* keep non-scope filter query; drop projects (path family owns scope). */
        if (k === "projects") u.searchParams.delete(k);
      });
      const family = nestFamilyForKind(kind);
      applyNestPathToUrl(u, family, family ? nestEncodeSlug(id) : "");
      return u;
    }
    let railPick = null;
    /* Which rail cut last wrote #here. An fp hit must not leave another cut on screen. */
    let _hereDomPick = "";
    let _floorBook = null;
    let _floorBookKey = "";
    /* #718: CONNECTED (#here) belongs to one scope. On a roster switch it shows the
       hourglass until the new roster's desks are read, instead of keeping the last
       roster's desks under a glance that already speaks for the new one. */
    function wallHereAgentsRead(d) {
      /* The cut view always carries an agents array (cutFloor fills []), so ask the
         scope's raw book whether the agents part was read; a slice says it in parts. */
      if (_floorBook) return Array.isArray(_floorBook.agents);
      if (!d || !Array.isArray(d.agents)) return false;
      return !Array.isArray(d.parts) || d.parts.indexOf("agents") >= 0;
    }
    function wallHereHourglass() {
      _hereDomPick = "";
      const h = (typeof document !== "undefined") ? document.getElementById("here") : null;
      if (h && !wallIsLoadingEl(h)) h.innerHTML = wallLoadingHtml("Loading desks...");
    }
    function wallHereNeedsPaint(pickKey, d) {
      /* Another cut wrote #here (or the hourglass holds it) and this scope's desks are
         read: paint, even when the new roster has no desks (that is the honest empty). */
      return String(pickKey || "") !== _hereDomPick && wallHereAgentsRead(d);
    }
    function resetFloorBook() {
      _floorBook = null;
      _floorBookKey = "";
      _floorHash = "";
      try { wallResetStripReady(); } catch (eStripReset) {}
      _railPickApplied = "";
      window._floorBook = null;
      window._floorRaw = null;
      /* #715: progressive paints merge into window._floor; a new scope must not
         inherit the last scope's rows and parts (the strip counted them). Panes
         keep their DOM until the new paint lands. */
      window._floor = null;
      try { wallHereHourglass(); } catch (eHereHg) {}
    }
    function bookIsProject(query) {
      return !!_floorBook && _floorBookKey === ("project:" + String(query || ""));
    }
    function absorbFloorSlice(slice, opts) {
      const key = floorScope().key;
      if (_floorBookKey !== key) {
        _floorBook = null;
        _floorBookKey = key;
      }
      _floorBook = mergeFloorSlice(_floorBook, slice, opts);
      window._floorBook = _floorBook;
      window._floorRaw = _floorBook;
      try { wallRememberTrust(slice); } catch (eTrust3) {}
      return _floorBook;
    }
    function goFilter(f, keepPick) {
      const prevProject = floorProjectQuery();
      if (!keepPick) {
        railPick = null;
        try { sessionStorage.removeItem("mill-rail-pick"); } catch (e) {}
        markRailPick();
      }
      history.pushState({}, "", applyFilterToUrl(f || {}));
      if (floorProjectQuery() !== prevProject) {
        resetFloorBook();
        try { floorFpForgetScope(floorScope().key); } catch (eFpForget) {}
      }
      paintWallLabel();
      paintWallNav();
      fillFilterForm(f || {});
      tick(true);
    }
    function goWall(ids) {
      goFilter({ projects: ids || [], owner: "", kind: "", status: "", from: "", to: "" });
    }
    function paintWallLabel() {
      const el = document.getElementById("wall-label");
      if (!el) return;
      const f = currentFilter();
      if (!filterActive(f)) { el.textContent = "office floor"; return; }
      const bits = [];
      if (f.projects.length) bits.push(f.projects.join(", "));
      if (f.owner) bits.push("owner " + f.owner);
      if (f.kind) bits.push(f.kind);
      if (f.status) bits.push(f.status);
      if (f.from || f.to) bits.push((f.from || "...") + " to " + (f.to || "..."));
      el.textContent = "filter: " + bits.join(" | ");
    }
    function wallCutList() {
      const raw = window._floorRaw || {};
      const known = [];
      const seenP = {};
      const addP = (p) => {
        p = String(p || "").trim();
        if (!p || seenP[p]) return;
        seenP[p] = true;
        known.push(p);
      };
      (raw.groups || []).forEach(addP);
      (raw.projects || []).forEach(addP);
      (raw.agents || []).forEach(a => addP(a.roster_id));
      const cuts = [];
      const seen = {};
      const add = (label, f, custom) => {
        const key = filterKey(f);
        if (seen[key]) return;
        seen[key] = true;
        cuts.push({ label, f, key, custom: !!custom });
      };
      (currentFilter().projects || []).forEach(p => add(millName("proj", p), { projects: [String(p)], owner: "", kind: "", status: "", from: "", to: "" }, false));
      known.forEach(p => add(millName("proj", p), { projects: [String(p)], owner: "", kind: "", status: "", from: "", to: "" }, false));
      savedFilters().forEach(sf => add(sf.label, sf, true));
      const officeName = String(raw.office || "Office");
      add(millName("proj", officeName), { projects: [], owner: "", kind: "", status: "", from: "", to: "" }, false);
      const office = cuts.filter(c => !filterActive(c.f));
      const rest = cuts.filter(c => filterActive(c.f)).sort((a, b) => a.label.localeCompare(b.label));
      return office.concat(rest);
    }
    function millNameSet(kind, rows) {
      const seen = {};
      const out = [];
      (rows || []).forEach(x => {
        const s = millName(kind, x);
        if (!s || seen[s]) return;
        seen[s] = true;
        out.push(s);
      });
      out.sort((a, b) => a.localeCompare(b));
      return out;
    }
    function millLabelBag(d) {
      const out = [];
      const push = (v) => {
        if (v == null || v === "") return;
        if (Array.isArray(v)) { v.forEach(push); return; }
        if (typeof v === "object") { push(v.name || v.label || v.slug); return; }
        out.push(v);
      };
      push(d.labels);
      (d.needs || []).forEach(n => push(n.labels || n.label));
      (d.issues || []).forEach(n => push(n.labels || n.label));
      (d.mailbox || []).forEach(m => push(m.labels || m.label));
      return out;
    }
    function paintGlossaryFrom(rows) {
      if (window.WallGlossary && typeof window.WallGlossary.paintFrom === "function") {
        return window.WallGlossary.paintFrom(rows);
      }
      wallEnsureGlossary().then(function () {
        if (window.WallGlossary) window.WallGlossary.paintFrom(rows);
      });
    }
    function paintGlossary() {
      wallEnsureGlossary().then(function () {
        if (window.WallGlossary) window.WallGlossary.paint();
      });
    }
    function wallEnsureGlossary() {
      if (typeof wallEnsureModule === "function") return wallEnsureModule("glossary");
      if (typeof wallLoadScript === "function") return wallLoadScript("/glossary/glossary.js?v=wow280");
      return Promise.resolve();
    }

    function paintWallNav() {
      const nav = document.getElementById("walls-nav");
      if (!nav) return;
      const cur = filterKey(currentFilter());
      const cuts = wallCutList();
      const keys = cuts.map(c => c.key + (c.custom ? "x" : "")).join("|");
      const sig = keys + "/" + cur;
      if (nav.dataset.sig === sig) return;
      nav.dataset.keys = keys;
      nav.dataset.sig = sig;
      const chip = (c, nest) => {
        const on = c.key === cur ? " on" : "";
        const extra = c.custom
          ? `<button type="button" class="wall-copy" data-copy-filter="${esc(c.key)}" title="copy shareable URL">copy</button>` +
            `<button type="button" class="wall-forget" data-forget="${esc(c.key)}" title="forget this chip on this browser">x</button>`
          : "";
        const ico = nest ? "project" : "office";
        return `<span class="wall-chip${on}${nest ? " nest" : ""}"><button type="button" class="${on}" data-ico="${ico}" data-filter="${esc(c.key)}" title="${esc(c.label || "Office")}">${esc(c.label || "Office")}</button>${extra}</span>`;
      };
      const office = cuts.filter(c => !filterActive(c.f));
      const rest = cuts.filter(c => filterActive(c.f));
      nav.innerHTML = office.map(c => chip(c, false)).join("") + rest.map(c => chip(c, true)).join("");
      nav.querySelectorAll("button[data-filter]").forEach(btn => {
        btn.addEventListener("click", () => {
          const key = btn.getAttribute("data-filter") || "";
          const hit = wallCutList().find(c => c.key === key);
          goFilter(hit ? hit.f : {});
        });
      });
      nav.querySelectorAll("button[data-forget]").forEach(btn => {
        btn.addEventListener("click", ev => {
          ev.preventDefault();
          ev.stopPropagation();
          forgetFilter(btn.getAttribute("data-forget") || "");
        });
      });
      nav.querySelectorAll("button[data-copy-filter]").forEach(btn => {
        btn.addEventListener("click", ev => {
          ev.preventDefault();
          ev.stopPropagation();
          const key = btn.getAttribute("data-copy-filter") || "";
          const hit = wallCutList().find(c => c.key === key);
          copyText(applyFilterToUrl(hit ? hit.f : currentFilter()).toString());
        });
      });
    }
    function fillFilterForm(f) {
      f = f || currentFilter();
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ""; };
      set("flt-projects", (f.projects || []).join(", "));
      set("flt-owner", f.owner);
      set("flt-kind", f.kind);
      set("flt-status", f.status);
      set("flt-from", f.from);
      set("flt-to", f.to);
    }
    function readFilterForm() {
      return {
        projects: csvList(document.getElementById("flt-projects").value),
        owner: (document.getElementById("flt-owner").value || "").trim(),
        kind: (document.getElementById("flt-kind").value || "").trim(),
        status: (document.getElementById("flt-status").value || "").trim(),
        from: (document.getElementById("flt-from").value || "").trim(),
        to: (document.getElementById("flt-to").value || "").trim(),
      };
    }
    function showFilterPanel(on) {
      document.getElementById("filter-panel").hidden = !on;
      if (on) fillFilterForm(currentFilter());
    }
    document.getElementById("wall-add").addEventListener("click", () => showFilterPanel(true));
    document.getElementById("filter-cancel").addEventListener("click", () => showFilterPanel(false));
    document.getElementById("filter-form").addEventListener("submit", ev => {
      ev.preventDefault();
      goFilter(readFilterForm());
    });
    document.getElementById("filter-save").addEventListener("click", () => {
      const f = readFilterForm();
      rememberFilter(f, (document.getElementById("flt-name").value || "").trim());
      goFilter(f);
      copyText(applyFilterToUrl(f).toString());
      showFilterPanel(false);
    });
    document.getElementById("filter-clear").addEventListener("click", () => {
      goFilter({});
      showFilterPanel(false);
    });
    window.addEventListener("popstate", () => {
      let painted = false;
      try {
        const np = nestPickFromPath();
        if (np && np.kind === "role") {
          try {
            const held = floorScope();
            if (held && held.query) _roleScopeHold = { key: held.key, query: held.query };
          } catch (eHoldPop) { _roleScopeHold = null; }
        } else {
          _roleScopeHold = null;
        }
        if (np) {
          railPick = { kind: np.kind, id: np.id, desks: np.kind === "project" ? null : (roleDeskCache[np.id] || null) };
          try { sessionStorage.setItem("mill-rail-pick", JSON.stringify({ kind: np.kind, id: np.id })); } catch (ePop) {}
          markRailPick();
          if (np.kind === "project" && bookIsProject("project=" + encodeURIComponent(np.id)) && window._floorRaw) {
            paintLoadedFloor();
            painted = true;
          } else if (np.kind === "role" && window._floorRaw) {
            const kind = np.kind;
            const id = np.id;
            Promise.resolve(roleDeskCache[id] || desksForPick(kind, id)).then(function (desks) {
              if (!railPick || railPick.kind !== kind || railPick.id !== id) return;
              railPick.desks = desks;
              if (window._floorRaw) paintLoadedFloor();
            });
            painted = true;
          }
        }
      } catch (eSync) {}
      paintWallLabel();
      paintWallNav();
      if (!painted) {
        try { floorFpForgetScope(floorScope().key); } catch (eFpPop) {}
      }
      tick(true);
    });
    try { compatNestQueryToPath(); } catch (eNestCompat) {}
    if (!urlHasFilter()) {
      /* no baked-in project filter; empty = show the live office */
    }
    paintWallLabel();
    paintWallNav();
    try { wallMarkShellLoading(); } catch (eShellLoad) {}
    const inviteFor = (new URLSearchParams(location.search).get("for") || "").toLowerCase();
    if (inviteFor === "agent" || inviteFor === "human") {
      showTab("guide");
    } else {
      /* FLOOR_BOOT_FIX: defer showTab until after floor/score lets init (end of script) */
      window.__wallDeferStartTab = true;
    }
    window.addEventListener("hashchange", () => {
      let name = (location.hash || "#session").replace("#", "");
      if (name === "scorecards") name = "score"; /* SCORE_BOOT_FIX */
      if (["session", "jobs", "plan", "trees", "nest", "backlog", "board", "issues", "mail", "wire", "stations", "leases", "watch", "score", "guide", "glossary", "admin", "floor"].includes(name)) showTab(name);
    });
    const adminOpen = document.getElementById("admin-open");
    if (adminOpen) adminOpen.addEventListener("click", () => showTab("admin"));
    const debugWire = document.getElementById("debug-wire");
    if (debugWire) debugWire.addEventListener("click", () => showTab("wire"));
    const guideOpen = document.getElementById("guide-open");
    if (guideOpen) guideOpen.addEventListener("click", () => showTab("guide"));
    const glossaryOpen = document.getElementById("glossary-open");
    if (glossaryOpen) glossaryOpen.addEventListener("click", () => showTab("glossary"));
    /* Service glance. One read when it opens. The board tick does not call it. */
    let _svcPacket = null;
    let _svcSection = "alerts";
    let _svcGen = 0;
    function glanceMarkSection() {
      document.querySelectorAll("#wall-service [data-svc]").forEach(function (btn) {
        btn.classList.toggle("on", btn.getAttribute("data-svc") === _svcSection);
      });
    }
    function paintWallService() { return wallLazyCall("servicePaint", "paintWallService", paintWallService, arguments); }
    async function loadWallService() {
      const gen = ++_svcGen;
      let data = null;
      try {
        const r = await fetch("/api/v1/glance", { cache: "no-store", credentials: "same-origin" });
        data = await r.json();
        if (!r.ok || !data || typeof data !== "object" || data.error) data = null;
      } catch (e) {
        data = null;
      }
      if (gen !== _svcGen || !data) {
        if (gen === _svcGen) _svcPacket = null;
        return 0;
      }
      _svcPacket = data;
      return gen;
    }
    async function openWallService() {
      const root = document.getElementById("wall-service");
      if (!root) return;
      const gen = await loadWallService();
      if (!gen || gen !== _svcGen) return;
      _svcSection = "alerts";
      glanceMarkSection();
      root.hidden = false;
      const exit = document.getElementById("wall-service-exit");
      if (exit) exit.focus();
      paintWallService();
    }
    function closeWallService() {
      const root = document.getElementById("wall-service");
      if (root) root.hidden = true;
      _svcPacket = null;
      _svcGen += 1;
      const body = document.getElementById("wall-service-body");
      if (body) body.textContent = "";
    }
    (function wireWallService() {
      const root = document.getElementById("wall-service");
      const exit = document.getElementById("wall-service-exit");
      if (exit) exit.addEventListener("click", closeWallService);
      if (root) {
        root.addEventListener("click", function (ev) {
          const btn = ev.target && ev.target.closest ? ev.target.closest("[data-svc]") : null;
          if (!btn) return;
          _svcSection = btn.getAttribute("data-svc") || "alerts";
          glanceMarkSection();
          paintWallService();
        });
      }
      /* Key names only. The order and the word stay out of this file. */
      const GLANCE_GLYPHS = [
        "\u{1F31E}", "\u{1F319}", "\u2B50", "\u26A1", "\u{1F525}", "\u{1F4A7}", "\u2744", "\u{1F308}", "\u2601", "\u2600",
        "\u{1F338}", "\u{1F332}", "\u{1F340}", "\u{1F341}", "\u{1F344}", "\u{1F335}", "\u{1F33B}", "\u{1F334}", "\u{1F339}", "\u{1F33A}",
        "\u{1F436}", "\u{1F431}", "\u{1F42D}", "\u{1F430}", "\u{1F98A}", "\u{1F43B}", "\u{1F43C}", "\u{1F428}", "\u{1F42F}", "\u{1F981}",
        "\u{1F42E}", "\u{1F437}", "\u{1F438}", "\u{1F435}", "\u{1F414}", "\u{1F427}", "\u{1F426}", "\u{1F984}", "\u{1F41D}", "\u{1F98B}",
        "\u{1F34E}", "\u{1F34A}", "\u{1F34B}", "\u{1F34C}", "\u{1F349}", "\u{1F347}", "\u{1F353}", "\u{1F34D}", "\u{1F351}", "\u{1F95D}",
        "\u{1F951}", "\u{1F33D}", "\u{1F955}", "\u{1F35E}", "\u{1F9C0}", "\u{1F355}", "\u{1F354}", "\u{1F36A}", "\u{1F369}", "\u{1F382}",
        "\u{1F697}", "\u{1F6F5}", "\u{1F68C}", "\u{1F693}", "\u{1F691}", "\u{1F692}", "\u{1F69C}", "\u{1F6B2}", "\u2708", "\u{1F680}",
        "\u26F5", "\u2693", "\u{1F3E0}", "\u26FA", "\u{1F3F0}", "\u{1F5FD}", "\u{1F5FF}", "\u26EA", "\u26F2", "\u{1F30B}",
        "\u231A", "\u23F0", "\u{1F511}", "\u{1F512}", "\u2709", "\u2702", "\u270F", "\u{1F4CC}", "\u{1F4CE}", "\u{1F50D}",
        "\u2654", "\u{1F3B8}", "\u{1F3BA}", "\u{1F3B2}", "\u{1F3AF}", "\u2660", "\u2665", "\u2666", "\u2663", "\u{1F3B5}"
      ];
      function glanceGlyph(index) {
        return GLANCE_GLYPHS[index] || "";
      }
      function glanceKeyName(index) {
        const a = "abcdefghijklmnopqrstuvwxyz";
        let n = (index + 1) * 7919;
        let s = "";
        for (let i = 0; i < 10; i++) {
          n = (Math.imul(n, 1103515245) + 12345 + i * 97) >>> 0;
          s += a[n % 26];
        }
        return s;
      }
      let _padTaps = [];
      let _padPost = false;
      let _padIdle = 0;
      function glancePaintPad() {
        const echo = document.getElementById("wall-keypad-echo");
        if (!echo) return;
        let text = "";
        for (let i = 0; i < _padTaps.length; i++) text += glanceGlyph(_padTaps[i]);
        echo.textContent = text;
      }
      function glanceClearPad() {
        _padTaps = [];
        const word = document.getElementById("wall-keypad-word");
        if (word) word.value = "";
        glancePaintPad();
      }
      function glanceBuildPad() {
        const grid = document.getElementById("wall-keypad-grid");
        if (!grid || grid.childElementCount) return;
        let board = null;
        for (let i = 0; i < 100; i++) {
          if (i % 25 === 0) {
            board = document.createElement("div");
            board.className = "pad-grid";
            grid.appendChild(board);
          }
          const b = document.createElement("button");
          b.type = "button";
          b.setAttribute("data-key", String(i));
          b.textContent = glanceGlyph(i);
          board.appendChild(b);
        }
      }
      function glanceShufflePad() {
        const grid = document.getElementById("wall-keypad-grid");
        if (!grid) return;
        const order = [];
        for (let i = 0; i < 100; i++) order.push(i);
        for (let i = order.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          const swap = order[i];
          order[i] = order[j];
          order[j] = swap;
        }
        const buttons = grid.querySelectorAll("button");
        for (let i = 0; i < buttons.length; i++) {
          const n = order[i];
          buttons[i].setAttribute("data-key", String(n));
          buttons[i].textContent = glanceGlyph(n);
        }
      }
      function glanceArmIdle(ms) {
        if (_padIdle) clearTimeout(_padIdle);
        _padIdle = setTimeout(function () {
          _padIdle = 0;
          glanceClearPad();
          glanceShowSymbols();
        }, ms || 8000);
      }
      function glanceStopIdle() {
        if (_padIdle) { clearTimeout(_padIdle); _padIdle = 0; }
      }
      function glanceShowSymbols() {
        const symbols = document.getElementById("wall-keypad-symbols");
        const form = document.getElementById("wall-keypad-form");
        if (symbols) symbols.hidden = false;
        if (form) form.hidden = true;
      }
      function glanceShowWord() {
        const form = document.getElementById("wall-keypad-form");
        if (form) form.hidden = false;
        const word = document.getElementById("wall-keypad-word");
        if (word) word.focus();
        glanceArmIdle(60000);
      }
      function openKeypad() {
        const pad = document.getElementById("wall-keypad");
        if (!pad) return;
        glanceBuildPad();
        glanceClearPad();
        glanceShufflePad();
        glanceShowSymbols();
        glanceArmIdle();
        pad.hidden = false;
      }
      function closeKeypad() {
        const pad = document.getElementById("wall-keypad");
        glanceStopIdle();
        if (pad) pad.hidden = true;
        glanceClearPad();
      }
      async function glanceSubmitPad(ev) {
        if (ev) ev.preventDefault();
        if (_padPost) return;
        const wordEl = document.getElementById("wall-keypad-word");
        const passphrase = String(wordEl && wordEl.value || "");
        if (_padTaps.length < 1 || _padTaps.length > 16) return;
        const taps = [];
        for (let i = 0; i < _padTaps.length; i++) taps.push(glanceKeyName(_padTaps[i]));
        glanceStopIdle();
        _padPost = true;
        let ok = false;
        try {
          const r = await fetch("/api/v1/glance/tap", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-Mill-Wall": "1" },
            body: JSON.stringify({ taps: taps, passphrase: passphrase })
          });
          let data = null;
          try { data = await r.json(); } catch (eJson) { data = null; }
          ok = r.status === 200 && !!(data && data.open === true);
        } catch (e) {
          ok = false;
        }
        _padPost = false;
        glanceClearPad();
        glanceShowSymbols();
        glanceArmIdle();
        if (!ok) return;
        closeKeypad();
        openWallService();
      }
      const pad = document.getElementById("wall-keypad");
      const padGrid = document.getElementById("wall-keypad-grid");
      const padForm = document.getElementById("wall-keypad-form");
      const padClear = document.getElementById("wall-keypad-clear");
      const padBack = document.getElementById("wall-keypad-back");
      const padNext = document.getElementById("wall-keypad-next");
      const padSymbols = document.getElementById("wall-keypad-symbols-back");
      const padClose = document.getElementById("wall-keypad-close");
      if (padGrid) padGrid.addEventListener("click", function (ev) {
        const btn = ev.target && ev.target.closest ? ev.target.closest("[data-key]") : null;
        if (!btn) return;
        const n = parseInt(btn.getAttribute("data-key") || "", 10);
        if (!Number.isFinite(n) || n < 0 || n > 99) return;
        if (_padTaps.length >= 16) return;
        _padTaps.push(n);
        glancePaintPad();
        glanceArmIdle();
      });
      if (padClear) padClear.addEventListener("click", function () {
        glanceClearPad();
        glanceArmIdle();
      });
      if (padBack) padBack.addEventListener("click", function () {
        _padTaps.pop();
        glancePaintPad();
        glanceArmIdle();
      });
      const padWord = document.getElementById("wall-keypad-word");
      if (padWord) padWord.addEventListener("input", function () { glanceArmIdle(60000); });
      if (padNext) padNext.addEventListener("click", function () {
        if (!_padTaps.length) return;
        glanceShowWord();
      });
      if (padSymbols) padSymbols.addEventListener("click", function () {
        glanceShowSymbols();
        glanceArmIdle(8000);
      });
      if (padClose) padClose.addEventListener("click", closeKeypad);
      if (padForm) padForm.addEventListener("submit", glanceSubmitPad);
      document.addEventListener("keydown", function (ev) {
        if (pad && !pad.hidden && ev.key === "Escape") { closeKeypad(); return; }
        const box = document.getElementById("wall-service");
        if (box && !box.hidden && ev.key === "Escape") closeWallService();
      });
      const mark = document.querySelector("header h1");
      if (mark) {
        let n = 0;
        let last = 0;
        mark.addEventListener("click", function () {
          if (pad && !pad.hidden) return;
          const svc = document.getElementById("wall-service");
          if (svc && !svc.hidden) return;
          const now = Date.now();
          if (now - last > 1000) n = 0;
          last = now;
          n += 1;
          if (n < 5) return;
          n = 0;
          openKeypad();
        });
      }
    })();
    const showDeadEl = document.getElementById("show-dead");
    if (showDeadEl) showDeadEl.addEventListener("change", ev => {
      showDead = ev.target.checked;
      if (window._floor) agents(window._floor);
    });
    document.getElementById("show-reads").addEventListener("change", ev => {
      showReads = ev.target.checked;
      if (window._floor) wire(window._floor);
    });
    document.getElementById("wire-details").addEventListener("change", ev => {
      wireDetails = ev.target.checked;
      if (window._floor) wire(window._floor);
    });
    (function paintWireProto() {
      const box = document.getElementById("wire-proto");
      if (!box) return;
      box.innerHTML = WIRE_PROTO.map(([id, label]) =>
        `<button type="button" data-proto="${id}" class="${wireProto===id?"on":""}">${label}</button>`
      ).join("");
      box.addEventListener("click", ev => {
        const btn = ev.target.closest("[data-proto]");
        if (!btn) return;
        wireProto = btn.dataset.proto || "";
        box.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === btn));
        if (window._floor) wire(window._floor);
      });
    })();
    let apiOk = true;
    let packVer = "";
    function wallClockNow() {
      try {
        return new Intl.DateTimeFormat(undefined, {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZoneName: "short"
        }).format(new Date());
      } catch (err) {
        return "";
      }
    }
    function wallClockLine(d) {
      d = d || {};
      return [d.version || packVer, d.node || "", wallClockNow()].filter(Boolean).join("  ");
    }
    function paintWallClock() {
      const clock = document.getElementById("clock");
      if (clock && apiOk) clock.textContent = wallClockLine(window._floor || {});
    }
    fetch("/version.json", { cache: "no-store" }).then(function (r) {
      return r.ok ? r.json() : {};
    }).then(function (j) {
      packVer = (j && j.version) ? String(j.version) : "";
      paintWallClock();
    }).catch(function () {});
    const _stripLast = { hereN: null, openN: null, scoreOff: null, mailUnreadN: null, waitingN: null, claimedN: null, sharedN: null };
    let _stripFillKey = "";
    let _stripFillTries = 0;
    let _stripSharedKey = "";
    function wallResetStripReady() {
      _stripReady.session = false;
      _stripReady.floor = false;
      _stripReady.todo = false;
      _stripReady.score = false;
      _stripReady.mail = false;
      _stripFillKey = "";
      _stripFillTries = 0;
      _stripLast.hereN = null;
      _stripLast.openN = null;
      _stripLast.scoreOff = null;
      _stripLast.mailUnreadN = null;
      _stripLast.waitingN = null;
      _stripLast.claimedN = null;
      _stripLast.sharedN = null;
      _stripSharedKey = "";
    }
    function wallStripFillScope() {
      /* A station scope asks the lan procedure for todos, and that call 500s.
         The todo, score, and mail tabs already use the project book. */
      try {
        const project = floorProjectQuery();
        if (project) return { key: "project:" + project, query: project };
      } catch (eProj) {}
      return floorScope();
    }
    function wallFillStripShared() {
      /* COLLAB counts Between rows (/api/activity window=between), the same read as
         its pane. Other tabs never carry them, so read them once per scope. */
      let between;
      try { between = activityBetweenQuery(); } catch (eQ) { return; }
      if (!between || _stripSharedKey === between.key) return;
      _stripSharedKey = between.key;
      wallFetchFloorV1({ key: between.key, query: "" }, [{ path: between.url, kind: "between", absolute: true }]).then(function (res) {
        const rows = res && !res.down && res.raw && res.raw.between;
        if (!Array.isArray(rows)) { _stripSharedKey = ""; return; }
        if (activityBetweenQuery().key !== between.key) return;
        _stripLast.sharedN = (floorShared({ between: rows }) || {}).rows || 0;
        _stripReady.floor = true;
        strip(window._floor || {});
      }).catch(function () { _stripSharedKey = ""; });
    }
    function wallFillStripCounts() {
      /* Chips stay on the spinner until their part has been fetched. The open tab's
         poll stays narrow. One pass fills TODO and MAIL. SCORE is the Office book. */
      const need = [];
      if (!_stripReady.session) need.push("agents");
      if (!_stripReady.todo) need.push("todos");
      if (!_stripReady.mail) need.push("mail");
      if (!_stripReady.floor) wallFillStripShared();
      if (!need.length || _stripFillTries >= 2) return;
      let scope;
      try { scope = wallStripFillScope(); } catch (eScope) { return; }
      const key = String(scope.key || "");
      if (_stripFillKey === key) return;
      _stripFillKey = key;
      _stripFillTries += 1;
      const partsStr = need.join(",");
      wallFetchFloorParts(scope, partsStr, function (slice) {
        try {
          if (wallStripFillScope().key !== scope.key) return;
          wallPaintFloorPartEarly(slice);
          strip(window._floor || {});
        } catch (eFill) {}
      }).then(function (res) {
        if (!res || res.down) _stripFillKey = "";
        else if (!_stripReady.session || !_stripReady.todo || !_stripReady.mail) _stripFillKey = "";
      }).catch(function () { _stripFillKey = ""; });
    }
    function strip(d) {
      d = d || window._floor || {};
      const clock = document.getElementById("clock");
      if (clock && apiOk) {
        clock.textContent = wallClockLine(d);
      }
      const parts = Array.isArray(d.parts) ? d.parts : [];
      const hasAgents = parts.indexOf("agents") >= 0 || (Array.isArray(d.agents) && d.agents.length > 0);
      const hasTodos = parts.indexOf("todos") >= 0 || (Array.isArray(d.needs) && d.needs.length > 0) || (Array.isArray(d.issues) && d.issues.length > 0);
      const hasScores = parts.indexOf("scores") >= 0 || (Array.isArray(d.kpis) && d.kpis.length > 0);
      const hasMail = parts.indexOf("mail") >= 0 || (Array.isArray(d.mailbox) && d.mailbox.length > 0);
      /* #715: a chip is known only once this scope's payload carried its part
         (resetFloorBook clears all of it on a rail switch). Until then it shows
         the loading mark, never a 0 counted from rows that were not read. */
      if (hasAgents) _stripReady.session = true;
      if (hasTodos) _stripReady.todo = true;
      if (hasScores) _stripReady.score = true;
      if (hasMail) _stripReady.mail = true;
      const hasShared = Array.isArray(d.between);
      if (hasShared) _stripReady.floor = true;
      const live = uniqueDesksByOwner((d.agents || []).filter(a => a.alive));
      let hereN = live.length;
      if (!hasAgents && _stripLast.hereN != null) hereN = _stripLast.hereN;
      else _stripLast.hereN = hereN;
      const todoNow = millTodoCards(d).filter(n => {
        const st = n.status || "";
        return st === "open" || st === "claimed" || st === "shipped";
      });
      let claimedN = todoNow.filter(n => n.status === "claimed" || n.status === "shipped").length;
      const openTotal = todoNow.length;
      if (!hasTodos && _stripLast.claimedN != null) claimedN = _stripLast.claimedN;
      else _stripLast.claimedN = claimedN;
      const leftBadge = "";
      let mailUnreadN = null;
      if (hasMail && Array.isArray(d.mailbox)) {
        /* mailIsFloor lives in the mail tab script. Counting must not throw before that loads. */
        if (typeof mailWallUnread === "function") {
          mailUnreadN = d.mailbox.filter(mailWallUnread).length;
        } else if (typeof mailIsFloor === "function" && typeof mailDstRead === "function") {
          mailUnreadN = d.mailbox.filter(m => !mailIsFloor(m) && !mailDstRead(m)).length;
        } else if (d.desk_unread && typeof d.desk_unread === "object") {
          mailUnreadN = Object.keys(d.desk_unread).reduce(function (sum, key) {
            return sum + (Number(d.desk_unread[key]) || 0);
          }, 0);
        } else {
          mailUnreadN = d.mailbox.length;
        }
        _stripLast.mailUnreadN = mailUnreadN;
      } else if (_stripLast.mailUnreadN != null) {
        mailUnreadN = _stripLast.mailUnreadN;
      }
      const mailOverflow = mailUnreadN != null && mailUnreadN >= 20;
      const mailVal = mailUnreadN == null ? "\u2014" : String(mailUnreadN);
      const mailCls = mailOverflow ? " warn mail-unread" : (mailUnreadN ? " mail-unread" : " mail-unread quiet");
      const mailCue = mailOverflow
        ? `<span class="kpi-cue">overflow</span>`
        : (mailUnreadN ? `<span class="kpi-cue">unread</span>` : `<span class="kpi-cue">caught up</span>`);
      const mailTitle = mailOverflow
        ? (mailUnreadN + " unread MAIL - overflow, desks are not consuming letters")
        : (mailUnreadN ? (mailUnreadN + " unread MAIL") : "No unread MAIL");
      /* SESSION_GLANCE honesty: Waiting = desks with non-empty waiting_on */
      let waitingN = live.filter(a => String(a.waiting_on || "").trim()).length;
      if (!hasAgents && _stripLast.waitingN != null) waitingN = _stripLast.waitingN;
      else _stripLast.waitingN = waitingN;
      const maint = d.maintenance && d.maintenance.eta_at ? d.maintenance : null;
      let maintPhase = maint ? String(maint.phase || "") : "";
      if (maint && !maintPhase) {
        const t = Date.parse(String(maint.eta_at));
        maintPhase = (Number.isFinite(t) && Date.now() >= t) ? "overdue" : "draining";
      }
      const apiHealth = document.getElementById("api-health");
      if (apiHealth) {
        const apiVal = maint ? ("maint " + maintPhase) : (apiOk ? "ok" : "down");
        apiHealth.textContent = "API | " + apiVal;
        apiHealth.classList.toggle("warn", !apiOk || !!maint);
        apiHealth.title = maint ? ("maintenance " + maintPhase) : (apiOk ? "Mill API ok" : "Mill API down");
      }
      const el = document.getElementById("strip");
      if (!el) return;
      let openN = millTodoCards(d).filter(n => n.status === "open").length;
      if (!hasTodos && _stripLast.openN != null) openN = _stripLast.openN;
      else _stripLast.openN = openN;
      /* SCORE chip counts Office misses, the same rows as the header. */
      const scoreRows = (typeof hereScoreRows === "function") ? hereScoreRows() : [];
      let scoreOff = scoreRows.length;
      if (_officeScoreSeen) _stripLast.scoreOff = scoreOff;
      else if (_stripLast.scoreOff != null) scoreOff = _stripLast.scoreOff;
      const sessCue = waitingN ? (waitingN + " waiting") : "all working";
      let sharedN = 0;
      if (hasShared) {
        try { sharedN = (floorShared(d) || {}).rows || 0; } catch (eSharedN) {}
        _stripLast.sharedN = sharedN;
      } else if (_stripLast.sharedN != null) {
        sharedN = _stripLast.sharedN;
      }
      const floorCue = "shared";
      const todoCue = claimedN ? (claimedN + " moving") : "none moving";
      const scoreCue = scoreOff ? "off target" : "on target";
      const scoreCls = scoreOff ? " warn" : "";
      const loadSpin = wallStripLoadHtml();
      const sessLoad = !_stripReady.session;
      const floorLoad = !_stripReady.floor;
      const todoLoad = !_stripReady.todo;
      const scoreLoad = !_officeScoreSeen;
      const mailLoad = !_stripReady.mail;
      const sessB = sessLoad ? "..." : esc(String(hereN));
      const floorB = floorLoad ? "..." : esc(String(sharedN));
      const todoB = todoLoad ? "..." : esc(String(openN));
      const scoreB = scoreLoad ? "..." : esc(scoreOff ? String(scoreOff) : "ok");
      const mailB = mailLoad ? "\u2014" : esc(mailVal);
      el.innerHTML =
        `<span class="kpi strip-nav${sessLoad ? " kpi-loading" : ""}" id="strip-here" title="Desks connected now" role="link" tabindex="0" data-wall-strip-loading="${sessLoad ? "1" : "0"}">CONNECTED${sessLoad ? loadSpin : ""}<b>${sessB}</b>${sessLoad ? "" : `<span class="kpi-cue">${esc(sessCue)}</span>`}</span>` +
        `<span class="kpi strip-nav${todoLoad ? " kpi-loading" : ""}" id="strip-todo" title="Open cards" role="link" tabindex="0" data-wall-strip-loading="${todoLoad ? "1" : "0"}">TODO${todoLoad ? loadSpin : ""}<b>${todoB}</b>${todoLoad ? "" : `<span class="kpi-cue">${esc(todoCue)}</span>`}</span>` +
        `<span class="kpi strip-nav${mailCls}${mailLoad ? " kpi-loading" : ""}" id="strip-mail" title="${esc(mailTitle)}" role="link" tabindex="0" data-wall-strip-loading="${mailLoad ? "1" : "0"}">MAIL${mailLoad ? loadSpin : ""}<b>${mailB}</b>${mailLoad ? "" : mailCue}</span>` +
        `<span class="kpi strip-nav${scoreCls}${scoreLoad ? " kpi-loading" : ""}" id="strip-score" title="Last against target" role="link" tabindex="0" data-wall-strip-loading="${scoreLoad ? "1" : "0"}">SCORE${scoreLoad ? loadSpin : ""}<b>${scoreB}</b>${scoreLoad ? "" : `<span class="kpi-cue">${esc(scoreCue)}</span>`}</span>` +
        `<span class="kpi strip-nav strip-later${floorLoad ? " kpi-loading" : ""}" id="strip-floor" title="Shared letters, cards, and promises" role="link" tabindex="0" data-wall-strip-loading="${floorLoad ? "1" : "0"}">COLLAB${floorLoad ? loadSpin : ""}<b>${floorB}</b>${floorLoad ? "" : `<span class="kpi-cue">${esc(floorCue)}</span>`}</span>`;
      /* strip() innerHTML destroys per-chip listeners. One-time document
       * delegation survives rebuilds. */
      if (!document._wallStripNavDelegated) {
        document._wallStripNavDelegated = true;
        const wallStripNavActivate = function (chip) {
          if (!chip || !chip.id) return;
          const id = chip.id;
          if (id === "strip-here") {
            showTab("session");
            if (window.setSessionMode) window.setSessionMode("now");
          } else if (id === "strip-floor") showTab("floor");
          else if (id === "strip-todo") showTab("jobs");
          else if (id === "strip-score") showTab("score");
          else if (id === "strip-mail") showTab("mail");
        };
        document.addEventListener("click", function (ev) {
          const t = ev.target;
          if (!t || !t.closest) return;
          const chip = t.closest("#strip > .kpi.strip-nav");
          if (!chip) return;
          wallStripNavActivate(chip);
        });
        document.addEventListener("keydown", function (ev) {
          if (ev.key !== "Enter" && ev.key !== " ") return;
          const t = ev.target;
          if (!t || !t.closest) return;
          const chip = t.closest("#strip > .kpi.strip-nav");
          if (!chip || chip !== t) return;
          ev.preventDefault();
          wallStripNavActivate(chip);
        });
      }
      const onTab = document.querySelector("nav.tabs button.on");
      paintStripTab((onTab && onTab.dataset.tab) || "session");
      /* Keep the welcome seat form behind the redesign gate. */
      try { wallApplyInviteGate(); } catch (eInvStrip) {}
      try { paintHereScores(d); } catch (eScores) {}
      try { if (_hereOwner) paintHereDesk(d, _hereOwner); } catch (eDesk) {}
      try { wireHereFront(); } catch (eHereWire) {}
    }
    function isMillNeedId(nid) {
      nid = String(nid || "");
      return !!(nid && nid !== "leftover" && nid.indexOf("idle-") !== 0);
    }
    function uniqueDesksByOwner(agents) {
      const by = {};
      (agents || []).forEach(a => {
        const o = String(a.owner || "").trim();
        if (!o) return;
        const t = Date.parse(a.heartbeat || a.updated || a.lastUpdate || "") || 0;
        const prev = by[o];
        const pt = prev ? (Date.parse(prev.heartbeat || prev.updated || "") || 0) : -1;
        if (!prev || t >= pt) by[o] = a;
      });
      return Object.keys(by).sort().map(k => by[k]);
    }

    /* Nest glance: floor.trees -> parent/depth for List+Board spine (no indent). */
    function millNestTitleBook(d) {
      const titles = Object.create(null);
      const push = (arr) => {
        if (!Array.isArray(arr)) return;
        arr.forEach(r => {
          if (!r || typeof r !== 'object') return;
          const id = String(r.id || '');
          if (!id || titles[id]) return;
          const t = String(r.detail || r.title || r.need_id || '').trim();
          if (t) titles[id] = t;
        });
      };
      /* claimed_needs/open_needs are counts on floor, not row lists - never foreach them. */
      try { push(typeof millTodoCards === 'function' ? millTodoCards(d || {}) : []); } catch (e) {}
      push(d && d.needs);
      push(d && d.issues);
      return titles;
    }
    function millNestIndex(d) {
      const byId = Object.create(null);
      const trees = d && Array.isArray(d.trees) ? d.trees : null;
      if (!trees) return byId;
      const titles = millNestTitleBook(d);
      trees.forEach((t, ti) => {
        const plan = String((t && (t.name || t.id)) || ('t' + ti));
        const nodes = (t && Array.isArray(t.nodes) ? t.nodes.slice() : []).filter(n =>
          n && String(n.type || '').toLowerCase() === 'todo');
        nodes.sort((a, b) => (Number(a && a.lft) || 0) - (Number(b && b.lft) || 0));
        const stack = [];
        nodes.forEach(n => {
          const id = String(n.id || '');
          if (!id) return;
          const lft = Number(n.lft) || 0;
          const rgt = Number(n.rgt) || 0;
          while (stack.length && Number(stack[stack.length - 1].rgt) < lft) stack.pop();
          /* Depth is how many todo cards contain this card. A non-card above lft 1 does not count. */
          const depth = stack.length;
          const parent = stack.length ? stack[stack.length - 1] : null;
          const parentId = parent ? String(parent.id || '') : '';
          let parentLabel = '';
          if (parentId) {
            parentLabel = String(
              titles[parentId] ||
              parent.title || parent.detail ||
              ('#' + parentId)
            ).trim();
            if (parentLabel.length > 42) parentLabel = parentLabel.slice(0, 40) + '\u2026';
          }
          const cur = byId[id];
          const row = {
            tree: plan,
            lft: lft,
            rgt: rgt,
            depth: Number.isFinite(depth) && depth >= 0 ? depth : 0,
            parentId: parentId,
            parentLabel: parentLabel,
            hidden: !!(t && t.hidden)
          };
          /* Prefer named (non-hidden) plan when a card sits on two. */
          if (!cur || (cur.hidden && !row.hidden) || (!cur.hidden && !row.hidden && row.lft < cur.lft)) {
            byId[id] = row;
          }
          stack.push({ id: id, rgt: rgt, title: titles[id] || n.title || '' });
        });
      });
      return byId;
    }
    function millNestMeta(index, r) {
      if (!index || !r) return null;
      const a = index[String(r.id || '')];
      if (a) return a;
      const nid = String(r.need_id || '');
      if (nid && index[nid]) return index[nid];
      return null;
    }
    function millNestSpineHtml(nest, showParentChip) {
      const depth = Math.max(0, Number(nest && nest.depth) || 0);
      if (depth <= 0) return '';
      const label = String((nest && nest.parentLabel) || '').trim();
      const pid = String((nest && nest.parentId) || '').trim();
      const chip = (showParentChip && label)
        ? `<span class="nest-parent" title="${esc(label)}${pid ? ' (#' + esc(pid) + ')' : ''}">\u21b3 ${esc(label)}</span>`
        : '';
      return `<div class="nest-spine" aria-hidden="true"></div>${chip}`;
    }
    function millNestSortRows(rows, index) {
      return (rows || []).slice().sort((a, b) => {
        const na = millNestMeta(index, a);
        const nb = millNestMeta(index, b);
        const ia = na ? 0 : 1;
        const ib = nb ? 0 : 1;
        if (ia !== ib) return ia - ib;
        if (na && nb) {
          if (na.tree !== nb.tree) return String(na.tree).localeCompare(String(nb.tree));
          if (na.lft !== nb.lft) return na.lft - nb.lft;
        }
        return String(a.id || a.need_id || '').localeCompare(String(b.id || b.need_id || ''));
      });
    }

    /* WALL_UI_DEFAULT_TODO: millTodoCards from domain module when lazy-loaded */
    function millTodoCards(d) {
      if (typeof WallTodo !== "undefined" && WallTodo && typeof WallTodo.millTodoCards === "function") {
        return WallTodo.millTodoCards(d);
      }
      /* cold boot / SESSION strip fallback before TODO tab loads domain */
      const STAT = { parked: 1, open: 1, claimed: 1, shipped: 1, done: 1 };
      const rows = [].concat(
        ((d && d.needs) || []).filter(r => String(r.status || "").toLowerCase() !== "parked"),
        ((d && d.issues) || []).filter(r => String(r.status || "").toLowerCase() === "parked")
      );
      const seen = {};
      const out = [];
      rows.forEach(r => {
        const st = String(r.status || "").toLowerCase();
        if (!STAT[st] || !isMillNeedId(r.need_id)) return;
        const key = String(r.need_id || r.id || "");
        if (!key || seen[key]) return;
        seen[key] = true;
        out.push(r);
      });
      return out;
    }
    function millJobsForOwner(d, owner, projectId) {
      const want = String(owner || "").trim();
      const name = x => String(x || "").trim() === want;
      const pool = [].concat(d.on_it || [], d.needs || []);
      return pool.filter(r => {
        if (!isMillNeedId(r.need_id)) return false;
        if (r.holder_dead) return false;
        const st = r.status || "";
        if (st !== "claimed" && st !== "shipped") return false;
        if (!name(r.volunteer) && !name(r.owner)) return false;
        if (projectId && millGid(r) && String(millGid(r)) !== String(projectId)) return false;
        return true;
      });
    }
    /* #818 PR C: what a desk is doing is the server's view (GET /api/v1/doing, the same
     * payload as `mill connected`). doing/doing-paint.js reads it into WALL_DOING; the Wall
     * never recomputes it and never guesses a state from the text. Until the view is read,
     * or when the route is not there, a desk shows its seat's doing text as is. */
    function wallDoingView(owner) {
      const v = window.WALL_DOING;
      if (!v || v.state !== "ok" || !v.byOwner) return null;
      return v.byOwner[String(owner || "").trim()] || null;
    }
    function wallDoingText(owner, seatText) {
      const v = wallDoingView(owner);
      if (v) return String(v.doing || "").trim();
      return String(seatText || "").trim();
    }
    function wallDoingWaitN(view) {
      /* Letters and cards waiting on a desk: the server's counts (waiting_on_it), never ours. */
      const w = (view && view.waiting_on_it) || {};
      return (Number((w.letters || {}).n) || 0) + (Number((w.cards || {}).n) || 0);
    }
    function wallDoingBlock(owner, seatText) {
      if (window.WALL_UI_DEFAULT_DOING_PAINT && typeof wallDoingDeskHtml === "function") {
        const html = wallDoingDeskHtml(owner, seatText);
        if (html) return html;
      }
      return `<div class="here-doing"><div class="here-doing-now">${esc(wallDoingText(owner, seatText) || "-")}</div></div>`;
    }
    function wallDoingRow(owner, seatText) {
      if (window.WALL_UI_DEFAULT_DOING_PAINT && typeof wallDoingRowHtml === "function") {
        const html = wallDoingRowHtml(owner, seatText);
        if (html) return html;
      }
      return `<span class="here-doing">${esc(wallDoingText(owner, seatText))}</span>`;
    }
    function wallDoingMeta(owner) {
      if (window.WALL_UI_DEFAULT_DOING_PAINT && typeof wallDoingMetaHtml === "function") return wallDoingMetaHtml(owner) || "";
      return "";
    }
    /* Lazy entries (doing/doing-paint.js replaces these stubs; lib/lazy.js MODULES.doingPaint). */
    function wallDoingSync() { return wallLazyCall("doingPaint", "wallDoingSync", wallDoingSync, arguments); }
    function wallDoingTrail() { return wallLazyCall("doingPaint", "wallDoingTrail", wallDoingTrail, arguments); }
    function wallDoingTrailSlot(item) {
      /* A card's doing rows, in order, from GET /api/v1/doing/history?on=ITEM. Blank until read. */
      const key = String(item || "");
      let inner = "";
      if (window.WALL_UI_DEFAULT_DOING_PAINT && typeof wallDoingTrailHtml === "function") inner = wallDoingTrailHtml(key) || "";
      /* A span: the slot also sits inside the plan's card button (phrasing content only). */
      return `<span class="doing-trail" data-doing-trail="${esc(key)}">${inner}</span>`;
    }
    function wallClaimedSlot(r) {
      /* #818 slot: the card's claimed_at from the server. Blank when the card has none. */
      const at = String((r && r.claimed_at) || "").trim();
      return `<span class="card-claimed" data-slot="claimed_at">${at ? esc("claimed " + dt(at).slice(5, 16)) : ""}</span>`;
    }
    function leftoverRec(d, projectId) {
      /* 0.3 leftover is spend, not a JOB. Do not paint leftover mill work. */
      return null;
    }
    function hereGlance(d, agent) {
      /* SESSION_GLANCE SoR: docs/acceptance/ACCEPTANCE-SESSION-GLANCE.md
         #818: the state comes from the server's doing view when it is read (doing -> working,
         none -> idle). Without it: a claimed card, the seat's doing text, or recent activity
         -> working, else here. Never parsed out of the text. */
      const view = wallDoingView(agent.owner);
      const doing = wallDoingText(agent.owner, agent.doing);
      const jobs = millJobsForOwner(d, agent.owner, millGid(agent));
      const stale = !!(agent.stale || (agent.alive === false));
      const jobRec = jobs.length ? jobs[0] : null;
      const job = jobRec ? {
        need_id: jobRec.need_id || "",
        eta: jobRec.eta || "",
        progress: jobRec.progress || "",
        title: jobRec.detail || ""
      } : null;
      const pack = (state, note) => ({ state, waiting_on: "", note: note || "", doing, view, job, stale });
      if (view) {
        if (stale && !doing) return pack("gone", "gone");
        if (doing) return pack("working", doing);
        return pack("idle", view.idle ? ("idle " + view.idle) : "idle");
      }
      if (!jobs.length) {
        if (stale || agent.alive === false) return pack("gone", "gone");
        const owner = String(agent.owner || "");
        const mutate = { mail: 1, todo: 1, hold: 1, score: 1, attach: 1 };
        const now = Date.now();
        const hb = Date.parse(agent.heartbeat || agent.updated || "");
        const recentHb = Number.isFinite(hb) && (now - hb) < 120000;
        const recentAct = (d.events || []).some(e => {
          if (String(e.owner || "") !== owner) return false;
          if (!mutate[String(e.kind || e.type || "")]) return false;
          const ts = Date.parse(e.at || e.updated || "");
          return Number.isFinite(ts) && (now - ts) < 15 * 60 * 1000;
        });
        if (doing || recentAct || recentHb) return pack("working", doing || "activity");
        return pack("here", "here");
      }
      const jobNote = job && job.need_id ? ("JOB " + job.need_id) : "";
      return pack("working", jobNote || doing || "on a claimed card");
    }
    function sgChip(g) {
      const st = g.state || "idle";
      const staleBit = g.stale ? '<span class="sg-stale">stale</span>' : "";
      return `<span class="sg-chip ${esc(st)}${g.stale ? " stale" : ""}">${esc(st)}${staleBit}</span>`;
    }
    function sgWho(agent, unreadN) {
      const owner = String(agent.owner || "").trim();
      const role = String(agent.role || "").trim();
      const deskLabel = millName("desk", owner);
      const roleLabel = millName("role", role);
      const roleBit = roleLabel
        ? ` <span class="sg-role">| ${esc(roleLabel)}</span>` : "";
      const host = String(agent.owner_host || agent.host || "").trim();
      const pid = agent.pid != null && agent.pid !== "" ? String(agent.pid) : "";
      const nodeLabel = (host || pid) ? (host + ":" + pid) : "";
      const rootTip = String(agent.session_root || agent.root || "").trim();
      const tip = rootTip ? ` title="${esc(rootTip)}"` : "";
      /* OFFICE_GLANCE P0: mill desk_unread badge; hide/mute zero */
      /* SESSION_COL_ORDER: under desk = node:pid ONLY (no project id). session_root tooltip OK. */
      return `<div class="sg-who-stack"${tip}><div class="sg-who-line"><span class="sg-who">${esc(deskLabel)}</span>${roleBit}</div>` +
        (nodeLabel ? `<div class="sg-node" data-sg-node="1">${esc(nodeLabel)}</div>` : "") + `</div>`;
    }
    function sgJobLine(g) {
      if (!g.job || !g.job.need_id) return "";
      const bits = [g.job.need_id];
      if (g.job.eta) bits.push("ETA " + t(g.job.eta));
      if (g.job.progress) bits.push(g.job.progress);
      return `<div class="sg-job">${esc(bits[0])}` +
        (bits.length > 1 ? ` <span class="sg-meta">| ${esc(bits.slice(1).join(" | "))}</span>` : "") +
        `</div>`;
    }
    const TODO_STATUSES = ["parked", "open", "claimed", "shipped", "done"];
    const TODO_STATUS_KEY = "factory-todo-status-collapse";
    let _todoStatusCollapsed = {};
    function loadTodoStatusCollapsed() {
      try {
        const raw = JSON.parse(localStorage.getItem(TODO_STATUS_KEY) || "[]");
        const set = {};
        if (Array.isArray(raw)) {
          raw.forEach(function (s) {
            const k = String(s || "").toLowerCase();
            if (TODO_STATUSES.indexOf(k) >= 0) set[k] = 1;
          });
        }
        return set;
      } catch (e) { return {}; }
    }
    function todoStatusCollapsed(st) {
      return !!_todoStatusCollapsed[String(st || "").toLowerCase()];
    }
    function paintTodoStatusChips() {
      const root = document.getElementById("todo-status-filter");
      if (!root) return;
      root.querySelectorAll("button[data-todo-status]").forEach(function (b) {
        const k = b.getAttribute("data-todo-status") || "";
        const open = !todoStatusCollapsed(k);
        b.classList.toggle("on", open);
        b.setAttribute("aria-pressed", open ? "true" : "false");
        b.title = open
          ? ("Shrink " + k + " cards to the status. The connection stays.")
          : ("Show " + k + " card details.");
      });
    }
    function toggleTodoStatus(st) {
      const k = String(st || "").toLowerCase();
      if (TODO_STATUSES.indexOf(k) < 0) return;
      if (_todoStatusCollapsed[k]) delete _todoStatusCollapsed[k];
      else _todoStatusCollapsed[k] = 1;
      try { localStorage.setItem(TODO_STATUS_KEY, JSON.stringify(Object.keys(_todoStatusCollapsed))); } catch (e) {}
      paintTodoStatusChips();
      if (window._floor) {
        try { board(window._floor); } catch (eB) {}
        try { paintPlan(window._floor); } catch (eP) {}
      }
    }
    try { _todoStatusCollapsed = loadTodoStatusCollapsed(); } catch (eStat) { _todoStatusCollapsed = {}; }
    function needCard(r, nestOrDepth, showParentChip) {
      const nest = (nestOrDepth && typeof nestOrDepth === "object")
        ? nestOrDepth
        : { depth: nestOrDepth };
      const st = String((r && r.status) || "").toLowerCase();
      const detailOpen = String(r && r.id || "") === String(_todoDetailId);
      if (todoStatusCollapsed(st) && !detailOpen) {
        const d0 = Math.max(0, Number(nest.depth) || 0);
        const nestCls0 = d0 > 0 ? " nest-child" : (nest.tree ? " nest-root" : "");
        const pid0 = String(nest.parentId || "");
        const spine0 = millNestSpineHtml(nest, !!showParentChip);
        const todoId0 = String(r.id || "");
        return `<div class="card is-collapsed st-${esc(st)}${nestCls0}" data-todo-id="${esc(todoId0)}" data-depth="${d0}"${pid0 ? ` data-parent="${esc(pid0)}"` : ""}>` +
          spine0 +
          `<div class="st">${esc(st)}</div>` +
          `</div>`;
      }
      const done = r.status === "done";
      const owned = r.status === "claimed";
      const nid = String(r.need_id || "").trim() || "(no id)";
      const asker = String(r.creator || r.asker || "").trim();
      const volunteer = String(r.assigned || r.volunteer || r.owner || "").trim();
      const human = /^\s*HUMAN\b/i.test(String(r.detail || ""));
      const meta = [];
      if (asker) meta.push("asker " + asker);
      if (volunteer && owned) meta.push("claimed by " + volunteer);
      if (r.progress) meta.push(String(r.progress));
      if (r.eta) meta.push("ETA " + t(r.eta));
      const claimedSlot = wallClaimedSlot(r);
      const metaLine = meta.length ? `<div class="meta">${esc(meta.join(" | "))} ${claimedSlot}</div>` : claimedSlot;
      const cues = [];
      if (r.stale) cues.push("stale");
      if (r.holder_dead) cues.push("holder_dead");
      const cueLine = cues.length ? `<div class="cue">${esc(cues.join(" | "))}</div>` : "";
      const cls = done ? "done" : (owned ? "claimed" : "open");
      const d = Math.max(0, Number(nest.depth) || 0);
      const nestCls = d > 0 ? " nest-child" : (nest.tree ? " nest-root" : "");
      const pid = String(nest.parentId || "");
      const spine = millNestSpineHtml(nest, !!showParentChip);
      const todoId = String(r.id || "");
      const todoTrunc = r.detail_trunc === true ? "1" : "0";
      /* #818: cards have no title; the card line is its detail. */
      const detailLine = String(r.detail || "").trim();
      const cardLine = detailLine || "(no instructions)";
      const cardNote = detailOpen && detailLine && detailLine !== cardLine
        ? `<div class="todo-card-note">${esc(detailLine)}</div>` : "";
      return `<div class="card ${cls}${human ? " human-card" : ""}${r.fading ? " fading" : ""}${nestCls}${detailOpen ? " is-open" : ""}" data-todo-id="${esc(todoId)}" data-todo-trunc="${todoTrunc}" data-depth="${d}"${pid ? ` data-parent="${esc(pid)}"` : ""}>` +
        spine +
        `<div class="who">${esc(nid)}${millWatchBadge("todo", r.id)}</div>` +
        `<div>${esc(cardLine)}</div>` +
        cardNote +
        metaLine + cueLine +
        (detailOpen && todoId ? wallDoingTrailSlot("todo-" + todoId) : "") +
        `</div>`;
    }

    /* nest time window for tree-mail / tree-todo (All | 1d | 1w | 30d).
     * Persist like floor-span / todo-done-span. All = omit window=.
     * Sticky: when v1 down, floor parts=trees does not take window -> All-only. */
    const TREES_WINDOW_KEY = "factory-trees-window";
    const TREES_WINDOW_OK = { "1d": 1, "1w": 1, "30d": 1, all: 1 };
    function loadTreesWindow() {
      try {
        const v = localStorage.getItem(TREES_WINDOW_KEY);
        if (v && Object.prototype.hasOwnProperty.call(TREES_WINDOW_OK, v)) return v;
      } catch (e) {}
      return "all";
    }
    function saveTreesWindow(v) {
      const w = (v && TREES_WINDOW_OK[v]) ? v : "all";
      try { localStorage.setItem(TREES_WINDOW_KEY, w); } catch (e) {}
      return w;
    }
    function wallTreesWindowEffective() {
      return loadTreesWindow();
    }
    function wallTreesWindowQuery() {
      /* Returns "&window=1d" etc, or "" for All / sticky. */
      const w = wallTreesWindowEffective();
      if (!w || w === "all") return "";
      return "&window=" + encodeURIComponent(w);
    }
    function paintTreesWindowChips() {
      const eff = wallTreesWindowEffective();
      ["todo-trees-window", "mail-trees-window"].forEach(function (id) {
        const root = document.getElementById(id);
        if (!root) return;
        root.querySelectorAll("button[data-trees-window]").forEach(function (b) {
          const val = b.getAttribute("data-trees-window") || "all";
          b.classList.toggle("on", val === eff);
          b.disabled = false;
          if (val === "1d") b.title = "Forests with TREE activity in the last day";
          else if (val === "1w") b.title = "Forests with TREE activity in the last week";
          else if (val === "30d") b.title = "Forests with TREE activity in the last 30 days";
          else b.title = "All forests (omit window)";
        });
      });
    }
    function wallResetTreesCursors() {
      try {
        _wallListNext["tree-mail"] = null;
        _wallListNext["tree-todo"] = null;
        _wallListNext["trees"] = null;
      } catch (eN) {}
      try {
        Object.keys(_wallTreeExpandNext || {}).forEach(function (k) {
          _wallTreeExpandNext[k] = null;
        });
      } catch (eE) {}
    }
    function setTreesWindow(which) {
      saveTreesWindow(which);
      paintTreesWindowChips();
      wallResetTreesCursors();
      /* Refetch active nest stream with new window (or omit for All). */
      try {
        if (typeof tick === "function") tick(true);
      } catch (eTick) {}
    }
    function syncMailRoomsFiltersVisible() {
      const box = document.getElementById("mail-rooms-filters");
      if (!box) return;
      const rooms = (typeof mailView !== "undefined" && mailView === "rooms");
      box.hidden = !rooms;
      if (rooms) paintTreesWindowChips();
    }

    const DONE_SPAN_KEY = "factory-jobs-done-span";
    const DONE_SOFT_CAP = 100;
    const DONE_SPAN_MS = { "1h": 3600e3, "24h": 86400e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3, all: null };
    function loadDoneSpan() {
      try {
        const v = localStorage.getItem(DONE_SPAN_KEY);
        if (v && Object.prototype.hasOwnProperty.call(DONE_SPAN_MS, v)) return v;
      } catch (e) {}
      return "24h";
    }
    function saveDoneSpan(v) {
      try { localStorage.setItem(DONE_SPAN_KEY, v); } catch (e) {}
    }
    function parseNeedTs(v) {
      if (v == null || v === "") return null;
      if (v instanceof Date) return v.getTime();
      if (typeof v === "number" && Number.isFinite(v)) return v;
      const s = String(v).trim();
      // MySQL DATETIME(3) naive local: "2026-09-10 15:21:02.227"
      const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
      if (m) {
        const ms = m[7] ? Number((m[7] + "000").slice(0, 3)) : 0;
        return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], ms).getTime();
      }
      const t = Date.parse(s);
      return Number.isFinite(t) ? t : null;
    }
    function doneSpanLabel(span) {
      return span === "all" ? "all" : span;
    }
    function paintDoneLabel(span) {
      const lab = document.getElementById("jobs-done-label");
      if (lab) lab.textContent = "| " + doneSpanLabel(span);
      document.querySelectorAll("#todo-done-span button[data-done-span]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-done-span") === span);
      });
    }

    function millTreeHexName(raw) {
      const s = String(raw || "").trim();
      return /^[0-9a-f]{10}$/i.test(s);
    }
    /* Office plan nouns. A hidden plan is 10 hex and is not painted. */
    const MILL_PLAN_NOUN = {
      engineering: "release",
      eng: "release",
      qa: "pass",
      validation: "pass",
      ops: "uptime",
      sre: "uptime",
      support: "ticket",
      sales: "close-won",
      marketing: "launch",
      people: "hire",
      hr: "hire",
      legal: "clear",
      finance: "approved",
      research: "brief"
    };
    function millPlanNounFromToken(raw) {
      let s = String(raw || "").trim();
      if (!s) return "";
      s = millNameBare("name", s);
      const key = s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      if (!key) return "";
      if (MILL_PLAN_NOUN[key]) return MILL_PLAN_NOUN[key];
      const parts = key.split(/\s+/);
      for (let i = 0; i < parts.length; i++) {
        if (MILL_PLAN_NOUN[parts[i]]) return MILL_PLAN_NOUN[parts[i]];
      }
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (p.indexOf("engineer") === 0) return "release";
      }
      return "";
    }
    function millTreePlanLabel(t) {
      /* Office plan noun (engineering -> release). A 10-hex plan name is not painted. */
      if (!t) return "";
      const raw = String(t.name || "").trim();
      if (millTreeHexName(raw)) return "";
      if (!raw) return "";
      let n = millNameBare("name", raw);
      if (!n || /^[0-9a-f]{6,}$/i.test(n)) return "";
      if (t.hidden) {
        return millPlanNounFromToken(n) || "";
      }
      const noun = millPlanNounFromToken(n);
      if (noun) return noun;
      return n;
    }
    /* #717: a plan row's face. Most plans carry only a 10-hex name, so the head was
       "unnamed plan" on every row. With no plan name the root card's title is the head and
       the line under it says the root's status and who has it; a named plan keeps its name
       as the head and the root title as the line. */
    /* #33: one nested-set pass per nodes array. Parent map + depth memo (a parent's
       depth is set before its kids in lft order), O(n log n) once, O(1) per lookup.
       Overlap, ties, inverted rows, or a repeated row mark the index bad and callers
       fall back to the old scan, so output is the same on any input. The index lives for
       one synchronous pass (cleared on the next microtask), so a later refresh that edits
       rows in place is never read from a stale index. */
    let _millNestCache = null;
    let _millNestFlush = false;
    let _millPaintScope = null;
    function millNestBuild(list) {
      const at = new Map();
      const order = [];
      let bad = false;
      let explicit = false;
      for (let i = 0; i < list.length; i++) {
        const o = list[i];
        if (!o) continue;
        if (o.depth != null && o.depth !== "") explicit = true;
        const a = Number(o.lft);
        const b = Number(o.rgt);
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        if (at.has(o) || !(a < b)) { bad = true; continue; }
        at.set(o, { node: o, lft: a, rgt: b, parent: null, depth: 0, kids: null, kidsLft: null });
        order.push(o);
      }
      order.sort((x, y) => at.get(x).lft - at.get(y).lft);
      const stack = [];
      for (let i = 0; i < order.length && !bad; i++) {
        const e = at.get(order[i]);
        while (stack.length) {
          const top = stack[stack.length - 1];
          if (top.rgt < e.lft) { stack.pop(); continue; }
          if (!(top.lft < e.lft && top.rgt > e.rgt)) bad = true;
          break;
        }
        if (bad) break;
        const up = stack.length ? stack[stack.length - 1] : null;
        e.parent = up ? up.node : null;
        e.depth = up ? up.depth + 1 : 0;
        stack.push(e);
      }
      return { len: list.length, at: at, order: order, bad: bad, explicit: explicit, kidsBuilt: false, spine: null };
    }
    function millNestIndex(nodes, fresh) {
      const list = Array.isArray(nodes) ? nodes : [];
      if (!_millNestCache && typeof WeakMap === "function") _millNestCache = new WeakMap();
      let idx = (!fresh && _millNestCache) ? _millNestCache.get(list) : null;
      if (!idx || idx.len !== list.length) {
        idx = millNestBuild(list);
        if (_millNestCache) _millNestCache.set(list, idx);
        if (!_millNestFlush) {
          _millNestFlush = true;
          Promise.resolve().then(() => { _millNestCache = null; _millNestFlush = false; });
        }
      }
      return idx;
    }
    /* #710 TODO paint code lives in todo/todo-paint.js (lib/lazy.js MODULES.todoPaint); it loads with
     * the pane. Until then each entry below loads it and replays the call; the file's
     * function declarations replace these stubs as globals. */
    function issues() { return wallLazyCall("todoPaint", "issues", issues, arguments); }
    function paintPlan() { return wallLazyCall("todoPaint", "paintPlan", paintPlan, arguments); }
    function paintWatchers() { return wallLazyCall("todoPaint", "paintWatchers", paintWatchers, arguments); }
    function millTodoCardLookup(d, id) {
      /* First card whose id or need_id is id. One map per paintPlan; a plain find elsewhere. */
      const sid = String(id);
      const scope = _millPaintScope;
      if (scope && scope.d === d) {
        if (!scope.cards) {
          const rows = millTodoCards(d || {});
          const byId = new Map();
          const byNeed = new Map();
          rows.forEach((r, i) => {
            const a = String(r.id);
            const b = String(r.need_id);
            if (!byId.has(a)) byId.set(a, i);
            if (!byNeed.has(b)) byNeed.set(b, i);
          });
          scope.cards = { rows: rows, byId: byId, byNeed: byNeed };
        }
        const c = scope.cards;
        const i = c.byId.has(sid) ? c.byId.get(sid) : Infinity;
        const j = c.byNeed.has(sid) ? c.byNeed.get(sid) : Infinity;
        const k = Math.min(i, j);
        return k === Infinity ? undefined : c.rows[k];
      }
      return millTodoCards(d || {}).find(x => String(x.id) === sid || String(x.need_id) === sid);
    }
    function millTreePayload(d, node) {
      const type = String((node && node.type) || "").toLowerCase();
      const id = node && node.id;
      let title = String((node && (node.title || node.detail || node.subject || node.body)) || "").trim();
      let status = String((node && node.status) || "").toLowerCase();
      let who = String((node && (node.who || node.src || node.owner || node.volunteer || node.asker)) || "").trim();
      let unread = false;
      if (!title && type === "todo") {
        const r = millTodoCardLookup(d, id);
        if (r) {
          title = String(r.detail || r.title || r.need_id || "").trim();
          status = String(r.status || status).toLowerCase();
          who = String(r.volunteer || r.assigned || r.owner || r.asker || who).trim();
        }
      }
      if (type === "mail") {
        const m = (d && d.mailbox || []).find(x => String(x.id) === String(id));
        if (m) {
          if (!title) title = String(m.body || m.subject || m.detail || "").trim();
          who = String((typeof mailSenderDesk === "function" ? mailSenderDesk(m) : (m.src || "")) || who).trim();
          if (typeof mailWallUnread === "function") unread = !!mailWallUnread(m);
          else if (m.unread != null) unread = !!m.unread;
          if (!unread && typeof mailMsgHumanRequiredOpen === "function" && mailMsgHumanRequiredOpen(m)) unread = true;
        }
      }
      if (!title && (type === "name" || type === "doing")) {
        title = millNameBare(type, (node && (node.name || node.owner)) || "") || ("#" + String(id || ""));
      }
      if (!title) title = type ? (type + " #" + String(id || "")) : "(untitled)";
      if (millTreeHexName(title)) title = type ? type : "on the plan";
      return { type: type || "name", title, status, who, unread };
    }
    /* Reused from parked Plan nest (~/.mill/www): ancestor spine for search. */
    function millOutlineAncestors(nodes, node) {
      const lft = Number(node && node.lft);
      const rgt = Number(node && node.rgt);
      return (nodes || []).filter(o => o && o !== node && Number(o.lft) < lft && Number(o.rgt) > rgt)
        .sort((a, b) => Number(a.lft) - Number(b.lft));
    }
    const TREES_COLLAPSE_KEY = "factory-trees-collapse";
    const TREES_Q_KEY = "factory-trees-q";
    function millWatchCount(type, id) {
      const rows = (window._floor && window._floor.watchers) || [];
      for (let i = 0; i < rows.length; i++) {
        const w = rows[i];
        if (String(w.type) !== String(type) || String(w.id) !== String(id)) continue;
        return Array.isArray(w.desks) ? w.desks.length : 0;
      }
      return 0;
    }
    function millWatchBadge(type, id) {
      const n = millWatchCount(type, id);
      if (!n) return "";
      const word = n === 1 ? "watcher" : "watchers";
      return `<span class="watch-n" title="${n} ${word}">${n}</span>`;
    }
    let _todoTreePlan = "";
    let _todoTreeCard = "";
    let _todoDetailId = "";
    let _todoTreeChainOpen = true;
    let _todoChartPanning = false;
    let _todoChartPaintWait = false;
    const _todoTreeExpandTried = {};
    let _hereOwner = "";
    function hereKpiName(k) {
      return String((k && (k.kpi || k.name || k.id)) || "");
    }
    function hereScoreLabel(name) {
      return String(name || "score").replace(/^mill-wall\./, "").replace(/^mill-desk\./, "").replace(/[._]+/g, " ");
    }
    /* Office score rows. The left pane does not change this book. */
    let _officeScores = { kpis: [] };
    let _officeScoreMiss = false;
    let _officeScoreInflight = null;
    function hereScoreRows() {
      const kpis = (_officeScores && _officeScores.kpis) || [];
      const byName = {};
      kpis.forEach(function (k) {
        const name = hereKpiName(k);
        if (!name || name === "system" || !wallKpiMiss(k.value, k.target)) return;
        const prev = byName[name];
        if (!prev) { byName[name] = k; return; }
        if (String(k.owner || "") === "Admin" && String(prev.owner || "") !== "Admin") byName[name] = k;
      });
      const prefer = ["mill-wall.ticks", "mill-desk.idle_verbs", "mill-desk.hint_drop"];
      const rows = [];
      prefer.forEach(function (name) {
        if (!byName[name]) return;
        rows.push(byName[name]);
        delete byName[name];
      });
      Object.keys(byName).forEach(function (name) { rows.push(byName[name]); });
      return rows;
    }
    function hereAnyScoreMiss() {
      return hereScoreRows().length > 0;
    }
    function paintHereScores() {
      const el = document.getElementById("here-scores");
      if (!el) return;
      const rows = hereScoreRows();
      if (!rows.length) {
        el.classList.remove("off");
        el.innerHTML = "";
        return;
      }
      el.classList.add("off");
      el.innerHTML = rows.map(function (k) {
        const name = hereKpiName(k);
        const who = String(k.owner || "");
        const label = hereScoreLabel(name) + (who && who !== "Admin" ? " " + who : "");
        const last = (k.value == null || k.value === "") ? "-" : String(k.value);
        const target = (k.target == null || k.target === "") ? "" : String(k.target);
        return `<span class="here-score off" title="${esc(name)} last ${esc(last)}${target ? " target " + esc(target) : ""}"><b>${esc(label)}</b> ${esc(last)}${target ? `<span class="tgt">/${esc(target)}</span>` : ""}</span>`;
      }).join("");
    }
    function officeScoreRepaint() {
      const was = _officeScoreMiss;
      _officeScoreSeen = true;
      paintHereScores();
      /* #872: the SCORE pane paints these itself when it opens; repaint only once its module is in. */
      if (window.WALL_UI_DEFAULT_SCORE_PAINT) try {
        const scoreFloor = window._floor || {};
        paintScoreShow(scoreFloor);
        paintScoreDeskTable((typeof scoreDeskRows === "function") ? scoreDeskRows(scoreFloor) : []);
      } catch (eScorePane) {}
      const now = hereScoreRows().length > 0;
      _officeScoreMiss = now;
      try { strip(window._floor || {}); } catch (eStrip) {}
      const d = window._floor;
      if (was === now) return;
      if (!d || !Array.isArray(d.agents) || !d.agents.length) return;
      try { board(d, { hereOnly: true }); } catch (eBoard) {}
    }
    function officeScoreLoad() {
      if (_officeScoreInflight) return _officeScoreInflight;
      const scopeKey = "project:project=" + encodeURIComponent("Office");
      const partsStr = "scores";
      const fpQ = floorFpQuery(scopeKey, partsStr);
      const url = "/api/v1/scores?project=" + encodeURIComponent("Office") + "&limit=50" + fpQ;
      _officeScoreInflight = fetch(url, { cache: "no-store" }).then(function (r) {
        if (!r.ok) return null;
        const ct = (r.headers.get("content-type") || "").toLowerCase();
        if (ct.indexOf("json") < 0) return null;
        return r.json();
      }).then(function (json) {
        _officeScoreInflight = null;
        if (!json) { officeScoreRepaint(); return; }
        const echoed = json.fp && json.fp.scores;
        const empty = !Array.isArray(json.kpis) || json.kpis.length === 0;
        const stored = floorFpStored(scopeKey, partsStr).scores;
        if (json.fp) floorFpRemember(scopeKey, partsStr, json.fp);
        if (!(empty && echoed && stored && String(echoed) === String(stored))) {
          if (Array.isArray(json.kpis)) _officeScores = json;
        }
        officeScoreRepaint();
      }).catch(function () {
        _officeScoreInflight = null;
        try { officeScoreRepaint(); } catch (eScore) {}
      });
      return _officeScoreInflight;
    }
    let _hereDesk = { key: "", ready: false, inflight: false, got: {}, needs: [], issues: [], mailbox: [], locks: [] };
    function hereDeskLoad() { return wallLazyCall("deskPaint", "hereDeskLoad", hereDeskLoad, arguments); }
    function paintHereDesk() { return wallLazyCall("deskPaint", "paintHereDesk", paintHereDesk, arguments); }
    function wireHereFront() {
      if (document._hereFrontWired) return;
      document._hereFrontWired = true;
      document.addEventListener("click", function (ev) {
        const t = ev.target && ev.target.closest ? ev.target : null;
        if (!t) return;
        const row = t.closest(".here-row");
        if (row && row.closest("#here")) {
          _hereOwner = String(row.getAttribute("data-here-owner") || "");
          document.querySelectorAll("#here .here-row").forEach(b => b.classList.toggle("on", b === row));
          hereDeskLoad(_hereOwner);
          paintHereDesk(window._floor || {}, _hereOwner);
          return;
        }
      });
    }
    function board(d, opts) {
      /* opts.hereOnly paints SESSION #here only - never rewrite TODO pane on agents ticks. */
      const hereOnly = !!(opts && opts.hereOnly);
      const cards = hereOnly ? [] : millTodoCards(d);
      const nestIx = hereOnly ? {} : millNestIndex(d);
      const parked = cards.filter(r => r.status === "parked");
      const open = cards.filter(r => r.status === "open");
      const claimedRows = cards.filter(r => r.status === "claimed");
      const shippedRows = cards.filter(r => r.status === "shipped");
      const rows = cards;
      const doneSpan = loadDoneSpan();
      if (!hereOnly) paintDoneLabel(doneSpan);
      const spanMs = DONE_SPAN_MS[doneSpan];
      const nowMs = Date.now();
      let recentDone = rows
        .filter(r => {
          if (r.status !== "done") return false;
          if (spanMs == null) return true;
          const ts = parseNeedTs(r.updated_at || r.asked_at);
          if (ts == null) return false;
          return (nowMs - ts) <= spanMs;
        })
        .slice()
        .sort((a, b) => String(b.updated_at || b.asked_at || "").localeCompare(String(a.updated_at || a.asked_at || "")));
      let doneCapped = false;
      if (recentDone.length > DONE_SOFT_CAP) {
        recentDone = recentDone.slice(0, DONE_SOFT_CAP);
        doneCapped = true;
      }
      const pk = document.getElementById("parked");
      if (!hereOnly && pk) {
        const parkedN = millNestSortRows(parked, nestIx);
        pk.innerHTML = parkedN.length ? (function(){ let _pp=""; return parkedN.map(r => { const n = millNestMeta(nestIx, r) || {}; const chip = !!(n.parentId && n.parentId !== _pp); _pp = n.parentId || ""; return needCard(r, n, chip); }); })().join("") :
          '<div class="idle">No parked cards</div>';
      }
      const w = document.getElementById("wanted");
      const c = document.getElementById("claimed");
      const sh = document.getElementById("shipped");
      const g = document.getElementById("jobs-done");
      function todoColHtml(rows, empty) {
        const sorted = millNestSortRows(rows, nestIx);
        if (!sorted.length) return '<div class="idle">' + empty + '</div>';
        let prev = "";
        return sorted.map(function (r) {
          const n = millNestMeta(nestIx, r) || {};
          const chip = !!(n.parentId && n.parentId !== prev);
          prev = n.parentId || "";
          return needCard(r, n, chip);
        }).join("");
      }
      if (!hereOnly && w && c) {
        w.innerHTML = todoColHtml(open, "No open cards");
        c.innerHTML = todoColHtml(claimedRows, "No claimed cards");
        if (sh) sh.innerHTML = todoColHtml(shippedRows, "No shipped cards");
      }
      if (!hereOnly && g) {
        const spanWord = doneSpanLabel(doneSpan);
        if (!recentDone.length) {
          g.innerHTML = `<div class="idle">No done mill todo in ${spanWord}</div>`;
        } else {
          const cap = doneCapped
            ? `<div class="idle" id="jobs-done-cap">showing first ${DONE_SOFT_CAP} in window</div>`
            : "";
          const doneN = millNestSortRows(recentDone, nestIx);
          g.innerHTML = cap + (function(){ let _pp=""; return doneN.map(r => { const n = millNestMeta(nestIx, r) || {}; const chip = !!(n.parentId && n.parentId !== _pp); _pp = n.parentId || ""; return needCard(r, n, chip); }); })().join("");
        }
      }
      (function paintTodoList() {
        if (hereOnly) return;
        const el = document.getElementById("jobs-list");
        if (!el) return;
        const groups = [
          { key: "parked", label: "Parked", match: s => s === "parked" },
          { key: "open", label: "Open", match: s => s === "open" },
          { key: "claimed", label: "Claimed", match: s => s === "claimed" },
          { key: "shipped", label: "Shipped", match: s => s === "shipped" },
          { key: "done", label: "Done | " + doneSpanLabel(doneSpan), match: s => s === "done" }
        ];
        const html = groups.map(g => {
          const rows = g.key === "done"
            ? recentDone
            : cards.filter(r => g.match(String(r.status || "").toLowerCase()));
          if (!rows.length) return "";
          return `<div class="todo-list-group" data-group="${esc(g.key)}">` +
            `<h3>${esc(g.label)} <span>${rows.length}</span></h3>` +
            (() => { let _pp = ""; return millNestSortRows(rows, nestIx).map(r => {
              const st = String(r.status || "").toLowerCase();
              const detailOpen = String(r.id || "") === String(_todoDetailId);
              const shrunk = todoStatusCollapsed(st) && !detailOpen;
              const detailLine = String(r.detail || "").trim();
              const title = detailLine || r.title || r.need_id || "";
              const cardNote = detailOpen && detailLine && detailLine !== title
                ? `<div class="todo-card-note">${esc(detailLine)}</div>` : "";
              const who = [r.asker || r.src ? ("asker " + (r.asker || r.src)) : "",
                r.volunteer ? ("claimed by " + r.volunteer) : ""].filter(Boolean).join(" | ");
              const nest = millNestMeta(nestIx, r) || {};
              const depth = Math.max(0, Number(nest.depth) || 0);
              const nestCls = depth > 0 ? " nest-child" : (nest.tree ? " nest-root" : "");
              const chip = !!(nest.parentId && nest.parentId !== _pp);
              _pp = nest.parentId || "";
              const pid = String(nest.parentId || "");
              const todoId = String(r.id || "");
              const todoTrunc = r.detail_trunc === true ? "1" : "0";
              const detail = shrunk ? "" : (
                `<div class="ttl"><b>${esc(title)}</b><code>${esc(r.need_id || "")}</code></div>` +
                `<span class="who">${esc(who)}</span>` +
                cardNote
              );
              return `<div class="todo-list-row st-${esc(st)}${nestCls}${shrunk ? " is-collapsed" : ""}${detailOpen ? " is-open" : ""}" data-todo-id="${esc(todoId)}" data-todo-trunc="${todoTrunc}" data-depth="${depth}"${pid ? ` data-parent="${esc(pid)}"` : ""}>` +
                millNestSpineHtml(nest, chip) +
                `<span class="st">${esc(st)}</span>` +
                detail +
                `</div>`;
            }).join(""); })() + `</div>`;
        }).filter(Boolean).join("");
        el.innerHTML = html || `<div class="idle">No mill todo</div>`;
      })();
      const live = uniqueDesksByOwner((d.agents || []).filter(r => r.alive));
      const h = document.getElementById("here");
      try { paintHereScores(d); } catch (eScores) {}
      try { wireHereFront(); } catch (eHereWire) {}
      if (!h) return;
      /* #718: desks not read for this scope yet (a TODO or MAIL poll): keep the hourglass,
         never a false "No desks are here". */
      if (!wallHereAgentsRead(d)) {
        if (!wallIsLoadingEl(h) && !_hereDomPick) h.innerHTML = wallLoadingHtml("Loading desks...");
        return;
      }
      _hereDomPick = (railPick && railPick.kind) ? (railPick.kind + ":" + railPick.id) : "";
      if (!live.length) {
        const m = d.maintenance && d.maintenance.eta_at ? d.maintenance : null;
        if (m) {
          let phase = String(m.phase || "");
          const t = Date.parse(String(m.eta_at));
          if (!phase) phase = (Number.isFinite(t) && Date.now() >= t) ? "overdue" : "draining";
          const label = phase === "overdue"
            ? `<b>maintenance overdue</b> (ETA was ${esc(String(m.eta_at))}) - desks reconnecting \u2264120s`
            : `<b>draining</b> for maintenance (ETA ${esc(String(m.eta_at))}) - not a false empty office`;
          h.innerHTML = `<div class="empty-session">${label}</div>`;
          return;
        }
        h.innerHTML = '<div class="empty-session"><b>No desks are here.</b> Ask your agent to join.</div>';
        return;
      }
      const mine = String((typeof wallResolveDeskId === "function" ? wallResolveDeskId() : "") || "").trim();
      const miss = hereAnyScoreMiss();
      const rank = miss
        ? { idle: 0, gone: 1, here: 2, waiting: 3, blocked: 4, working: 5 }
        : { working: 0, waiting: 1, blocked: 2, here: 3, idle: 4, gone: 5 };
      const ordered = live.slice().sort((a, b) => {
        const ao = String(a.owner || "").trim();
        const bo = String(b.owner || "").trim();
        const am = mine && ao === mine ? 0 : 1;
        const bm = mine && bo === mine ? 0 : 1;
        if (am !== bm) return am - bm;
        const ga = hereGlance(d, a).state;
        const gb = hereGlance(d, b).state;
        const ra = rank[ga] != null ? rank[ga] : 9;
        const rb = rank[gb] != null ? rank[gb] : 9;
        if (ra !== rb) return ra - rb;
        return ao.localeCompare(bo);
      });
      const hereTop = h.scrollTop;
      h.innerHTML = ordered.map(r => {
        const g = hereGlance(d, r);
        const owner = String(r.owner || "").trim();
        const on = owner && owner === _hereOwner ? " on" : "";
        /* #818: the item link and the waiting-on pill sit beside the row button, not in it. */
        return `<div class="here-line" data-here-owner="${esc(owner)}">` +
          `<button type="button" class="here-row${on}" data-here-owner="${esc(owner)}">` +
          `<span class="here-dot ${esc(g.state || "")}"></span>` +
          `<span class="here-name">${esc(millName("desk", owner))}</span>` +
          `<span class="here-state">${esc(g.state || "")}</span>` +
          wallDoingRow(owner, r.doing) +
          `</button>` + wallDoingMeta(owner) + `</div>`;
      }).join("");
      h.scrollTop = hereTop;
      /* #818: the doing view loads after this first paint (lazy) and repaints only on change. */
      try { wallDoingSync(); } catch (eDoing) {}
      if (_hereOwner) {
        try { hereDeskLoad(_hereOwner); } catch (eHereLoad) {}
        paintHereDesk(d, _hereOwner);
      }
    }

    /* OFFICE_GLANCE P1 + TIMELINE + RESIZE: Floor map|timeline peer modes; drag split */
    const FLOOR_SPAN_KEY = "factory-floor-span";
    const FLOOR_MODE_KEY = "factory-floor-mode";
    const FLOOR_SPLIT_KEY = "factory-floor-split";
    /* FLOOR_DESK_WORKSTATION: Desk|Workstation map aggregation (desk default) */
    const FLOOR_AGG_KEY = "factory-floor-agg";
    let floorAgg = (function() {
      try {
        const v = localStorage.getItem(FLOOR_AGG_KEY);
        if (v === "desk" || v === "workstation") return v;
      } catch (e) {}
      return "desk";
    })();
    function paintFloorAgg() {
      const root = document.getElementById("floor-agg");
      if (!root) return;
      root.querySelectorAll("button[data-floor-agg]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-floor-agg") === floorAgg);
      });
    }
    /* #710 COLLAB paint code lives in floor/floor-paint.js (lib/lazy.js MODULES.floorPaint); it loads with
     * the pane. Until then each entry below loads it and replays the call; the file's
     * function declarations replace these stubs as globals. */
    function ensureFloorPaint() { return wallLazyCall("floorPaint", "ensureFloorPaint", ensureFloorPaint, arguments); }
    function paintFloorMap() { return wallLazyCall("floorPaint", "paintFloorMap", paintFloorMap, arguments); }
    function paintFloorTimeline() { return wallLazyCall("floorPaint", "paintFloorTimeline", paintFloorTimeline, arguments); }
    function setFloorAgg() { return wallLazyCall("floorPaint", "setFloorAgg", setFloorAgg, arguments); }
    function setFloorMode() { return wallLazyCall("floorPaint", "setFloorMode", setFloorMode, arguments); }
    function setFloorSpan() { return wallLazyCall("floorPaint", "setFloorSpan", setFloorSpan, arguments); }

    function normalizeFloorSpan(span) {
      if (span === "15m" || span === "min") return "min";
      if (span === "1h" || span === "hourly" || span === "hour") return "hourly";
      if (span === "24h" || span === "7d" || span === "daily" || span === "day") return "daily";
      return "";
    }
    let floorSpan = (function() {
      try {
        const v = normalizeFloorSpan(localStorage.getItem(FLOOR_SPAN_KEY));
        if (v) return v;
      } catch (e) {}
      return "daily";
    })();
    let floorMode = "map";
    let floorTlSplit = (function () {
      try {
        const s = localStorage.getItem("factory-floor-tl-split");
        if (s === "type" || s === "desk") return s;
      } catch (e) {}
      return "desk";
    })();
    let floorGlanceCache = null;
    let floorDetailSel = null;
    function activitySpanQuery() {
      let kind = "project";
      let id = ((currentFilter().projects || [])[0]) || "Office";
      if (railPick && railPick.kind === "role" && railPick.id) {
        kind = "role";
        id = String(railPick.id);
      } else if (railPick && railPick.kind === "lan" && railPick.id) {
        kind = "lan";
        id = String(railPick.id);
      } else if (railPick && railPick.kind === "project" && railPick.id) {
        id = String(railPick.id);
      }
      const windowName = normalizeFloorSpan(floorSpan) || "daily";
      let url = "/api/activity?scope=" + encodeURIComponent(kind) +
        "&id=" + encodeURIComponent(id) +
        "&window=" + encodeURIComponent(windowName) +
        "&limit=50";
      if (kind === "project") url += "&project=" + encodeURIComponent(id);
      return { key: kind + ":" + id + "|" + windowName, url: url, kind: kind, id: id, window: windowName };
    }
    function activityBetweenQuery() {
      /* Shared rows for Collab Between. Same scope as the span read, window=between. */
      let kind = "project";
      let id = ((currentFilter().projects || [])[0]) || "Office";
      if (railPick && railPick.kind === "role" && railPick.id) {
        kind = "role";
        id = String(railPick.id);
      } else if (railPick && railPick.kind === "lan" && railPick.id) {
        kind = "lan";
        id = String(railPick.id);
      } else if (railPick && railPick.kind === "project" && railPick.id) {
        id = String(railPick.id);
      }
      let url = "/api/activity?scope=" + encodeURIComponent(kind) +
        "&id=" + encodeURIComponent(id) +
        "&window=between" +
        "&limit=50";
      if (kind === "project") url += "&project=" + encodeURIComponent(id);
      return { key: kind + ":" + id + "|between", url: url, kind: kind, id: id, window: "between" };
    }
    function paintFloorSpan() {
      const root = document.getElementById("floor-span");
      if (!root) return;
      root.querySelectorAll("button[data-floor-span]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-floor-span") === floorSpan);
      });
    }
    function paintFloorMode() {
      const root = document.getElementById("floor-mode");
      if (!root) return;
      root.querySelectorAll("button[data-floor-mode]").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-floor-mode") === floorMode);
      });
      const mapEl = document.getElementById("floor-map");
      const tlEl = document.getElementById("floor-timeline");
      if (mapEl) mapEl.classList.toggle("off", floorMode === "timeline");
      if (tlEl) {
        tlEl.classList.toggle("on", floorMode === "timeline");
        if (floorMode === "timeline") tlEl.removeAttribute("hidden");
        else tlEl.setAttribute("hidden", "");
      }
      const split = document.getElementById("floor-tl-split");
      if (split) {
        split.hidden = floorMode !== "timeline";
        split.querySelectorAll("button[data-tl-split]").forEach(b => {
          b.classList.toggle("on", b.getAttribute("data-tl-split") === floorTlSplit);
        });
      }
      const span = document.getElementById("floor-span");
      if (span) span.hidden = floorMode !== "timeline";
    }
        /* FLOOR_DEFAULT_MAP: paint Map (or saved pref) immediately - no blank until click */
    function floorMailSender(m) {
      if (typeof mailSenderDesk === "function") return mailSenderDesk(m);
      if (!m) return "";
      const sender = m.sender;
      if (sender && typeof sender === "object") return sender.deskId || sender.desk || "";
      if (sender != null && sender !== "") return sender;
      return m.src || m.desk || "";
    }
    function floorMailDests(m) {
      if (typeof mailDstDesks === "function") return mailDstDesks(m);
      if (!m) return [];
      if (Array.isArray(m.mail_tos) && m.mail_tos.length) {
        return m.mail_tos.map(function (t) { return (t && (t.deskId || t.desk)) || ""; }).filter(Boolean);
      }
      const dst = String(m.dst || "").trim();
      if (!dst || dst === "*") return [];
      return [dst];
    }
    function floorDeskKey(name) {
      let s = String(name || "").trim();
      if (!s || s === "*") return "";
      try {
        const bare = millNameBare("desk", s);
        if (bare) s = bare;
      } catch (eKey) {}
      return s;
    }
    function floorRowInSpan(row) {
      const ts = floorParseTs(row && (row.at || row.created || row.updated));
      if (!Number.isFinite(ts)) return true;
      /* Shared lines are interaction. Only the activity window has that. */
      const spec = floorWindowSpec("min");
      const now = Date.now();
      return ts >= (now - spec.ms) && ts <= now + 1000;
    }
    /* Shared rows only: a letter, a card that moved, or a promise. */
    function floorShared(d) {
      d = d || {};
      const agents = d.agents || [];
      const byOwner = {};
      agents.forEach(function (a) {
        const o = floorDeskKey(a && a.owner);
        if (o && !byOwner[o]) byOwner[o] = a;
      });
      function resolveDst(dst) {
        const raw = String(dst || "").trim();
        if (!raw || raw === "*") return [];
        const b = floorDeskKey(raw);
        if (!b) return [];
        if (byOwner[b]) return [b];
        const role = b.indexOf(":") >= 0 ? b.split(":").pop() : b;
        const byRole = agents.filter(function (a) {
          const r = floorDeskKey(a && a.role);
          return r === role || String((a && a.role) || "").trim() === role;
        }).map(function (a) { return floorDeskKey(a && a.owner); }).filter(Boolean);
        return byRole;
      }
      const pair = {};
      const lone = {};
      let rows = 0;
      function addEdge(a, b, kind) {
        a = floorDeskKey(a);
        b = floorDeskKey(b);
        if (!a || !b || a === b) return;
        const lo = a < b ? a : b;
        const hi = a < b ? b : a;
        const k = lo + "\0" + hi;
        let p = pair[k];
        if (!p) p = pair[k] = { a: lo, b: hi, count: 0, kinds: { mail: 0, todo: 0, hold: 0 }, back_and_forth: false };
        p.count += 1;
        p.kinds[kind] = (p.kinds[kind] || 0) + 1;
        rows += 1;
      }
      function addLone(a) {
        a = floorDeskKey(a);
        if (!a) return;
        lone[a] = (lone[a] || 0) + 1;
        rows += 1;
      }
      if (Array.isArray(d.between)) {
        /* Empty means nothing between. Do not fall back to the book. */
        d.between.forEach(function (row) {
          const kind = String((row && row.type) || "");
          if (kind !== "mail" && kind !== "todo" && kind !== "hold") return;
          addEdge(row && row.owner, row && row.other, kind);
        });
      } else {
      (d.mailbox || []).forEach(function (m) {
        if (!floorRowInSpan(m)) return;
        const a = floorDeskKey(floorMailSender(m));
        if (!a) return;
        const dests = floorMailDests(m);
        dests.forEach(function (rawDst) {
          resolveDst(rawDst).forEach(function (b) {
            if (!b || b === a) return;
            addEdge(a, b, "mail");
          });
        });
      });
      let cards = [];
      try { cards = millTodoCards(d) || []; } catch (eCards) { cards = []; }
      cards.forEach(function (r) {
        const asker = floorDeskKey(r && (r.creator || r.asker || ""));
        const holder = floorDeskKey(r && (r.assigned || r.volunteer || ""));
        if (asker && holder && asker !== holder) addEdge(asker, holder, "todo");
      });
      (d.locks || []).forEach(function (row) {
        const names = [];
        [row && row.owner, row && row.holder, row && row.desk, row && row.volunteer].forEach(function (v) {
          const n = floorDeskKey(v);
          if (n && names.indexOf(n) < 0) names.push(n);
        });
        if (names.length >= 2) addEdge(names[0], names[1], "hold");
        else if (names.length === 1) addLone(names[0]);
      });
      }
      const edges = Object.keys(pair).map(function (k) { return pair[k]; });
      const deskSet = {};
      edges.forEach(function (e) { deskSet[e.a] = 1; deskSet[e.b] = 1; });
      Object.keys(lone).forEach(function (o) { deskSet[o] = 1; });
      const desks = Object.keys(deskSet).sort().map(function (owner) {
        const a = byOwner[owner] || {};
        return {
          owner: owner,
          doing: a.doing || "",
          stale: a.alive === false,
          alive: a.alive !== false,
          kind: "desk",
          rollup_state: a.alive === false ? "stale" : "here",
        };
      });
      return { edges: edges, desks: desks, rows: rows, lone: lone };
    }
    function normalizeFloorEdges(edges) {
      return (edges || []).map(e => ({
        a: e.a || e.src || e.from || "",
        b: e.b || e.dst || e.to || "",
        count: e.count != null ? e.count : (e.n != null ? e.n : 1),
        back_and_forth: !!e.back_and_forth,
        kinds: e.kinds || null,
      })).filter(e => e.a && e.b && e.a !== e.b);
    }
    function floorGlanceFromFloor(d) {
      const src = d || window._floor || {};
      const shared = floorShared(src);
      const g = {
        window: floorSpan || "daily",
        desks: shared.desks,
        edges: shared.edges,
        rows: shared.rows,
      };
      return attachFloorTimeline(g, src);
    }
    function attachFloorTimeline(g, d) {
      if (!g) return g;
      if (g.timeline && (g.timeline.lanes || []).length) return g;
      const desks = g.desks || [];
      const events = ((d || window._floor || {}).events) || [];
      const now = new Date();
      const since = new Date(now.getTime() - 86400000);
      g.timeline = {
        since: since.toISOString(),
        gap: "best-effort lanes from here and activity (no v1 office_glance.timeline)",
        lanes: desks.map(desk => {
          const ev = events.filter(e => String(e.owner || "") === String(desk.owner || ""));
          const first = ev[0];
          const t0 = (first && (first.at || first.updated)) || since.toISOString();
          const st = desk.rollup_state || (desk.stale ? "stale" : "here");
          return {
            owner: desk.owner,
            alive: !desk.stale,
            now_state: st,
            bands: [{ t0: t0, t1: now.toISOString(), state: st }],
            jobs_done: 0,
            tokens: 0,
          };
        }),
      };
      return g;
    }
    let _floorSharedFill = "";
    function floorEnsureSharedBook() {
      /* Map already has agents and mail. Cards and promises are separate parts. */
      const d = window._floor || {};
      const parts = Array.isArray(d.parts) ? d.parts : [];
      const needTodos = parts.indexOf("todos") < 0 && !(Array.isArray(d.needs) && d.needs.length);
      const needHolds = parts.indexOf("holds") < 0 && !(Array.isArray(d.locks) && d.locks.length);
      if (!needTodos && !needHolds) return;
      let scope;
      try { scope = floorScope(); } catch (eScope) { return; }
      if (!scope || !String(scope.query || "").trim()) return;
      const key = scope.key + (needTodos ? ":t" : "") + (needHolds ? ":h" : "");
      if (_floorSharedFill === key || _floorSharedFill === ("fail:" + key)) return;
      _floorSharedFill = key;
      const lan = String(scope.key || "").indexOf("lan:") === 0;
      const jobs = [];
      if (needTodos) {
        const todosQ = lan ? floorProjectQuery() : scope.query;
        jobs.push(wallFetchFloorV1(
          { key: "project:" + todosQ, query: todosQ },
          [{ path: "/api/v1/todos", kind: "todos" }]
        ));
      }
      if (needHolds) {
        jobs.push(wallFetchFloorV1(scope, [{ path: "/api/v1/holds", kind: "holds" }]));
      }
      Promise.all(jobs).then(function (rows) {
        const prev = window._floor || {};
        let next = prev;
        let failed = false;
        (rows || []).forEach(function (res) {
          if (!res || res.down || !res.raw) { failed = true; return; }
          next = mergeFloorSlice(next, res.raw, {});
        });
        if (failed) {
          _floorSharedFill = "fail:" + key;
          return;
        }
        if (String(scope.key || "").indexOf("project:") === 0) {
          try { next = applyRailPick(cutFloor(next)); } catch (eCut) {}
        }
        window._floor = next;
        const g = floorGlanceFromFloor(next);
        floorGlanceCache = g;
        paintFloorView(g, { force: true });
        try { strip(next); } catch (eStrip) {}
      }).catch(function () { _floorSharedFill = "fail:" + key; });
    }
    function paintFloorView(g, opts) {
      /* keep prior floor paint when glance empty / floor pane not on (leave must not blank). */
      paintFloorSpan();
      paintFloorMode();
      const floorOn = document.getElementById("pane-floor");
      const active = !!(floorOn && floorOn.classList.contains("on"));
      const force = !!(opts && opts.force);
      const merged = g && g.desks ? g : floorGlanceFromFloor(window._floor);
      const desks = (merged && merged.desks) || [];
      if (!desks.length) {
        const mapEl = document.getElementById("floor-map");
        const tlEl = document.getElementById("floor-timeline");
        if ((mapEl && wallHasRealContent(mapEl)) || (tlEl && wallHasRealContent(tlEl))) {
          if (!force && !active) return;
          if (!force) return; /* keep prior paint when inbound glance has no desks */
        }
        if (!active && !force) return;
      } else if (!active && !force) {
        /* Still refresh cache; only skip DOM wipe/rebuild when leaving floor. */
        try { floorGlanceCache = merged; } catch (eC) {}
        return;
      }
      const withEdges = Object.assign({}, merged, {
        edges: normalizeFloorEdges(merged && merged.edges),
      });
      const gUse = attachFloorTimeline(withEdges, window._floor);
      if (floorMode === "timeline") paintFloorTimeline(gUse);
      else paintFloorMap(gUse);
      try { if (active) floorEnsureSharedBook(); } catch (eShare) {}
    }

    function floorParseTs(s) {
      if (!s) return NaN;
      const t = Date.parse(String(s).replace(" ", "T") + "Z");
      if (!isNaN(t)) return t;
      return Date.parse(String(s));
    }
    const PRESENCE_SERIES = [
      ["mail", "#e6b84c"],
      ["todo", "#5ec8d8"],
      ["hold", "#c17cff"],
    ];
    function floorWindowSpec(span) {
      const s = normalizeFloorSpan(span || floorSpan) || "daily";
      if (s === "min") return { ms: 15 * 60 * 1000, bucket: 60 * 1000, unit: "min", slots: 15 };
      if (s === "hourly") return { ms: 24 * 3600000, bucket: 3600000, unit: "hour", slots: 24 };
      return { ms: 30 * 86400000, bucket: 86400000, unit: "day", slots: 30 };
    }
    let _presenceRows = [];
    let _presenceKey = "";
    let _presenceSource = "";
    let _presenceMiss = false;
    async function loadPresenceBuckets() {
      const q = activitySpanQuery();
      const rows = [];
      let url = q.url;
      let last = null;
      let source = "";
      try {
        for (let guard = 0; url && guard < 8; guard++) {
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) {
            _presenceRows = [];
            _presenceKey = q.key;
            _presenceSource = "";
            _presenceMiss = true;
            return;
          }
          const j = await r.json();
          last = j;
          source = j.source || source;
          (j.rows || []).forEach(function (row) { rows.push(row); });
          if (!j.next) break;
          url = q.url + "&cursor=" + encodeURIComponent(j.next);
        }
        _presenceRows = rows;
        _presenceKey = q.key;
        _presenceSource = source;
        _presenceMiss = false;
        try { if (last && typeof wallRememberListNext === "function") wallRememberListNext("activity", last); } catch (eActN) {}
      } catch (e) {
        _presenceRows = [];
        _presenceKey = "";
        _presenceSource = "";
        _presenceMiss = true;
      }
    }
    const DESK_PALETTE = ["#6fbf73", "#e6b84c", "#5ec8d8", "#c17cff", "#f07178", "#9aa7b5", "#d4a574", "#7eb8f0"];
    function presenceRowsForUi(opts) {
      /* WALL_HISTORY_EVENTS_92: the History diary paints one row per activity (events,
       * with at/kind/state). Hourly and daily span rows are score_evidence (timestamp +
       * value doc, no type/updated/state), so they never feed a row list. */
      const q = activitySpanQuery();
      const fl = window._floor || {};
      const evRows = fl.events || [];
      const tlRows = fl.timeline || [];
      let src;
      if (opts && opts.diary && evRows.length) src = evRows;
      else if (_presenceKey === q.key && _presenceSource === "activity") src = _presenceRows;
      else src = tlRows.length ? tlRows : evRows;
      return (src || []).map(r => ({
        id: r.id,
        at: r.updated || r.at,
        updated: r.updated || r.at,
        kind: r.type || r.kind,
        type: r.type || r.kind,
        owner: r.owner,
        roster_id: millGid(r),
        items: r.items,
        act: r.act || null,
        state: r.state || null,
      }));
    }
    function evidenceHour(row) {
      const m = String((row && row.timestamp) || "").match(/(\d{2}):\d{2}:\d{2}/);
      return m ? Number(m[1]) : -1;
    }
    function evidenceDay(row) {
      const m = String((row && (row.timestamp || row.taken)) || "").match(/(\d{4}-\d{2}-\d{2})/);
      return m ? m[1] : "";
    }
    (function wireFloorSpan() {
      const root = document.getElementById("floor-span");
      if (!root || root._wired) return;
      root._wired = true;
      root.addEventListener("click", ev => {
        const b = ev.target.closest("button[data-floor-span]");
        if (!b) return;
        setFloorSpan(b.getAttribute("data-floor-span"));
      });
    })();
    (function wireFloorTlSplit() {
      const root = document.getElementById("floor-tl-split");
      if (!root || root._wired) return;
      root._wired = true;
      root.addEventListener("click", ev => {
        const b = ev.target.closest("button[data-tl-split]");
        if (!b) return;
        const v = b.getAttribute("data-tl-split");
        if (v !== "desk" && v !== "type") return;
        floorTlSplit = v;
        try { localStorage.setItem("factory-floor-tl-split", v); } catch (e) {}
        paintFloorMode();
        const g = floorGlanceCache || floorGlanceFromFloor(window._floor);
        paintFloorTimeline(g);
      });
    })();
    (function wireFloorMode() {
      const root = document.getElementById("floor-mode");
      if (!root || root._wired) return;
      root._wired = true;
      root.addEventListener("click", ev => {
        const b = ev.target.closest("button[data-floor-mode]");
        if (!b) return;
        setFloorMode(b.getAttribute("data-floor-mode"));
      });
      paintFloorMode();
      const aggRoot = document.getElementById("floor-agg");
      if (aggRoot && !aggRoot._wired) {
        aggRoot._wired = true;
        aggRoot.addEventListener("click", (ev) => {
          const b = ev.target.closest("button[data-floor-agg]");
          if (!b) return;
          setFloorAgg(b.getAttribute("data-floor-agg"));
        });
      }
      paintFloorAgg();
    })();
    /* WALL_UI_COMPONENTS_GUTTER: Floor split uses shared wallWireSplitGutter */
    (function wireFloorResize() {
      if (typeof wallWireSplitGutter !== "function") return;
      if (!document.getElementById("floor-gutter")) return;
      wallWireSplitGutter({
        split: document.getElementById("floor-split"),
        main: document.getElementById("floor-main"),
        gutter: document.getElementById("floor-gutter"),
        detail: document.getElementById("floor-detail"),
        storageKey: FLOOR_SPLIT_KEY,
        defaultPct: 58,
        minMainPx: 192,
        minDetailPx: 224,
        minPct: 20,
        maxPct: 78,
        cssVar: "--floor-main-w",
        applyDefaultIfEmpty: true,
        keyboard: true,
        detailGapPx: 8
      });
    })();

    function paintLeftoverBanner(d) {
      /* v1 leftover-as-work retired. leftover is not a job. */
      const el = document.getElementById("leftover-banner");
      if (!el) return;
      el.classList.remove("on");
      el.hidden = true;
      el.textContent = "";
    }
    function wireMatch(p, proto) {
      if (!proto) return true;
      const k = p.kind || "";
      const res = p.resource || "";
      const det = p.detail || "";
      if (proto === "refuse") return k === "refuse";
      if (proto === "leftover") return false;
      if (proto === "kpi") return k === "kpi" || (k === "refuse" && det.indexOf("kpi") === 0);
      return WIRE_KIND[k] === proto;
    }
    const PRESENCE_TYPES = ["mail", "todo", "doing", "hold", "score", "attach", "name"];
    /* WALL_ACTIVITY_STATE_92: row.state from mill_activity_select via events / between rows.
     * deleted (any type) or sent (live letter); null paints nothing. Read-only pill. */
    function activityStatePill(row) {
      const st = String((row && row.state) || "").trim().toLowerCase();
      if (st !== "deleted" && st !== "sent") return "";
      return `<span class="act-state st-${st}" title="activity state: ${st}">${st}</span>`;
    }
    function paintSessionWire(d) {
      const box = document.getElementById("session-wire");
      const log = document.getElementById("wire-log");
      if (!box || !log) return;
      const onType = document.querySelector("#wire-type button.on");
      const type = String((onType && onType.getAttribute("data-wire-type")) || "live").trim().toLowerCase();
      const deskEl = document.getElementById("wire-desk");
      const projEl = document.getElementById("wire-project");
      const desk = String((deskEl && deskEl.value) || "").trim().toLowerCase();
      const proj = String((projEl && projEl.value) || "").trim().toLowerCase();
      const inWin = presenceRowsForUi({ diary: true });
      const kinds = new Set(inWin.map(p => String(p.kind || p.type || "").toLowerCase()));
      const filters = box.querySelector(".wire-filters");
      if (filters) filters.hidden = !inWin.length;
      document.querySelectorAll("#wire-type button").forEach(b => {
        const wt = String(b.getAttribute("data-wire-type") || "");
        if (wt === "all" || wt === "live") {
          b.hidden = !inWin.length;
          return;
        }
        const key = wt;
        b.hidden = !kinds.has(key) && wt !== type;
      });
      if (deskEl) deskEl.hidden = !inWin.length;
      if (projEl) projEl.hidden = !inWin.length;
      const rows = inWin.filter(p => {
        const k = String(p.kind || p.type || "").toLowerCase();
        const o = String(p.owner || "").toLowerCase();
        const pr = String(millGid(p) || "").toLowerCase();
        if (!type || type === "live") {
          if (k === "heartbeat") return false;
        } else if (type !== "all" && k !== type) return false;
        if (desk && o.indexOf(desk) < 0) return false;
        if (proj && pr.indexOf(proj) < 0) return false;
        return true;
      });
      /* #818: one muted row per doing entry (the newest sighting), so a desk's steps never flood the diary. */
      const seenDoing = {};
      const rowsOne = rows.filter(p => {
        if (String(p.kind || p.type || "").toLowerCase() !== "doing" || p.id == null) return true;
        const key = String(p.id);
        if (seenDoing[key]) return false;
        seenDoing[key] = 1;
        return true;
      });
      if (!rowsOne.length) {
        log.innerHTML = '<div class="idle">Nothing in this diary filter.</div>';
        return;
      }
      log.innerHTML = rowsOne.slice().reverse().map(p => {
        const kind = String(p.kind || p.type || "");
        const when = t(p.at || p.updated);
        const act = p.act != null && p.act !== "" ? (typeof wallActLabel === "function" ? wallActLabel(p.act) : String(p.act)) : "";
        return `<div class="hist-row kind-${esc(kind)}${kind === "doing" ? " muted" : ""}">` +
          `<span class="when">${esc(when)}</span>` +
          `<span class="k">${esc(kind)}</span>` +
          `<span class="who">${esc(millName("desk", p.owner || ""))}</span>` +
          `<span class="prod">${esc(millName("proj", millGid(p) || ""))}</span>` +
          `<span class="act" title="${esc(act || "")}">${esc(act || "")}</span>` +
          activityStatePill(p) +
          `</div>`;
      }).join("");
    }
    function wire(d) {
      const ev = d.events || [];
      const el = document.getElementById("wire");
      const shown = ev.filter(p => (showReads || !WIRE_QUIET[p.kind]) && wireMatch(p, wireProto));
      if (!shown.length) {
        el.innerHTML = ev.length
          ? '<div class="idle">no packets in this filter (valid)</div>'
          : '<div class="idle">quiet mill - no packets (valid)</div>';
        return;
      }
      const headDetail = wireDetails ? `<th>detail</th>` : "";
      el.innerHTML = `<table data-table="wire"><thead><tr>` +
        `<th>at</th><th>kind</th><th>line</th><th>owner</th>${headDetail}` +
        `</tr></thead><tbody>` +
        shown.slice().reverse().map(p => {
          const detailCell = wireDetails
            ? `<td class="detail">${esc(p.resource)} ${esc(p.detail)} <span class="note">${esc(p.host || "")}</span></td>`
            : "";
          return `<tr class="${p.fading ? "fading" : ""}${p.kind === "refuse" ? " refuse" : ""}"><td data-sort="${esc(p.at)}">${esc(t(p.at))}</td>` +
          `<td class="${kindClass(p.kind)}">${esc(p.kind)}${activityStatePill(p)}</td>` +
          `<td>${esc(millGid(p))}</td><td>${esc(p.owner)}</td>` +
          detailCell + `</tr>`;
        }).join("") +
        `</tbody></table>`;
    }
    /* #710 MAIL paint code lives in mail/mail-paint.js (lib/lazy.js MODULES.mailPaint); it loads with
     * the pane. Until then each entry below loads it and replays the call; the file's
     * function declarations replace these stubs as globals. */
    function ensureMailPaint() { return wallLazyCall("mailPaint", "ensureMailPaint", ensureMailPaint, arguments); }
    function mail() { return wallLazyCall("mailPaint", "mail", mail, arguments); }
    function paintMailRooms() { return wallLazyCall("mailPaint", "paintMailRooms", paintMailRooms, arguments); }
    function setMailDestClass() { return wallLazyCall("mailPaint", "setMailDestClass", setMailDestClass, arguments); }
    function setMailMode() { return wallLazyCall("mailPaint", "setMailMode", setMailMode, arguments); }
    function setMailView() { return wallLazyCall("mailPaint", "setMailView", setMailView, arguments); }
    const BARE_HUMAN_MAILBOX = new Set(["setter-upper", "human"]);
    /* MAIL_TO_SRC_JS */
    const MAIL_MODE_KEY = "factory-mail-mode";
    const MAIL_DESK_KEY = "factory-mail-desk";
    const MAIL_TO_KEY = "factory-mail-to";
    const MAIL_SRC_KEY = "factory-mail-src";
    const MAIL_CLASS_KEY = "factory-mail-class";
    let mailView = "rooms";
    let _mailViewChosen = false;
    /* Wave 3: skip Rooms left/nest DOM rewrite when fingerprint unchanged (15s poll). */
    let _mailRoomsRailSig = "";
    let _mailRoomsNestSig = "";
    let mailMode = "attention";
    let mailDestClassFilter = "all";
    let mailSelectedDesk = "";
    let mailSelectedDst = "";
    let mailSelectedSrc = "";
    const MAIL_ROOM_KEY = "factory-mail-room";
    const MAIL_ROOMS_Q_KEY = "factory-mail-rooms-q";
    let mailSelectedRoom = "";
    let mailRoomsQ = "";
    const MAIL_LETTER_SPANS = [
      ["1h", "1h", 3600e3, "No letters in the last hour."],
      ["8h", "8h", 8 * 3600e3, "No letters in the last 8 hours."],
      ["1d", "1d", 86400e3, "No letters in the last day."],
      ["7d", "7d", 7 * 86400e3, "No letters in the last 7 days."],
      ["all", "All", null, "No letters in this cut."]
    ];
    let mailLetterSpan = "all";
    function planCut() {
      const el = document.getElementById("plan-cut");
      return el ? String(el.value || "") : "";
    }
    function planHist() {
      const on = document.querySelector("#plan-hist button.on");
      return (on && on.dataset.planHist) || "this";
    }
    function planView() {
      const on = document.querySelector("#plan-view-toggle button.on");
      return (on && on.dataset.planView) || "tiles";
    }
    function paintPlanView() {
      const listEl = document.getElementById("issue-list");
      const v = planView();
      if (listEl) {
        listEl.classList.toggle("plan-tiles", v === "tiles");
        listEl.classList.toggle("plan-list", v === "list");
      }
      document.querySelectorAll("#plan-view-toggle button").forEach(b => {
        b.classList.toggle("on", b.dataset.planView === v);
      });
    }
    function savePlanChrome() {
      try {
        localStorage.setItem(PLAN_CHROME_KEY, JSON.stringify({
          cut: planCut(),
          hist: planHist(),
          label: (document.getElementById("plan-label") || {}).value || "",
          q: (document.getElementById("board-search") || {}).value || "",
          view: planView(),
        }));
      } catch (e) {}
    }
    function restorePlanChrome() {
      try {
        const raw = JSON.parse(localStorage.getItem(PLAN_CHROME_KEY) || "{}");
        const set = (id, v) => { const el = document.getElementById(id); if (el && v != null) el.value = v; };
        set("board-search", raw.q || "");
        set("plan-label", raw.label || "");
        if (raw.cut != null) {
          const cutEl = document.getElementById("plan-cut");
          if (cutEl) cutEl.dataset.want = raw.cut;
        }
        const hist = raw.hist || "this";
        document.querySelectorAll("#plan-hist button").forEach(b => {
          b.classList.toggle("on", b.dataset.planHist === hist);
        });
        const view = raw.view === "list" ? "list" : "tiles";
        document.querySelectorAll("#plan-view-toggle button").forEach(b => {
          b.classList.toggle("on", b.dataset.planView === view);
        });
      } catch (e) {}
    }
    function group(rows, key) {
      const g = {};
      for (const r of rows || []) (g[r[key]] ??= []).push(r);
      return g;
    }
    function stations(d) {
      const by = group((d.locks || []).map(r => Object.assign({}, r, { roster_id: millGid(r) })), "roster_id");
      const el = document.getElementById("stations");
      const ids = Object.keys(by).sort();
      if (!ids.length) { el.innerHTML = '<div class="idle">No promises. Scarce files are free.</div>'; return; }
      el.innerHTML = ids.map(pid => {
        const rows = by[pid].map(r => {
          const live = !(r.holder_dead || r.stale);
          const st = r.holder_dead ? "stale" : (r.stale ? "stale" : "live");
          const pid = (r.owner_pid != null && r.owner_pid !== "") ? String(r.owner_pid) : "";
          const holder = `<span class="st-owner">${esc(millName("desk", r.owner))}</span>` +
            (pid ? ` <span class="st-pid">${esc(pid)}</span>` : "");
          return `<tr class="${live ? "alive" : "dead"}"><td>${esc(millName("res", r.resource))}</td><td>${holder}</td>` +
            `<td>${esc(st)}</td><td>${esc(t(r.lease_until))}</td></tr>`;
        }).join("");
        return `<div class="station"><h3>${esc(millName("proj", pid))}</h3><table data-table="stations-${esc(pid)}"><thead><tr>` +
          `<th>resource</th><th>holder</th><th>live/stale</th><th>until</th>` +
          `</tr></thead><tbody>${rows}</tbody></table></div>`;
      }).join("");
    }
    function agents(d) {
      const el = document.getElementById("agents");
      if (!el) return; /* WALL_IA_BACKLOG: AGENTS removed from Jobs Wall */
      const live = (d.agents || []).filter(r => r.alive);
      const shown = showDead ? (d.agents || []) : live;
      const by = group(shown.map(r => Object.assign({}, r, { roster_id: millGid(r) })), "roster_id");
      const ids = Object.keys(by).sort();
      if (!ids.length) {
        el.innerHTML = '<div class="idle">' + (showDead ? "no registered pids" : "no live agents") + "</div>";
        return;
      }
      el.innerHTML = ids.map(pid => {
        const rows = by[pid].map(r => {
          const st = !r.alive ? "dead" : r.remote ? "remote" : "alive";
          return `<tr class="${st}"><td>${esc(r.owner)}</td><td>${esc(r.pid)}</td>` +
            `<td>${esc(r.owner_host || "")}</td><td>${wallDoingRow(r.owner, r.doing)}</td>` +
            `<td data-sort="${esc(r.heartbeat || "")}">${esc(t(r.heartbeat))}</td></tr>`;
        }).join("");
        return `<div class="station"><h3>${esc(pid)}</h3><table data-table="agents-${esc(pid)}"><thead><tr>` +
          `<th>owner</th><th>pid</th><th>node</th><th>doing</th><th>last ping</th>` +
          `</tr></thead><tbody>${rows}</tbody></table></div>`;
      }).join("");
    }
    /* WALL_UI_DEFAULT_SCORE: numish from domain module */
    /* WALL_UI_DEFAULT_SCORE: kpiMiss from domain module */
    function wallNumish(s) {
      const t = String(s || "").replace(/\*/g, "").trim();
      if (/^(not run|leftover|pass|stay|shipped|none|-)$/i.test(t)) return null;
      const m = t.match(/-?\d+(?:\.\d+)?/);
      return m ? Number(m[0]) : null;
    }
    function wallKpiMiss(last, target) {
      /* Score's kpiMiss loads with that tab. The strip must judge Last vs target without it. */
      if (typeof kpiMiss === "function") return kpiMiss(last, target);
      if (typeof WallScore !== "undefined" && typeof WallScore.kpiMiss === "function") {
        return WallScore.kpiMiss(last, target);
      }
      const L = String(last || "").toLowerCase();
      if (!L || /not run|leftover|shipped|stay|none/.test(L)) return false;
      if (/\bfail\b|\bstarve\b|\bmiss\b/.test(L)) return true;
      const T = String(target == null ? "" : target).trim();
      if (!T) return false;
      const ln = wallNumish(last);
      const tn = wallNumish(target);
      if (ln == null || tn == null) return false;
      if (tn === 0) return ln !== 0;
      return ln < tn;
    }
    function collectKpiMisses(d) {
      const hits = [];
      const seen = {};
      const add = (line, k) => {
        if (!wallKpiMiss(k.value, k.target)) return;
        const key = line + "|" + (k.kpi || "");
        if (seen[key]) return;
        seen[key] = true;
        hits.push({ line: line, kpi: k.kpi || "", last: k.value || "", target: k.target || "" });
      };
      (d.kpis || []).forEach(k => add(millGid(k), k));
      return hits;
    }
    function paintKpiBanner(d) {
      const el = document.getElementById("kpi-banner");
      if (!el) return;
      el.classList.remove("on");
      el.textContent = "";
    }

    function leftoverCard(d) {
      const pools = [].concat(d.needs || [], d.wanted || [], d.on_it || []);
      return pools.find(r => String(r.need_id || "") === "leftover") || null;
    }
    function parseRatio(s) {
      const raw = String(s || "").replace(/\*/g, "").trim();
      if (!raw) return null;
      const pct = raw.match(/(-?\d+(?:\.\d+)?)\s*%/);
      if (pct) {
        const n = Number(pct[1]);
        if (isNaN(n)) return null;
        return { pct: Math.max(0, Math.min(100, Math.round(n))), label: Math.round(n) + "%" };
      }
      const frac = raw.match(/(-?\d+(?:\.\d+)?)\s*\/\s*(-?\d+(?:\.\d+)?)/);
      if (frac) {
        const n = Number(frac[1]), of = Number(frac[2]);
        if (!of || isNaN(n) || isNaN(of)) return null;
        return { pct: Math.max(0, Math.min(100, Math.round(100 * n / of))), label: frac[1] + "/" + frac[2] };
      }
      return null;
    }
    function ratioFromKpi(k) {
      const fromLast = parseRatio(k.value);
      if (fromLast) return fromLast;
      const ln = numish(k.value), tn = numish(k.target);
      if (ln != null && tn != null && tn > 0) {
        return { pct: Math.max(0, Math.min(100, Math.round(100 * ln / tn))), label: ln + "/" + tn };
      }
      return null;
    }
    function paintHero(d) {
      const el = document.getElementById("hero");
      if (!el) return;
      const live = uniqueDesksByOwner((d.agents || []).filter(a => a.alive));
      const f = currentFilter();
      const cutName = (f.projects && f.projects.length) ? f.projects.join(", ") : "Office";
      const on = document.querySelector("nav.tabs button.on");
      let tab = (on && on.dataset.tab) || "session";
      if (tab === "leases" || tab === "stations") tab = "session";
      const chip = (desk, value, extra, hot) => {
        const cls = "row" + (hot ? " hot" : "");
        return `<div class="${cls}" title="${esc([desk, value, extra].filter(Boolean).join(" | "))}">` +
          `<span class="hero-desk">${esc(desk)}</span><b>${esc(value)}</b>` +
          (extra ? `<span>${esc(extra)}</span>` : "") + `</div>`;
      };
      const track = parts => {
        const bits = (parts || []).filter(Boolean);
        if (!bits.length) return `<div class="idle">all quiet</div>`;
        const html = bits.join("");
        const loop = bits.length >= 3 ? html + html : html;
        const dur = Math.max(18, bits.length * 5);
        return `<div class="hero-ticker" tabindex="0" title="hover to pause"><div class="hero-ticker-track" style="animation-duration:${dur}s">${loop}</div></div>`;
      };
      let name = cutName, doing = "", parts = [], hotBox = false;
      if (tab === "score") {
        const filedNow = (typeof scoreFiledList === "function") ? scoreFiledList(d) : [];
        const hits = filedNow.filter(function (k) {
          return typeof kpiMiss === "function" && kpiMiss(k.value, k.target);
        });
        hits.sort(function (a, b) {
          const fa = (typeof scoreFiledFace === "function") ? scoreFiledFace(hereKpiName(a)) : hereKpiName(a);
          const fb = (typeof scoreFiledFace === "function") ? scoreFiledFace(hereKpiName(b)) : hereKpiName(b);
          return fa.localeCompare(fb);
        });
        name = "SCORE";
        if (hits.length) {
          hotBox = true;
          const h0 = hits[0];
          const face = (typeof scoreFiledFace === "function") ? scoreFiledFace(hereKpiName(h0)) : hereKpiName(h0);
          const lastTxt = (h0.value == null || h0.value === "") ? "-" : String(h0.value);
          const tgtTxt = (h0.target == null || h0.target === "") ? "-" : String(h0.target);
          doing = "A score is off target. " + face + " last " + lastTxt +
            ", target " + tgtTxt + ". Ask your agent.";
          parts = hits.map(function (k) {
            const label = (typeof scoreFiledFace === "function") ? scoreFiledFace(hereKpiName(k)) : hereKpiName(k);
            const lastBit = (k.value == null || k.value === "") ? "-" : String(k.value);
            const tgtBit = (k.target == null || k.target === "") ? "-" : String(k.target);
            return chip(label, "off target", "last " + lastBit + " | target " + tgtBit, true);
          });
        } else {
          doing = "Last vs Target is on track. You do not write Last.";
          const rows = typeof scoreDeskRows === "function" ? scoreDeskRows(d) : [];
          parts = rows.slice(0, 10).map(r => chip(r.desk, (r.miss || r.hot) ? "off" : "ok",
            String(r.last || ""), !!(r.miss || r.hot)));
        }
      } else if (tab === "jobs") {
        const cards = millTodoCards(d);
        const open = cards.filter(r => r.status === "open");
        const claimedN = cards.filter(r => r.status === "claimed");
        const shippedN = cards.filter(r => r.status === "shipped");
        name = "TODO";
        const leadCard = claimedN[0] || shippedN[0];
        const lead = leadCard ? ((leadCard.volunteer || "") + " on " + (leadCard.need_id || "")) : "";
        doing = open.length + " open, " + claimedN.length + " claimed, " + shippedN.length + " shipped" + (lead ? ". " + lead : ".");
        parts = claimedN.concat(shippedN).map(r => chip(r.need_id || "", r.status || "", r.volunteer || "", false));
      } else if (tab === "mail") {
        const box = d.mailbox || [];
        const unread = box.filter(m => typeof mailWallUnread === "function" ? mailWallUnread(m) : false);
        name = "MAIL";
        hotBox = unread.length >= 20;
        doing = unread.length >= 20
          ? unread.length + " unread. Overflow - agents are not consuming mail."
          : (unread.length ? unread.length + " unread letters waiting on desks." : "Mail is caught up.");
        parts = unread.slice(0, 14).map(m => chip(String(m.dst || m.to || "*"), "unread",
          String(m.subject || m.body || "").slice(0, 42), true));
      } else if (tab === "floor") {
        let shared = { rows: 0, desks: [] };
        try { shared = floorShared(d) || shared; } catch (eFloorHero) {}
        name = "COLLAB";
        doing = shared.rows
          ? (shared.rows + " shared. A line is a letter, a card, or a promise.")
          : "Nothing between desks yet. A desk shows up when a letter, a card, or a promise joins it to another desk.";
        parts = (shared.desks || []).slice(0, 14).map(n => {
          const agent = (d.agents || []).find(a => floorDeskKey(a.owner) === n.owner) || { owner: n.owner, doing: n.doing || "", alive: false };
          const g = hereGlance(d, agent);
          const hot = !!g.stale;
          return chip(n.owner || "", g.stale ? "stale" : (g.state || ""), String(g.doing || wallDoingText(n.owner, n.doing) || "").slice(0, 36), hot);
        });
      } else {
        const sm = (document.querySelector("[data-session-mode].on") || {}).getAttribute
          ? document.querySelector("[data-session-mode].on").getAttribute("data-session-mode")
          : "now";
        if (sm === "leases") {
          const locks = d.locks || [];
          name = "Promise";
          const top = locks[0] ? ((locks[0].owner || "") + " holds " + String(locks[0].resource || "a file").split(/[/\\]/).pop()) : "";
          doing = (locks.length === 1 ? "1 file held" : (locks.length + " files held")) +
            (top ? ". " + top : ".") + (hotBox ? " Something is stale." : "");
          hotBox = locks.some(L => L.holder_dead || L.stale);
          parts = locks.map(L => chip(
            String(L.resource || "file").split(/[/\\]/).pop() || L.resource || "file",
            L.owner || "-",
            (L.holder_dead || L.stale) ? "stale" : "live",
            !!(L.holder_dead || L.stale)
          ));
        } else if (sm === "history") {
          name = "History";
          doing = "Diary of who was here - same clock as Now.";
          const ev = (d.events || []).slice(0, 14);
          parts = ev.map(e => chip(e.owner || e.desk || "", e.type || "pulse", String(e.doing || "").slice(0, 36), false));
        } else {
          if (!live.length) {
            el.className = "hero empty";
            el.innerHTML = `<div class="idle">No desks are here on ${esc(cutName)}. Ask your agent to join.</div>`;
            return;
          }
          const glances = live.map(a => ({ a: a, g: hereGlance(d, a) }));
          const nWork = glances.filter(x => x.g.state === "working").length;
          /* #818: "waiting" is who waits on a desk (the server's waiting_on_it), and only once
             the doing view is read; nothing is guessed from a desk's text. */
          const viewRead = glances.some(x => x.g.view);
          const nWaitOn = glances.filter(x => wallDoingWaitN(x.g.view) > 0).length;
          const nHot = glances.filter(x => x.g.stale || x.g.state === "gone").length;
          name = cutName;
          doing = live.length + " desks here." +
            (viewRead ? (nWaitOn ? " " + nWaitOn + " with mail or cards waiting on them." : " Nothing waiting on them.") : "") +
            (nHot ? " " + nHot + " need eyes." : (nWork ? " " + nWork + " working." : ""));
          hotBox = nHot > 0;
          parts = glances.map(x => {
            const g = x.g;
            const hot = !!(g.stale || g.state === "gone");
            return chip(x.a.owner || "", g.stale ? "stale" : g.state, String(g.doing || wallDoingText(x.a.owner, x.a.doing) || "").slice(0, 36), hot);
          });
        }
      }
      if (!apiOk) {
        hotBox = true;
        doing = "API down - " + doing;
        parts.unshift(chip("API", "down", "mill not answering", true));
      }
      el.className = "hero presence" + (hotBox ? " has-hot" : "");
      const doingHtml = (doing.indexOf("off target") >= 0 || doing.indexOf("API down") >= 0)
        ? `<span class="hot-n">${esc(doing)}</span>`
        : esc(doing);
      el.innerHTML =
        `<div class="hero-left"><div class="name">${esc(name)}</div>` +
        `<div class="doing">${doingHtml}</div></div>`;
    }
    function kpiMissCards(d) {
      const hits = collectKpiMisses(d);
      if (!hits.length) return "";
      const body = hits.map(h =>
        `<div class="card open kpi-miss-card">` +
        `<div class="issue-kind bug">KPI MISS</div>` +
        `<div>${esc(h.line)} / ${esc(h.kpi)}</div>` +
        `<div class="note">last ${esc(h.last)} | target ${esc(h.target)}</div>` +
        `<div class="who">glance SCORE, then ask your agent. re-measure Last.</div>` +
        `</div>`
      ).join("");
      return `<section id="sec-kpi-miss"><h2>KPI MISS - stop and debug</h2><div class="body">${body}</div></section>`;
    }
    let spendWindow = "all";
    let spendOwner = "";


    /* SCORECARDS_BOTTLENECK / SCORECARDS_GLANCE / SCORECARDS_TOKEN_DETAIL / SCORECARDS_TOKENS_EST */
    let scoreSpan = "24h";
    let scoreFilter = "needs";
    let scoreMode = "scores";
    let scoreSelectedDesk = "";
    let scoreSelectedCommand = "";
    let _scoreEv = { key: "", min: [], hourly: [], daily: [], missMin: false, missHour: false, missDay: false };
    let _scoreEvBusy = "";
    let _scoreEvAt = 0;
    const SCORE_SPLIT_KEY = "factory-score-split";
    try { scoreSpan = localStorage.getItem("factory-score-span") || "24h"; } catch (e) {}
    try { scoreFilter = localStorage.getItem("factory-score-filter") || "needs"; } catch (e) {}
    try { scoreSelectedDesk = localStorage.getItem("factory-score-desk") || ""; } catch (e) {}
    /* #710 SCORE paint code lives in score/score-paint.js (lib/lazy.js MODULES.scorePaint); it loads with
     * the pane. Until then each entry below loads it and replays the call; the file's
     * function declarations replace these stubs as globals. */
    function cards() { return wallLazyCall("scorePaint", "cards", cards, arguments); }
    function ensureScorePaint() { return wallLazyCall("scorePaint", "ensureScorePaint", ensureScorePaint, arguments); }
    function loadScoreEvidence() { return wallLazyCall("scorePaint", "loadScoreEvidence", loadScoreEvidence, arguments); }
    function paintScoreCommands() { return wallLazyCall("scorePaint", "paintScoreCommands", paintScoreCommands, arguments); }
    function selectScoreDesk() { return wallLazyCall("scorePaint", "selectScoreDesk", selectScoreDesk, arguments); }
    /* WALL_UI_DEFAULT_SCORE: scoreDeskRows from domain module */
    /* WALL_UI_DEFAULT_SCORE: thin bridge - module scoreDeskRows(d, span?) */
    function scoreDeskRows(d) {
      return (typeof WallScore !== "undefined" && WallScore.scoreDeskRows)
        ? WallScore.scoreDeskRows(d, (typeof scoreSpan !== "undefined" ? scoreSpan : "24h"))
        : [];
    }
    const SCORE_SHOW_KEY = "factory-score-show";
    let _scoreShowOff = {};
    let _scoreGroupOff = {};
    function loadScoreShow() {
      try {
        const raw = JSON.parse(localStorage.getItem(SCORE_SHOW_KEY) || "{}");
        const off = {};
        const groups = {};
        (Array.isArray(raw.off) ? raw.off : []).forEach(function (s) {
          const k = String(s || "").trim();
          if (k) off[k] = 1;
        });
        (Array.isArray(raw.groups) ? raw.groups : []).forEach(function (s) {
          const k = String(s || "").trim();
          if (k === "platform" || k === "product") groups.platform = 1;
          else if (k === "office") groups.office = 1;
        });
        _scoreShowOff = off;
        _scoreGroupOff = groups;
      } catch (e) {
        _scoreShowOff = {};
        _scoreGroupOff = {};
      }
    }
    function saveScoreShow() {
      try {
        localStorage.setItem(SCORE_SHOW_KEY, JSON.stringify({
          off: Object.keys(_scoreShowOff),
          groups: Object.keys(_scoreGroupOff)
        }));
      } catch (e) {}
    }
    function scoreKpiBucket(name) {
      return String(name || "").trim() === "system" ? "platform" : "office";
    }
    function scoreShown(name) {
      const bucket = scoreKpiBucket(name);
      if (_scoreGroupOff[bucket]) return false;
      return !_scoreShowOff[String(name || "").trim()];
    }
    function scoreFiledFace(name) {
      const raw = String(name || "").trim();
      const mapped = (typeof scoreKpiLabel === "function") ? scoreKpiLabel(raw) : "";
      if (mapped && mapped !== raw) return mapped;
      const dot = raw.indexOf(".");
      const rest = dot > 0 ? raw.slice(dot + 1) : raw;
      return rest.replace(/[._]+/g, " ");
    }
    function scoreFiledList(d) {
      const books = [];
      if (_officeScores && Array.isArray(_officeScores.kpis)) books.push(_officeScores.kpis);
      if (d && Array.isArray(d.kpis)) books.push(d.kpis);
      const seen = {};
      const rows = [];
      books.forEach(function (list) {
        list.forEach(function (k) {
          const name = hereKpiName(k);
          if (!name || name === "system" || !scoreShown(name)) return;
          let desk = "";
          if (typeof scoreDeskSlug === "function") desk = scoreOwnerKey(scoreDeskSlug(k));
          else desk = scoreOwnerKey(k && k.owner);
          const key = name + "\n" + desk;
          if (seen[key]) return;
          seen[key] = 1;
          rows.push(k);
        });
      });
      return rows;
    }
    function paintScoreShow() { return wallLazyCall("scorePaint", "paintScoreShow", paintScoreShow, arguments); }
    try { loadScoreShow(); } catch (eShow) {}
    function scoreOwnerKey(raw) {
      let s = String(raw || "").trim();
      if (!s) return "";
      try {
        const bare = millNameBare("desk", s);
        if (bare) s = bare;
      } catch (eOwner) {}
      return s;
    }
    function paintScoreDeskTable() { return wallLazyCall("scorePaint", "paintScoreDeskTable", paintScoreDeskTable, arguments); }
    let _scoreGlanceUser = false;
    let _scoreGlanceScroll = 0;
    let _scoreGlanceLock = false;
    (function wireScorecardsGlance() {
      const chrome = document.getElementById("score-chrome");
      const sub = document.getElementById("subnav");
      if (sub && !sub._todoScoreWired) {
        sub._todoScoreWired = true;
        sub.addEventListener("click", ev => {
          const tv = ev.target.closest("button[data-todo-view]");
          if (tv) {
            setJobsView(tv.getAttribute("data-todo-view") || "board");
            return;
          }
          const sm = ev.target.closest("button[data-score-mode]");
          if (sm) {
            scoreMode = sm.getAttribute("data-score-mode") || "scores";
            try { localStorage.setItem("factory-score-mode", scoreMode); } catch (e) {}
            if (window._floor) cards(window._floor);
          }
        });
      }
      const show = document.getElementById("score-show");
      if (show && !show._scoreShowWired) {
        show._scoreShowWired = true;
        show.addEventListener("change", ev => {
          const t = ev.target;
          if (!t || !t.getAttribute) return;
          const g = t.getAttribute("data-score-group");
          const k = t.getAttribute("data-score-kpi");
          if (g) {
            if (t.checked) delete _scoreGroupOff[g];
            else _scoreGroupOff[g] = 1;
          } else if (k) {
            if (t.checked) delete _scoreShowOff[k];
            else _scoreShowOff[k] = 1;
          } else return;
          saveScoreShow();
          if (window._floor) cards(window._floor);
        });
      }
      if (chrome && !chrome._scoreWired) {
        chrome._scoreWired = true;
        chrome.addEventListener("click", ev => {
          const span = ev.target.closest("button[data-score-span]");
          if (span) {
            scoreSpan = span.getAttribute("data-score-span") || "24h";
            try { localStorage.setItem("factory-score-span", scoreSpan); } catch (e) {}
            if (window._floor) cards(window._floor);
            return;
          }
          const mode = ev.target.closest("button[data-score-mode]");
          if (mode) {
            scoreMode = mode.getAttribute("data-score-mode") || "scores";
            try { localStorage.setItem("factory-score-mode", scoreMode); } catch (e) {}
            if (window._floor) cards(window._floor);
            return;
          }
          const filt = ev.target.closest("button[data-score-filter]");
          if (filt) {
            scoreFilter = filt.getAttribute("data-score-filter") || "needs";
            try { localStorage.setItem("factory-score-filter", scoreFilter); } catch (e) {}
            if (window._floor) cards(window._floor);
          }
        });
      }
      const root = document.getElementById("pane-score");
      if (root && !root._scoreDeskWired) {
        root._scoreDeskWired = true;
        root.addEventListener("click", ev => {
          const commandHit = ev.target.closest("#score-verbs [data-score-verb]");
          if (commandHit) {
            scoreSelectedCommand = commandHit.getAttribute("data-score-verb") || "";
            paintScoreDeskTable(scoreDeskRows(window._floor || {}));
            return;
          }
          const hit = ev.target.closest("#score-desk-table [data-score-desk]");
          if (!hit || !window._floor) return;
          const desk = hit.getAttribute("data-score-desk") || "";
          if (!desk || desk === scoreSelectedDesk) return;
          scoreSelectedCommand = "";
          selectScoreDesk(desk, scoreDeskRows(window._floor));
        });
      }
      /* WALL_UI_COMPONENTS_GUTTER: Score split uses shared wallWireSplitGutter */
      if (typeof wallWireSplitGutter === "function") {
        wallWireSplitGutter({
          split: document.getElementById("score-split"),
          main: document.getElementById("score-hot"),
          gutter: document.getElementById("score-gutter"),
          detail: document.getElementById("score-detail"),
          storageKey: SCORE_SPLIT_KEY,
          defaultPct: 42,
          minMainPx: 160,
          minDetailPx: 200,
          minPct: 22,
          maxPct: 72,
          cssVar: "--score-hot-w",
          applyDefaultIfEmpty: false,
          keyboard: false,
          detailGapPx: 0
        });
      }
    })();


    function uiBusy() {
      if (holdTick) return true;
      const s = document.getSelection && document.getSelection();
      if (s && !s.isCollapsed && document.querySelector("main") && document.querySelector("main").contains(s.anchorNode)) {
        return true;
      }
      return false;
    }
    /* WALL_UI_LIB_DATA: thin wrapper -> wallPaintApiDown (keep last-good) */
    /* WALL_HONEST_EMPTY_VS_DOWN: API-down banner only on fetch fail; last-good OK */
    function paintApiDown(msg) {
      apiOk = false;
      if (typeof wallPaintApiDown === "function") {
        wallPaintApiDown({ msg: msg, lastGood: window._floor || {}, strip: strip });
        return;
      }
      const lastGood = window._floor || {};
      const maint = lastGood.maintenance && lastGood.maintenance.eta_at ? lastGood.maintenance : null;
      const clock = document.getElementById("clock");
      if (clock) {
        clock.classList.add("warn");
        clock.textContent = maint
          ? ("maintenance " + (maint.phase || "draining") + " eta " + maint.eta_at)
          : msg;
      }
      const banner = document.getElementById("kpi-banner");
      if (banner) {
        banner.classList.add("on");
        if (maint) {
          banner.classList.remove("api-down");
          banner.classList.add("maintenance");
          banner.setAttribute("data-wall-api", "maintenance");
          banner.innerHTML = (typeof wallMaintenanceBannerHtml === "function")
            ? wallMaintenanceBannerHtml(maint)
            : ("<b>maintenance / draining.</b> ETA " + esc(String(maint.eta_at)) + ". Not false API-down.");
        } else {
          banner.classList.add("api-down");
          banner.setAttribute("data-wall-api", "down");
          banner.innerHTML = (typeof WALL_UI_LIB_API_DOWN_BANNER === "string")
            ? WALL_UI_LIB_API_DOWN_BANNER
            : "<b>mill API down.</b> Last-good wall kept if any. Tell your Mill desk to restart the wall.";
        }
      }
      strip(lastGood);
    }
    function clearApiDownBanner() {
      if (typeof wallClearApiDownBanner === "function") {
        wallClearApiDownBanner();
        return;
      }
      const banner = document.getElementById("kpi-banner");
      if (!banner) return;
      const apiState = banner.getAttribute("data-wall-api");
      if (apiState === "down" || apiState === "maintenance" || banner.classList.contains("api-down") || banner.classList.contains("maintenance")) {
        banner.classList.remove("api-down");
        banner.classList.remove("maintenance");
        banner.removeAttribute("data-wall-api");
        banner.classList.remove("on");
        banner.textContent = "";
      }
    }

    /* WALL_CUT6_WIRE: mill prefs office_default+desk (desk wins) -> Wall inject
       SoR: wall-contract (tests/wall)
       Fail closed: missing prefs / API down -> pack defaults (no fake knobs).
       Pack CSS/JS override ladder still valid; knobs do not replace pack. */
    const WALL_PACK_STUB = {
      deskId: null,
      prefs: {
        land_tab: "session",
        tabs: ["session", "jobs", "score", "mail", "plan"],
        density: "comfortable",
        css_vars: {},
        chrome_flags: {},
        mail_default_view: "list",
        score_default_filter: "needs",
        pack_id: "default",
        keyboard_profile: "windows",
        keyboard_overrides: {},
        pane_order: ["session", "jobs", "score", "mail", "plan"]
      },
      pack: null,
      officeDefault: null,
      inject: null,
      cut6: true
    };
    let _wallLoadedAssetId = null;
    let _wallPrefsLoaded = false;
    function wallAssetEndpoints() {
      return ["/api/v1/wall-asset", "/api/wall-asset"];
    }
    function wallPrefsEndpoints() {
      return ["/api/v1/wall-prefs", "/api/wall-prefs"];
    }
    /* WALL_UI_LIB_DATA */
    async function fetchJsonFirst(urls) {
      if (typeof wallFetchJsonFirst === "function") return wallFetchJsonFirst(urls);
      for (const u of urls) {
        try {
          const r = await fetch(u, { cache: "no-store" });
          const ct = (r.headers.get("content-type") || "").toLowerCase();
          if (r.ok && ct.indexOf("json") >= 0) return await r.json();
        } catch (e) { /* try next */ }
      }
      return null;
    }
    function paintRefreshBanner(need) {
      const el = document.getElementById("wall-refresh-banner");
      if (!el) return;
      el.classList.toggle("on", !!need);
    }
    async function checkWallAsset() {
      const data = await fetchJsonFirst(wallAssetEndpoints());
      if (!data || !data.asset_id) return;
      const meta = document.querySelector('meta[name="wall-asset-id"]');
      if (meta && data.asset_id) meta.setAttribute("content", data.asset_id);
      if (_wallLoadedAssetId == null) {
        _wallLoadedAssetId = String(data.asset_id);
        paintRefreshBanner(false);
        return;
      }
      paintRefreshBanner(String(data.asset_id) !== String(_wallLoadedAssetId));
    }
    function wallResolveDeskId() {
      try {
        const qs = new URLSearchParams(location.search);
        const q = qs.get("desk") || qs.get("for") || "";
        if (q) return String(q).trim();
      } catch (e) {}
      try {
        const badge = JSON.parse(localStorage.getItem("factory-desk-badge") || "null");
        if (badge && (badge.name || badge.dst)) return String(badge.name || badge.dst).trim();
      } catch (e2) {}
      try {
        return (localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || "").trim();
      } catch (e3) {
        return "";
      }
    }
    function applyChromeFlagsCut6(flags) {
      if (!flags || typeof flags !== "object") return;
      const guideBtn = document.getElementById("guide-open");
      const adminBtn = document.getElementById("admin-open");
      const wireBtn = document.getElementById("wire-open") || document.querySelector('button[data-tab="wire"]');
      if ("show_guide" in flags && guideBtn) guideBtn.hidden = !flags.show_guide;
      if ("show_admin_chrome" in flags && adminBtn) adminBtn.hidden = !flags.show_admin_chrome;
      if ("show_wire" in flags && wireBtn) wireBtn.hidden = !flags.show_wire;
    }
    function applyDensityAndCssVars(inject) {
      if (!inject) return;
      const dens = String(inject.density || "comfortable");
      document.body.classList.toggle("wall-density-compact", dens === "compact");
      document.body.classList.toggle("wall-density-comfortable", dens !== "compact");
      const vars = (inject.css_vars && typeof inject.css_vars === "object") ? inject.css_vars : {};
      if (typeof wallApplyCssVars === "function") {
        try { wallApplyCssVars(vars); } catch (e) {}
      } else {
        Object.keys(vars).forEach(function (k) {
          if (String(k).indexOf("--") !== 0) return;
          try { document.documentElement.style.setProperty(k, String(vars[k]).replace(/[;{}]/g, "")); } catch (e2) {}
        });
      }
    }
    function applyPaneOrderCut6(order) {
      if (!Array.isArray(order) || !order.length) return;
      const nav = document.querySelector("nav.tabs");
      if (!nav) return;
      const buttons = Array.prototype.slice.call(nav.querySelectorAll("button[data-tab]"));
      if (!buttons.length) return;
      const byTab = {};
      buttons.forEach(function (b) { byTab[b.getAttribute("data-tab")] = b; });
      order.forEach(function (tab) {
        const b = byTab[tab];
        if (b) nav.appendChild(b);
      });
    }
    function applyPackIdCut6(packId) {
      const id = String(packId || "default").trim() || "default";
      WALL_PACK_STUB.pack = id === "default" ? null : { id: id };
      if (id === "default") return;
      /* Pack CSS/JS override ladder: try pack assets; fail closed keeps default pack already loaded */
      const hrefCss = "/packs/" + encodeURIComponent(id) + "/board.css";
      const srcJs = "/packs/" + encodeURIComponent(id) + "/boot.js";
      if (!document.querySelector('link[data-wall-pack-css="' + id + '"]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = hrefCss;
        link.setAttribute("data-wall-pack-css", id);
        link.onerror = function () { try { link.remove(); } catch (e) {} };
        document.head.appendChild(link);
      }
      if (!document.querySelector('script[data-wall-pack-js="' + id + '"]')) {
        const s = document.createElement("script");
        s.src = srcJs;
        s.async = true;
        s.setAttribute("data-wall-pack-js", id);
        s.onerror = function () { try { s.remove(); } catch (e) {} };
        document.head.appendChild(s);
      }
    }
    function applyKeyboardCut6(inject, deskId) {
      if (!inject) return;
      const profile = inject.keyboard_profile;
      const overrides = inject.keyboard_overrides;
      const hasMillKeys = !!(profile || (overrides && Object.keys(overrides).length));
      if (typeof wallKeysApplyMillPrefs === "function") {
        try {
          wallKeysApplyMillPrefs(deskId, hasMillKeys ? {
            profile: profile || "windows",
            overrides: overrides || {},
            millWins: true
          } : null);
        } catch (e) {}
      }
    }
    function applyWallPrefsCut6(payload) {
      if (!payload || typeof payload !== "object") return;
      const inject = payload.inject || payload.prefs || {};
      WALL_PACK_STUB.prefs = Object.assign({}, WALL_PACK_STUB.prefs, inject);
      WALL_PACK_STUB.inject = inject;
      if (payload.office_default) WALL_PACK_STUB.officeDefault = payload.office_default;
      if (payload.pack) WALL_PACK_STUB.pack = payload.pack;
      applyDensityAndCssVars(inject);
      /* only apply chrome_flags when office/desk explicitly set them (not pack defaults) */
      var rawFlags = null;
      if (payload.desk_prefs && payload.desk_prefs.chrome_flags) rawFlags = inject.chrome_flags;
      else if (payload.office_default && payload.office_default.chrome_flags) rawFlags = inject.chrome_flags;
      if (rawFlags) applyChromeFlagsCut6(rawFlags);
      applyPaneOrderCut6(inject.pane_order || inject.tabs);
      applyPackIdCut6(inject.pack_id || "default");
      /* mail / score defaults - mill when localStorage unset */
      try {
        const mv = String(inject.mail_default_view || "").toLowerCase();
        if (!_mailViewChosen && (mv === "rooms" || mv === "letters") && typeof mailView !== "undefined") {
          mailView = mv;
        }
      } catch (e1) {}
      try {
        const sf = String(inject.score_default_filter || "").toLowerCase();
        if ((sf === "needs" || sf === "all") && typeof scoreFilter !== "undefined") {
          const saved = localStorage.getItem("factory-score-filter");
          if (!saved) {
            scoreFilter = sf;
            try { localStorage.setItem("factory-score-filter", sf); } catch (e2) {}
          }
        }
      } catch (e3) {}
      /* LAST_TAB: refresh restores last tab; else SESSION (not mill land_tab). */
      const land = (typeof loadWallTab === "function") ? loadWallTab() : "session";
      const hash = (location.hash || "").replace(/^#/, "");
      if (!hash) {
        if (typeof showTab === "function") {
          try { showTab(land); } catch (e4) {}
        } else if (land) {
          try { location.hash = land; } catch (e5) {}
        }
      }
      applyKeyboardCut6(inject, WALL_PACK_STUB.deskId || wallResolveDeskId());
    }
    async function loadWallPrefsCut6() {
      const desk = wallResolveDeskId();
      WALL_PACK_STUB.deskId = desk || null;
      const urlQs = desk ? ("?desk=" + encodeURIComponent(desk)) : "";
      let data = null;
      try {
        data = await fetchJsonFirst(wallPrefsEndpoints().map(u => u + urlQs));
      } catch (e) {
        data = null;
      }
      if (!data) {
        /* fail closed: pack defaults already on WALL_PACK_STUB */
        _wallPrefsLoaded = true;
        return null;
      }
      applyWallPrefsCut6(data);
      _wallPrefsLoaded = true;
      return data;
    }
    /* back-compat aliases */
    function applyWallPrefsStub(prefs) {
      applyWallPrefsCut6({ prefs: prefs, inject: prefs });
    }
    async function loadWallPrefsStub() {
      return loadWallPrefsCut6();
    }
    document.getElementById("wall-refresh-btn")?.addEventListener("click", () => {
      location.reload();
    });



    let _floorHash = "";
    let _railPickApplied = "";
    let _railRestored = false;
    function deskNameSet(rows) {
      const out = new Set();
      (rows || []).forEach(r => {
        const n = String((r && (r.desk || r.name || r.owner)) || "").trim().toLowerCase();
        if (n) out.add(n);
      });
      return out;
    }
    function rowInDeskSet(row, desks) {
      if (!desks || !desks.size) return false;
      const names = rowOwners(row);
      if (row && row.desk) names.push(String(row.desk).toLowerCase());
      if (row && Array.isArray(row.desks)) {
        row.desks.forEach(d => {
          const n = typeof d === "string" ? d : (d && d.desk);
          if (n) names.push(String(n).toLowerCase());
        });
      }
      if (row && row.sender && row.sender.deskId) names.push(String(row.sender.deskId).toLowerCase());
      if (row && Array.isArray(row.mail_tos)) {
        row.mail_tos.forEach(function (t) {
          const id = t && (t.deskId || t.desk);
          if (id) names.push(String(id).toLowerCase());
        });
      }
      return names.some(o => desks.has(String(o).toLowerCase()));
    }
    function applyRailPick(d) {
      if (!railPick || railPick.kind === "project" || !railPick.desks) return d;
      const desks = railPick.desks;
      const keep = rows => (rows || []).filter(r => {
        if (railPick.kind === "lan" && String(r.lan_ip || "").trim() === railPick.id) return true;
        return rowInDeskSet(r, desks);
      });
      const out = Object.assign({}, d);
      out.events = keep(d.events);
      out.mailbox = keep(d.mailbox);
      out.locks = keep(d.locks);
      out.agents = keep(d.agents);
      out.kpis = keep(d.kpis);
      out.needs = keep(d.needs);
      out.wanted = keep(d.wanted);
      out.spend = keep(d.spend);
      out.spend_lines = keep(d.spend_lines);
      out.issues = keep(d.issues);
      out.watchers = keep(d.watchers);
      out.on_it = keep(d.on_it);
      out.live_agents = (out.agents || []).filter(a => a.alive).length;
      out.live_locks = (out.locks || []).length;
      out.open_needs = (out.needs || []).filter(n => n.status === "open").length;
      out.claimed_needs = (out.needs || []).filter(n => n.status === "claimed").length;
      if (out.desk_unread) {
        const slim = {};
        Object.keys(out.desk_unread).forEach(k => { if (desks.has(String(k).toLowerCase())) slim[k] = out.desk_unread[k]; });
        out.desk_unread = slim;
      }
      return out;
    }
    function markRailPick() {
      document.querySelectorAll("#rail-book .rail-row").forEach(el => {
        const on = !!(railPick && el.getAttribute("data-kind") === railPick.kind && el.getAttribute("data-id") === railPick.id);
        el.classList.toggle("on", on);
      });
    }
    const roleDeskCache = {};
    async function desksForPick(kind, id) {
      if (kind === "project") return null;
      if (kind === "lan") {
        return deskNameSet((window.__railDeskRows || []).filter(r => String(r.lan_ip || "").trim() === id));
      }
      if (roleDeskCache[id]) return roleDeskCache[id];
      try {
        const r = await fetch("/api/rows?role=" + encodeURIComponent(id) + "&tab=here", { cache: "no-store" });
        if (!r.ok) return new Set();
        const data = await r.json();
        const set = deskNameSet(data && data.rows);
        roleDeskCache[id] = set;
        return set;
      } catch (e) { return new Set(); }
    }
    function paintLoadedFloor() {
      const raw = window._floorRaw;
      if (!raw) return;
      const pickKey = railPick ? (railPick.kind + ":" + railPick.id) : "";
      _railPickApplied = pickKey;
      const scoped = floorScope().key.indexOf("project:") !== 0;
      const d = scoped ? raw : applyRailPick(cutFloor(raw));
      window._floor = d;
      const clock = document.getElementById("clock");
      const safe = (typeof wallPaintThrowSafe === "function")
        ? wallPaintThrowSafe
        : function (fn) { try { return fn(); } catch (e) {} };
      safe(function () { strip(d); });
      safe(function () { paintHero(d); });
      safe(function () { paintKpiBanner(d); });
      safe(function () { paintLeftoverBanner(d); });
      safe(function () { board(d); });
      safe(function () { paintPlan(d); });
      safe(function () { paintWatchers(d); });
      safe(function () { issues(d); });
      safe(function () { wire(d); });
      safe(function () { mail(d); });
      safe(function () { stations(d); });
      safe(function () { agents(d); });
      safe(function () { paintSessionWire(d); });
      safe(function () { cards(d); });
      try {
        const glance = floorGlanceFromFloor(d);
        if (glance && (glance.desks || []).length) {
          floorGlanceCache = glance;
          paintFloorView(glance);
        }
      } catch (e) {}
      if (clock) clock.textContent = wallClockLine(d);
      enhanceTables(document);
      markOverflow();
    }
    async function selectRail(kind, id) {
      if (kind === "role") {
        try {
          const held = floorScope();
          if (held && held.query) _roleScopeHold = { key: held.key, query: held.query };
        } catch (eHold) { _roleScopeHold = null; }
      } else {
        _roleScopeHold = null;
      }
      railPick = { kind: kind, id: id, desks: kind === "project" ? null : (roleDeskCache[id] || null) };
      try { sessionStorage.setItem("mill-rail-pick", JSON.stringify({ kind: kind, id: id })); } catch (e) {}
      markRailPick();
      const blank = { projects: [], owner: "", kind: "", status: "", from: "", to: "" };
      if (kind === "project") {
        const cur = currentFilter().projects || [];
        const sameUrl = cur.length === 1 && cur[0] === id;
        const nextQ = "project=" + encodeURIComponent(id);
        /* Role and station hops leave this project's book loaded. Paint it. Do not refetch an empty fp hit. */
        if (bookIsProject(nextQ)) {
          try {
            const url = applyRailNestUrl("project", id);
            if (sameUrl) history.replaceState({}, "", url);
            else history.pushState({}, "", url);
          } catch (ePath) {}
          paintLoadedFloor();
          return;
        }
        if (!sameUrl) goFilter(Object.assign({}, blank, { projects: [id] }), true);
        else {
          try { history.replaceState({}, "", applyRailNestUrl("project", id)); } catch (ePath) {}
          try { floorFpForgetScope(floorScope().key); } catch (eFpSame) {}
          tick(true);
        }
        return;
      }
      if (kind === "lan") {
        try { history.pushState({}, "", applyRailNestUrl("lan", id)); } catch (eLan) {}
        resetFloorBook();
        try { floorFpForgetScope(floorScope().key); } catch (eFpLan) {}
        tick(true);
        return;
      }
      try { history.pushState({}, "", applyRailNestUrl("role", id)); } catch (eRole) {}
      railPick.desks = roleDeskCache[id] || await desksForPick(kind, id);
      if (!railPick || railPick.kind !== kind || railPick.id !== id) return;
      markRailPick();
      if (window._floorRaw) paintLoadedFloor();
      else {
        try { floorFpForgetScope(floorScope().key); } catch (eFpRole) {}
        tick(true);
      }
    }
    function paintRailBook(host, html) {
      if (!host || host.dataset.sig === html) return;
      host.dataset.sig = html;
      host.innerHTML = html;
    }
    /* Last rail read (ms). Rail counts change slowly; a read this fresh is reused. */
    let _railBookAt = 0;
    const WALL_RAIL_FRESH_MS = 5000;
    async function loadRailBook() {
      const root = document.getElementById("rail-book");
      if (!root || root.dataset.busy === "1") return;
      root.dataset.busy = "1";
      _railBookAt = Date.now();
      /* spinner until each POV part lands; fetch desks/projects/roles in parallel. */
      try {
        ["rail-desks", "rail-roster"].forEach(function (id) {
          const el = document.getElementById(id);
          if (el && !wallHasRealContent(el)) wallShowLoading(el, "Loading\u2026");
        });
      } catch (eSpin) {}
      async function part(name) {
        try {
          const r = await fetch("/api/pov?part=" + encodeURIComponent(name), { cache: "no-store" });
          if (!r.ok) return null;
          return await r.json();
        } catch (e) { return null; }
      }
      const nameRows = (data, empty, hostId) => {
        const rows = (data && data.rows) || [];
        if (hostId === "rail-roster") {
          rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
        }
        if (!rows.length) return `<div class="rail-empty">${empty}</div>`;
        return rows.map(row => {
          const name = String(row.name || "");
          const n = row.desks;
          const count = n != null ? `<span class="n">${esc(String(n))}</span>` : "";
          /* One Roster list (0.7.0). The floor scope token stays "project" (rows tagged with that roster). */
          const kind = "project";
          const ico = "project";
          return `<button type="button" class="rail-row" data-kind="${kind}" data-ico="${ico}" data-id="${esc(name)}" title="${esc(name)}"><span class="nm">${esc(name)}</span>${count}</button>`;
        }).join("");
      };
      function paintDesks(desks) {
        const mine = String((desks && desks.mine) || "").trim();
        window.__railDeskRows = (desks && desks.rows) || [];
        const groups = [];
        ((desks && desks.rows) || []).forEach(row => {
          const ip = String(row.lan_ip || "").trim();
          let g = groups[groups.length - 1];
          if (!g || g.ip !== ip) {
            g = { ip: ip, n: 0, live: false };
            groups.push(g);
          }
          g.n += 1;
          if (row.connected) g.live = true;
        });
        paintRailBook(document.getElementById("rail-desks"), groups.length
          ? groups.map(g => {
              const mark = g.live ? `<span class="live" title="connected"></span>` : `<span class="off" title="away"></span>`;
              const my = g.ip && g.ip === mine ? `<span class="my" title="This screen"></span>` : "";
              return `<button type="button" class="rail-row" data-kind="lan" data-ico="station" data-id="${esc(g.ip)}" title="${esc(g.ip || "station")}">${mark}<span class="nm">${esc(g.ip || "-")}</span>${my}<span class="n">${g.n}</span></button>`;
            }).join("")
          : `<div class="rail-empty">none</div>`);
        if (typeof wallPerfFirst === "function") wallPerfFirst("rail_desks");
      }
      const desksP = part("desks").then(function (desks) {
        try { paintDesks(desks); } catch (eD) {}
        return desks;
      });
      const rostersP = part("rosters").then(function (rosters) {
        try {
          paintRailBook(document.getElementById("rail-roster"), nameRows(rosters, "none", "rail-roster"));
          if (typeof wallPerfFirst === "function") wallPerfFirst("rail_roster");
        } catch (eP) {}
        return rosters;
      });
      /* Desks can paint first. A project or role in the URL waits for its button, or the first station steals the path. */
      function railSavedPick() {
        let saved = null;
        try { saved = JSON.parse(sessionStorage.getItem("mill-rail-pick") || "null"); } catch (e) { saved = null; }
        try {
          const nestSaved = nestPickFromPath();
          if (nestSaved) saved = nestSaved;
        } catch (eNestSaved) {}
        return saved;
      }
      function restoreRailPick(saved) {
        const rows = Array.from(document.querySelectorAll("#rail-book .rail-row"));
        let match = null;
        if (saved && saved.kind && saved.id) {
          match = rows.find(el => el.getAttribute("data-kind") === saved.kind && el.getAttribute("data-id") === String(saved.id));
        }
        if (!match) match = document.querySelector("#rail-desks .rail-row");
        if (match) selectRail(match.getAttribute("data-kind") || "", match.getAttribute("data-id") || "");
        else markRailPick();
      }
      await desksP;
      const savedEarly = railSavedPick();
      const deferNest = !!(savedEarly && (savedEarly.kind === "project" || savedEarly.kind === "role"));
      if (!_railRestored && !deferNest) {
        _railRestored = true;
        restoreRailPick(savedEarly);
      }
      await Promise.all([rostersP]);
      if (!_railRestored) {
        _railRestored = true;
        restoreRailPick(railSavedPick());
      } else {
        markRailPick();
      }
      root.dataset.busy = "";
    }
    const railBook = document.getElementById("rail-book");
    if (railBook && !railBook.dataset.wired) {
      railBook.dataset.wired = "1";
      railBook.addEventListener("click", ev => {
        const row = ev.target.closest(".rail-row");
        if (!row) return;
        selectRail(row.getAttribute("data-kind") || "", row.getAttribute("data-id") || "");
      });
    }
    /* Wave 2 poll hygiene: pause when hidden; multi-tab single-flight leader. */
    const WALL_POLL_TAB_ID = (function () {
      try {
        let id = sessionStorage.getItem("factory-wall-poll-tab");
        if (!id) {
          id = "t" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
          sessionStorage.setItem("factory-wall-poll-tab", id);
        }
        return id;
      } catch (e) {
        return "t" + Math.random().toString(36).slice(2, 10);
      }
    })();
    const WALL_POLL_LOCK_KEY = "factory-wall-poll-lock";
    const WALL_POLL_LOCK_MS = 12000;
    let _tickForce = false;
    function wallClaimPollLeader() {
      try {
        const now = Date.now();
        const raw = localStorage.getItem(WALL_POLL_LOCK_KEY);
        const prev = raw ? JSON.parse(raw) : null;
        if (prev && prev.id && prev.id !== WALL_POLL_TAB_ID && (now - (prev.at || 0)) < WALL_POLL_LOCK_MS) {
          return false;
        }
        localStorage.setItem(WALL_POLL_LOCK_KEY, JSON.stringify({ id: WALL_POLL_TAB_ID, at: now }));
        return true;
      } catch (e) {
        return true;
      }
    }
    function wallStopFloorPoll() {
      if (window.__wallFloorPoll) {
        try { clearInterval(window.__wallFloorPoll); } catch (eClear) {}
        window.__wallFloorPoll = null;
      }
    }
    function wallStartFloorPoll() {
      /* Wave 3 / #40: 15s poll lessened via Rooms trees fingerprint skip + no-op mail paint.
       * Toward: event-driven floor (WS/HINT), longer interval, then kill this timer. */
      wallStopFloorPoll();
      if (typeof document !== "undefined" && document.hidden) return;
      window.__wallFloorPoll = setInterval(function () { tick(); }, 15000);
    }
    if (typeof document !== "undefined" && !window.__wallVisWired) {
      window.__wallVisWired = true;
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
          wallStopFloorPoll();
        } else {
          _tickForce = true;
          try { tick(true); } finally { _tickForce = false; }
          wallStartFloorPoll();
        }
      });
    }
    window.wallClaimPollLeader = wallClaimPollLeader;

    let _tickInflight = null;
    let _tickAgain = false;
    let _tickAgainForce = false;
    let _tickDebounce = null;
    const TICK_DEBOUNCE_MS = 50;
    function tick(force) {
      /* Coalesce: tab/rail/mode flips + 15s timer must not stack concurrent part reads. */
      if (force) _tickForce = true;
      if (_tickInflight) {
        _tickAgain = true;
        if (force) _tickAgainForce = true;
        return _tickInflight;
      }
      if (_tickDebounce != null) return;
      _tickDebounce = setTimeout(function () {
        _tickDebounce = null;
        _tickRun();
      }, TICK_DEBOUNCE_MS);
    }
    async function _tickRun() {
      if (_tickInflight) {
        _tickAgain = true;
        return _tickInflight;
      }
      _tickInflight = (async function () {
        try {
          await _tickBody();
        } finally {
          _tickInflight = null;
          _tickForce = false;
          if (_tickAgain) {
            const againForce = _tickAgainForce;
            _tickAgain = false;
            _tickAgainForce = false;
            tick(againForce);
          }
        }
      })();
      return _tickInflight;
    }
    async function _tickBody() {
      /* WALL_API_DOWN_FALSE + WALL_HONEST_EMPTY_VS_DOWN:
         fetch/json failures -> paintApiDown; 200 empty payload -> honest empty;
         paint/render throws -> clock warn only (never flip API-down). */
      if (uiBusy()) return;
      if (typeof document !== "undefined" && document.hidden) return;
      /* Multi-tab debounce: only the poll leader issues the 15s part reads.
         Focused/visible tabs claim leadership; followers skip until they become leader. */
      if (!_tickForce && typeof wallClaimPollLeader === "function" && !wallClaimPollLeader()) return;
      let tickGen = wallBeginTickGen(wallSwitchGen());
      if (!_railRestored) {
        await loadRailBook();
        if (!wallTickGenAlive(tickGen) && !_wallReuseInflight) return;
        if (railPick) return;
      }
      /* The restore tick and the tick its rail pick starts land together: one rail read, not two. */
      if (Date.now() - _railBookAt > WALL_RAIL_FRESH_MS) loadRailBook();
      const clock = document.getElementById("clock");
      const scope = floorScope();
      const projectKey = scope.key;
      const partsStr = wallParts();
      _tickInflightParts = partsStr;
      _tickInflightScope = projectKey;
      try { officeScoreLoad(); } catch (eOfficeScore) {}
      try {
        window._tickInflightParts = _tickInflightParts;
        window._tickInflightScope = _tickInflightScope;
      } catch (eMeta) {}
      const storedFpBefore = floorFpStored(projectKey, partsStr);
      let raw = null;
      try {
        const v1Routes = (typeof wallV1Routes === "function") ? wallV1Routes(scope) : null;
        if (!(v1Routes && v1Routes.length && typeof wallFetchFloorV1 === "function")) {
          paintApiDown("wall API down - mill API or mill-wall");
          return;
        }
        try {
            const earlyRows = [];
            try { wallMarkTabLoading(); } catch (eMark) {}
            const onRow = function (row) {
              if (!row || row.down) return;
              if (floorScope().key !== projectKey) return;
              earlyRows.push(row);
              /* even if switch-gen stale, keep absorbing isolates into last-good. */
              if (!wallTickGenAlive(tickGen)) {
                try {
                  const mergedStale = wallMergeV1Isolates(earlyRows);
                  wallAbsorbOffPaneResult(mergedStale, {
                    storedFp: storedFpBefore,
                    projectKey: projectKey,
                    partsStr: partsStr,
                  });
                } catch (eStaleRow) {}
                return;
              }
              const kind = row.kind;
              const tabBtnNow = document.querySelector("nav.tabs button.on");
              const tabNow = (tabBtnNow && tabBtnNow.dataset.tab) || "session";
              if (tabNow === "mail" && typeof mailView !== "undefined" && mailView === "rooms") {
                if (kind !== "tree-mail" && kind !== "rooms" && kind !== "mailbox") return;
                /* Mailbox-first: absorb/paint as soon as mailbox lands; trees enrich after. */
                try {
                  wallPaintMailRoomsEarly(wallMergeV1Isolates(earlyRows));
                  if (kind === "mailbox") {
                    try { wallShowPaneOverlay("pane-mail", "Loading rooms\u2026"); } catch (eOvMail) {}
                  } else if (kind === "tree-mail" || kind === "rooms") {
                    try { wallClearPaneOverlay("pane-mail"); } catch (eClrMail) {}
                  }
                } catch (eEarly) {}
                return;
              }
              if (tabNow === "mail") {
                /* Letters paints when the mailbox lands. Other mail views wait for fp settle. */
                if (kind === "mailbox") {
                  try {
                    const merged = wallMergeV1Isolates(earlyRows);
                    const book = absorbFloorSlice(merged);
                    const d = (projectKey.indexOf("project:") === 0)
                      ? applyRailPick(cutFloor(book))
                      : book;
                    window._floor = d;
                    if (typeof mailView !== "undefined" && mailView === "letters" && typeof mail === "function") {
                      mail(d);
                    }
                  } catch (eMailEarly) {}
                }
                return;
              }
              if ((tabNow === "session" || tabNow === "score" || tabNow === "glossary") &&
                  (kind === "agents" || kind === "holds" || kind === "watchers" ||
                   kind === "events" || kind === "scores" || kind === "names")) {
                /* absorb single-part v1 early; paint after fp settle (like mail list). */
                try {
                  const merged = wallMergeV1Isolates(earlyRows);
                  const book = absorbFloorSlice(merged);
                  const d = (projectKey.indexOf("project:") === 0)
                    ? applyRailPick(cutFloor(book))
                    : book;
                  window._floor = d;
                } catch (eSingleEarly) {}
                return;
              }
              if (tabNow === "jobs") {
                if (kind !== "todos" && kind !== "tree-todo") return;
                try {
                  wallPaintTodosEarly(wallMergeV1Isolates(earlyRows));
                  if (kind === "todos") {
                    try { wallShowPaneOverlay("pane-todo", "Loading plan\u2026"); } catch (eOvTodo) {}
                  } else if (kind === "tree-todo") {
                    try { wallClearPaneOverlay("pane-todo"); } catch (eClrTodo) {}
                  }
                } catch (eTodoEarly) {}
              }
            };
            const v1 = await wallFetchFloorV1(scope, v1Routes, onRow);
            if (v1 && v1.down) {
              if (projectKey.indexOf("project:") !== 0) {
                if (clock) {
                  clock.classList.add("warn");
                  clock.title = "scope HTTP " + (v1.status || "?");
                }
                return;
              }
              paintApiDown("wall API down (HTTP " + (v1.status || "?") + ") - mill API or mill-wall");
              return;
            }
            if (v1 && v1.raw) raw = v1.raw;
          } catch (eV1) {
            paintApiDown("wall API down - mill API or mill-wall");
            return;
          }
      } catch (e) {
        paintApiDown("wall API down - mill API or mill-wall");
        /* Only clear overlay if this switch still owns the pane. */
        if (wallTickGenAlive(tickGen)) {
          try { wallClearActivePaneOverlay(); } catch (eOvDown) {}
        }
        return;
      }
      try {
        if (floorScope().key !== projectKey) return;
                /* leave->return mid-flight reuses this result on LIVE pane (no second fetch).
           otherwise commit off-pane last-good; live .on untouched. */
        if (!wallTickGenAlive(tickGen)) {
          const reuseLive = !!(
            _wallReuseInflight
            && String(floorScope().key || "") === String(projectKey || "")
            && String(wallParts() || "") === String(partsStr || "")
          );
          if (reuseLive) {
            wallClearReuseInflight();
            tickGen = wallBeginTickGen(wallSwitchGen());
          } else {
            try {
              if (raw && typeof raw === "object") {
                wallAbsorbOffPaneResult(raw, {
                  storedFp: storedFpBefore,
                  projectKey: projectKey,
                  partsStr: partsStr,
                });
              }
            } catch (eAbsStale) {}
            try { wallPreserveThemeChrome(); } catch (eThStale) {}
            wallClearReuseInflight();
            return;
          }
        }
        const h = JSON.stringify(raw);
        const pickKey = railPick ? (railPick.kind + ":" + railPick.id) : "";
        if (h === _floorHash && pickKey === _railPickApplied && pickKey === _hereDomPick) {
          const cl = document.getElementById("clock");
          /* Same version, node and local zone as every other paint (no bare UTC). */
          if (cl) cl.textContent = wallClockLine(raw);
          /* fp same / hash same - keep last result; drop checking overlay. */
          try { wallRestoreActivePaneFromFloor(); } catch (eRest0) {}
          try { wallPreserveThemeChrome(); } catch (eTh0) {}
          if (wallTickGenAlive(tickGen)) {
            try { wallClearActivePaneOverlay(); } catch (eOv0) {}
          }
          return;
        }
        _floorHash = h;
        _railPickApplied = pickKey;
        apiOk = true;
        clearApiDownBanner();
        clock.classList.remove("warn");
        clock.removeAttribute("title");
        /* Fingerprint hits: empty part + unchanged fp => keep prior; skip that part's paint. */
        const fpHits = {};
        (Array.isArray(raw.parts) ? raw.parts : []).forEach(function (part) {
          if (floorPartFpHit(raw, part, storedFpBefore[part])) fpHits[part] = true;
        });
        if (raw.fp && typeof raw.fp === "object") {
          floorFpRemember(projectKey, partsStr, raw.fp);
        }
        const book = absorbFloorSlice(raw, { storedFp: storedFpBefore });
        const d = projectKey.indexOf("project:") === 0 ? applyRailPick(cutFloor(book)) : book;
        /* do NOT await /api/activity before first paint - run in parallel, refresh timeline after. */
        const presenceP = loadPresenceBuckets().then(function () {
          if (!wallTickGenAlive(tickGen)) return;
          if (floorScope().key !== projectKey) return;
          try {
            if (window._floor) paintSessionWire(window._floor);
            const floorOn = document.getElementById("pane-floor");
            if (floorOn && floorOn.classList.contains("on")) ensureFloorPaint();
          } catch (ePres) {}
        }).catch(function () {});
                if (floorScope().key !== projectKey) return;
        if (!wallTickGenAlive(tickGen)) {
          const reuseLive2 = !!(
            _wallReuseInflight
            && String(wallParts() || "") === String(partsStr || "")
          );
          if (reuseLive2) {
            wallClearReuseInflight();
            tickGen = wallBeginTickGen(wallSwitchGen());
          } else {
            try {
              window._floor = d;
              if (raw && raw.fp && typeof raw.fp === "object") {
                floorFpRemember(projectKey, partsStr, raw.fp);
              }
              try {
                const glance = floorGlanceFromFloor(d);
                if (glance) floorGlanceCache = glance;
              } catch (eG2) {}
              wallPaintOffPaneLastGood(d, (raw && raw.parts) || []);
            } catch (eStale2) {}
            try { wallPreserveThemeChrome(); } catch (eThStale2) {}
            wallClearReuseInflight();
            return;
          }
        }
        window._floor = d;
        /* fp decided refresh - paint below, then drop overlay (keep last-good until then). */
        try { wallPreserveThemeChrome(); } catch (eTh1) {}
        /* paint throws must not call paintApiDown (prior P0 wall-api-down-false) */
        const safe = (typeof wallPaintThrowSafe === "function")
          ? wallPaintThrowSafe
          : function (fn, label) {
              try { return fn(); } catch (e) {
                if (clock) {
                  clock.classList.add("warn");
                  clock.title = "render warn:" + (label ? (" " + label + ":") : "") + " " + ((e && e.message) ? e.message : String(e));
                }
              }
            };
        const sliceParts = Array.isArray(raw.parts) ? raw.parts : [];
        const sliceHas = function (name) { return sliceParts.indexOf(name) >= 0; };
        const partPaint = function (name) { return sliceHas(name) && !fpHits[name]; };
        /* Card/list paints only when this poll requested that book - avoids re-binding
           every todo/mail/score body into the DOM on seats-only or mail-only polls.
           Fingerprint hit (empty-on-match) also skips paint for that part. */
        safe(function () { strip(d); }, "strip");
        try { wallFillStripCounts(); } catch (eStripFill) {}
        safe(function () { paintHero(d); }, "hero");
        safe(function () { paintKpiBanner(d); }, "kpi-banner");
        safe(function () { paintLeftoverBanner(d); }, "leftover");
        if (partPaint("todos") || partPaint("trees")) {
          if (typeof wallEnsureDomain === "function") await wallEnsureDomain("todo");
          if (!wallTickGenAlive(tickGen)) return;
          safe(function () { board(d); }, "jobs");
          safe(function () { paintPlan(d); }, "plan");
          safe(function () { issues(d); }, "plan");
        }
        if (partPaint("watchers")) safe(function () { paintWatchers(d); }, "watch");
        safe(function () { wire(d); }, "wire");
        if (partPaint("mail")) safe(function () { mail(d); }, "mail");
        safe(function () { stations(d); }, "stations");
        const hereStale = wallHereNeedsPaint(pickKey, d);
        if (partPaint("agents") || partPaint("holds") || partPaint("events") || hereStale) {
          safe(function () { agents(d); }, "session");
          safe(function () { paintSessionWire(d); }, "session-wire");
          /* board() owns #here (SESSION glance); agents-only polls must still paint it. */
          safe(function () { board(d, { hereOnly: true }); }, "session-here");
        }
        if (partPaint("scores")) safe(function () { cards(d); }, "scorecards");
        try {
          const glance = floorGlanceFromFloor(d);
          floorGlanceCache = glance;
          paintFloorView(glance);
          const floorOn = document.getElementById("pane-floor");
          if (floorOn && floorOn.classList.contains("on")) ensureFloorPaint();
          const mailOn = document.getElementById("pane-mail");
          if (mailOn && mailOn.classList.contains("on")) {
            if (typeof wallEnsureDomain === "function") await wallEnsureDomain("mail");
            if (!wallTickGenAlive(tickGen)) return;
            /* Wave 3: sliceHas(mail) already called mail(d); chrome-only avoids 2nd/3rd DOM rebuild. */
            /* chromeOnly when tick painted mail OR fp-hit kept prior mail DOM */
            ensureMailPaint(sliceHas("mail") ? { chromeOnly: true } : undefined);
          }
          const scoreOn = document.getElementById("pane-score");
          if (scoreOn && scoreOn.classList.contains("on")) {
            if (typeof wallEnsureDomain === "function") await wallEnsureDomain("score");
            if (!wallTickGenAlive(tickGen)) return;
            ensureScorePaint();
          }
          const todoOn = document.getElementById("pane-todo");
          if (todoOn && todoOn.classList.contains("on") && typeof wallEnsureDomain === "function") {
            await wallEnsureDomain("todo");
            if (!wallTickGenAlive(tickGen)) return;
          }
        } catch (eFloorTick) {
          if (clock) {
            clock.classList.add("warn");
            clock.title = "render warn: floor/mail/score " + ((eFloorTick && eFloorTick.message) ? eFloorTick.message : String(eFloorTick));
          }
        }
        /* drop checking overlay only after confirmed paint (or skip) finished. */
        if (wallTickGenAlive(tickGen)) {
          try { wallClearActivePaneOverlay(); } catch (eOv1) {}
        }
        enhanceTables(document);
        markOverflow();
        requestAnimationFrame(() => { try { markOverflow(); } catch (eMore) {} });
        paintWallNav();
        try { await checkWallAsset(); } catch (eAsset) {}
      } catch (ePaint) {
        if (clock) {
          clock.classList.add("warn");
          clock.title = "render warn: " + ((ePaint && ePaint.message) ? ePaint.message : String(ePaint));
        }
      }
    }
    document.addEventListener("click", ev => {
      const v = ev.target.closest(".tile-v");
      if (!v) return;
      copyText(v.innerText);
      v.classList.add("copied");
      setTimeout(() => v.classList.remove("copied"), 600);
    });
    /* lean list + detail-on-open (Wall contract card rule-lean-rows: mill todo wall-contract rule-lean-rows).
     * List/poll paints snippets (body/doing/detail <=256 + *_trunc flags).
     * On human open of a truncated mail/todo: GET detail, merge into local
     * _floor row (drop trunc flags), re-paint that surface. GET-only. */
    function wallMailIsTrunc(m) {
      return !!(m && m.body_trunc === true);
    }
    function wallTodoIsTrunc(r) {
      return !!(r && r.detail_trunc === true);
    }
    const _wallLeanDetailInflight = Object.create(null);
    function wallOpenMailIfTrunc() { return wallLazyCall("mailPaint", "wallOpenMailIfTrunc", wallOpenMailIfTrunc, arguments); }
    function wallOpenTodoIfTrunc() { return wallLazyCall("todoPaint", "wallOpenTodoIfTrunc", wallOpenTodoIfTrunc, arguments); }
    try {
      window.wallOpenMailIfTrunc = wallOpenMailIfTrunc;
      window.wallOpenTodoIfTrunc = wallOpenTodoIfTrunc;
      window.wallMailIsTrunc = wallMailIsTrunc;
      window.wallTodoIsTrunc = wallTodoIsTrunc;
    } catch (eWinLean) {}

    /* parts=events infinite scroll (Builder next fix) + floor/activity scroll.
     * floor/activity infinite scroll + scrollable translucent Checking.
     * Checking overlay: translucent over last-good; opaque when pane empty.
     * translucent Checking overlay: last-good visible under semi-transparent backdrop.
     * reuse in-flight: leave->return mid-fetch keeps same request; Checking until settle.
     * absorb off-pane: stale-gen still commits last-good for next visit (live pane untouched).
     * fp-before-paint: opaque Checking overlay; no DOM overwrite until fp confirms.
     * tab-switch generation guard (stale tick/early-paint no-op; never blank).
     * keep prior pane+theme on subtab leave/return (never blank).
     * limit+cursor infinite scroll (Wall contract card rule-paging: mill todo wall-contract rule-paging).
     * First poll: ?limit=50. Near-bottom: if next, fetch ?limit=50&cursor=, append, keep trunc. */
    /* floor parts + /api/activity + events infinite scroll (Wall contract card rule-paging: mill todo wall-contract rule-paging).
     * Kinds: mailbox, todos (v1), agents, scores, holds, watchers, activity, events.
     * tree-mail / tree-todo + parent_id expand.
     * First poll: ?limit=50. Near-bottom: ?limit=50&cursor=, append, keep trunc / last-good. */
    const _wallListNext = { mailbox: null, todos: null, agents: null, scores: null, holds: null, watchers: null, activity: null, events: null, "tree-mail": null, "tree-todo": null, trees: null };
    const _wallListInflight = { mailbox: null, todos: null, agents: null, scores: null, holds: null, watchers: null, activity: null, events: null, "tree-mail": null, "tree-todo": null, trees: null };
    const _wallTreeExpandNext = Object.create(null);
    const _wallTreeExpandInflight = Object.create(null);
    const WALL_LIST_KINDS = { mailbox: 1, todos: 1, agents: 1, scores: 1, holds: 1, watchers: 1, activity: 1, events: 1, names: 1, "tree-mail": 1, "tree-todo": 1, trees: 1 };
    function wallRememberListNext(kind, json) {
      if (!WALL_LIST_KINDS[kind]) return;
      if (!json || typeof json !== "object") return;
      const nxt = json.next;
      _wallListNext[kind] = (nxt == null || nxt === "") ? null : String(nxt);
    }
    function wallDedupeAppend(dst, rows, getKey) {
      if (!Array.isArray(dst)) dst = [];
      if (!Array.isArray(rows) || !rows.length) return dst;
      const keyFn = (typeof getKey === "function") ? getKey : function (r) { return r && r.id; };
      const seen = Object.create(null);
      for (let i = 0; i < dst.length; i++) {
        const id = keyFn(dst[i]);
        if (id != null && id !== "") seen[String(id)] = true;
      }
      for (let j = 0; j < rows.length; j++) {
        const row = rows[j];
        if (!row) continue;
        const id = keyFn(row);
        if (id != null && id !== "" && seen[String(id)]) continue;
        if (id != null && id !== "") seen[String(id)] = true;
        dst.push(row);
      }
      return dst;
    }
    function wallTreeNodeKey(n) {
      return String((n && n.type) || "").toLowerCase() + ":" + String((n && n.id) || "");
    }
    function wallMergeTreesForests(dstTrees, srcTrees) {
      /* Merge progressive tree pages: forest by name; nodes dedupe type:id (nest-set order append).
       * A later page refreshes a node already loaded and keeps nodes that page does not repeat. */
      let dst = Array.isArray(dstTrees) ? dstTrees.slice() : [];
      (srcTrees || []).forEach(function (st) {
        if (!st || typeof st !== "object") return;
        const name = String(st.name || "");
        let forest = null;
        for (let i = 0; i < dst.length; i++) {
          if (String((dst[i] && dst[i].name) || "") === name) { forest = dst[i]; break; }
        }
        if (!forest) {
          forest = { name: name, hidden: !!st.hidden, nodes: [] };
          dst.push(forest);
        }
        if (st.hidden != null) forest.hidden = !!st.hidden;
        const incoming = Array.isArray(st.nodes) ? st.nodes : [];
        const have = Array.isArray(forest.nodes) ? forest.nodes.slice() : [];
        const index = Object.create(null);
        for (let i = 0; i < have.length; i++) index[wallTreeNodeKey(have[i])] = i;
        const fresh = [];
        for (let j = 0; j < incoming.length; j++) {
          const node = incoming[j];
          if (!node) continue;
          const key = wallTreeNodeKey(node);
          const at = index[key];
          if (at != null) have[at] = node;
          else fresh.push(node);
        }
        forest.nodes = wallDedupeAppend(have, fresh, wallTreeNodeKey);
      });
      return dst;
    }
    function wallAppendTreesPage(json, kind) {
      if (!json || !Array.isArray(json.trees)) return false;
      const d = window._floor;
      if (!d) return false;
      d.trees = wallMergeTreesForests(Array.isArray(d.trees) ? d.trees : [], json.trees);
      const k = kind || "trees";
      wallRememberListNext(k, json);
      try {
        if (_floorBook && typeof _floorBook === "object") _floorBook.trees = d.trees;
      } catch (eBook) {}
      return true;
    }
    function wallActiveTreeKind() {
      /* Which progressive tree stream the active pane owns. */
      try {
        const tabBtn = document.querySelector("nav.tabs button.on");
        const tab = (tabBtn && tabBtn.dataset.tab) || "";
        if (tab === "mail" && typeof mailView !== "undefined" && mailView === "rooms") return "tree-mail";
        if (tab === "jobs") return "tree-todo";
      } catch (eTab) {}
      return null;
    }
    function wallFetchTreeExpand() { return wallLazyCall("listsPaint", "wallFetchTreeExpand", wallFetchTreeExpand, arguments); }
    function wallFetchListNextPage() { return wallLazyCall("listsPaint", "wallFetchListNextPage", wallFetchListNextPage, arguments); }
    function wallScrollNearBottom(el) {
      if (!el) return false;
      const ch = el.clientHeight;
      if (ch < 16) return false;
      return el.scrollTop + ch >= el.scrollHeight - 48;
    }
    function wallWireListInfiniteScroll() {
      const bind = function (el, kind) {
        if (!el || el._wallPageScroll) return;
        el._wallPageScroll = true;
        el.addEventListener("scroll", function () {
          if (!wallScrollNearBottom(el)) return;
          let k = kind;
          /* SESSION History uses #wire-log with parts=events; otherwise activity. */
          if (kind === "activity-or-events") {
            const histOn = document.querySelector('[data-session-mode="history"].on');
            k = histOn ? "events" : "activity";
          }
          /* tree scroll hosts only page when that tree pane is active. */
          if (kind === "tree-mail" || kind === "tree-todo") {
            const active = wallActiveTreeKind();
            if (active !== kind) return;
          }
          try { wallFetchListNextPage(k); } catch (ePage) {}
        }, { passive: true });
      };
      try {
        document.querySelectorAll(".mail-col").forEach(function (c) { bind(c, "mailbox"); });
        bind(document.getElementById("mail"), "mailbox");
        bind(document.getElementById("mail-msg-col"), "mailbox");
        bind(document.getElementById("jobs-list"), "todos");
        document.querySelectorAll("#pane-todo .jobs-kanban-col .body").forEach(function (b) {
          bind(b, "todos");
        });
        /* progressive trees outline / mail rooms nest near-bottom -> tree next. */
        bind(document.getElementById("jobs-outline"), "tree-todo");
        bind(document.getElementById("mail"), "tree-mail");
        bind(document.getElementById("mail-msg-col"), "tree-mail");
        /* dense panes incl. events. */
        bind(document.getElementById("here"), "agents");
        bind(document.getElementById("stations"), "holds");
        bind(document.getElementById("watchers"), "watchers");
        bind(document.getElementById("score-desk-table"), "scores");
        bind(document.getElementById("score-core"), "scores");
        bind(document.getElementById("wire-log"), "activity-or-events");
        bind(document.getElementById("wire"), "events"); /* Wire body = parts=events scroll host */
      } catch (eBind) {}
    }

    try {
      window.wallFetchListNextPage = wallFetchListNextPage;
      window.wallRememberListNext = wallRememberListNext;
      window.wallWireListInfiniteScroll = wallWireListInfiniteScroll;
      window.wallAppendTreesPage = wallAppendTreesPage;
      window.wallFetchTreeExpand = wallFetchTreeExpand;
      window.wallActiveTreeKind = wallActiveTreeKind;
      window.wallMergeTreesForests = wallMergeTreesForests;
      window.wallShowPaneOverlay = wallShowPaneOverlay;
      window.wallClearPaneOverlay = wallClearPaneOverlay;
      window.wallPreserveThemeChrome = wallPreserveThemeChrome;
      window.wallRestoreActivePaneFromFloor = wallRestoreActivePaneFromFloor;
      window.wallLoadingOnly = wallLoadingOnly;
      window.wallBumpSwitchGen = wallBumpSwitchGen;
      window.wallSwitchGen = wallSwitchGen;
      window.wallSwitchGenAlive = wallSwitchGenAlive;
      window.wallBeginTickGen = wallBeginTickGen;
      window.wallTickGenAlive = wallTickGenAlive;
      window.wallPaneHasCheckOverlay = wallPaneHasCheckOverlay;
      window.wallCommitFloorBook = wallCommitFloorBook;
      window.wallPaintOffPaneLastGood = wallPaintOffPaneLastGood;
      window.wallAbsorbOffPaneResult = wallAbsorbOffPaneResult;
      window.wallTickInflight = wallTickInflight;
      window.wallShouldReuseInflight = wallShouldReuseInflight;
      window.wallReuseInflightForReturn = wallReuseInflightForReturn;
      window.wallClearReuseInflight = wallClearReuseInflight;
    } catch (eWinPage) {}
    try { wallWireListInfiniteScroll(); } catch (eWire0) {}

    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape") {
        const openHelp = document.querySelector(".help-box:not([hidden])");
        if (openHelp) {
          ev.preventDefault();
          const id = openHelp.getAttribute("data-help-id") || openHelp.id;
          if (window._helpBoxes && window._helpBoxes[id]) window._helpBoxes[id].setOpen(false);
          else openHelp.hidden = true;
        }
      }
    });
    /* lean: on open, if body_trunc / detail_trunc, fetch detail
     * and merge into local _floor then re-paint (Wall contract card rule-lean-rows: mill todo wall-contract rule-lean-rows). */
    document.addEventListener("click", ev => {
      const tr = ev.target.closest("#mail tr[data-mail-id]");
      if (tr) {
        const id = parseInt(tr.getAttribute("data-mail-id") || "0", 10);
        if (id) {
          try { wallOpenMailIfTrunc(id); } catch (eLeanMail) {}
        }
        return;
      }
      const roomMsg = ev.target.closest(".mail-room-msg[data-mail-id]");
      if (roomMsg) {
        const id = parseInt(roomMsg.getAttribute("data-mail-id") || "0", 10);
        if (id) {
          try { wallOpenMailIfTrunc(id); } catch (eLeanRoom) {}
        }
        return;
      }
      if (ev.target.closest("button, a, input, select, textarea")) return;
      const todoEl = ev.target.closest("[data-todo-id]");
      if (!todoEl) return;
      const tid = parseInt(todoEl.getAttribute("data-todo-id") || "0", 10);
      if (tid) {
        const same = String(_todoDetailId) === String(tid);
        _todoDetailId = same ? "" : String(tid);
        try {
          if (window._floor) {
            board(window._floor);
            paintPlan(window._floor);
          }
        } catch (eOpenCard) {}
        if (!same) {
          try { wallOpenTodoIfTrunc(tid); } catch (eLeanTodo) {}
          try { wallDoingTrail(); } catch (eTrail) {}
        }
      }
    });
    /* HELP_BOX component: one pattern, different copy slots */
    window._helpBoxes = window._helpBoxes || {};
    /* WALL_UI_LIB_POPUP: thin wrapper -> wallMountHelpBox */
    function mountHelpBox(cfg) {
      if (typeof wallMountHelpBox === "function") return wallMountHelpBox(cfg);
      console.warn("wallMountHelpBox missing");
      return null;
    }
    window.mountHelpBox = mountHelpBox;
    mountHelpBox({
      id: "session",
      box: "session-help-box",
      reopen: "session-help-reopen",
      dismiss: "session-help-dismiss",
      storageKey: "factory-session-help",
      defaultOn: false,
    });
    mountHelpBox({
      id: "jobs",
      box: "jobs-help-box",
      reopen: "jobs-help-reopen",
      dismiss: "jobs-help-dismiss",
      storageKey: "factory-jobs-help",
      defaultOn: false,
    });
    mountHelpBox({
      id: "floor",
      box: "floor-help-box",
      reopen: "floor-help-reopen",
      dismiss: "floor-help-dismiss",
      storageKey: "factory-floor-help",
      defaultOn: false,
    });
    mountHelpBox({
      id: "score",
      box: "score-help-box",
      reopen: "score-help-reopen",
      dismiss: "score-help-dismiss",
      storageKey: "factory-score-help",
      defaultOn: false,
    });
    mountHelpBox({
      id: "mail",
      box: "mail-help-box",
      reopen: "mail-help-reopen",
      dismiss: "mail-help-dismiss",
      storageKey: "factory-mail-help",
      defaultOn: false,
    });
    (function wireAgentsToggle() {
      const sec = document.getElementById("sec-agents");
      const btn = document.getElementById("agents-toggle");
      if (!sec || !btn) return;
      const KEY = "factory-agents-open";
      function setOpen(on) {
        sec.classList.toggle("collapsed", !on);
        btn.setAttribute("aria-expanded", on ? "true" : "false");
        btn.textContent = on ? "hide" : "show";
        try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (e) {}
      }
      let want = false;
      try { want = localStorage.getItem(KEY) === "on"; } catch (e) {}
      setOpen(want);
      btn.addEventListener("click", () => setOpen(sec.classList.contains("collapsed")));
    })();

    (function wireTextMode() {
      const KEY = "factory-text-mode";
      const OLD = "factory-todo-text";
      function tabOf(name) {
        const n = String(name || "");
        if (n === "stations" || n === "leases") return "session";
        if (n === "plan" || n === "backlog" || n === "board" || n === "issues" || n === "todo") return "jobs";
        if (n === "scorecards") return "score";
        return n || "session";
      }
      function currentTab() {
        const on = document.querySelector("nav.tabs button.on");
        return tabOf((on && on.dataset.tab) || (location.hash || "").replace("#", "") || "session");
      }
      function loadAll() {
        let o = {};
        try { o = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { o = {}; }
        if (!o.jobs) {
          try {
            const old = localStorage.getItem(OLD);
            if (old) o.jobs = old;
          } catch (e) {}
        }
        return o;
      }
      function save(tab, m) {
        const o = loadAll();
        o[tab] = m;
        try { localStorage.setItem(KEY, JSON.stringify(o)); } catch (e) {}
      }
      function apply(mode, tab) {
        const m = (mode === "wrap" || mode === "overflow") ? mode : "clip";
        const t = tabOf(tab || currentTab());
        document.body.setAttribute("data-text-mode", m);
        document.querySelectorAll(".pane").forEach(p => p.setAttribute("data-todo-text", m));
        document.querySelectorAll(".tbl-wrap").forEach(w => {
          w.classList.toggle("cell-wrap", m === "wrap");
          const tbl = w.querySelector("table");
          if (tbl && typeof layoutTableCols === "function") layoutTableCols(tbl, w);
        });
        document.querySelectorAll("#text-mode button[data-todo-text]").forEach(b => {
          b.classList.toggle("on", b.getAttribute("data-todo-text") === m);
        });
        save(t, m);
      }
      window.applyTextMode = apply;
      window.syncTextModeForTab = function (name) {
        const t = tabOf(name || currentTab());
        const o = loadAll();
        apply(o[t] || "wrap", t);
      };
      document.querySelectorAll("#text-mode button[data-todo-text]").forEach(b => {
        b.addEventListener("click", () => apply(b.getAttribute("data-todo-text"), currentTab()));
      });
      window.syncTextModeForTab(currentTab());
    })();
    (function wireTickerToggle() {
      const KEY = "factory-ticker";
      function apply(on) {
        document.body.classList.toggle("ticker-off", !on);
        document.querySelectorAll("#ticker-toggle button[data-ticker]").forEach(b => {
          b.classList.toggle("on", (b.getAttribute("data-ticker") === "on") === on);
        });
        const more = document.getElementById("ticker-more-btn");
        if (more) more.textContent = on ? "Ticker off" : "Ticker on";
        try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (e) {}
      }
      window.applyTicker = apply;
      const box = document.getElementById("ticker-toggle");
      if (box) {
        box.addEventListener("click", ev => {
          const b = ev.target.closest("button[data-ticker]");
          if (b) apply(b.getAttribute("data-ticker") !== "off");
        });
      }
      const moreBtn = document.getElementById("ticker-more-btn");
      if (moreBtn) {
        moreBtn.addEventListener("click", () => {
          apply(document.body.classList.contains("ticker-off"));
        });
      }
      let on = true;
      try { on = localStorage.getItem(KEY) !== "off"; } catch (e) {}
      apply(on);
    })();
    (function wireThemePref() {
      /* Auto resolves via matchMedia -> data-theme light|dark.
         data-theme-pref keeps auto|light|dark. CSS still keys the palette off
         data-theme. Chrome treats a single root color-scheme as the OS, so the
         read forces light dark first. Auto leaves that inline in place so the
         change listener keeps tracking the OS. Light or dark clears it. */
      const KEY = "factory-theme";
      function systemTheme() {
        const root = document.documentElement;
        const prev = root.style.colorScheme;
        const prevTheme = root.getAttribute("data-theme");
        try {
          root.removeAttribute("data-theme");
          root.style.colorScheme = "light dark";
          void root.offsetWidth;
          const q = window.matchMedia("(prefers-color-scheme: dark)");
          return (q && q.matches) ? "dark" : "light";
        } catch (e) {
          return "dark";
        } finally {
          if (prevTheme) root.setAttribute("data-theme", prevTheme);
          if (prev) root.style.colorScheme = prev;
          else root.style.removeProperty("color-scheme");
        }
      }
      function apply(pref) {
        const p = (pref === "light" || pref === "dark") ? pref : "auto";
        const resolved = (p === "auto") ? systemTheme() : p;
        const root = document.documentElement;
        root.setAttribute("data-theme-pref", p);
        root.setAttribute("data-theme", resolved);
        if (p === "auto") root.style.colorScheme = "light dark";
        else root.style.removeProperty("color-scheme");
        document.querySelectorAll("#theme-pref button[data-theme-pref]").forEach(b => {
          b.classList.toggle("on", b.getAttribute("data-theme-pref") === p);
        });
        try { localStorage.setItem(KEY, p); } catch (e) {}
      }
      const box = document.getElementById("theme-pref");
      if (box) {
        box.addEventListener("click", ev => {
          const b = ev.target.closest("button[data-theme-pref]");
          if (b) apply(b.getAttribute("data-theme-pref"));
        });
      }
      let pref = "auto";
      try { pref = localStorage.getItem(KEY) || "auto"; } catch (e) {}
      apply(pref);
      if (typeof window.matchMedia === "function") {
        let mql = null;
        try { mql = window.matchMedia("(prefers-color-scheme: dark)"); } catch (eQ) { mql = null; }
        if (mql) {
          const onOsTheme = function () {
            let cur = "auto";
            try { cur = localStorage.getItem(KEY) || "auto"; } catch (eC) {}
            if (cur !== "light" && cur !== "dark") apply("auto");
          };
          if (typeof mql.addEventListener === "function") mql.addEventListener("change", onOsTheme);
          else if (typeof mql.addListener === "function") mql.addListener(onOsTheme);
        }
      }
    })();
    (function wireRailToggle() {
      const KEY = "factory-rail";
      const btn = document.getElementById("rail-toggle");
      function apply(narrow, persist) {
        document.body.classList.toggle("rail-narrow", !!narrow);
        if (btn) {
          btn.textContent = narrow ? ">" : "<";
          btn.setAttribute("aria-expanded", narrow ? "false" : "true");
          btn.title = narrow ? "Expand the rail" : "Narrow the rail";
        }
        if (persist) {
          try { localStorage.setItem(KEY, narrow ? "narrow" : "wide"); } catch (e) {}
        }
      }
      if (btn) btn.addEventListener("click", () => apply(!document.body.classList.contains("rail-narrow"), true));
      let stored = "";
      try { stored = localStorage.getItem(KEY) || ""; } catch (e) {}
      let narrow = stored === "narrow";
      if (stored !== "wide" && stored !== "narrow") {
        try { narrow = window.matchMedia("(max-width: 720px)").matches; } catch (eM) {}
      }
      apply(narrow, false);
    })();
    (function wireSkinnyPanes() {
      function wire(key, btnId, rootEl, openClass, titleOpen, titleShut) {
        const btn = document.getElementById(btnId);
        if (!rootEl) return;
        function apply(open, persist) {
          rootEl.classList.toggle(openClass, !!open);
          if (btn) {
            btn.textContent = open ? "<" : ">";
            btn.setAttribute("aria-expanded", open ? "true" : "false");
            btn.title = open ? titleOpen : titleShut;
          }
          if (persist) {
            try { localStorage.setItem(key, open ? "wide" : "narrow"); } catch (e) {}
          }
        }
        if (btn) btn.addEventListener("click", function () {
          apply(!rootEl.classList.contains(openClass), true);
        });
        let open = false;
        try { open = localStorage.getItem(key) === "wide"; } catch (e) {}
        apply(open, false);
      }
      wire("factory-mail-dst", "mail-dst-toggle", document.getElementById("mail-browser"), "dst-open", "Narrow rooms", "Expand rooms");
      wire("factory-mail-src", "mail-src-toggle", document.getElementById("mail-browser"), "src-open", "Narrow party", "Expand party");
      wire("factory-here-desk", "here-desk-toggle", document.getElementById("here-split"), "desk-open", "Narrow the desk", "Expand the desk");
      wire("factory-score-show", "score-show-toggle", document.getElementById("pane-score"), "show-open", "Narrow scores to show", "Expand scores to show");
    })();
    try { wirePaneCopy(); } catch (eCopy) {}
    (function wireTodoKanban() {
      const pane = document.getElementById("pane-todo") || document.getElementById("pane-jobs");
      const row = document.getElementById("jobs-kanban");
      if (!pane || !row) return;
      const KEY_W = "factory-todo-col-w";
      const KEY_C = "factory-todo-col-c";
      const KEY_T = "factory-todo-text"; /* migrated into factory-text-mode.jobs */
      function loadW() {
        try { return JSON.parse(localStorage.getItem(KEY_W) || "{}"); } catch (e) { return {}; }
      }
      function saveW(w) {
        try { localStorage.setItem(KEY_W, JSON.stringify(w)); } catch (e) {}
      }
      function loadC() {
        try { return JSON.parse(localStorage.getItem(KEY_C) || "{}"); } catch (e) { return {}; }
      }
      function saveC(c) {
        try { localStorage.setItem(KEY_C, JSON.stringify(c)); } catch (e) {}
      }
      function applyText(mode) {
        if (typeof window.applyTextMode === "function") window.applyTextMode(mode, "jobs");
        else {
          const m = (mode === "wrap" || mode === "overflow") ? mode : "clip";
          pane.setAttribute("data-todo-text", m);
        }
      }
      function applyCols() {
        const w = loadW();
        const c = loadC();
        const tracks = [];
        row.querySelectorAll(".jobs-kanban-col").forEach(col => {
          const id = col.getAttribute("data-col") || col.id;
          const collapsed = !!c[id];
          col.classList.toggle("collapsed", collapsed);
          col.style.flex = "";
          col.style.width = "";
          const btn = col.querySelector(".col-collapse");
          if (btn) {
            btn.textContent = collapsed ? ">" : "<";
            btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
          }
          if (collapsed) tracks.push("1.7rem");
          else if (w[id]) tracks.push("minmax(8rem," + Math.max(128, w[id]) + "px)");
          else tracks.push(window.matchMedia("(max-width: 720px)").matches ? "minmax(12rem,1fr)" : "minmax(0,1fr)");
        });
        if (tracks.length) {
          row.style.display = "grid";
          row.style.setProperty("grid-template-columns", tracks.join(" "), "important");
          row.style.gridAutoFlow = "column";
        }
      }
      row.querySelectorAll(".col-collapse").forEach(btn => {
        btn.addEventListener("click", () => {
          const col = btn.closest(".jobs-kanban-col");
          if (!col) return;
          const id = col.getAttribute("data-col") || col.id;
          const c = loadC();
          const w = loadW();
          c[id] = !c[id];
          if (c[id]) delete w[id];
          const openIds = [...row.querySelectorAll(".jobs-kanban-col")].map(col => col.getAttribute("data-col") || col.id).filter(k => !c[k]);
          if (openIds.length && openIds.every(k => w[k])) {
            openIds.forEach(k => { delete w[k]; });
          }
          saveC(c);
          saveW(w);
          applyCols();
        });
      });
      row.querySelectorAll(".jobs-col-gutter").forEach(g => {
        g.addEventListener("mousedown", ev => {
          ev.preventDefault();
          const col = g.closest(".jobs-kanban-col");
          if (!col || col.classList.contains("collapsed")) return;
          const id = col.getAttribute("data-col") || col.id;
          const startX = ev.clientX;
          const startW = col.getBoundingClientRect().width;
          function move(e) {
            const nw = Math.max(128, startW + (e.clientX - startX));
            const map = loadW();
            map[id] = Math.round(nw);
            saveW(map);
            applyCols();
          }
          function up() {
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", up);
          }
          document.addEventListener("mousemove", move);
          document.addEventListener("mouseup", up);
        });
      });
      applyCols();
    })();

    (function wireSessionMode() {
      const hereSec = document.getElementById("sec-here");
      const hereEl = document.getElementById("here");
      const histEl = document.getElementById("session-wire");
      const leaseEl = document.getElementById("sec-leases");
      function apply(mode) {
        const m = (mode === "stations") ? "leases" : (mode || "now");
        const hist = m === "history";
        const leases = m === "leases";
        const watch = m === "watch";
        const now = !hist && !leases && !watch;
        const watchEl = document.getElementById("sec-watch");
        if (hereSec) hereSec.hidden = !now;
        if (hereEl) hereEl.hidden = !now;
        if (histEl) histEl.hidden = !hist;
        if (leaseEl) leaseEl.hidden = !leases;
        if (watchEl) watchEl.hidden = !watch;
        const meta = document.getElementById("session-meta");
        const leaseSub = document.getElementById("lease-sub");
        const wireFilters = document.querySelector("#session-meta .wire-filters");
        if (meta) meta.hidden = !hist && !leases;
        if (wireFilters) wireFilters.hidden = !hist;
        if (leaseSub) leaseSub.hidden = !leases;
        document.querySelectorAll("[data-session-mode]").forEach(b => {
          b.classList.toggle("on", b.getAttribute("data-session-mode") === m);
        });
        /* SESSION subtoggles bump gen; keep prior DOM+theme; drop leftover cover only. */
        try { wallBumpSwitchGen(); } catch (eGenSess) {}
        try { wallShowPaneOverlay("pane-session", "Checking\u2026"); } catch (eOvSess) {}
        if (typeof wallReuseInflightForReturn === "function" && wallReuseInflightForReturn()) {
          /* reuse in-flight */
        } else if (typeof tick === "function") {
          tick(true);
        }
        if (hist && window._floor) paintSessionWire(window._floor);
        if (watch && window._floor) paintWatchers(window._floor);
        if (!leases && !watch && (location.hash === "#stations" || location.hash === "#leases" || location.hash === "#watch")) {
          location.hash = "session";
        }
        if (window._floor) {
          try { paintHero(window._floor); } catch (eHero) {}
        }
      }
      window.setSessionMode = apply;
      document.querySelectorAll("[data-session-mode]").forEach(b => {
        b.addEventListener("click", () => apply(b.getAttribute("data-session-mode")));
      });
      ["wire-desk", "wire-project"].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener("input", () => { if (window._floor) paintSessionWire(window._floor); });
        el.addEventListener("change", () => { if (window._floor) paintSessionWire(window._floor); });
      });
      const typeBox = document.getElementById("wire-type");
      if (typeBox) {
        typeBox.addEventListener("click", ev => {
          const b = ev.target.closest("button[data-wire-type]");
          if (!b) return;
          typeBox.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
          if (window._floor) paintSessionWire(window._floor);
        });
      }
      let start = "now";
      const hash = (location.hash || "").replace("#", "");
      if (hash === "stations" || hash === "leases") start = "leases";
      if (hash === "watch") start = "watch";
      apply(start);
    })();

    (function wireJobsViewToggle() {
      const pane = document.getElementById("pane-todo") || document.getElementById("pane-jobs");
      if (!pane) return;
      let v = "board";
      const hash = (location.hash || "").replace("#", "");
      if (hash === "trees" || hash === "plan" || hash === "nest") v = "nest";
      setJobsView(v);
    })();

    (function wireTodoStatusFilter() {
      const box = document.getElementById("todo-status-filter");
      if (!box) return;
      paintTodoStatusChips();
      box.addEventListener("click", ev => {
        const b = ev.target && ev.target.closest ? ev.target.closest("button[data-todo-status]") : null;
        if (!b) return;
        toggleTodoStatus(b.getAttribute("data-todo-status") || "");
      });
    })();

    (function wireDoneSpan() {
      const box = document.getElementById("todo-done-span");
      if (!box) return;
      paintDoneLabel(loadDoneSpan());
      box.addEventListener("click", ev => {
        const b = ev.target.closest("button[data-done-span]");
        if (!b) return;
        const v = b.getAttribute("data-done-span") || "24h";
        saveDoneSpan(v);
        paintDoneLabel(v);
        if (window._floor) board(window._floor);
      });
    })();

    (function wireTreesWindow() {
      /* All | 1 day | 1 week | 30 days on TODO Nest + MAIL Rooms. */
      paintTreesWindowChips();
      try { syncMailRoomsFiltersVisible(); } catch (eSync) {}
      function onChip(ev) {
        const b = ev.target.closest("button[data-trees-window]");
        if (!b || b.disabled) return;
        setTreesWindow(b.getAttribute("data-trees-window") || "all");
      }
      const todoBox = document.getElementById("todo-trees-window");
      const mailBox = document.getElementById("mail-trees-window");
      if (todoBox) todoBox.addEventListener("click", onChip);
      if (mailBox) mailBox.addEventListener("click", onChip);
      try {
        window.wallTreesWindowQuery = wallTreesWindowQuery;
        window.setTreesWindow = setTreesWindow;
        window.loadTreesWindow = loadTreesWindow;
      } catch (eExp) {}
    })();

    (function bindPlanChrome() {
      const cut = document.getElementById("plan-cut");
      const label = document.getElementById("plan-label");
      const search = document.getElementById("board-search");
      const rerender = () => {
        savePlanChrome();
        if (window._floor) issues(window._floor);
      };
      if (cut) cut.addEventListener("change", rerender);
      if (label) label.addEventListener("input", rerender);
      if (search) search.addEventListener("input", rerender);
      document.querySelectorAll("#plan-hist button").forEach(btn => {
        btn.addEventListener("click", ev => {
          ev.preventDefault();
          document.querySelectorAll("#plan-hist button").forEach(b => b.classList.toggle("on", b === btn));
          rerender();
        });
      });
      document.querySelectorAll("#plan-view-toggle button").forEach(btn => {
        btn.addEventListener("click", ev => {
          ev.preventDefault();
          document.querySelectorAll("#plan-view-toggle button").forEach(b => b.classList.toggle("on", b === btn));
          savePlanChrome();
          paintPlanView();
        });
      });
      restorePlanChrome();
      paintPlanView();
    })();

    /* WALL_PLAN_TAB: plan chrome bound in bindPlanChrome */
    const scorePane = document.getElementById("pane-score");
    if (scorePane && !scorePane.dataset.spendCut) {
      scorePane.dataset.spendCut = "1";
      scorePane.addEventListener("click", ev => {
        const btn = ev.target.closest("[data-spend-window]");
        if (!btn) return;
        spendWindow = btn.dataset.spendWindow || "all";
        if (window._floor) {
          cards(window._floor);
          enhanceTables(document.getElementById("pane-score"));
        }
      });
      scorePane.addEventListener("change", ev => {
        if (!ev.target || ev.target.id !== "spend-owner") return;
        spendOwner = ev.target.value || "";
        if (window._floor) {
          cards(window._floor);
          enhanceTables(document.getElementById("pane-score"));
        }
      });
    }
    paintBoardViewToggle();
    paintLayoutToggles();
    applyBoardView();
    window.addEventListener("resize", markOverflow);
    /* WALL_CUT6_WIRE + FLOOR_BOOT_FIX: mill prefs then land_tab / first tick */
    Promise.resolve()
      .then(function () { return loadWallPrefsCut6(); })
      .catch(function () { /* fail closed: pack defaults */ })
      .then(function () {
        if (window.__wallDeferStartTab) {
          window.__wallDeferStartTab = false;
          let start = (location.hash || "").replace("#", "");
          const savedTab = (typeof loadWallTab === "function") ? loadWallTab() : "session";
          const nestHash = (start === "nest" || start === "trees" || start === "plan");
          const savedIsTodo = ["jobs", "nest", "trees", "plan", "backlog", "board", "issues"].includes(savedTab);
          /* Old Nest boot stole #nest even on MAIL/SESSION; prefer saved strip tab when that happens. */
          if (nestHash && savedTab && !savedIsTodo) start = savedTab;
          else if (!start) start = savedTab || "session";
          if (start === "scorecards") start = "score"; /* SCORE_BOOT_FIX */
          if (["session", "jobs", "plan", "trees", "nest", "backlog", "board", "issues", "mail", "wire", "stations", "leases", "watch", "score", "guide", "glossary", "admin", "floor"].includes(start)) showTab(start);
          else showTab("session");
        }
        tick(true);
        wallStartFloorPoll();
      });
  
    /* ADMIN_INVITES */
    let adminLadder = localStorage.getItem("factory-admin-ladder") || "solo";
    function applyAdminLadder(name) {
      adminLadder = name || "solo";
      localStorage.setItem("factory-admin-ladder", adminLadder);
      document.querySelectorAll("#admin-ladder button").forEach(b => {
        b.classList.toggle("on", b.getAttribute("data-ladder") === adminLadder);
      });
      const keysPanel = document.getElementById("admin-keys-panel");
      if (keysPanel) keysPanel.classList.toggle("light", adminLadder === "solo");
      const oidc = document.getElementById("admin-oidc-panel");
      if (oidc) oidc.style.display = (adminLadder === "company" || adminLadder === "office") ? "" : (adminLadder === "solo" ? "none" : "");
      if (adminLadder === "solo" && oidc) oidc.style.display = "none";
      if (adminLadder === "company" && oidc) oidc.style.display = "";
      if (adminLadder === "office" && oidc) oidc.style.display = "";
    }
    function wallEnsureAdminInvites() {
      if (typeof wallEnsureModule === "function") return wallEnsureModule("adminInvite");
      if (typeof wallLoadScript === "function") return wallLoadScript("/admin/invite.js?v=wow281");
      return Promise.resolve();
    }
    function wallLoadAdminInvitesLazy() {
      return wallEnsureAdminInvites().then(function () {
        if (window.WallAdminInvites && typeof window.WallAdminInvites.ensureAndLoad === "function") {
          return window.WallAdminInvites.ensureAndLoad({
            esc: esc,
            applyAdminLadder: typeof applyAdminLadder === "function" ? applyAdminLadder : null,
            wallHumanReadonly: wallHumanReadonly
          });
        }
      });
    }
    (function wallAdminInviteShowTabHook() {
      const _showTabAdmin = showTab;
      showTab = function (name) {
        _showTabAdmin(name);
        if (name === "admin") wallLoadAdminInvitesLazy();
      };
    })();

/* WALL_UI_LIB_KEYS wire: desk-scoped shortcuts (Path A). Logic lives in lib/keys.js */
(function wallKeysBootHook() {
  function deskId() {
    try {
      var badge = JSON.parse(localStorage.getItem("factory-desk-badge") || "null");
      if (badge && (badge.name || badge.dst)) return String(badge.name || badge.dst).trim();
    } catch (e) {}
    try {
      return (localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || "builder").trim() || "builder";
    } catch (e2) {
      return "builder";
    }
  }
  function bind() {
    if (typeof wallKeysBind !== "function") return;
    wallKeysBind({
      deskId: deskId,
      showTab: typeof showTab === "function" ? showTab : null,
      refresh: typeof tick === "function" ? tick : null,
      openFilter: function () {
        var btn = document.getElementById("wall-add");
        if (btn) btn.click();
      },
      toggleFloorAgg: function () {
        if (typeof setFloorAgg !== "function") return;
        var next = (typeof floorAgg !== "undefined" && floorAgg === "desk") ? "workstation" : "desk";
        setFloorAgg(next);
      },
      toggleFloorMapTimeline: function () {
        if (typeof setFloorMode !== "function") return;
        var next = (typeof floorMode !== "undefined" && floorMode === "map") ? "timeline" : "map";
        setFloorMode(next);
      },
      mailNav: function (dir) {
        /* soft: click adjacent mail row if present */
        var on = document.querySelector("#mail tr[data-mail-id].on, #mail tr[data-mail-id].hi, #mail tr[data-mail-id]:focus");
        var rows = Array.prototype.slice.call(document.querySelectorAll("#mail tr[data-mail-id]"));
        if (!rows.length) return;
        var i = on ? rows.indexOf(on) : -1;
        var j = dir > 0 ? Math.min(rows.length - 1, i + 1) : Math.max(0, i < 0 ? 0 : i - 1);
        if (rows[j]) rows[j].click();
      },
      mailOpen: function () {
        var on = document.querySelector("#mail tr[data-mail-id].on, #mail tr[data-mail-id].hi");
        if (on) on.click();
      },
      mailMarkRead: function () {
        var on = document.querySelector("#mail tr[data-mail-id].on, #mail tr[data-mail-id].hi");
        if (on) on.click();
      }
    });
  }
  try { window.wallHumanReadonly = wallHumanReadonly; window.wallApplyHumanReadonly = wallApplyHumanReadonly; } catch (eWinRo) {}
  try {
    window.wallWelcomeBoot = wallWelcomeBoot;
    window.wallWelcomeHide = wallWelcomeHide;
    window.wallWelcomeDismiss = wallWelcomeDismiss;
    window.wallWelcomeShow = wallWelcomeShow;
    window.wallMintInvite = wallMintInvite;
    window.wallInviteGateOk = wallInviteGateOk;
    window.wallRefreshInviteCount = wallRefreshInviteCount;
    window.wallBuildInviteUrl = wallBuildInviteUrl;
  } catch (eWinW) {}
  function wallBootHumanReadonlyAndKeys() {
    try { wallApplyHumanReadonly(); } catch (eRoBoot) {}
    bind();
  }
  function wallBootWelcomeInvite() {
    try { wallWelcomeWire(); } catch (eWire172) {}
    try { wallWelcomeBoot(); } catch (eWBoot) {}
    /* page refresh gets the same seat_count refresh as strip() rebuilds. */
    try { wallRefreshInviteCount(); } catch (eCntBoot) {}
  }
  function wallBootReadonlyKeysWelcome() {
    wallBootHumanReadonlyAndKeys();
    wallBootWelcomeInvite();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wallBootReadonlyKeysWelcome);
  else wallBootReadonlyKeysWelcome();
})();

