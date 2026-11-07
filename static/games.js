/* ================================================================
   Žaidimai: viskas viename faile. Kiekvienas žaidimas užpildo
   #game-root pagal data-game atributą. Rezultatas siunčiamas į
   POST /games/<name>/score ir įrašomas į rezultatų lentelę.
   ================================================================ */
(function () {
  var root = document.getElementById("game-root");
  if (!root) return;

  var KEY = root.getAttribute("data-game");
  var startBtn = document.getElementById("game-start");
  var scoreEl = document.getElementById("game-score");
  var statusEl = document.getElementById("game-status");
  var form = document.getElementById("score-form");
  var scoreInput = document.getElementById("score-input");

  var stopCurrent = null;

  function setScore(n) { scoreEl.textContent = "Rezultatas: " + n; }
  function setStatus(t) { statusEl.textContent = t; }
  function clearRoot() { root.innerHTML = ""; }

  function el(tag, cls, parent, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  /* Rezultato įrašymas į lentelę */
  function finish(score, msg) {
    setScore(score);
    if (!window.GAME_LOGGED_IN) {
      setStatus("Žaidimas baigtas! Prisijungęs gali įrašyti rezultatą.");
      return;
    }
    setStatus("🏆 " + (msg || "Žaidimas baigtas!") + " Įrašoma...");
    scoreInput.value = String(score);
    var fd = new FormData(form);
    fetch(window.GAME_SCORE_URL, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var msg = "✅ Rezultatas įrašytas!";
        try {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var f = doc.querySelector(".flash");
          if (f && f.textContent) msg = "✅ " + f.textContent.trim();
        } catch (e) {}
        setStatus(msg);
        setTimeout(function () { location.reload(); }, 1700);
      })
      .catch(function () { setStatus("❌ Nepavyko įrašyti rezultato."); });
  }

  /* --------------------------------------------------- žaidimo laikas
     Užduočiai "žaisk X minučių": kas 30 sek. siunčiamas ping'as į
     POST /games/ping, kol žaidimas paleistas ir lapas matomas. */
  var playTimer = null;
  function startPlayTimer() {
    if (playTimer || !window.GAME_LOGGED_IN || !window.GAME_PING_URL) return;
    playTimer = setInterval(function () {
      if (document.hidden) return;
      fetch(window.GAME_PING_URL, { method: "POST", credentials: "same-origin" })
        .catch(function () {});
    }, 30000);
  }

  function launch(init) {
    if (stopCurrent) { try { stopCurrent(); } catch (e) {} }
    stopCurrent = null;
    clearRoot();
    setStatus("");
    setScore(0);
    stopCurrent = init() || null;
    startPlayTimer();
  }

  /* ---------------------------------------------------------- 2048 */
  function init2048() {
    var board = [], score = 0, dead = false, i;
    for (i = 0; i < 16; i++) board.push(0);
    var wrap = el("div", "g2048", root);
    var cells = [];
    for (i = 0; i < 16; i++) cells.push(el("div", "g2048-cell", wrap));

    function addRandom() {
      var free = [];
      for (var k = 0; k < 16; k++) if (!board[k]) free.push(k);
      if (!free.length) return;
      board[free[Math.floor(Math.random() * free.length)]] = Math.random() < 0.9 ? 2 : 4;
    }
    function render() {
      for (var k = 0; k < 16; k++) {
        cells[k].textContent = board[k] || "";
        cells[k].className = "g2048-cell v" + (board[k] || 0);
      }
      setScore(score);
    }
    function slide(line) {
      var arr = line.filter(function (v) { return v; });
      var out = [], gained = 0;
      for (var k = 0; k < arr.length; k++) {
        if (arr[k] === arr[k + 1]) { out.push(arr[k] * 2); gained += arr[k] * 2; k++; }
        else out.push(arr[k]);
      }
      while (out.length < 4) out.push(0);
      return { out: out, gained: gained };
    }
    function canMove() {
      for (var k = 0; k < 16; k++) {
        if (!board[k]) return true;
        if (k % 4 < 3 && board[k] === board[k + 1]) return true;
        if (k < 12 && board[k] === board[k + 4]) return true;
      }
      return false;
    }
    function move(dir) {
      if (dead) return;
      var before = board.join(","), gained = 0, lines = [], r, c, line;
      if (dir === "left" || dir === "right") {
        for (r = 0; r < 4; r++) {
          line = [];
          for (c = 0; c < 4; c++) line.push(board[r * 4 + c]);
          if (dir === "right") line.reverse();
          lines.push({ line: line, r: r, horiz: true, rev: dir === "right" });
        }
      } else {
        for (c = 0; c < 4; c++) {
          line = [];
          for (r = 0; r < 4; r++) line.push(board[r * 4 + c]);
          if (dir === "down") line.reverse();
          lines.push({ line: line, c: c, horiz: false, rev: dir === "down" });
        }
      }
      lines.forEach(function (L) {
        var res = slide(L.line);
        gained += res.gained;
        var row = res.out;
        if (L.rev) row = row.slice().reverse();
        for (var k = 0; k < 4; k++) {
          if (L.horiz) board[L.r * 4 + k] = row[k];
          else board[k * 4 + L.c] = row[k];
        }
      });
      if (board.join(",") !== before) {
        score += gained;
        addRandom();
        render();
        if (!canMove()) {
          dead = true;
          finish(score, "2048 baigtas!");
        }
      }
    }
    function onKey(e) {
      var map = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
      if (map[e.key]) { e.preventDefault(); move(map[e.key]); }
    }
    document.addEventListener("keydown", onKey);
    addRandom(); addRandom(); render();
    setStatus("Naudok rodykles ← ↑ → ↓");
    return function () { document.removeEventListener("keydown", onKey); };
  }

  /* ---------------------------------------------------------- Gyvatė */
  function initSnake() {
    var cv = el("canvas", "game-canvas", root);
    cv.width = 400; cv.height = 400;
    var ctx = cv.getContext("2d");
    var N = 20, CELL = 20;
    var snake = [{ x: 8, y: 10 }, { x: 7, y: 10 }, { x: 6, y: 10 }];
    var dir = { x: 1, y: 0 }, pending = { x: 1, y: 0 };
    var score = 0, dead = false;
    var apple = randomApple();

    function randomApple() {
      var p;
      do {
        p = { x: Math.floor(Math.random() * N), y: Math.floor(Math.random() * N) };
      } while (snake.some(function (s) { return s.x === p.x && s.y === p.y; }));
      return p;
    }
    function draw() {
      ctx.fillStyle = "#0d1220";
      ctx.fillRect(0, 0, 400, 400);
      ctx.fillStyle = "#ff5f6d";
      ctx.beginPath();
      ctx.arc(apple.x * CELL + 10, apple.y * CELL + 10, 8, 0, Math.PI * 2);
      ctx.fill();
      snake.forEach(function (s, i) {
        ctx.fillStyle = i === 0 ? "#7ee787" : "#3fb950";
        ctx.fillRect(s.x * CELL + 1, s.y * CELL + 1, CELL - 2, CELL - 2);
      });
      ctx.fillStyle = "#e6edf3";
      ctx.font = "16px sans-serif";
      ctx.fillText("Taškai: " + score, 10, 24);
    }
    function tick() {
      if (dead) return;
      dir = pending;
      var head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
      if (head.x < 0 || head.y < 0 || head.x >= N || head.y >= N ||
          snake.some(function (s) { return s.x === head.x && s.y === head.y; })) {
        dead = true;
        finish(score, "Gyvatė susidūrė!");
        return;
      }
      snake.unshift(head);
      if (head.x === apple.x && head.y === apple.y) {
        score += 10;
        setScore(score);
        apple = randomApple();
      } else snake.pop();
      draw();
    }
    function onKey(e) {
      var k = e.key.toLowerCase();
      var nd = null;
      if (k === "arrowleft" || k === "a") nd = { x: -1, y: 0 };
      else if (k === "arrowright" || k === "d") nd = { x: 1, y: 0 };
      else if (k === "arrowup" || k === "w") nd = { x: 0, y: -1 };
      else if (k === "arrowdown" || k === "s") nd = { x: 0, y: 1 };
      if (nd) {
        e.preventDefault();
        if (nd.x !== -dir.x || nd.y !== -dir.y) pending = nd;
      }
    }
    document.addEventListener("keydown", onKey);
    var timer = setInterval(tick, 120);
    draw();
    setStatus("Valdyk rodyklėmis arba WASD");
    return function () {
      clearInterval(timer);
      document.removeEventListener("keydown", onKey);
    };
  }

  /* ---------------------------------------------------------- Atmintis */
  function initMemory() {
    var all = ["🐶", "🐱", "🦊", "🐻", "🐼", "🐸", "🦄", "🚀", "🍕", "⚽", "🎮", "🌟"];
    var deck = shuffle(all.slice());
    var open = [], matched = {}, moves = 0, lock = false, found = 0;
    var grid = el("div", "mem-grid", root);

    deck.forEach(function (emoji, idx) {
      var card = el("button", "mem-card", grid);
      card.type = "button";
      card.textContent = "❓";
      card.addEventListener("click", function () {
        if (lock || matched[idx] || open.indexOf(idx) >= 0) return;
        card.textContent = emoji;
        card.classList.add("flipped");
        open.push(idx);
        if (open.length === 2) {
          moves++;
          setScore(Math.max(0, 1000 - moves * 10));
          var a = open[0], b = open[1];
          if (deck[a] === deck[b]) {
            matched[a] = matched[b] = true;
            open = [];
            found++;
            if (found === 6) {
              var sc = Math.max(100, 1000 - moves * 10);
              finish(sc, "Poros rastos per " + moves + " bandymų!");
            }
          } else {
            lock = true;
            setTimeout(function () {
              [a, b].forEach(function (i) {
                var c = grid.children[i];
                c.textContent = "❓";
                c.classList.remove("flipped");
              });
              open = [];
              lock = false;
            }, 700);
          }
        }
      });
    });
    setStatus("Atverk korteles ir rask poras");
    return null;
  }

  /* -------------------------------------------- Kryžiukai–nuliai */
  function initTicTacToe() {
    var board = [], i;
    for (i = 0; i < 9; i++) board.push("");
    var over = false;
    var grid = el("div", "ttt-grid", root);
    var buttons = [];
    var LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];

    function winner(b) {
      for (var k = 0; k < LINES.length; k++) {
        var L = LINES[k];
        if (b[L[0]] && b[L[0]] === b[L[1]] && b[L[1]] === b[L[2]]) return b[L[0]];
      }
      return "";
    }
    function endGame() {
      over = true;
      var w = winner(board);
      if (w === "X") finish(100, "Laimėjai!");
      else if (w === "O") finish(0, "Pralaimėjai...");
      else finish(30, "Lygiosios!");
    }
    function aiMove() {
      if (over) return;
      var free = [];
      for (var k = 0; k < 9; k++) if (!board[k]) free.push(k);
      if (!free.length) { endGame(); return; }
      var mv = null;
      // laimėti
      for (var k = 0; k < 9; k++) {
        if (!board[k]) { board[k] = "O"; if (winner(board) === "O") { mv = k; } board[k] = ""; }
        if (mv !== null) break;
      }
      // blokuoti
      if (mv === null) {
        for (var k = 0; k < 9; k++) {
          if (!board[k]) { board[k] = "X"; if (winner(board) === "X") { mv = k; } board[k] = ""; }
          if (mv !== null) break;
        }
      }
      if (mv === null && !board[4]) mv = 4;
      if (mv === null) {
        var corners = shuffle([0, 2, 6, 8].filter(function (k) { return !board[k]; }));
        if (corners.length) mv = corners[0];
      }
      if (mv === null) mv = free[Math.floor(Math.random() * free.length)];
      board[mv] = "O";
      render();
      if (winner(board) === "O" || board.every(Boolean)) endGame();
    }
    function render() {
      for (var k = 0; k < 9; k++) {
        buttons[k].textContent = board[k];
        buttons[k].className = "ttt-cell" + (board[k] === "X" ? " x" : board[k] === "O" ? " o" : "");
      }
    }
    for (i = 0; i < 9; i++) {
      (function (idx) {
        var b = el("button", "ttt-cell", grid);
        b.type = "button";
        buttons.push(b);
        b.addEventListener("click", function () {
          if (over || board[idx]) return;
          board[idx] = "X";
          render();
          if (winner(board) === "X" || board.every(Boolean)) { endGame(); return; }
          setTimeout(aiMove, 350);
        });
      })(i);
    }
    setStatus("Tu – ❌, kompiuteris – ⭕");
    return null;
  }

  /* ------------------------------------------------ Minų laukas */
  function initMines() {
    var N = 9, MINES = 10;
    var grid = el("div", "mine-grid", root);
    var cells = [], revealed = 0, started = false, over = false, flags = 0;
    var mines = {}, counts = {};
    var seconds = 0, timer = null;
    var timerEl = el("div", "hint", null);
    root.appendChild(timerEl);

    function idx(x, y) { return y * N + x; }
    function neighbors(x, y) {
      var out = [];
      for (var dx = -1; dx <= 1; dx++) for (var dy = -1; dy <= 1; dy++) {
        if (!dx && !dy) continue;
        var nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < N && ny < N) out.push([nx, ny]);
      }
      return out;
    }
    function placeMines(sx, sy) {
      var placed = 0;
      while (placed < MINES) {
        var x = Math.floor(Math.random() * N), y = Math.floor(Math.random() * N);
        if (mines[idx(x, y)]) continue;
        if (Math.abs(x - sx) <= 1 && Math.abs(y - sy) <= 1) continue; // pirmas click saugus
        mines[idx(x, y)] = true;
        placed++;
      }
      for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) {
        var c = 0;
        neighbors(x, y).forEach(function (p) { if (mines[idx(p[0], p[1])]) c++; });
        counts[idx(x, y)] = c;
      }
    }
    function startTimer() {
      timer = setInterval(function () {
        seconds++;
        timerEl.textContent = "⏱ " + seconds + " sek. | 🚩 " + flags + "/" + MINES;
      }, 1000);
    }
    function lose() {
      over = true;
      clearInterval(timer);
      for (var k = 0; k < N * N; k++) {
        if (mines[k]) { cells[k].textContent = "💣"; cells[k].classList.add("boom"); }
        cells[k].disabled = true;
      }
      setStatus("💥 Sprogo! Bandyk dar (mygtukas „Pradėti“).");
    }
    function win() {
      over = true;
      clearInterval(timer);
      setStatus("✅ Laimėjai!");
      finish(seconds, "Minų laukas išvalytas per " + seconds + " sek.!");
    }
    function reveal(x, y) {
      var k = idx(x, y);
      if (cells[k].disabled || cells[k].classList.contains("flag")) return;
      if (mines[k]) { lose(); return; }
      if (cells[k].classList.contains("open")) return;
      cells[k].classList.add("open");
      cells[k].disabled = true;
      revealed++;
      if (counts[k] > 0) {
        cells[k].textContent = counts[k];
        cells[k].classList.add("n" + counts[k]);
      } else {
        neighbors(x, y).forEach(function (p) { reveal(p[0], p[1]); });
      }
      if (revealed === N * N - MINES) win();
    }
    for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) {
      (function (x, y) {
        var b = el("button", "mine-cell", grid);
        b.type = "button";
        cells.push(b);
        b.addEventListener("click", function () {
          if (over || b.classList.contains("flag")) return;
          if (!started) { started = true; placeMines(x, y); startTimer(); }
          reveal(x, y);
        });
        b.addEventListener("contextmenu", function (e) {
          e.preventDefault();
          if (over || b.classList.contains("open")) return;
          if (b.classList.contains("flag")) {
            b.classList.remove("flag"); b.textContent = ""; flags--;
          } else {
            b.classList.add("flag"); b.textContent = "🚩"; flags++;
          }
          timerEl.textContent = "⏱ " + seconds + " sek. | 🚩 " + flags + "/" + MINES;
        });
      })(x, y);
    }
    timerEl.textContent = "⏱ 0 sek. | 🚩 0/" + MINES;
    setStatus("Kairysis mygtukas – atverti, dešiniysis – vėliavėlė 🚩");
    return function () { if (timer) clearInterval(timer); };
  }

  /* --------------------------------------------------- Breakout */
  function initBreakout() {
    var cv = el("canvas", "game-canvas wide", root);
    cv.width = 480; cv.height = 360;
    var ctx = cv.getContext("2d");
    var PW = 80, PH = 10, BR = 7;
    var paddle = { x: 200 };
    var ball = { x: 240, y: 300, vx: 3.2, vy: -3.2, r: BR };
    var score = 0, lives = 3, over = false, raf = null;
    var bricks = [];
    var colors = ["#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#4dabf7", "#b197fc"];
    for (var r = 0; r < 6; r++) for (var c = 0; c < 9; c++) {
      bricks.push({ x: 15 + c * 51, y: 40 + r * 24, w: 45, h: 18, on: true, color: colors[r] });
    }
    function draw() {
      ctx.fillStyle = "#0d1220"; ctx.fillRect(0, 0, 480, 360);
      bricks.forEach(function (b) {
        if (!b.on) return;
        ctx.fillStyle = b.color;
        ctx.fillRect(b.x, b.y, b.w, b.h);
      });
      ctx.fillStyle = "#e6edf3";
      ctx.fillRect(paddle.x, 340, PW, PH);
      ctx.beginPath(); ctx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2); ctx.fill();
      ctx.font = "16px sans-serif";
      ctx.fillText("Taškai: " + score + "   Gyvybės: " + lives, 10, 24);
    }
    function step() {
      if (over) return;
      ball.x += ball.vx; ball.y += ball.vy;
      if (ball.x < ball.r || ball.x > 480 - ball.r) ball.vx *= -1;
      if (ball.y < ball.r + 20) ball.vy *= -1;
      if (ball.y > 340 - ball.r && ball.y < 352 && ball.x > paddle.x && ball.x < paddle.x + PW) {
        ball.vy = -Math.abs(ball.vy);
        ball.vx += (ball.x - (paddle.x + PW / 2)) / 25;
        ball.vx = Math.max(-5, Math.min(5, ball.vx));
      }
      bricks.forEach(function (b) {
        if (!b.on) return;
        if (ball.x > b.x - ball.r && ball.x < b.x + b.w + ball.r &&
            ball.y > b.y - ball.r && ball.y < b.y + b.h + ball.r) {
          b.on = false;
          ball.vy *= -1;
          score += 10;
          setScore(score);
        }
      });
      if (bricks.every(function (b) { return !b.on; })) {
        over = true; cancelAnimationFrame(raf);
        finish(score, "Plytos sunaikintos!");
        return;
      }
      if (ball.y > 370) {
        lives--;
        if (lives <= 0) {
          over = true; cancelAnimationFrame(raf);
          finish(score, "Gyvybės baigėsi!");
          return;
        }
        ball = { x: 240, y: 300, vx: 3.2 * (Math.random() < 0.5 ? 1 : -1), vy: -3.2, r: BR };
      }
      draw();
      raf = requestAnimationFrame(step);
    }
    function onMove(e) {
      var rect = cv.getBoundingClientRect();
      var cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      paddle.x = Math.max(0, Math.min(480 - PW, cx - PW / 2));
    }
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("touchmove", function (e) { e.preventDefault(); onMove(e); }, { passive: false });
    draw();
    raf = requestAnimationFrame(step);
    setStatus("Pelę virš lentelės – valdyk padą");
    return function () { over = true; cancelAnimationFrame(raf); };
  }

  /* --------------------------------------------------------- Pong */
  function initPong() {
    var cv = el("canvas", "game-canvas wide", root);
    cv.width = 480; cv.height = 320;
    var ctx = cv.getContext("2d");
    var PH = 60, PW = 10;
    var player = { y: 130 }, ai = { y: 130 };
    var ball = { x: 240, y: 160, vx: 4, vy: 2.5 };
    var score = 0, opp = 0, over = false, raf = null;
    var keys = {};

    function reset(dir) {
      ball = { x: 240, y: 160, vx: 4 * dir, vy: (Math.random() * 3 - 1.5) || 2 };
    }
    function draw() {
      ctx.fillStyle = "#0d1220"; ctx.fillRect(0, 0, 480, 320);
      ctx.strokeStyle = "#30363d"; ctx.setLineDash([6, 8]);
      ctx.beginPath(); ctx.moveTo(240, 0); ctx.lineTo(240, 320); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#4dabf7"; ctx.fillRect(10, player.y, PW, PH);
      ctx.fillStyle = "#ff6b6b"; ctx.fillRect(460, ai.y, PW, PH);
      ctx.fillStyle = "#e6edf3";
      ctx.fillRect(ball.x - 5, ball.y - 5, 10, 10);
      ctx.font = "20px sans-serif";
      ctx.fillText(score + " : " + opp, 220, 30);
    }
    function step() {
      if (over) return;
      if (keys.ArrowUp || keys.w) player.y -= 6;
      if (keys.ArrowDown || keys.s) player.y += 6;
      player.y = Math.max(0, Math.min(320 - PH, player.y));
      // AI seka kamuoliuką
      var target = ball.y - PH / 2;
      if (ai.y < target) ai.y += 3.4;
      else if (ai.y > target) ai.y -= 3.4;
      ai.y = Math.max(0, Math.min(320 - PH, ai.y));

      ball.x += ball.vx; ball.y += ball.vy;
      if (ball.y < 5 || ball.y > 315) ball.vy *= -1;
      if (ball.x < 25 && ball.x > 15 && ball.y > player.y && ball.y < player.y + PH) {
        ball.vx = Math.abs(ball.vx);
        ball.vy += (ball.y - (player.y + PH / 2)) / 12;
      }
      if (ball.x > 455 && ball.x < 465 && ball.y > ai.y && ball.y < ai.y + PH) {
        ball.vx = -Math.abs(ball.vx);
      }
      if (ball.x < -10) { opp++; if (opp >= 7) { over = true; cancelAnimationFrame(raf); finish(score, "Pralaimėjai " + score + ":" + opp); return; } reset(1); }
      if (ball.x > 490) { score += 10; setScore(score); if (score >= 70) { over = true; cancelAnimationFrame(raf); finish(score, "Laimėjai " + score + ":" + opp + "!"); return; } reset(-1); }
      draw();
      raf = requestAnimationFrame(step);
    }
    function onKey(e, down) {
      keys[e.key] = down;
      if (["ArrowUp", "ArrowDown"].indexOf(e.key) >= 0) e.preventDefault();
    }
    function kd(e) { onKey(e, true); }
    function ku(e) { onKey(e, false); }
    document.addEventListener("keydown", kd);
    document.addEventListener("keyup", ku);
    draw();
    raf = requestAnimationFrame(step);
    setStatus("Rodyklėmis ↑ ↓ valdyk kairįjį padą. Laimėk 7 taškus!");
    return function () {
      over = true; cancelAnimationFrame(raf);
      document.removeEventListener("keydown", kd);
      document.removeEventListener("keyup", ku);
    };
  }

  /* ------------------------------------------------------- Flappy */
  function initFlappy() {
    var cv = el("canvas", "game-canvas", root);
    cv.width = 400; cv.height = 500;
    var ctx = cv.getContext("2d");
    var bird = { y: 250, vy: 0 };
    var pipes = [], score = 0, over = false, raf = null, frame = 0;
    var GAP = 130;

    function flap() {
      if (over) return;
      bird.vy = -8.5;
    }
    function onKey(e) {
      if (e.code === "Space" || e.key === " ") { e.preventDefault(); flap(); }
    }
    function onClick() { flap(); }
    function draw() {
      ctx.fillStyle = "#0d1220"; ctx.fillRect(0, 0, 400, 500);
      pipes.forEach(function (p) {
        ctx.fillStyle = "#3fb950";
        ctx.fillRect(p.x, 0, 52, p.gapY);
        ctx.fillRect(p.x, p.gapY + GAP, 52, 500 - p.gapY - GAP);
        ctx.fillStyle = "#2ea043";
        ctx.fillRect(p.x - 4, p.gapY - 14, 60, 14);
        ctx.fillRect(p.x - 4, p.gapY + GAP, 60, 14);
      });
      ctx.fillStyle = "#ffd43b";
      ctx.beginPath(); ctx.arc(70, bird.y, 14, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#0d1220";
      ctx.beginPath(); ctx.arc(76, bird.y - 4, 3, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#e6edf3";
      ctx.font = "18px sans-serif";
      ctx.fillText("Taškai: " + score, 10, 26);
    }
    function step() {
      if (over) return;
      frame++;
      bird.vy += 0.45;
      bird.y += bird.vy;
      if (frame % 95 === 1) {
        pipes.push({ x: 400, gapY: 60 + Math.random() * 300, passed: false });
      }
      pipes.forEach(function (p) { p.x -= 2.6; });
      pipes = pipes.filter(function (p) { return p.x > -60; });
      pipes.forEach(function (p) {
        if (!p.passed && p.x + 52 < 70) {
          p.passed = true; score++; setScore(score);
        }
        if (70 + 14 > p.x && 70 - 14 < p.x + 52 &&
            (bird.y - 14 < p.gapY || bird.y + 14 > p.gapY + GAP)) {
          over = true; cancelAnimationFrame(raf);
          finish(score, "Susidūrei po " + score + " vamzdžių!");
        }
      });
      if (bird.y > 500 || bird.y < 0) {
        over = true; cancelAnimationFrame(raf);
        finish(score, "Krito žemyn!");
        return;
      }
      if (over) return;
      draw();
      raf = requestAnimationFrame(step);
    }
    document.addEventListener("keydown", onKey);
    cv.addEventListener("mousedown", onClick);
    cv.addEventListener("touchstart", function (e) { e.preventDefault(); flap(); }, { passive: false });
    draw();
    raf = requestAnimationFrame(step);
    setStatus("SPACE arba pelės mygtukas – pakilti");
    return function () {
      over = true; cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
    };
  }

  /* -------------------------------------------------------- Simon */
  function initSimon() {
    var COLORS = ["#ff5f6d", "#ffd43b", "#4dabf7", "#3fb950"];
    var seq = [], input = [], round = 0, score = 0, accepting = false;
    var timeouts = [];
    var grid = el("div", "simon-grid", root);
    var pads = [];
    COLORS.forEach(function (c) {
      var b = el("button", "simon-pad", grid);
      b.type = "button";
      b.style.background = c;
      pads.push(b);
    });
    function later(fn, ms) { timeouts.push(setTimeout(fn, ms)); }
    function flash(i, ms) {
      pads[i].classList.add("lit");
      later(function () { pads[i].classList.remove("lit"); }, ms);
    }
    function playback() {
      accepting = false;
      input = [];
      setStatus("Žiūrėk seką...");
      seq.forEach(function (v, k) {
        later(function () { flash(v, 400); }, k * 650);
      });
      later(function () { accepting = true; setStatus("Kartok seką (" + seq.length + " žingsniai)"); }, seq.length * 650);
    }
    function nextRound() {
      seq.push(Math.floor(Math.random() * 4));
      round++;
      playback();
    }
    pads.forEach(function (b, i) {
      b.addEventListener("click", function () {
        if (!accepting) return;
        flash(i, 200);
        input.push(i);
        var k = input.length - 1;
        if (input[k] !== seq[k]) {
          accepting = false;
          finish(score, "Klaida " + round + " rate!");
          return;
        }
        if (input.length === seq.length) {
          accepting = false;
          score += 10;
          setScore(score);
          later(nextRound, 800);
        }
      });
    });
    nextRound();
    return function () { timeouts.forEach(clearTimeout); };
  }

  /* --------------------------------------------- Reakcijos laikas */
  function initReaction() {
    var rounds = [], TRIES = 5;
    var state = "wait", startT = 0, timeout = null;
    var box = el("div", "reaction-box", root);
    var label = el("div", "reaction-label", box, "Palauk žalios spalvos...");
    box.classList.add("red");

    function nextRound() {
      if (rounds.length >= TRIES) {
        var avg = Math.round(rounds.reduce(function (a, b) { return a + b; }, 0) / rounds.length);
        finish(avg, "Vidutinis laikas: " + avg + " ms!");
        return;
      }
      state = "wait";
      box.className = "reaction-box red";
      label.textContent = "Palauk... (" + (rounds.length + 1) + "/" + TRIES + ")";
      timeout = setTimeout(function () {
        state = "ready";
        box.classList.remove("red");
        box.classList.add("green");
        label.textContent = "SPAUSK DABAR!";
        startT = Date.now();
      }, 1500 + Math.random() * 2500);
    }
    box.addEventListener("click", function () {
      if (state === "wait") {
        clearTimeout(timeout);
        state = "early";
        box.className = "reaction-box red";
        label.textContent = "Per anksti! Spausk „Toliau“ ir bandyk dar kartą.";
        var btn = el("button", "btn", root, "Toliau");
        btn.type = "button";
        btn.addEventListener("click", function () { btn.remove(); nextRound(); });
        return;
      }
      if (state === "ready") {
        var ms = Date.now() - startT;
        rounds.push(ms);
        state = "done";
        box.className = "reaction-box green";
        label.textContent = ms + " ms! ✅";
        setScore(ms);
        setTimeout(function () { nextRound(); }, 900);
      }
    });
    nextRound();
    return function () { clearTimeout(timeout); };
  }

  /* ---------------------------------------------- Mušti kurmius */
  function initWhack() {
    var TIME = 30, score = 0, left = TIME, moleAt = -1, over = false;
    var grid = el("div", "whack-grid", root);
    var cells = [];
    var info = el("div", "hint", root);
    for (var i = 0; i < 9; i++) {
      (function (i) {
        var b = el("button", "whack-cell", grid, "🕳️");
        b.type = "button";
        cells.push(b);
        b.addEventListener("click", function () {
          if (over || i !== moleAt) return;
          score += 10;
          setScore(score);
          cells[i].textContent = "🕳️";
          moleAt = -1;
        });
      })(i);
    }
    var moleTimer = setInterval(function () {
      if (over) return;
      if (moleAt >= 0) cells[moleAt].textContent = "🕳️";
      moleAt = Math.floor(Math.random() * 9);
      cells[moleAt].textContent = "🐹";
    }, 700);
    var timer = setInterval(function () {
      left--;
      info.textContent = "⏱ Liko: " + left + " sek. | Taškai: " + score;
      if (left <= 0) {
        over = true;
        clearInterval(timer); clearInterval(moleTimer);
        if (moleAt >= 0) cells[moleAt].textContent = "🕳️";
        finish(score, "Laikas baigėsi!");
      }
    }, 1000);
    info.textContent = "⏱ Liko: " + left + " sek. | Taškai: 0";
    setStatus("Spausk 🐹 kai tik jis pasirodo!");
    return function () {
      over = true;
      clearInterval(timer); clearInterval(moleTimer);
    };
  }

  /* ------------------------------------------------ 15 dėlionė */
  function initPuzzle15() {
    var tiles = [];
    for (var i = 1; i <= 15; i++) tiles.push(i);
    tiles.push(0);
    var moves = 0, over = false;
    // maišome teisėtais judesiais – dėlionė visada išsprendžiama
    for (var s = 0; s < 300; s++) {
      var blank = tiles.indexOf(0);
      var bx = blank % 4, by = Math.floor(blank / 4);
      var opts = [];
      if (bx > 0) opts.push(blank - 1);
      if (bx < 3) opts.push(blank + 1);
      if (by > 0) opts.push(blank - 4);
      if (by < 3) opts.push(blank + 4);
      var pick = opts[Math.floor(Math.random() * opts.length)];
      tiles[blank] = tiles[pick];
      tiles[pick] = 0;
    }
    var grid = el("div", "p15-grid", root);
    var info = el("div", "hint", root);
    function render() {
      grid.innerHTML = "";
      tiles.forEach(function (v, i) {
        var b = el("button", v ? "p15-cell" : "p15-cell empty", grid, v || "");
        b.type = "button";
        if (v) b.addEventListener("click", function () { clickTile(i); });
      });
      info.textContent = "Judesiai: " + moves;
    }
    function clickTile(i) {
      if (over) return;
      var blank = tiles.indexOf(0);
      var bi = Math.abs((i % 4) - (blank % 4)) + Math.abs(Math.floor(i / 4) - Math.floor(blank / 4));
      if (bi !== 1) return;
      tiles[blank] = tiles[i];
      tiles[i] = 0;
      moves++;
      setScore(moves);
      render();
      var ok = true;
      for (var k = 0; k < 15; k++) if (tiles[k] !== k + 1) { ok = false; break; }
      if (ok) {
        over = true;
        finish(moves, "Sudėliota per " + moves + " judesių!");
      }
    }
    render();
    setStatus("Perkelk plytelę šalia tuščios vietos");
    return null;
  }

  /* ------------------------------------- Akmuo–žirklės–popierius */
  function initRPS() {
    var round = 0, ROUNDS = 5, score = 0;
    var ICONS = { rock: "✊", scissors: "✌️", paper: "✋" };
    var BEATS = { rock: "scissors", scissors: "paper", paper: "rock" };
    var info = el("div", "rps-info", root);
    var result = el("div", "rps-result", root);
    var bar = el("div", "rps-bar", root);
    ["rock", "scissors", "paper"].forEach(function (k) {
      var b = el("button", "btn rps-btn", bar, ICONS[k]);
      b.type = "button";
      b.title = k === "rock" ? "Akmuo" : k === "scissors" ? "Žirklės" : "Popierius";
      b.addEventListener("click", function () {
        if (round >= ROUNDS) return;
        var ai = ["rock", "scissors", "paper"][Math.floor(Math.random() * 3)];
        round++;
        var msg;
        if (ai === k) { score += 5; msg = "Lygiosios! +5"; }
        else if (BEATS[k] === ai) { score += 20; msg = "Laimėjai raundą! +20"; }
        else { msg = "Pralaimėjai raundą..."; }
        setScore(score);
        result.textContent = "Tu: " + ICONS[k] + "  |  Kompiuteris: " + ICONS[ai] + " → " + msg;
        info.textContent = "Raundas " + round + "/" + ROUNDS;
        if (round >= ROUNDS) {
          finish(score, "Baigta 5 raundai! Surinkai " + score + " taškų.");
        }
      });
    });
    info.textContent = "Raundas 0/" + ROUNDS;
    setStatus("Rinkis: ✊ akmuo, ✌️ žirklės, ✋ popierius");
    return null;
  }

  /* ------------------------------------------------ Greitas rašymas */
  function initTyping() {
    var WORDS = ["labas", "rytas", "naktis", "diena", "zodis", "kniga", "sunys",
                 "kates", "medis", "ranka", "koja", "akis", "nosis", "galva",
                 "duona", "pienas", "zole", "jura", "kalnas", "miestas",
                 "zaidejas", "kompiuteris", "draugas", "saule", "lietus"];
    var idx = Math.floor(Math.random() * WORDS.length);
    var score = 0, left = 60, over = false;
    var wordEl = el("div", "type-word", root, WORDS[idx]);
    var input = el("input", "type-input", root);
    input.type = "text";
    input.autocomplete = "off";
    input.placeholder = "Rašyk žodį ir spausk Enter";
    var info = el("div", "hint", root);
    info.textContent = "⏱ Liko: 60 sek. | Taškai: 0";

    function nextWord() {
      var n;
      do { n = Math.floor(Math.random() * WORDS.length); } while (WORDS.length > 1 && n === idx);
      idx = n;
      wordEl.textContent = WORDS[idx];
      input.value = "";
    }
    input.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || over) return;
      e.preventDefault();
      if (input.value.trim().toLowerCase() === WORDS[idx]) {
        score += 10;
        setScore(score);
      }
      nextWord();
      input.focus();
    });
    var timer = setInterval(function () {
      left--;
      info.textContent = "⏱ Liko: " + left + " sek. | Taškai: " + score;
      if (left <= 0) {
        over = true;
        clearInterval(timer);
        input.disabled = true;
        finish(score, "Laikas baigėsi!");
      }
    }, 1000);
    input.focus();
    setStatus("Rašyk rodomą žodį ir spausk Enter");
    return function () { over = true; clearInterval(timer); };
  }

  /* ------------------------------------------- Kauliukų dvikova */
  function initDice() {
    var THROWS = 10, used = 0, mine = 0, theirs = 0, over = false;
    var grid = el("div", "dice-area", root);
    var pD = el("div", "dice-pair", grid);
    var aD = el("div", "dice-pair", grid);
    var info = el("div", "hint", root);
    var btn = el("button", "btn", root, "🎲 Mesti kauliukus");
    btn.type = "button";
    function pair(el2) {
      el2.innerHTML = "";
      var a = 1 + Math.floor(Math.random() * 6);
      var b = 1 + Math.floor(Math.random() * 6);
      el("span", "die", el2, String(a));
      el("span", "die", el2, String(b));
      return a + b;
    }
    function update() {
      info.textContent = "Metimai: " + used + "/" + THROWS + " | Tavo taškai: " + mine + " | Kompiuterio: " + theirs;
    }
    btn.addEventListener("click", function () {
      if (over || used >= THROWS) return;
      used++;
      var m = pair(pD), t = pair(aD);
      mine += m; theirs += t;
      setScore(mine);
      update();
      if (used >= THROWS) {
        over = true;
        btn.disabled = true;
        if (mine > theirs) finish(mine, "Laimėjai " + mine + " prieš " + theirs + "!");
        else if (mine < theirs) finish(mine, "Pralaimėjai " + mine + " prieš " + theirs + "...");
        else finish(mine, "Lygiosios " + mine + ":" + theirs + "!");
      }
    });
    pD.appendChild(document.createTextNode(""));
    info.textContent = "Metimai: 0/" + THROWS + " | Tavo taškai: 0 | Kompiuterio: 0";
    setStatus("Mėtyk 10 kartų – daugiau taškų laimi!");
    return null;
  }

  /* --------------------------------------------- Spėk skaičių */
  function initGuess() {
    var target = 1 + Math.floor(Math.random() * 100);
    var tries = 0, over = false;
    var info = el("div", "hint", root, "Aš galvoju skaičių nuo 1 iki 100. Spėk!");
    var row = el("div", "guess-row", root);
    var input = el("input", "guess-input", row);
    input.type = "number"; input.min = "1"; input.max = "100";
    var btn = el("button", "btn", row, "Spėti");
    btn.type = "button";
    var log = el("div", "guess-log", root);
    function doGuess() {
      if (over) return;
      var v = parseInt(input.value, 10);
      if (isNaN(v) || v < 1 || v > 100) {
        info.textContent = "Įrašyk skaičių nuo 1 iki 100.";
        return;
      }
      tries++;
      setScore(tries);
      var line = el("div", "hint", log, tries + ". bandymas: " + v);
      if (v === target) {
        over = true;
        input.disabled = true; btn.disabled = true;
        info.textContent = "🎉 Atspėjai! Skaičius buvo " + target + ".";
        finish(tries, "Atspėjai per " + tries + " bandymų!");
      } else if (v < target) {
        info.textContent = "📈 Per mažai! Bandyk didesnį.";
      } else {
        info.textContent = "📉 Per daug! Bandyk mažesnį.";
      }
      input.value = "";
      input.focus();
    }
    btn.addEventListener("click", doGuess);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") doGuess(); });
    input.focus();
    setStatus("Spėk skaičių 1–100");
    return null;
  }

  /* ------------------------------------------------- Viktorina */
  function initQuiz() {
    var QS = [
      { q: "Kiek kojų turi katė?", a: ["2", "4", "6", "8"], c: 1 },
      { q: "Koks yra 7 × 8?", a: ["54", "56", "64", "72"], c: 1 },
      { q: "Kokia yra Lietuvos sostinė?", a: ["Kaunas", "Klaipėda", "Vilnius", "Šiauliai"], c: 2 },
      { q: "Kiek mėnesių turi metai?", a: ["10", "11", "12", "13"], c: 2 },
      { q: "Kokią formą turi Žemė?", a: ["Kubą", "Rutulį", "Piramidę", "Diską"], c: 1 },
      { q: "Kiek spalvų yra vaivorykštėje?", a: ["5", "6", "7", "9"], c: 2 },
      { q: "Koks gyvūnas yra greičiausias pasaulyje?", a: ["Liūtas", "Gepardas", "Voverė", "Erelias"], c: 1 },
      { q: "Kiek sekundžių yra vienoje minutėje?", a: ["30", "50", "60", "100"], c: 2 },
      { q: "Kas parašė pjese „Hamletas“?", a: ["Dumas", "Šekspyras", "Tolstojus", "Baltas"], c: 1 },
      { q: "Koks yra vandens cheminis ženklas?", a: ["CO2", "O2", "H2O", "NaCl"], c: 2 }
    ];
    var i = 0, score = 0, locked = false;
    var qEl = el("div", "quiz-q", root);
    var aEl = el("div", "quiz-answers", root);
    var info = el("div", "hint", root);
    function show() {
      locked = false;
      info.textContent = "Klausimas " + (i + 1) + "/" + QS.length;
      qEl.textContent = QS[i].q;
      aEl.innerHTML = "";
      QS[i].a.forEach(function (txt, k) {
        var b = el("button", "quiz-btn", aEl, txt);
        b.type = "button";
        b.addEventListener("click", function () {
          if (locked) return;
          locked = true;
          if (k === QS[i].c) {
            score += 10;
            setScore(score);
            b.classList.add("right");
          } else {
            b.classList.add("wrong");
            aEl.children[QS[i].c].classList.add("right");
          }
          setTimeout(function () {
            i++;
            if (i >= QS.length) finish(score, "Teisingai: " + (score / 10) + "/10!");
            else show();
          }, 700);
        });
      });
    }
    show();
    setStatus("Atsakyk į 10 klausimų");
    return null;
  }

  /* ------------------------------------------- Žodžių spėjimas */
  function initWordle() {
    var WORDS = ["NAMAS", "KNYGA", "SAULĖ", "ŽUVIS", "NAMAI", "RANKA", "TĖVAS",
                 "RUDUO", "ŠALIS", "MĖNUO", "BANGA", "LAIMĖ", "PILIS", "NOSIS",
                 "ŠOKIS", "DAINA", "ŽODIS", "VĖJAS", "DUONA", "TAMSA", "LEDAS",
                 "PUŠIS", "ŪKIAI", "ŠUNYS", "KATĖS", "SENAS", "ILGAS", "MAŽAS",
                 "GERAS", "RUDAS", "MERGA", "KOJOS"];
    var target = WORDS[Math.floor(Math.random() * WORDS.length)];
    var tries = 0, MAX = 6, over = false;
    var grid = el("div", "wordle-grid", root);
    var rows = [];
    for (var r = 0; r < MAX; r++) {
      var row = el("div", "wordle-row", grid);
      var cells = [];
      for (var c = 0; c < 5; c++) cells.push(el("span", "wordle-cell", row));
      rows.push(cells);
    }
    var inputRow = el("div", "guess-row", root);
    var input = el("input", "guess-input", inputRow);
    input.type = "text"; input.maxLength = 5; input.autocomplete = "off";
    input.placeholder = "5 raidės";
    var btn = el("button", "btn", inputRow, "Spėti");
    btn.type = "button";
    var info = el("div", "hint", root);

    function mark(word, guess) {
      var res = ["", "", "", "", ""];
      var t = word.split("");
      for (var i = 0; i < 5; i++) {
        if (guess[i] === t[i]) { res[i] = "hit"; t[i] = null; }
      }
      for (var i = 0; i < 5; i++) {
        if (res[i]) continue;
        var p = t.indexOf(guess[i]);
        if (p >= 0) { res[i] = "near"; t[p] = null; }
      }
      return res;
    }
    function doGuess() {
      if (over) return;
      var g = input.value.trim().toUpperCase();
      if (g.length !== 5) { info.textContent = "Reikia tiksliai 5 raidžių!"; return; }
      var res = mark(target, g);
      var cells = rows[tries];
      for (var i = 0; i < 5; i++) {
        cells[i].textContent = g[i];
        cells[i].className = "wordle-cell " + (res[i] || "");
      }
      tries++;
      input.value = "";
      if (g === target) {
        over = true;
        input.disabled = true; btn.disabled = true;
        var sc = (MAX - tries + 1) * 20;
        setScore(sc);
        finish(sc, "Atspėjai žodį per " + tries + " bandymus!");
      } else if (tries >= MAX) {
        over = true;
        input.disabled = true; btn.disabled = true;
        info.textContent = "😱 Baigėsi bandymai! Žodis buvo: " + target;
        finish(0, "Nepavyko atspėti.");
      } else {
        info.textContent = "Bandymas " + tries + "/" + MAX + ". Dar " + (MAX - tries) + "!";
      }
      input.focus();
    }
    btn.addEventListener("click", doGuess);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") doGuess(); });
    input.focus();
    setStatus("Spėk 5 raidžių žodį per 6 bandymus");
    return null;
  }

  /* ----------------------------------------------------- startas */
  var ALL = {
    "2048": init2048,
    "snake": initSnake,
    "memory": initMemory,
    "tictactoe": initTicTacToe,
    "mines": initMines,
    "breakout": initBreakout,
    "pong": initPong,
    "flappy": initFlappy,
    "simon": initSimon,
    "reaction": initReaction,
    "whack": initWhack,
    "puzzle15": initPuzzle15,
    "rps": initRPS,
    "typing": initTyping,
    "dice": initDice,
    "guess": initGuess,
    "quiz": initQuiz,
    "wordle": initWordle
  };

  startBtn.addEventListener("click", function () {
    var fn = ALL[KEY];
    if (fn) launch(fn);
  });
})();
