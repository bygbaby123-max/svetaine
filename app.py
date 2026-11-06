"""
Svetainė: registracija ir prisijungimas (el. paštas arba vartotojo vardas),
gimimo metai (galima praleisti), automatinis laiškas į vartotojo Gmail
su jo įvestais duomenimis ir mygtuku į asmeninę panelę,
administratoriaus panelė su visų vartotojų sąrašu.

Paleidimas:
    pip install -r requirements.txt
    python app.py
"""
import os
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import fetch_user, get_db, init_db
from emailer import send_email, smtp_configured

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "").strip() or secrets.token_hex(32)

# Render (ar kitas proxy) nustato X-Forwarded-* antraštes - reikia jas perskaityti,
# kad laiško nuorodos būtų su https, o ne http.
if os.getenv("RENDER", "").strip().lower() in ("true", "1", "yes"):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
SITE_URL = os.getenv("SITE_URL", "").strip().rstrip("/")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")


# ------------------------------------------------------------------ pagalbinukai
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "?"


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return fetch_user(uid)


def record_login(user):
    ip = client_ip()
    ua = (request.user_agent.string or "")[:300]
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET last_login_at = ?, last_login_ip = ?, login_count = login_count + 1 WHERE id = ?",
            (now_str(), ip, user["id"]),
        )
        db.execute(
            "INSERT INTO logins (user_id, ip, user_agent, created_at) VALUES (?, ?, ?, ?)",
            (user["id"], ip, ua, now_str()),
        )
        db.commit()
    finally:
        db.close()


def ensure_panel_token(user):
    if user["panel_token"]:
        return user["panel_token"]
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute("UPDATE users SET panel_token = ? WHERE id = ?", (token, user["id"]))
    db.commit()
    db.close()
    return token


def send_data_email(user, action, heading):
    """Išsiunčia vartotojui laišką su visais jo įvestais duomenimis."""
    token = ensure_panel_token(user)
    path = url_for("my_panel", token=token)
    panel_url = f"{SITE_URL}{path}" if SITE_URL else url_for("my_panel", token=token, _external=True)
    html = render_template(
        "email/summary.html",
        user=user, heading=heading, action=action,
        panel_url=panel_url, now=now_str(),
    )
    return send_email(user["email"], f"{heading} – tavo duomenys", html)


def warn_if_no_smtp():
    if not smtp_configured():
        flash("El. laiškas neišsiųstas: nesukonfigūruotas SMTP (.env faile "
              "SMTP_EMAIL ir SMTP_APP_PASSWORD).", "info")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Pirmiausia prisijunkite.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def owner_required(f):
    """Tik savininkas (is_admin): trinti vartotojus ir tvarkyti co-owner'ius."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Pirmiausia prisijunkite.", "error")
            return redirect(url_for("login", next=request.path))
        if not user["is_admin"]:
            flash("Ši veiksma skirta tik savininkui.", "error")
            return redirect(url_for("admin"))
        return f(*args, **kwargs)
    return wrapper


def staff_required(f):
    """Savininkas ARBA co-owner: peržiūrėti vartotojų lentelę."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Pirmiausia prisijunkite.", "error")
            return redirect(url_for("login", next=request.path))
        if not (user["is_admin"] or user["is_coowner"]):
            flash("Ši skiltis skirta tik administratoriui.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


# Senasis pavadinimas (naudojamas kitose vietose) rodo į savininką
admin_required = owner_required


@app.context_processor
def inject_globals():
    u = current_user()
    unread = unread_count() if u else 0
    return {
        "user": u,
        "google_client_id": GOOGLE_CLIENT_ID,
        "is_owner": bool(u and u["is_admin"]),
        "is_staff": bool(u and (u["is_admin"] or u["is_coowner"])),
        "unread": unread,
    }


# ---------------------------------------------------------------------- puslapiai
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", form={})

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    birth_raw = request.form.get("birth_year", "").strip()
    skipped = "skip_birth" in request.form

    errors = []
    if not USERNAME_RE.fullmatch(username):
        errors.append("Vartotojo vardas: 3–20 simbolių (raidės, skaičiai, _ - .).")
    if not EMAIL_RE.fullmatch(email):
        errors.append("Įrašykite teisingą el. paštą.")
    if len(password) < 6:
        errors.append("Slaptažodis turi būti bent 6 simbolių.")

    birth_year = None
    if not skipped:
        if not birth_raw:
            errors.append("Įrašykite gimimo metus arba paspauskite „Praleisti“.")
        elif not birth_raw.isdigit() or len(birth_raw) != 4 or not (1900 <= int(birth_raw) <= datetime.now().year):
            errors.append("Gimimo metai turi būti 4 skaitmenys (nuo 1900 iki šių metų).")
        else:
            birth_year = int(birth_raw)

    if not errors:
        db = get_db()
        try:
            if db.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
                errors.append("Toks vartotojo vardas jau užimtas.")
            elif db.execute("SELECT 1 FROM users WHERE lower(email) = lower(?)", (email,)).fetchone():
                errors.append("Toks el. paštas jau registruotas.")
        finally:
            db.close()

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("register.html", form=request.form)

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, email, password_hash, birth_year, panel_token, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username, email, generate_password_hash(password), birth_year,
             secrets.token_urlsafe(32), now_str()),
        )
        db.commit()
        new_id = cur.lastrowid
    finally:
        db.close()

    user = fetch_user(new_id)
    session["user_id"] = user["id"]
    record_login(user)
    sent = send_data_email(user, "registracijos", "Registracija sėkminga")
    if not sent:
        warn_if_no_smtp()
    flash("Sveikinimai! Paskyra sukurta ir prisijungta.", "success")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", next=request.args.get("next", ""))

    ident = request.form.get("identity", "").strip()
    password = request.form.get("password", "")
    nxt = request.form.get("next", "")

    if not ident or not password:
        flash("Įveskite vartotojo vardą / el. paštą ir slaptažodį.", "error")
        return render_template("login.html", next=nxt)

    db = get_db()
    try:
        user = db.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
            (ident, ident),
        ).fetchone()
    finally:
        db.close()

    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        flash("Neteisingi prisijungimo duomenys.", "error")
        return render_template("login.html", next=nxt)

    session["user_id"] = user["id"]
    record_login(user)

    flash(f"Sveikas, {user['username']}! Prisijungta.", "success")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    if user["is_admin"]:
        return redirect(url_for("admin"))
    return redirect(url_for("index"))


@app.route("/auth/google", methods=["POST"])
def auth_google():
    if not GOOGLE_CLIENT_ID:
        return jsonify(ok=False, error="Google prisijungimas nesukonfigūruotas (GOOGLE_CLIENT_ID tuščias)."), 400

    credential = (request.get_json(silent=True) or {}).get("credential")
    if not credential:
        return jsonify(ok=False, error="Nėra Google credentials."), 400

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
        info = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except Exception as exc:
        return jsonify(ok=False, error=f"Google patikra nepavyko: {exc}"), 401

    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        return jsonify(ok=False, error="Google nepatvirtino el. pašto."), 401

    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if user:
            uid = user["id"]
        else:
            base = re.sub(r"[^a-z0-9_.-]", "", email.split("@")[0]) or "vartotojas"
            username, i = base, 1
            while db.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
                i += 1
                username = f"{base}{i}"
            cur = db.execute(
                "INSERT INTO users (username, email, password_hash, birth_year, panel_token, created_at)"
                " VALUES (?, ?, NULL, NULL, ?, ?)",
                (username, email, secrets.token_urlsafe(32), now_str()),
            )
            db.commit()
            uid = cur.lastrowid
    finally:
        db.close()

    user = fetch_user(uid)
    session["user_id"] = uid
    record_login(user)
    return jsonify(ok=True, redirect=url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Atsijungta.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------- vartotojo asmeninė panelė
@app.route("/panel/<token>")
def my_panel(token):
    db = get_db()
    try:
        target = db.execute("SELECT * FROM users WHERE panel_token = ?", (token,)).fetchone()
        if not target:
            abort(404)
        logs = db.execute(
            "SELECT * FROM logins WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (target["id"],),
        ).fetchall()
    finally:
        db.close()
    is_owner = session.get("user_id") == target["id"]
    return render_template("panel.html", target=target, logins=logs, is_owner=is_owner)


# ---------------------------------------------------------------- administratoriaus panelė
@app.route("/admin")
@staff_required
def admin():
    q = request.args.get("q", "").strip()
    db = get_db()
    try:
        if q:
            like = f"%{q}%"
            users = db.execute(
                "SELECT * FROM users WHERE username LIKE ? OR email LIKE ? ORDER BY id DESC",
                (like, like),
            ).fetchall()
        else:
            users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
        logs = db.execute(
            "SELECT l.id, l.ip, l.user_agent, l.created_at, u.username, u.email"
            " FROM logins l JOIN users u ON u.id = l.user_id"
            " ORDER BY l.id DESC LIMIT 300",
        ).fetchall()
        stats = db.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]
        logs_total = db.execute("SELECT COUNT(*) AS n FROM logins").fetchone()["n"]
    finally:
        db.close()
    return render_template("admin.html", users=users, logs=logs, q=q,
                           total_users=stats, total_logins=logs_total)


@app.post("/admin/delete/<int:user_id>")
@owner_required
def admin_delete(user_id):
    if user_id == session.get("user_id"):
        flash("Negalima ištrinti savo paskyros iš admin panelės.", "error")
        return redirect(url_for("admin"))
    db = get_db()
    try:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    finally:
        db.close()
    flash("Vartotojas ištrintas.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/coowner/<int:user_id>/add")
@owner_required
def coowner_add(user_id):
    user = fetch_user(user_id)
    if not user:
        flash("Vartotojas nerastas.", "error")
        return redirect(url_for("admin"))
    if user["is_admin"]:
        flash("Šis vartotojas jau yra savininkas.", "info")
        return redirect(url_for("admin"))
    db = get_db()
    try:
        db.execute("UPDATE users SET is_coowner = 1 WHERE id = ?", (user_id,))
        db.commit()
    finally:
        db.close()
    flash(f"Vartotojas {user['username']} dabar yra co-owner.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/coowner/<int:user_id>/remove")
@owner_required
def coowner_remove(user_id):
    user = fetch_user(user_id)
    if not user:
        flash("Vartotojas nerastas.", "error")
        return redirect(url_for("admin"))
    db = get_db()
    try:
        db.execute("UPDATE users SET is_coowner = 0 WHERE id = ?", (user_id,))
        db.commit()
    finally:
        db.close()
    flash(f"Vartotojui {user['username']} co-owner teisės atimtos.", "success")
    return redirect(url_for("admin"))


# --------------------------------------------------------------------------- meme siena
MEME_SQL = """
SELECT m.id, m.user_id, m.title, m.image, m.created_at,
       u.username,
       COALESCE((SELECT SUM(v.vote) FROM meme_votes v WHERE v.meme_id = m.id), 0) AS score,
       (SELECT COUNT(*) FROM meme_comments c WHERE c.meme_id = m.id) AS comment_count
FROM memes m
JOIN users u ON u.id = m.user_id
"""


@app.route("/memes")
def memes():
    db = get_db()
    try:
        rows = db.execute(MEME_SQL + " ORDER BY m.id DESC LIMIT 100").fetchall()
        comment_rows = db.execute(
            """SELECT c.id, c.meme_id, c.body, c.created_at, u.username
               FROM meme_comments c JOIN users u ON u.id = c.user_id
               ORDER BY c.id ASC"""
        ).fetchall()
    finally:
        db.close()
    uid = session.get("user_id")
    votes = {}
    if uid:
        db = get_db()
        try:
            my_votes = db.execute(
                "SELECT meme_id, vote FROM meme_votes WHERE user_id = ?", (uid,)
            ).fetchall()
            votes = {v["meme_id"]: v["vote"] for v in my_votes}
        finally:
            db.close()
    comments = {}
    for c in comment_rows:
        comments.setdefault(c["meme_id"], []).append(c)
    return render_template("memes.html", memes=rows, my_votes=votes, comments=comments)


@app.post("/memes")
@login_required
def meme_create():
    title = (request.form.get("title") or "").strip()
    image = (request.form.get("image") or "").strip()
    if not title:
        flash("Įrašyk antraštę.", "error")
        return redirect(url_for("memes"))
    if len(title) > 100:
        flash("Antraštė per ilga (maks. 100 simbolių).", "error")
        return redirect(url_for("memes"))
    if not image.startswith("data:image/"):
        flash("Nepasirinkai nuotraukos.", "error")
        return redirect(url_for("memes"))
    if len(image) > 1_500_000:
        flash("Nuotrauka per didelė (maks. ~1,5 MB).", "error")
        return redirect(url_for("memes"))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO memes (user_id, title, image, created_at) VALUES (?, ?, ?, ?)",
            (session["user_id"], title, image, now_str()),
        )
        db.commit()
    finally:
        db.close()
    flash("Meme įkelta!", "success")
    return redirect(url_for("memes"))


@app.post("/memes/<int:meme_id>/vote")
@login_required
def meme_vote(meme_id):
    db = get_db()
    try:
        meme = db.execute("SELECT id FROM memes WHERE id = ?", (meme_id,)).fetchone()
        if not meme:
            flash("Meme nerasta.", "error")
            return redirect(url_for("memes"))
        existing = db.execute(
            "SELECT id, vote FROM meme_votes WHERE meme_id = ? AND user_id = ?",
            (meme_id, session["user_id"]),
        ).fetchone()
        new_vote = int(request.form.get("vote") or 1)
        if new_vote not in (1, -1):
            new_vote = 1
        if existing:
            if existing["vote"] == new_vote:
                db.execute("DELETE FROM meme_votes WHERE id = ?", (existing["id"],))
            else:
                db.execute(
                    "UPDATE meme_votes SET vote = ? WHERE id = ?",
                    (new_vote, existing["id"]),
                )
        else:
            db.execute(
                "INSERT INTO meme_votes (meme_id, user_id, vote) VALUES (?, ?, ?)",
                (meme_id, session["user_id"], new_vote),
            )
        db.commit()
    finally:
        db.close()
    return redirect(url_for("memes"))


@app.post("/memes/<int:meme_id>/comment")
@login_required
def meme_comment(meme_id):
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Komentaras tuščias.", "error")
        return redirect(url_for("memes"))
    if len(body) > 1000:
        flash("Komentaras per ilgas (maks. 1000 simbolių).", "error")
        return redirect(url_for("memes"))
    db = get_db()
    try:
        meme = db.execute("SELECT id FROM memes WHERE id = ?", (meme_id,)).fetchone()
        if not meme:
            flash("Meme nerasta.", "error")
            return redirect(url_for("memes"))
        db.execute(
            "INSERT INTO meme_comments (meme_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
            (meme_id, session["user_id"], body, now_str()),
        )
        db.commit()
    finally:
        db.close()
    return redirect(url_for("memes"))


@app.post("/memes/<int:meme_id>/delete")
@login_required
def meme_delete(meme_id):
    db = get_db()
    try:
        meme = db.execute(
            "SELECT id, user_id FROM memes WHERE id = ?", (meme_id,)
        ).fetchone()
        if not meme:
            flash("Meme nerasta.", "error")
            return redirect(url_for("memes"))
        user = current_user()
        if meme["user_id"] != session["user_id"] and not (user and user["is_admin"]):
            flash("Gali trinti tik savo memes.", "error")
            return redirect(url_for("memes"))
        db.execute("DELETE FROM memes WHERE id = ?", (meme_id,))
        db.commit()
    finally:
        db.close()
    flash("Meme ištrinta.", "success")
    return redirect(url_for("memes"))


# ------------------------------------------------------------------------- chatas
CHAT_SQL = """
SELECT c.id, c.body, c.created_at, u.username, c.user_id
FROM chat_messages c
JOIN users u ON u.id = c.user_id
"""


@app.route("/chat")
def chat():
    db = get_db()
    try:
        rows = db.execute(CHAT_SQL + " ORDER BY c.id DESC LIMIT 100").fetchall()
    finally:
        db.close()
    rows = list(reversed(rows))
    return render_template("chat.html", chat=rows)


@app.post("/chat")
@login_required
def chat_post():
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Žinutė tuščia.", "error")
        return redirect(url_for("chat"))
    if len(body) > 500:
        flash("Žinutė per ilga (maks. 500 simbolių).", "error")
        return redirect(url_for("chat"))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO chat_messages (user_id, body, created_at) VALUES (?, ?, ?)",
            (session["user_id"], body, now_str()),
        )
        db.commit()
    finally:
        db.close()
    return redirect(url_for("chat"))


@app.post("/chat/<int:msg_id>/delete")
@login_required
def chat_delete(msg_id):
    """Žinutę gali ištrinti jos autorius arba savininkas (bet kieno)."""
    db = get_db()
    try:
        m = db.execute(
            "SELECT id, user_id FROM chat_messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if not m:
            flash("Žinutė nerasta.", "error")
            return redirect(url_for("chat"))
        user = current_user()
        if m["user_id"] != session["user_id"] and not (user and user["is_admin"]):
            flash("Gali trinti tik savo žinutes.", "error")
            return redirect(url_for("chat"))
        db.execute("DELETE FROM chat_messages WHERE id = ?", (msg_id,))
        db.commit()
    finally:
        db.close()
    flash("Žinutė ištrinta.", "success")
    return redirect(url_for("chat"))


# ------------------------------------------------------------- privačios žinutės
@app.route("/messages")
@login_required
def messages_inbox():
    uid = session["user_id"]
    db = get_db()
    try:
        users = db.execute(
            "SELECT id, username FROM users WHERE id != ? ORDER BY username", (uid,)
        ).fetchall()
        convos = db.execute(
            """SELECT u.id, u.username,
                      (SELECT body FROM direct_messages
                       WHERE (from_id = ? AND to_id = u.id) OR (from_id = u.id AND to_id = ?)
                       ORDER BY id DESC LIMIT 1) AS last_body,
                      (SELECT created_at FROM direct_messages
                       WHERE (from_id = ? AND to_id = u.id) OR (from_id = u.id AND to_id = ?)
                       ORDER BY id DESC LIMIT 1) AS last_at,
                      (SELECT COUNT(*) FROM direct_messages
                       WHERE from_id = u.id AND to_id = ? AND read_at IS NULL) AS unread
               FROM users u
               WHERE u.id != ? AND EXISTS (
                   SELECT 1 FROM direct_messages d
                   WHERE (d.from_id = ? AND d.to_id = u.id) OR (d.from_id = u.id AND d.to_id = ?)
               )
               ORDER BY last_at DESC""",
            (uid, uid, uid, uid, uid, uid, uid, uid),
        ).fetchall()
    finally:
        db.close()
    return render_template("messages.html", users=users, convos=convos)


@app.route("/messages/<int:other_id>")
@login_required
def messages_thread(other_id):
    uid = session["user_id"]
    if other_id == uid:
        flash("Negali rašyti žinutės sau.", "error")
        return redirect(url_for("messages_inbox"))
    db = get_db()
    try:
        other = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (other_id,)
        ).fetchone()
        if not other:
            flash("Vartotojas nerastas.", "error")
            return redirect(url_for("messages_inbox"))
        rows = db.execute(
            """SELECT id, from_id, body, created_at FROM direct_messages
               WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)
               ORDER BY id DESC LIMIT 100""",
            (uid, other_id, other_id, uid),
        ).fetchall()
        db.execute(
            "UPDATE direct_messages SET read_at = ? WHERE from_id = ? AND to_id = ? AND read_at IS NULL",
            (now_str(), other_id, uid),
        )
        db.commit()
    finally:
        db.close()
    rows = list(reversed(rows))
    return render_template("thread.html", other=other, msgs=rows)


@app.post("/messages/<int:other_id>")
@login_required
def messages_send(other_id):
    uid = session["user_id"]
    body = (request.form.get("body") or "").strip()
    if other_id == uid:
        flash("Negali rašyti žinutės sau.", "error")
        return redirect(url_for("messages_inbox"))
    if not body:
        flash("Žinutė tuščia.", "error")
        return redirect(url_for("messages_thread", other_id=other_id))
    if len(body) > 1000:
        flash("Žinutė per ilga (maks. 1000 simbolių).", "error")
        return redirect(url_for("messages_thread", other_id=other_id))
    db = get_db()
    try:
        other = db.execute("SELECT id FROM users WHERE id = ?", (other_id,)).fetchone()
        if not other:
            flash("Vartotojas nerastas.", "error")
            return redirect(url_for("messages_inbox"))
        db.execute(
            "INSERT INTO direct_messages (from_id, to_id, body, created_at) VALUES (?, ?, ?, ?)",
            (uid, other_id, body, now_str()),
        )
        db.commit()
    finally:
        db.close()
    return redirect(url_for("messages_thread", other_id=other_id))


@app.post("/messages/<int:msg_id>/delete")
@login_required
def message_delete(msg_id):
    """Žinutę gali ištrinti jos autorius arba savininkas (bet kieno)."""
    db = get_db()
    try:
        m = db.execute(
            "SELECT id, from_id, to_id FROM direct_messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if not m:
            flash("Žinutė nerasta.", "error")
            return redirect(url_for("messages_inbox"))
        user = current_user()
        if m["from_id"] != session["user_id"] and not (user and user["is_admin"]):
            flash("Gali trinti tik savo žinutes.", "error")
            return redirect(url_for("messages_inbox"))
        # grįžtame į tą patį pokalbį (jei savininkas trina svetimą – į dėžutę)
        if m["from_id"] == session["user_id"]:
            other_id = m["to_id"]
        elif m["to_id"] == session["user_id"]:
            other_id = m["from_id"]
        else:
            db.execute("DELETE FROM direct_messages WHERE id = ?", (msg_id,))
            db.commit()
            flash("Žinutė ištrinta.", "success")
            return redirect(url_for("messages_inbox"))
        db.execute("DELETE FROM direct_messages WHERE id = ?", (msg_id,))
        db.commit()
    finally:
        db.close()
    flash("Žinutė ištrinta.", "success")
    return redirect(url_for("messages_thread", other_id=other_id))


def unread_count():
    uid = session.get("user_id")
    if not uid:
        return 0
    db = get_db()
    try:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM direct_messages WHERE to_id = ? AND read_at IS NULL",
            (uid,),
        ).fetchone()
        return row["n"] if row else 0
    finally:
        db.close()


# --------------------------------------------------------------------- žaidimai
# Kiekvienam žaidimui: antraštė, aprašymas, emoji, ar geriau didelis rezultatas
# (higher=True -> daugiau taškų geriau; False -> mažiau geriau, pvz. laikas).
GAMES = {
    "2048": {
        "title": "2048",
        "desc": "Sujung vienodus skaičius ir pasiek 2048! Valdai rodyklėmis.",
        "icon": "🔢", "higher": True, "unit": "taškų",
        "rules": "Rodyklėmis (←↑→↓) stumk lentelę. Vienodi skaičiai sujungiasi. Tikslas – surinkti 2048 arba daugiau taškų.",
    },
    "snake": {
        "title": "Gyvatė",
        "desc": "Valdyk gyvatę, rink obuolius ir nesusidurk su sienomis.",
        "icon": "🐍", "higher": True, "unit": "taškų",
        "rules": "Valdyk rodyklėmis arba WASD. Kiekvienas obuolis +10 taškų. Susidūrimas su siena arba savo uodega – žaidimas baigiasi.",
    },
    "memory": {
        "title": "Atmintis",
        "desc": "Atverk korteles ir rask visas poras – kuo mažiau bandymų, tuo geriau.",
        "icon": "🃏", "higher": True, "unit": "taškų",
        "rules": "Atverk po dvi korteles. Jei simboliai sutampa – pora lieka. Taškai = 1000 − 10 × bandymų. Baigęs gausi rezultatą.",
    },
    "tictactoe": {
        "title": "Kryžiukai–nuliai",
        "desc": "Žaisk 3×3 lentelėje prieš kompiuterį.",
        "icon": "❌", "higher": True, "unit": "taškų",
        "rules": "Tu – ❌, kompiuteris – ⭕. Laimėk = 100 taškų, lygiosios = 30, pralaimėjimas = 0.",
    },
    "mines": {
        "title": "Minų laukas",
        "desc": "Rask 10 minų 9×9 lentelėje – kuo greičiau, tuo geriau.",
        "icon": "💣", "higher": False, "unit": "sek.",
        "rules": "Dešiniu pelės mygtuku (arba ilgai paspaudus) dėk vėliavėles. Rezultatas – praleistos sekundės (mažiau geriau).",
    },
    "breakout": {
        "title": "Breakout",
        "desc": "Sulaužyk visas plytas kamuoliuku.",
        "icon": "🧱", "higher": True, "unit": "taškų",
        "rules": "Pelę (arba ← →) valdyk padą. Kiekviena plyta – 10 taškų. Nepraleisk kamuoliuko žemyn!",
    },
    "pong": {
        "title": "Pong",
        "desc": "Įmušk kamuoliuką į kompiuterio vartus.",
        "icon": "🏓", "higher": True, "unit": "taškų",
        "rules": "Pelę (arba ← →) valdyk padą. Kiekvienas įmuštas vartas – 10 taškų. Kompiuteris bėga atgal.",
    },
    "flappy": {
        "title": "Flappy",
        "desc": "Skriski pro plyšius tarp vamzdžių – spausk SPACE.",
        "icon": "🐦", "higher": True, "unit": "taškų",
        "rules": "Paspausk SPACE (arba pelės mygtuką), kad paukštis pakiltų. Kiekvienas praskridus vamzdis +1 taškas.",
    },
    "simon": {
        "title": "Simon",
        "desc": "Kartok vis ilgėjančią spalvų seką.",
        "icon": "🌈", "higher": True, "unit": "taškų",
        "rules": "Išklausyk sekos (šviečia spalvos) ir ją pakartok paspaudimais. Kiekvienas teisingas ratas +10 taškų.",
    },
    "reaction": {
        "title": "Reakcijos laikas",
        "desc": "Paspausk, kai tik pasidarys žalia – kuo greičiau, tuo geriau.",
        "icon": "⚡", "higher": False, "unit": "ms",
        "rules": "Palauk, kol ekranas pasidarys žalias, ir kuo greičiau paspausk mygtuką. Rezultatas – milisekundės (mažiau geriau).",
    },
    "whack": {
        "title": "Mušti kurmius",
        "desc": "30 sekundžių – mušk kuo daugiau kurmių!",
        "icon": "🔨", "higher": True, "unit": "taškų",
        "rules": "Spausk pasirodančius kurmius. Kiekvienas pagautas kirmis +10 taškų. Laikas baigiasi po 30 sekundžių.",
    },
    "puzzle15": {
        "title": "15 dėlionė",
        "desc": "Sudėliok skaičius nuo 1 iki 15 – kuo mažiau judesių.",
        "icon": "🧩", "higher": False, "unit": "judes.",
        "rules": "Spausk plytelę šalia tuščios vietos ir perkelk ją. Tikslas – sudėlioti skaičius eilėje. Rezultatas – judesių skaičius (mažiau geriau).",
    },
    "rps": {
        "title": "Akmuo–žirklės–popierius",
        "desc": "5 raundai prieš kompiuterį – laimėk daugiau.",
        "icon": "✊", "higher": True, "unit": "taškų",
        "rules": "Rinkis: ✊ akmuo, ✌️ žirklės, ✋ popierius. Laimėtas raundas +20 taškų, lygiosios +5.",
    },
    "typing": {
        "title": "Greitas rašymas",
        "desc": "60 sekundžių – rašyk žodžius kuo greičiau.",
        "icon": "⌨️", "higher": True, "unit": "taškų",
        "rules": "Įrašyk rodomą žodį ir spausk Enter. Kiekvienas teisingas žodis +10 taškų. Laikas – 60 sekundžių.",
    },
    "dice": {
        "title": "Kauliukų dvikova",
        "desc": "10 metimų prieš kompiuterį – kas surinks daugiau taškų?",
        "icon": "🎲", "higher": True, "unit": "taškų",
        "rules": "Mėtyk 2 kauliukus (10 kartų). Kompiuteris irgi meta. Kiekvienas metimas = kauliukų suma. Daugiau taškų – laimi!",
    },
    "guess": {
        "title": "Spėk skaičių",
        "desc": "Rask slapptą skaičių nuo 1 iki 100 – kuo mažiau bandymų.",
        "icon": "🎯", "higher": False, "unit": "band.",
        "rules": "Spėk skaičių 1–100. Sistema sako „daugiau“ arba „mažiau“. Rezultatas – bandymų skaičius (mažiau geriau).",
    },
    "quiz": {
        "title": "Viktorina",
        "desc": "10 klausimų – kiek atsakysi teisingai?",
        "icon": "❓", "higher": True, "unit": "taškų",
        "rules": "10 klausimų su 4 atsakymų variantais. Kiekvienas teisingas atsakymas +10 taškų.",
    },
    "wordle": {
        "title": "Žodžių spėjimas",
        "desc": "Atspėk 5 raidžių žodį per 6 bandymus.",
        "icon": "📝", "higher": True, "unit": "taškų",
        "rules": "Spėk 5 raidžių žodį. 🟩 – raida teisingoje vietoje, 🟨 – raida yra, bet ne ta vieta, ⬜ – raidės nėra. Laimėjimas = daugiau bandymų likus = daugiau taškų.",
    },
}


def _game_top_scores(name):
    """Geriausi 10 rezultatų žaidime (su vartotojo vardais)."""
    g = GAMES[name]
    order = "DESC" if g["higher"] else "ASC"
    db = get_db()
    try:
        rows = db.execute(
            "SELECT gs.score, gs.created_at, u.username"
            " FROM game_scores gs JOIN users u ON u.id = gs.user_id"
            " WHERE gs.game = ?"
            f" ORDER BY gs.score {order}, gs.id ASC LIMIT 10",
            (name,),
        ).fetchall()
        return rows
    finally:
        db.close()


@app.route("/games")
def games():
    # geriausias kiekvieno žaidimo rezultatas
    best = {}
    db = get_db()
    try:
        rows = db.execute(
            "SELECT game, score FROM game_scores"
        ).fetchall()
    finally:
        db.close()
    for r in rows:
        g = GAMES.get(r["game"])
        if not g:
            continue
        cur = best.get(r["game"])
        if cur is None or (r["score"] > cur if g["higher"] else r["score"] < cur):
            best[r["game"]] = r["score"]
    return render_template("games.html", games=GAMES, best=best)


@app.route("/games/<name>")
def game(name):
    g = GAMES.get(name)
    if not g:
        abort(404)
    rows = _game_top_scores(name)
    my_best = None
    if session.get("user_id"):
        db = get_db()
        try:
            row = db.execute(
                "SELECT score FROM game_scores WHERE user_id = ? AND game = ?",
                (session["user_id"], name),
            ).fetchall()
        finally:
            db.close()
        if row:
            scores = [r["score"] for r in row]
            my_best = max(scores) if g["higher"] else min(scores)
    return render_template("game.html", key=name, game=g, rows=rows, my_best=my_best)


@app.post("/games/<name>/score")
@login_required
def game_score(name):
    g = GAMES.get(name)
    if not g:
        abort(404)
    raw = (request.form.get("score") or "").strip()
    try:
        score = int(raw)
    except ValueError:
        flash("Rezultatas turi būti sveikasis skaičius.", "error")
        return redirect(url_for("game", name=name))
    if score < -1000000 or score > 100000000:
        flash("Rezultatas per didelis.", "error")
        return redirect(url_for("game", name=name))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO game_scores (user_id, game, score, created_at) VALUES (?, ?, ?, ?)",
            (session["user_id"], name, score, now_str()),
        )
        db.commit()
    finally:
        db.close()
    flash(f"Rezultatas įrašytas: {score} {g['unit']}! 🏆", "success")
    return redirect(url_for("game", name=name))


# --------------------------------------------------------------------- paleidimas
def seed_admin():
    username = os.getenv("ADMIN_USERNAME", "").strip()
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not (username and email and password):
        return
    db = get_db()
    try:
        exists = db.execute(
            "SELECT 1 FROM users WHERE lower(email) = lower(?) OR lower(username) = lower(?)",
            (email, username),
        ).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO users (username, email, password_hash, is_admin, panel_token, created_at)"
                " VALUES (?, ?, ?, 1, ?, ?)",
                (username, email, generate_password_hash(password),
                 secrets.token_urlsafe(32), now_str()),
            )
            db.commit()
            print(f"[ADMIN] Sukurtas administratorius: {username} <{email}>")
    finally:
        db.close()


init_db()
seed_admin()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("PORT", "5000").strip() or "5000")
    debug = os.getenv("DEBUG", "false").strip().lower() == "true"
    print(f"Svetainė veikia: http://{host}:{port}")
    if SITE_URL:
        print(f"Svetainės adresas: {SITE_URL}")
    app.run(debug=debug, host=host, port=port)
