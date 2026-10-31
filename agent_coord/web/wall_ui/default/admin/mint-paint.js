/* WALL_UI_DEFAULT_ADMIN_MINT - split out of boot.js (#872).
 * Marker: WALL_UI_DEFAULT_ADMIN_MINT
 * Loads on first use through lib/lazy.js (MODULES.adminMint); boot.js keeps a stub for each entry.
 * Classic script on purpose: it shares boot.js globals (let/const state and functions),
 * and its function declarations replace the boot.js stubs.
 */


    /* Moved out of boot.js with the pane (#872, wall-contract rule-lazy-panes). */
    function wallResolveMintDesk(hint) {
      /* empty or still auto-default -> regenerate agent+10digits;
       * user-edited name -> trimmed as-is (no random append). */
      let bare = wallInviteDeskBare(hint || "");
      bare = bare.replace(/\s+/g, "-");
      if (!bare || wallIsAutoDefaultDesk(bare)) return wallFreshMintDesk();
      return bare;
    }
    function wallInviteUrlFromHub(hubUrl, desk, seat) {
      /* Prefer Hub invite_url origin when present; force root /welcome and the stored desk name. */
      const bare = wallInviteDeskBare(desk);
      const s = String(seat || "").trim();
      const hub = String(hubUrl || "").trim();
      if (hub && bare && s) {
        try {
          const abs = /^https?:\/\//i.test(hub);
          const u = new URL(hub, wallBaseOrigin() || "http://local.invalid");
          u.pathname = "/welcome";
          u.search = "";
          u.hash = "";
          u.searchParams.set("desk", bare);
          u.searchParams.set("seat", s);
          if (abs) return u.origin + u.pathname + u.search;
          return u.pathname + u.search;
        } catch (eNorm) {}
      }
      return wallBuildInviteUrl(bare, s);
    }
    function wallStubSeatToken() {
      const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
      let s = "";
      try {
        const arr = new Uint8Array(24);
        (window.crypto || crypto).getRandomValues(arr);
        for (let i = 0; i < arr.length; i++) s += alphabet[arr[i] % alphabet.length];
      } catch (eR) {
        s = "stub" + String(Date.now());
      }
      return s;
    }
    async function wallMintInvite(deskHint) {
      /* Human-readonly write exception: mint_seat only via HTTP (not CLI).
       * POST /api/admin/invites { action:"mint_seat", desk }. Stub only on 404.
       * each mint needs a fresh desk (Hub join no-steal / desk live).
       * invite URL uses the stored desk name.
       * empty/auto agent+10digits -> regenerate; user-edited name minted as-is. */
      const deskIn = document.getElementById("wall-welcome-desk");
      const hint = String(deskHint || (deskIn && deskIn.value) || "").trim();
      let desk = wallResolveMintDesk(hint);
      try { if (deskIn) deskIn.value = desk; } catch (eDeskFill) {}
      function applyMint(data, stub) {
        const rawDesk = (data && data.desk) || desk;
        const rawSeat = (data && data.seat) || "";
        const bare = wallInviteDeskBare(rawDesk) || desk;
        const hubUrl = String((data && data.invite_url) || "").trim();
        const url = hubUrl
          ? wallInviteUrlFromHub(hubUrl, bare, rawSeat)
          : wallBuildInviteUrl(bare, rawSeat);
        wallWelcomeSetInvite(url, bare, rawSeat);
        const note = document.getElementById("wall-welcome-invite-note");
        if (note) {
          note.textContent = stub
            ? "This office cannot make a seat URL yet."
            : ("Ready. " + bare);
        }
        return { invite_url: url, desk: bare, seat: rawSeat || "", stub: !!stub };
      }
      let human = "";
      let owner = "";
      try {
        human = localStorage.getItem("factory-human") || "";
        owner = human || localStorage.getItem("factory-desk") || localStorage.getItem("AGENT_COORD_OWNER") || "builder";
      } catch (eLs) {
        owner = "builder";
      }
      const seatBody = { action: "mint_seat", desk: desk, owner: owner };
      let status = 0;
      let data = null;
      try {
        const r = await fetch("/api/admin/invites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(seatBody),
        });
        status = r.status;
        try { data = await r.json(); } catch (eJ) { data = null; }
        if (r.ok && data && !data.error && (data.invite_url || (data.desk && data.seat))) {
          const out = applyMint(data, false);
          try { wallRefreshInviteCount(); } catch (eRef) {}
          return out;
        }
      } catch (eFetch) {
        status = 0;
      }
      /* desk already live -> one retry with fresh agent+10digits desk. */
      const errText = (data && data.error) ? String(data.error) : "";
      const liveCollide = status === 400 && /desk live|token required|no steal/i.test(errText);
      if (liveCollide) {
        desk = wallFreshMintDesk();
        try { if (deskIn) deskIn.value = desk; } catch (eDesk2) {}
        const seatBody2 = { action: "mint_seat", desk: desk, owner: owner };
        try {
          const r2 = await fetch("/api/admin/invites", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(seatBody2),
          });
          status = r2.status;
          try { data = await r2.json(); } catch (eJ2) { data = null; }
          if (r2.ok && data && !data.error && (data.invite_url || (data.desk && data.seat))) {
            const out = applyMint(data, false);
            try { wallRefreshInviteCount(); } catch (eRef2) {}
            return out;
          }
        } catch (eFetch2) {
          status = 0;
        }
      }
      /* Stub only when endpoint missing (404). Other errors surface in note. */
      if (status === 404) {
        const seat = wallStubSeatToken();
        return applyMint({ desk: desk, seat: seat, invite_url: wallBuildInviteUrl(desk, seat), status: "stub" }, true);
      }
      const note = document.getElementById("wall-welcome-invite-note");
      const err = (data && data.error) ? String(data.error) : ("mint_seat HTTP " + (status || "fail"));
      if (note) note.textContent = err;
      wallWelcomeFillJoin();
      return { invite_url: _wallInviteUrl || "", desk: desk, seat: _wallInviteSeat || "", stub: false, error: err };
    }
var WALL_UI_DEFAULT_ADMIN_MINT = "WALL_UI_DEFAULT_ADMIN_MINT";
