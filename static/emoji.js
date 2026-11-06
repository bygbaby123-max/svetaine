/* Emocijų (emoji) mygtukas – įdeda emoji į žinutės lauką */
(function () {
  var EMOJIS = [
    "😀", "😂", "🤣", "😊", "😍", "😎", "🤔", "😅",
    "😉", "😁", "🥳", "😇", "🤪", "😭", "😢", "😡",
    "👍", "👎", "👏", "🙌", "🤝", "💪", "✌️", "🤞",
    "❤️", "🔥", "⭐", "🎉", "💯", "✨", "💥", "🏆",
    "😀", "😃", "😄", "😆", "🙃", "😘", "🥰", "😜",
    "🤗", "🤭", "🤫", "🫡", "🫰", "👀", "💀", "👻",
    "🐶", "🐱", "🦊", "🐻", "🐼", "🐸", "🦄", "🚀",
    "🍕", "🍔", "🍟", "🌮", "🍩", "🍰", "☕", "🧃",
    "⚽", "🏀", "🎮", "🎲", "🎯", "🎵", "🎸", "📸",
    "✅", "❌", "⚠️", "💡", "📌", "🔑", "🎁", "👑"
  ];

  function init() {
    var toggle = document.getElementById("emoji-toggle");
    var panel = document.getElementById("emoji-panel");
    var input = document.getElementById("chat-input");
    if (!toggle || !panel || !input) return;

    if (!panel.childElementCount) {
      EMOJIS.forEach(function (e) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "emoji-item";
        b.textContent = e;
        panel.appendChild(b);
      });
    }

    toggle.addEventListener("click", function (ev) {
      ev.preventDefault();
      panel.hidden = !panel.hidden;
    });

    panel.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t.classList || !t.classList.contains("emoji-item")) return;
      ev.preventDefault();
      var start = input.selectionStart || input.value.length;
      var end = input.selectionEnd || input.value.length;
      input.value = input.value.slice(0, start) + t.textContent + input.value.slice(end);
      var pos = start + t.textContent.length;
      input.focus();
      input.setSelectionRange(pos, pos);
      panel.hidden = true;
    });

    document.addEventListener("click", function (ev) {
      if (panel.hidden) return;
      if (!panel.contains(ev.target) && ev.target !== toggle) panel.hidden = true;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
