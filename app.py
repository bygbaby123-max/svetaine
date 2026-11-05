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
EMAIL_ON_LOGIN = os.getenv("EMAIL_ON_LOGIN", "true").strip().lower() != "false"
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


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Pirmiausia prisijunkite.", "error")
            return redirect(url_for("login", next=request.path))
        if not user["is_admin"]:
            flash("Ši skiltis skirta tik administratoriui.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {"user": current_user(), "google_client_id": GOOGLE_CLIENT_ID}


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

    if EMAIL_ON_LOGIN:
        sent = send_data_email(user, "prisijungimo", "Prisijungimas prie paskyros")
        if not sent:
            warn_if_no_smtp()

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
    if EMAIL_ON_LOGIN:
        send_data_email(user, "prisijungimo", "Prisijungimas su Google")
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
@admin_required
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
@admin_required
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
