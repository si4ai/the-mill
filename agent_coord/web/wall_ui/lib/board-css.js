/* Apply the async board sheet without an inline handler (card 815). */
(function () {
  var link = document.getElementById("board-css");
  if (!link) return;
  function live() { link.media = "all"; }
  if (link.sheet) live();
  else link.onload = live;
})();
