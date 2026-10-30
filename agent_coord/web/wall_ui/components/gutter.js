/* WALL_UI_COMPONENTS_GUTTER - shared split gutter drag (Floor + Score).
 * Path A extract from board.html duplicate applyPct/onMove/onUp.
 * SoR: wall-contract; wall_logic/gutter.py
 * Marker: WALL_UI_COMPONENTS_GUTTER
 *
 * wireSplitGutter({
 *   split, main, gutter, detail,   // HTMLElements
 *   storageKey,                    // localStorage key
 *   defaultPct,                    // number
 *   minMainPx, minDetailPx,        // pixel mins while dragging
 *   minPct, maxPct,                // percent clamp
 *   cssVar,                        // e.g. --floor-main-w
 *   applyDefaultIfEmpty,           // floor=true, score=false
 *   keyboard,                      // floor=true
 *   detailGapPx                    // floor uses 8; score 0
 * })
 */
(function (global) {
  "use strict";

  function clampPct(pct, minPct, maxPct, fallback) {
    var n = Number(pct);
    if (!isFinite(n)) n = fallback;
    if (n < minPct) n = minPct;
    if (n > maxPct) n = maxPct;
    return n;
  }

  function wireSplitGutter(opts) {
    if (!opts) return false;
    var split = opts.split;
    var main = opts.main;
    var gutter = opts.gutter;
    var detail = opts.detail;
    if (!split || !main || !gutter || !detail) return false;
    if (gutter._wired) return false;
    gutter._wired = true;

    var storageKey = opts.storageKey || "";
    var defaultPct = opts.defaultPct != null ? opts.defaultPct : 50;
    var minMainPx = opts.minMainPx != null ? opts.minMainPx : 160;
    var minDetailPx = opts.minDetailPx != null ? opts.minDetailPx : 200;
    var minPct = opts.minPct != null ? opts.minPct : 20;
    var maxPct = opts.maxPct != null ? opts.maxPct : 80;
    var cssVar = opts.cssVar || "";
    var applyDefaultIfEmpty = opts.applyDefaultIfEmpty !== false;
    var keyboard = !!opts.keyboard;
    var detailGapPx = opts.detailGapPx != null ? opts.detailGapPx : 0;

    function applyPct(pct) {
      var p = clampPct(pct, minPct, maxPct, defaultPct);
      if (cssVar) split.style.setProperty(cssVar, p + "%");
      main.style.width = p + "%";
      main.style.flex = "0 0 auto";
      detail.style.flex = "1 1 auto";
      return p;
    }

    try {
      var saved = storageKey ? localStorage.getItem(storageKey) : null;
      if (saved) applyPct(parseFloat(saved));
      else if (applyDefaultIfEmpty) applyPct(defaultPct);
    } catch (e) {
      if (applyDefaultIfEmpty) applyPct(defaultPct);
    }

    var dragging = false;
    function onMove(ev) {
      if (!dragging) return;
      var rect = split.getBoundingClientRect();
      var x = ev.clientX != null
        ? ev.clientX
        : (ev.touches && ev.touches[0] && ev.touches[0].clientX);
      if (x == null) return;
      var mainW = x - rect.left;
      var maxMain = rect.width - minDetailPx - detailGapPx;
      if (mainW < minMainPx) mainW = minMainPx;
      if (mainW > maxMain) mainW = maxMain;
      var pct = applyPct((mainW / rect.width) * 100);
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, String(Number(pct.toFixed ? pct.toFixed(1) : pct)));
        } catch (err) {}
      }
    }
    function onUp() {
      if (!dragging) return;
      dragging = false;
      split.classList.remove("resizing");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }
    gutter.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      dragging = true;
      split.classList.add("resizing");
      try { gutter.setPointerCapture(ev.pointerId); } catch (err) {}
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
    if (keyboard) {
      gutter.addEventListener("keydown", function (ev) {
        var cur = parseFloat((main.style.width || String(defaultPct)).replace("%", "")) || defaultPct;
        if (ev.key === "ArrowLeft") {
          var left = applyPct(cur - 2);
          if (storageKey) {
            try { localStorage.setItem(storageKey, String(left)); } catch (err) {}
          }
          ev.preventDefault();
        }
        if (ev.key === "ArrowRight") {
          var right = applyPct(cur + 2);
          if (storageKey) {
            try { localStorage.setItem(storageKey, String(right)); } catch (err) {}
          }
          ev.preventDefault();
        }
      });
    }
    return true;
  }

  global.wallWireSplitGutter = wireSplitGutter;
  global.wallClampSplitPct = clampPct;
  global.WALL_UI_COMPONENTS_GUTTER = "WALL_UI_COMPONENTS_GUTTER";
})(typeof window !== "undefined" ? window : globalThis);
