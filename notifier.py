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

MAX_STRUCTURE_ROWS = 25   # cap per side in email to keep it readable


def send_daily_report(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_summary: List[dict] = None,
):
    if not new_signals and not resolved_signals and not structure_summary:
        log.info("No signals and no structure data — skipping email")
        return

    subject = f"NSE Scanner — {scan_date} | {len(new_signals)} new setup(s)"
    body = _build_body(new_signals, resolved_signals, scan_date, structure_summary or [])

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


def _build_body(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_summary: List[dict],
) -> str:

    # ── New signals table ────────────────────────────────────────────
    rows_new = ""
    for s in new_signals:
        rr = ""
        if s.get("target_price") and s.get("stop_loss") and s.get("entry_price"):
            risk   = abs(s["entry_price"] - s["stop_loss"])
            reward = abs(s["target_price"] - s["entry_price"])
            rr = f"{reward/risk:.1f}R" if risk > 0 else "-"
        side_color = "#1a7a1a" if s["side"] == "long" else "#c0392b"
        rows_new += f"""
        <tr>
          <td><b>{s['symbol']}</b></td>
          <td style='color:{side_color}'>{s['side'].upper()}</td>
          <td>{s.get('confirmation_date', s['scan_date'])}</td>
          <td><b>{s['entry_price']}</b></td>
          <td>{s['stop_loss']}</td>
          <td>{s.get('target_price', '—')}</td>
          <td>{rr}</td>
          <td>{s['zone_low']} – {s['zone_high']}</td>
          <td>{s.get('retest_number', 1)}</td>
          <td>{s.get('quality_score', '')}</td>
        </tr>"""

    new_signals_html = ""
    if new_signals:
        new_signals_html = f"""
        <table border=1 cellpadding=6 cellspacing=0 style="border-collapse:collapse;font-size:13px">
          <tr style="background:#e8f5e9">
            <th>Symbol</th><th>Side</th><th>Confirm Date</th><th>Entry</th>
            <th>Stop</th><th>Target</th><th>R:R</th><th>Zone</th><th>Retest#</th><th>Score</th>
          </tr>
          {rows_new}
        </table>"""
    else:
        new_signals_html = "<p style='color:#888'>No new confirmed setups today.</p>"

    # ── Resolved signals table ──────────────────────────────────────
    rows_resolved = ""
    for s in resolved_signals:
        status_color = {
            "target_hit":  "#1a7a1a",
            "stop_hit":    "#c0392b",
            "invalidated": "#888",
        }.get(s.get("status", ""), "#333")
        rows_resolved += f"""
        <tr>
          <td><b>{s['symbol']}</b></td>
          <td>{s['side'].upper()}</td>
          <td>{s['scan_date']}</td>
          <td>{s.get('resolved_at', '—')}</td>
          <td style='color:{status_color}'>{s.get('status','').replace('_',' ').title()}</td>
          <td>{s.get('resolution_reason','')}</td>
        </tr>"""

    resolved_html = ""
    if resolved_signals:
        resolved_html = f"""
        <table border=1 cellpadding=6 cellspacing=0 style="border-collapse:collapse;font-size:13px">
          <tr style="background:#f0f0f0">
            <th>Symbol</th><th>Side</th><th>Recommended On</th>
            <th>Resolved On</th><th>Status</th><th>Reason</th>
          </tr>
          {rows_resolved}
        </table>"""
    else:
        resolved_html = "<p style='color:#888'>No updates on open setups today.</p>"

    # ── Market structure summary ──────────────────────────────────────
    bullish_stocks = sorted(
        [s for s in structure_summary if s["daily_structure"] == "bullish"],
        key=lambda x: x["symbol"]
    )[:MAX_STRUCTURE_ROWS]

    bearish_stocks = sorted(
        [s for s in structure_summary if s["daily_structure"] == "bearish"],
        key=lambda x: x["symbol"]
    )[:MAX_STRUCTURE_ROWS]

    def structure_rows(stocks, side):
        rows = ""
        for s in stocks:
            zone_str = (
                f"{s['zone_low']} – {s['zone_high']}"
                if s.get("zone_low") else "— (no zone below price)"
            )
            weekly_badge = (
                f"<span style='background:#c8e6c9;padding:1px 5px;border-radius:3px;font-size:11px'>W↑</span>"
                if s["weekly_structure"] == "bullish" else
                f"<span style='background:#ffcdd2;padding:1px 5px;border-radius:3px;font-size:11px'>W↓</span>"
                if s["weekly_structure"] == "bearish" else
                f"<span style='background:#f5f5f5;padding:1px 5px;border-radius:3px;font-size:11px'>W↔</span>"
            )
            rows += f"""
            <tr>
              <td><b>{s['symbol']}</b></td>
              <td>{s['current_price']}</td>
              <td>{weekly_badge}</td>
              <td style='font-family:monospace'>{zone_str}</td>
            </tr>"""
        return rows

    structure_html = ""
    if bullish_stocks or bearish_stocks:
        bull_table = ""
        bear_table = ""
        if bullish_stocks:
            bull_table = f"""
            <h4 style='color:#1a7a1a;margin-top:12px'>▲ Bullish Structure — HH + HL (Demand Zones)</h4>
            <p style='font-size:12px;color:#555'>These stocks are making higher highs and higher lows.
            The zone shown is the nearest demand zone below current price — watch for a retest.</p>
            <table border=1 cellpadding=5 cellspacing=0 style="border-collapse:collapse;font-size:12px">
              <tr style="background:#e8f5e9"><th>Symbol</th><th>CMP</th><th>Weekly</th><th>Nearest Demand Zone</th></tr>
              {structure_rows(bullish_stocks, 'long')}
            </table>"""

        if bearish_stocks:
            bear_table = f"""
            <h4 style='color:#c0392b;margin-top:16px'>▼ Bearish Structure — LH + LL (Supply Zones)</h4>
            <p style='font-size:12px;color:#555'>These stocks are making lower highs and lower lows.
            The zone shown is the nearest supply zone above current price — watch for a rejection.</p>
            <table border=1 cellpadding=5 cellspacing=0 style="border-collapse:collapse;font-size:12px">
              <tr style="background:#ffebee"><th>Symbol</th><th>CMP</th><th>Weekly</th><th>Nearest Supply Zone</th></tr>
              {structure_rows(bearish_stocks, 'short')}
            </table>"""

        structure_html = f"""
        <h3>📊 Market Structure Summary</h3>
        <p style='font-size:12px;color:#555'>
          Showing up to {MAX_STRUCTURE_ROWS} stocks per side with confirmed daily structure.
          <b>W↑</b> = weekly also bullish (high conviction). <b>W↔</b> = weekly neutral (daily leading).
          Use this section for your own backtesting review.
        </p>
        {bull_table}
        {bear_table}"""
    else:
        structure_html = "<h3>📊 Market Structure Summary</h3><p style='color:#888'>No clear structure identified today.</p>"

    return f"""
    <html><body style='font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:900px'>
    <h2 style='color:#01696f'>NSE Supply/Demand Scanner — {scan_date}</h2>

    <h3>🆕 New Confirmed Setups</h3>
    {new_signals_html}

    <h3>📋 Updates on Open Setups</h3>
    {resolved_html}

    {structure_html}

    <hr/>
    <p style='color:#888;font-size:11px'>
      Automated scan across Nifty 500. Not financial advice. Always verify before trading.<br/>
      Confirmed = close beyond prior bar high/low after zone retest.
    </p>
    </body></html>
    """
