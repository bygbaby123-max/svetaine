"""El. laiškų siuntimas.

Serveryje (Render) naudojama BREVO API per HTTPS (443 portas - Render blokuoja
SMTP 587/465/25 portus). Lokaliai naudojamas Gmail SMTP su App Password.
"""
import json
import os
import smtplib
import ssl
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def smtp_configured():
    """Ar yra bent vienas siuntimo budas (Brevo API arba Gmail SMTP)."""
    if os.getenv("BREVO_API_KEY", "").strip():
        return True
    return bool(os.getenv("SMTP_EMAIL", "").strip() and os.getenv("SMTP_APP_PASSWORD", "").strip())


def _send_brevo(api_key, to_address, subject, html_body, text_body=""):
    sender_email = (os.getenv("BREVO_SENDER", "").strip()
                    or os.getenv("SMTP_EMAIL", "").strip())
    sender_name = os.getenv("BREVO_SENDER_NAME", "ManoSvetaine").strip()
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_address}],
        "subject": subject,
        "htmlContent": html_body,
    }
    if text_body:
        payload["textContent"] = text_body

    req = urllib.request.Request(
        BREVO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            ok = 200 <= resp.status < 300
        if ok:
            print(f"[EL. LAIŠKAS IŠSIŲSTAS per Brevo] Kam: {to_address} | Tema: {subject}")
        else:
            print(f"[BREVO KLAIDA] Kam: {to_address} | HTTP {resp.status}")
        return ok
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        print(f"[BREVO KLAIDA] {to_address}: HTTP {exc.code} {detail}")
        return False
    except Exception as exc:
        print(f"[BREVO KLaida] {to_address}: {exc}")
        return False


def send_email(to_address, subject, html_body, text_body=""):
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    if api_key:
        return _send_brevo(api_key, to_address, subject, html_body, text_body)

    # --- Gmail SMTP (lokali versija) ---
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    user = os.getenv("SMTP_EMAIL", "").strip()
    password = os.getenv("SMTP_APP_PASSWORD", "").strip()

    if not user or not password:
        print(f"[EL. LAIŠKAS NEKONFIGŪRUOTAS] Kam: {to_address} | Tema: {subject}")
        return False

    message = MIMEMultipart("alternative")
    message["From"] = user
    message["To"] = to_address
    message["Subject"] = subject
    if text_body:
        message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, [to_address], message.as_string())
        print(f"[EL. LAIŠKAS IŠSIŲSTAS] Kam: {to_address} | Tema: {subject}")
        return True
    except Exception as exc:
        print(f"[EL. LAIŠKO KLAIDA] {to_address}: {exc}")
        return False
