"""Gmail SMTP email notifier."""
import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from config import (
    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT,
    EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO,
)

log = logging.getLogger(__name__)


def send_daily_report(new_signals: List[dict], resolved_signals: List[dict], scan_date: date):
    if not new_signals and not resolved_signals:
        log.info("No signals to report — skipping email")
        return

    subject = f"NSE Scanner — {scan_date} | {len(new_signals)} new setup(s)"
    body = _build_body(new_signals, resolved_signals, scan_date)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())

    log.info("Email sent to %s", EMAIL_TO)


def _build_body(new_signals: List[dict], resolved_signals: List[dict], scan_date: date) -> str:
    rows_new = ""
    for s in new_signals:
        rr = ""
        if s.get("target_price") and s.get("stop_loss") and s.get("entry_price"):
            risk = abs(s["entry_price"] - s["stop_loss"])
            reward = abs(s["target_price"] - s["entry_price"])
            rr = f"{reward/risk:.1f}R" if risk > 0 else "-"
        rows_new += f"""
        <tr>
          <td><b>{s['symbol']}</b></td>
          <td style='color:{'#1a7a1a' if s['side']=='long' else '#c0392b'}'>{s['side'].upper()}</td>
          <td>{s['scan_date']}</td>
          <td>{s['entry_price']}</td>
          <td>{s['stop_loss']}</td>
          <td>{s.get('target_price','—')}</td>
          <td>{rr}</td>
          <td>{s['zone_low']} – {s['zone_high']}</td>
          <td>{s.get('quality_score','')}</td>
        </tr>"""

    rows_resolved = ""
    for s in resolved_signals:
        status_color = {
            "target_hit": "#1a7a1a",
            "stop_hit": "#c0392b",
            "invalidated": "#888",
        }.get(s.get("status", ""), "#333")
        rows_resolved += f"""
        <tr>
          <td><b>{s['symbol']}</b></td>
          <td>{s['side'].upper()}</td>
          <td>{s['scan_date']}</td>
          <td>{s.get('resolved_at','—')}</td>
          <td style='color:{status_color}'>{s.get('status','').replace('_',' ').title()}</td>
          <td>{s.get('resolution_reason','')}</td>
        </tr>"""

    return f"""
    <html><body style='font-family:Arial,sans-serif;font-size:14px;color:#222'>
    <h2 style='color:#01696f'>NSE Supply/Demand Scanner — {scan_date}</h2>

    <h3>🆕 New Setups Today</h3>
    {'<p>No new setups today.</p>' if not new_signals else ''}
    {'<table border=1 cellpadding=6 cellspacing=0 style="border-collapse:collapse"><tr style="background:#f0f0f0"><th>Symbol</th><th>Side</th><th>Recommended On</th><th>Entry</th><th>Stop</th><th>Target</th><th>R:R</th><th>Zone</th><th>Score</th></tr>' + rows_new + '</table>' if new_signals else ''}

    <h3>📋 Updates on Open Setups</h3>
    {'<p>No updates today.</p>' if not resolved_signals else ''}
    {'<table border=1 cellpadding=6 cellspacing=0 style="border-collapse:collapse"><tr style="background:#f0f0f0"><th>Symbol</th><th>Side</th><th>Recommended On</th><th>Resolved On</th><th>Status</th><th>Reason</th></tr>' + rows_resolved + '</table>' if resolved_signals else ''}

    <hr/><p style='color:#888;font-size:12px'>This is an automated signal. Not financial advice. Always verify before trading.</p>
    </body></html>
    """
