/* WALL_UI_LIB_POPUP - shared help-float / popup helpers (Path A).
 * Extract from board.html mountHelpBox / openMailPopup chrome.
 * SoR: wall-contract; tests/wall
 * Marker: WALL_UI_LIB_POPUP
 */
(function (global) {
  "use strict";

  function clampHelpPos(box, x, y) {
    var w = (box && box.offsetWidth) || 280;
    var hgt = (box && box.offsetHeight) || 200;
    var grip = 48;
    var iw = (typeof window !== "undefined" && window.innerWidth) || 800;
    var ih = (typeof window !== "undefined" && window.innerHeight) || 600;
    return {
      x: Math.min(iw - grip, Math.max(grip - w, x)),
      y: Math.min(ih - grip, Math.max(grip - hgt, y))
    };
  }

  function mountHelpBox(cfg) {
    if (!cfg || typeof document === "undefined") return null;
    var box = typeof cfg.box === "string" ? document.getElementById(cfg.box) : cfg.box;
    var reopen = typeof cfg.reopen === "string" ? document.getElementById(cfg.reopen) : cfg.reopen;
    var dismiss = typeof cfg.dismiss === "string" ? document.getElementById(cfg.dismiss) : cfg.dismiss;
    if (!box) return null;
    var storageKey = cfg.storageKey || ("factory-help-" + (cfg.id || box.id));
    var posKey = storageKey + "-pos";

    function setOpen(on) {
      box.hidden = !on;
      if (reopen) reopen.setAttribute("aria-expanded", on ? "true" : "false");
      try { localStorage.setItem(storageKey, on ? "on" : "off"); } catch (e) {}
    }
    function place(x, y) {
      var p = clampHelpPos(box, x, y);
      box.style.left = p.x + "px";
      box.style.top = p.y + "px";
      box.style.right = "auto";
    }
    function savePos() {
      var r = box.getBoundingClientRect();
      try { localStorage.setItem(posKey, JSON.stringify({ x: r.left, y: r.top })); } catch (e) {}
    }
    if (reopen) reopen.addEventListener("click", function () { setOpen(!!box.hidden); });
    if (dismiss) dismiss.addEventListener("click", function () { setOpen(false); });
    var want = false;
    try {
      var v = localStorage.getItem(storageKey);
      if (v === "on") want = true;
      else if (v === "off") want = false;
      else want = !!cfg.defaultOn;
    } catch (e) { want = !!cfg.defaultOn; }
    setOpen(want);
    try {
      var saved = JSON.parse(localStorage.getItem(posKey) || "null");
      if (saved && typeof saved.x === "number" && typeof saved.y === "number") place(saved.x, saved.y);
    } catch (e) {}
    (function drag() {
      var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
      var handle = box.querySelector("[data-help-drag]") || box;
      handle.addEventListener("pointerdown", function (ev) {
        if (ev.target.closest(".dismiss, a, button.jump, input, textarea")) return;
        dragging = true;
        box.classList.add("dragging");
        try { box.setPointerCapture(ev.pointerId); } catch (err) {}
        var r = box.getBoundingClientRect();
        sx = ev.clientX; sy = ev.clientY; ox = r.left; oy = r.top;
        ev.preventDefault();
      });
      box.addEventListener("pointermove", function (ev) {
        if (!dragging) return;
        place(ox + ev.clientX - sx, oy + ev.clientY - sy);
      });
      function stop() {
        if (!dragging) return;
        dragging = false;
        box.classList.remove("dragging");
        savePos();
      }
      box.addEventListener("pointerup", stop);
      box.addEventListener("pointercancel", stop);
      if (typeof window !== "undefined") {
        window.addEventListener("resize", function () {
          var r = box.getBoundingClientRect();
          place(r.left, r.top);
        });
      }
    })();
    var api = { setOpen: setOpen, place: place, box: box, id: cfg.id || box.id };
    global._helpBoxes = global._helpBoxes || {};
    global._helpBoxes[api.id] = api;
    if (box.id) global._helpBoxes[box.id] = api;
    return api;
  }

  function closeOpenHelpOnEscape(ev) {
    if (!ev || ev.key !== "Escape") return false;
    if (typeof document === "undefined") return false;
    var openHelp = document.querySelector(".help-box:not([hidden])");
    if (!openHelp) return false;
    ev.preventDefault();
    var id = openHelp.getAttribute("data-help-id") || openHelp.id;
    if (global._helpBoxes && global._helpBoxes[id]) global._helpBoxes[id].setOpen(false);
    else openHelp.hidden = true;
    return true;
  }

  global.wallMountHelpBox = mountHelpBox;
  global.wallClampHelpPos = clampHelpPos;
  global.wallCloseOpenHelpOnEscape = closeOpenHelpOnEscape;
  global.WALL_UI_LIB_POPUP = "WALL_UI_LIB_POPUP";
})(typeof window !== "undefined" ? window : globalThis);
