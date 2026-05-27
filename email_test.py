"""Send a test email to confirm SMTP credentials work.
Usage:  python email_test.py
Requires: EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO in environment or .env
"""
import smtplib
import sys
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
USER = os.environ.get("EMAIL_USER")
PASS = os.environ.get("EMAIL_APP_PASSWORD")
TO   = os.environ.get("EMAIL_TO")

missing = [k for k, v in {"EMAIL_USER": USER, "EMAIL_APP_PASSWORD": PASS, "EMAIL_TO": TO}.items() if not v]
if missing:
    print(f"[email_test] ERROR: Missing env vars: {missing}", file=sys.stderr)
    sys.exit(1)

print(f"[email_test] Sending test email from {USER} to {TO} via {SMTP_HOST}:{SMTP_PORT}...")

msg = MIMEText("""
<html><body>
<h2 style='color:#01696f'>NSE Scanner — Email Test ✅</h2>
<p>If you received this, your Gmail SMTP credentials are working correctly.</p>
<p><b>EMAIL_USER:</b> {user}<br><b>EMAIL_TO:</b> {to}</p>
</body></html>
""".format(user=USER, to=TO), "html")
msg["Subject"] = "NSE Scanner — Email Test"
msg["From"] = USER
msg["To"] = TO

try:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(USER, PASS)
        server.sendmail(USER, TO, msg.as_string())
    print("[email_test] ✅ Test email sent successfully! Check your inbox.")
except smtplib.SMTPAuthenticationError:
    print("[email_test] ❌ Authentication failed.", file=sys.stderr)
    print("  → Make sure EMAIL_APP_PASSWORD is a Gmail App Password, not your login password.", file=sys.stderr)
    print("  → Enable 2-Step Verification first: https://myaccount.google.com/security", file=sys.stderr)
    print("  → Then create App Password: https://myaccount.google.com/apppasswords", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[email_test] ❌ Failed: {e}", file=sys.stderr)
    sys.exit(1)
