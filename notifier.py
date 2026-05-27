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

MAX_PER_SIDE = 20   # max stocks per side in email


def send_daily_report(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict] = None,
):
    subject = f"NSE Scanner — {scan_date} | {len(new_signals)} new setup(s)"
    body    = _build_body(new_signals, resolved_signals, scan_date, structure_data or [])

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())

    log.info("Email sent to %s", EMAIL_TO)


def _swing_paragraph(s: dict) -> str:
    """Build a one-paragraph narrative for a single stock's swing structure."""
    sym    = s["symbol"].replace(".NS", "")
    cmp    = s["current_price"]
    highs  = s["pivot_highs"]   # [(date, price), ...]
    lows   = s["pivot_lows"]
    zl, zh = s.get("zone_low"), s.get("zone_high")
    weekly = s["weekly_structure"]

    if s["daily_structure"] == "bullish":
        # Describe HH sequence
        hh_parts = " → ".join(f"<b>{p}</b> on {d}" for d, p in highs)
        hl_parts = " → ".join(f"<b>{p}</b> on {d}" for d, p in lows)
        zone_str = (
            f"Nearest demand zone: <b>{zl} – {zh}</b>."
            if zl else "No clear demand zone below current price."
        )
        weekly_note = (
            "Weekly is also bullish — high conviction."
            if weekly == "bullish" else
            "Weekly is neutral — daily is leading."
            if weekly == "neutral" else
            "Weekly is bearish — caution, counter-trend on higher TF."
        )
        return f"""
        <div style='margin-bottom:10px;padding:8px 12px;
                    border-left:3px solid #1a7a1a;background:#f9fdf9;
                    font-size:13px;line-height:1.6'>
          <b style='font-size:14px'>{sym}</b>
          &nbsp;<span style='color:#888'>CMP: {cmp}</span>
          &nbsp;<span style='background:#c8e6c9;padding:1px 6px;
                border-radius:3px;font-size:11px'>BULLISH</span><br/>
          Higher Highs: {hh_parts}<br/>
          Higher Lows: {hl_parts}<br/>
          {zone_str} {weekly_note}
        </div>"""
    else:
        # Describe LH/LL sequence
        lh_parts = " → ".join(f"<b>{p}</b> on {d}" for d, p in highs)
        ll_parts = " → ".join(f"<b>{p}</b> on {d}" for d, p in lows)
        zone_str = (
            f"Nearest supply zone: <b>{zl} – {zh}</b>."
            if zl else "No clear supply zone above current price."
        )
        weekly_note = (
            "Weekly is also bearish — high conviction."
            if weekly == "bearish" else
            "Weekly is neutral — daily is leading."
            if weekly == "neutral" else
            "Weekly is bullish — caution, counter-trend on higher TF."
        )
        return f"""
        <div style='margin-bottom:10px;padding:8px 12px;
                    border-left:3px solid #c0392b;background:#fff9f9;
                    font-size:13px;line-height:1.6'>
          <b style='font-size:14px'>{sym}</b>
          &nbsp;<span style='color:#888'>CMP: {cmp}</span>
          &nbsp;<span style='background:#ffcdd2;padding:1px 6px;
                border-radius:3px;font-size:11px'>BEARISH</span><br/>
          Lower Highs: {lh_parts}<br/>
          Lower Lows: {ll_parts}<br/>
          {zone_str} {weekly_note}
        </div>"""


def _build_body(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict],
) -> str:

    # ── New signals ───────────────────────────────────────────────
    rows_new = ""
    for s in new_signals:
        rr = ""
        if s.get("target_price") and s.get("stop_loss") and s.get("entry_price"):
            risk   = abs(s["entry_price"] - s["stop_loss"])
            reward = abs(s["target_price"] - s["entry_price"])
            rr     = f"{reward/risk:.1f}R" if risk > 0 else "-"
        side_color = "#1a7a1a" if s["side"] == "long" else "#c0392b"
        rows_new += f"""
        <tr>
          <td><b>{s['symbol'].replace('.NS','')}</b></td>
          <td style='color:{side_color}'>{s['side'].upper()}</td>
          <td>{s.get('confirmation_date', s['scan_date'])}</td>
          <td><b>{s['entry_price']}</b></td>
          <td>{s['stop_loss']}</td>
          <td>{s.get('target_price','—')}</td>
          <td>{rr}</td>
          <td style='font-size:12px'>{s['zone_low']} – {s['zone_high']}</td>
          <td>{s.get('retest_number',1)}</td>
          <td>{s.get('quality_score','')}</td>
        </tr>"""

    new_html = (
        f"""<table border=1 cellpadding=6 cellspacing=0
             style="border-collapse:collapse;font-size:13px">
          <tr style="background:#e8f5e9">
            <th>Symbol</th><th>Side</th><th>Confirm Date</th><th>Entry</th>
            <th>Stop</th><th>Target</th><th>R:R</th><th>Zone</th><th>Retest#</th><th>Score</th>
          </tr>{rows_new}</table>"""
        if new_signals else
        "<p style='color:#888'>No new confirmed setups today.</p>"
    )

    # ── Resolved ────────────────────────────────────────────────
    rows_res = ""
    for s in resolved_signals:
        sc = {"target_hit": "#1a7a1a", "stop_hit": "#c0392b",
              "invalidated": "#888"}.get(s.get("status", ""), "#333")
        rows_res += f"""
        <tr>
          <td><b>{s['symbol'].replace('.NS','')}</b></td>
          <td>{s['side'].upper()}</td><td>{s['scan_date']}</td>
          <td>{s.get('resolved_at','—')}</td>
          <td style='color:{sc}'>{s.get('status','').replace('_',' ').title()}</td>
          <td>{s.get('resolution_reason','')}</td>
        </tr>"""

    resolved_html = (
        f"""<table border=1 cellpadding=6 cellspacing=0
             style="border-collapse:collapse;font-size:13px">
          <tr style="background:#f0f0f0">
            <th>Symbol</th><th>Side</th><th>Rec. On</th>
            <th>Resolved On</th><th>Status</th><th>Reason</th>
          </tr>{rows_res}</table>"""
        if resolved_signals else
        "<p style='color:#888'>No updates on open setups today.</p>"
    )

    # ── Structure narrative ────────────────────────────────────────
    bullish = [s for s in structure_data if s["daily_structure"] == "bullish"][:MAX_PER_SIDE]
    bearish = [s for s in structure_data if s["daily_structure"] == "bearish"][:MAX_PER_SIDE]

    bull_blocks = "".join(_swing_paragraph(s) for s in bullish)
    bear_blocks = "".join(_swing_paragraph(s) for s in bearish)

    structure_html = f"""
    <h3>📊 Market Structure Review &mdash; for your backtesting</h3>
    <p style='font-size:12px;color:#555'>
      Showing up to {MAX_PER_SIDE} stocks per side with confirmed daily swing structure.
      Verify these on your charts before acting.
    </p>
    {'<h4 style="color:#1a7a1a">▲ Bullish (HH + HL) — ' + str(len(bullish)) + ' stocks</h4>' + bull_blocks if bullish else ''}
    {'<h4 style="color:#c0392b">▼ Bearish (LH + LL) — ' + str(len(bearish)) + ' stocks</h4>' + bear_blocks if bearish else ''}
    """

    return f"""
    <html><body style='font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:920px'>
    <h2 style='color:#01696f'>NSE Supply/Demand Scanner &mdash; {scan_date}</h2>

    <h3>🆕 New Confirmed Setups</h3>
    {new_html}

    <h3>📋 Updates on Open Setups</h3>
    {resolved_html}

    {structure_html}

    <hr/>
    <p style='color:#888;font-size:11px'>
      Automated scan across Nifty 500. Not financial advice. Verify on charts before trading.
    </p>
    </body></html>
    """
