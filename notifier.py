"""GitHub Issues reporter.

Strategy:
- Label all scanner issues with 'nse-scanner-report'
- On each run: archive issues older than 7 days, close previous open, create today's
- Uses GITHUB_TOKEN (zero extra secrets)
- Open setup lifecycle is tracked in DB; each day's issue shows resolved/still-open
- Idempotent: if an open issue for today already exists, update it instead of creating a new one
"""
import logging
import os
import json
import urllib.request
import urllib.error
from datetime import date, datetime, timezone, timedelta
from typing import List

log = logging.getLogger(__name__)

REPO         = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_BASE     = "https://api.github.com"
LABEL_NAME   = "nse-scanner-report"
KEEP_DAYS    = 7
MAX_PER_SIDE = 20

# Pre-computed emoji constants (avoids backslash-in-f-string on Python < 3.12)
_GREEN  = "\U0001f7e2"   # 🟢
_YELLOW = "\U0001f7e1"   # 🟡
_RED    = "\U0001f534"   # 🔴
_FIRE   = "\U0001f525"   # 🔥
_UP     = "\u2b06\ufe0f" # ⬆️
_TICK   = "\u2705"       # ✅
_CROSS  = "\u274c"       # ❌
_CIRCLE = "\u26aa"       # ⚪
_NEW    = "\U0001f195"   # 🆕
_CLIP   = "\U0001f4cb"   # 📋
_CHART  = "\U0001f4ca"   # 📊
_BULL   = "\u25b2"       # ▲
_BEAR   = "\u25bc"       # ▼
_DASH   = "\u2014"       # —
_ARROW  = "\u2192"       # →
_NBSP   = "\u00a0"       # non-breaking space
_NNBSP  = "\u202f"       # narrow non-breaking space
_TREND_UP   = "\u2197\ufe0f"  # ↗️ price above EMA
_TREND_DOWN = "\u2198\ufe0f"  # ↘️ price below EMA


def _gh_request(method: str, path: str, body: dict = None):
    url     = f"{API_BASE}{path}"
    data    = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "nse-scanner",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read()) if resp.status not in (204,) else {}
    except urllib.error.HTTPError as e:
        log.warning("GitHub API %s %s -> %s: %s", method, path, e.code, e.read())
        return None


def _ensure_label():
    result = _gh_request("GET", f"/repos/{REPO}/labels/{LABEL_NAME}")
    if result is None:
        _gh_request("POST", f"/repos/{REPO}/labels", {
            "name": LABEL_NAME, "color": "0075ca",
            "description": "Daily NSE scanner report",
        })
        log.info("Created label '%s'", LABEL_NAME)


def _get_scanner_issues():
    issues, page = [], 1
    while True:
        batch = _gh_request(
            "GET",
            f"/repos/{REPO}/issues?labels={LABEL_NAME}&state=all&per_page=50&page={page}"
        )
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return issues


def _archive_old_issues():
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    for issue in _get_scanner_issues():
        created_at = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
        if created_at < cutoff:
            n = issue["number"]
            _gh_request("PATCH", f"/repos/{REPO}/issues/{n}", {
                "state": "closed",
                "title": f"[ARCHIVED] {issue['title']}",
            })
            log.info("Archived issue #%d", n)


def _close_previous_open_issues(today_str: str):
    """Close any open scanner issue that is NOT today's."""
    for issue in _get_scanner_issues():
        if issue["state"] == "open" and today_str not in issue["title"]:
            _gh_request("PATCH", f"/repos/{REPO}/issues/{issue['number']}",
                        {"state": "closed"})
            log.info("Closed previous issue #%d", issue["number"])


def _find_todays_issue(today_str: str):
    """Return the existing open issue for today, or None."""
    for issue in _get_scanner_issues():
        if issue["state"] == "open" and today_str in issue["title"]:
            return issue
    return None


def send_daily_report(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict] = None,
):
    if not GITHUB_TOKEN or not REPO:
        log.error("GITHUB_TOKEN or GITHUB_REPOSITORY not set")
        return

    today_str = str(scan_date)
    _ensure_label()
    _archive_old_issues()
    _close_previous_open_issues(today_str)

    title = f"NSE Scanner {_DASH} {scan_date} | {len(new_signals)} new setup(s)"
    body  = _build_body(new_signals, resolved_signals, scan_date, structure_data or [])

    # Idempotency: update today's issue if it already exists, else create
    existing = _find_todays_issue(today_str)
    if existing:
        issue = _gh_request("PATCH", f"/repos/{REPO}/issues/{existing['number']}", {
            "title": title, "body": body,
        })
        if issue:
            log.info("Issue updated (idempotent re-run): #%d %s %s",
                     issue["number"], _DASH, issue["html_url"])
        else:
            log.error("Failed to update existing GitHub issue")
    else:
        issue = _gh_request("POST", f"/repos/{REPO}/issues", {
            "title": title, "body": body, "labels": [LABEL_NAME],
        })
        if issue:
            log.info("Issue created: #%d %s %s", issue["number"], _DASH, issue["html_url"])
        else:
            log.error("Failed to create GitHub issue")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rsi_badge(rsi: float, side: str) -> str:
    if side == "long":
        tag = _GREEN if rsi >= 60 else _YELLOW if rsi >= 50 else _RED
    else:
        tag = _RED if rsi <= 40 else _YELLOW if rsi <= 50 else _GREEN
    return f"{tag}{_NNBSP}{rsi:.1f}"


def _vol_badge(ratio: float) -> str:
    tag = _FIRE if ratio >= 2.0 else _UP if ratio >= 1.5 else _TICK
    return f"{tag}{_NNBSP}{ratio:.2f}x"


def _ema_line(cmp: float, ema21: float, ema63: float) -> str:
    """Format EMA 21 and EMA 63 with directional arrows vs CMP."""
    arrow21 = _TREND_UP if cmp >= ema21 else _TREND_DOWN
    arrow63 = _TREND_UP if cmp >= ema63 else _TREND_DOWN
    return (
        f"- EMA21: {arrow21}{_NNBSP}**{ema21}** &nbsp;|&nbsp; "
        f"EMA63: {arrow63}{_NNBSP}**{ema63}**\n"
    )


def _swing_paragraph(s: dict) -> str:
    """One stock block in the Market Structure Review section."""
    sym     = s["symbol"].replace(".NS", "")
    cmp     = s["current_price"]
    highs   = s["pivot_highs"]
    lows    = s["pivot_lows"]
    zl, zh  = s.get("zone_low"), s.get("zone_high")
    entry   = s.get("entry")
    stop    = s.get("stop")
    target  = s.get("target")
    rr      = s.get("rr")
    weekly  = s["weekly_structure"]
    rsi_val = s.get("rsi_latest")
    vol_val = s.get("vol_ratio_latest")
    ema21   = s.get("ema21")
    ema63   = s.get("ema63")
    dstruct = s["daily_structure"]

    rsi_line = (
        f"- RSI: {_rsi_badge(rsi_val, dstruct)} &nbsp;|&nbsp; "
        f"Vol ratio: {_vol_badge(vol_val)}\n"
        if rsi_val is not None and vol_val is not None
        else ""
    )
    ema_line_str = (
        _ema_line(cmp, ema21, ema63)
        if ema21 is not None and ema63 is not None
        else ""
    )
    levels_line = (
        f"- **Entry:** {entry}{_NBSP}|{_NBSP}**Stop:** {stop}"
        f"{_NBSP}|{_NBSP}**Target:** {target}{_NBSP}|{_NBSP}**R:R** {rr}R\n"
        if entry and stop and target
        else "- _No zone close enough to price for level calculation_\n"
    )
    zone_line = f"- Zone: **{zl} {_DASH} {zh}**\n" if zl else "- Zone: _none identified_\n"

    if dstruct == "bullish":
        hh = f" {_ARROW} ".join(f"**{p}** ({d})" for d, p in highs)
        hl = f" {_ARROW} ".join(f"**{p}** ({d})" for d, p in lows)
        if weekly == "bullish":
            weekly_note = f"Weekly also bullish {_DASH} high conviction {_GREEN}"
        elif weekly == "neutral":
            weekly_note = f"Weekly neutral {_DASH} daily leading {_CIRCLE}"
        else:
            weekly_note = f"Weekly bearish {_DASH} counter-trend caution {_RED}"
        return (
            f"**{sym}** &nbsp;`CMP: {cmp}` &nbsp;`BULLISH`\n"
            f"- HH: {hh}\n- HL: {hl}\n"
            + zone_line + rsi_line + ema_line_str + levels_line
            + f"- {weekly_note}\n\n"
        )
    else:
        lh = f" {_ARROW} ".join(f"**{p}** ({d})" for d, p in highs)
        ll = f" {_ARROW} ".join(f"**{p}** ({d})" for d, p in lows)
        if weekly == "bearish":
            weekly_note = f"Weekly also bearish {_DASH} high conviction {_RED}"
        elif weekly == "neutral":
            weekly_note = f"Weekly neutral {_DASH} daily leading {_CIRCLE}"
        else:
            weekly_note = f"Weekly bullish {_DASH} counter-trend caution {_GREEN}"
        return (
            f"**{sym}** &nbsp;`CMP: {cmp}` &nbsp;`BEARISH`\n"
            f"- LH: {lh}\n- LL: {ll}\n"
            + zone_line + rsi_line + ema_line_str + levels_line
            + f"- {weekly_note}\n\n"
        )


def _build_body(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict],
) -> str:

    # ── New signals ───────────────────────────────────────────────────────────
    if new_signals:
        rows  = "| Symbol | Side | CMP | Confirm Date | Entry | Stop | Target | R:R | RSI | Vol | Zone | Retest# | Score |\n"
        rows += "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        for s in new_signals:
            rr = ""
            if s.get("target_price") and s.get("stop_loss") and s.get("entry_price"):
                risk   = abs(float(s["entry_price"]) - float(s["stop_loss"]))
                reward = abs(float(s["target_price"]) - float(s["entry_price"]))
                rr     = f"{reward/risk:.1f}R" if risk > 0 else "-"
            rsi_disp  = _rsi_badge(float(s.get("rsi_at_confirm") or 0), s["side"])
            vol_disp  = _vol_badge(float(s.get("volume_ratio") or 0))
            side_text = f"{_GREEN} LONG" if s["side"] == "long" else f"{_RED} SHORT"
            cmp_val   = s.get("cmp", _DASH)
            tgt_val   = s.get("target_price", _DASH)
            rows += (
                f"| **{s['symbol'].replace('.NS', '')}** "
                f"| {side_text} "
                f"| **{cmp_val}** "
                f"| {s.get('confirmation_date', s['scan_date'])} "
                f"| {s['entry_price']} "
                f"| {s['stop_loss']} "
                f"| {tgt_val} "
                f"| {rr} "
                f"| {rsi_disp} "
                f"| {vol_disp} "
                f"| {s['zone_low']} {_DASH} {s['zone_high']} "
                f"| {s.get('retest_number', 1)} "
                f"| {s.get('quality_score', '')} |\n"
            )
        new_section = f"## {_NEW} New Confirmed Setups\n\n{rows}\n"
    else:
        new_section = (
            f"## {_NEW} New Confirmed Setups\n\n"
            "_No new confirmed setups today._\n\n"
            "> **Why no setups?** A confirmed setup requires **all five** conditions to be met "
            "on the same bar: (1) daily structure HH+HL or LH+LL, (2) price retest of a "
            "supply/demand zone, (3) confirmation candle closing beyond the prior bar's high/low, "
            "(4) RSI \u2265 50 and rising (longs) or \u2264 50 and falling (shorts), "
            "(5) confirmation bar volume \u2265 1.3\u00d7 the 20-day average. "
            "On quiet or indecisive days all five rarely align \u2014 that is by design. "
            "Use the Market Structure Review below to monitor stocks approaching zones "
            "and prepare watchlists for the next session.\n\n"
        )

    # ── Resolved / open updates ───────────────────────────────────────────────
    open_setup_note = (
        f"> Each day a **new issue** is created. Open setups from previous days are "
        "tracked in the database and checked against today's high/low/close. "
        "If stop, target or zone invalidation is triggered, the signal is marked resolved "
        "and appears in this table. Issues older than 7 days are archived automatically.\n\n"
    )
    if resolved_signals:
        rows  = "| Symbol | Side | Rec. On | Resolved On | Status | Reason |\n"
        rows += "|---|---|---|---|---|---|\n"
        for s in resolved_signals:
            if s.get("status") == "target_hit":
                status_emoji = f"{_TICK} Target Hit"
            elif s.get("status") == "stop_hit":
                status_emoji = f"{_CROSS} Stop Hit"
            else:
                status_emoji = f"{_CIRCLE} Invalidated"
            resolved_val = s.get("resolved_at", _DASH)
            rows += (
                f"| **{s['symbol'].replace('.NS', '')}** "
                f"| {s['side'].upper()} "
                f"| {s['scan_date']} "
                f"| {resolved_val} "
                f"| {status_emoji} "
                f"| {s.get('resolution_reason', '')} |\n"
            )
        resolved_section = (
            f"## {_CLIP} Updates on Open Setups\n\n"
            + open_setup_note
            + rows + "\n"
        )
    else:
        resolved_section = (
            f"## {_CLIP} Updates on Open Setups\n\n"
            + open_setup_note
            + "_No open setups were resolved today._\n\n"
        )

    # ── Structure narrative ───────────────────────────────────────────────────
    bullish = [s for s in structure_data if s["daily_structure"] == "bullish"][:MAX_PER_SIDE]
    bearish = [s for s in structure_data if s["daily_structure"] == "bearish"][:MAX_PER_SIDE]

    struct_section = (
        f"## {_CHART} Market Structure Review {_DASH} Watchlist Builder\n\n"
        "> **How to use this section:** These stocks are in a confirmed daily swing structure "
        "(HH+HL = bullish, LH+LL = bearish) but have **not yet met all five signal conditions**. "
        "Use them as a **watchlist for the next 1\u20133 sessions**. "
        "Watch for price to pull back into the listed Zone, then look for a confirmation candle "
        "with RSI turning in the trend direction and volume \u2265 1.3\u00d7 average \u2014 "
        "that is your manual entry trigger. "
        "Entry / Stop / Target levels are projections based on the nearest zone + ATR buffer; "
        f"always verify on your chart before acting. "
        f"Showing up to {MAX_PER_SIDE} stocks per side, sorted by structure quality.\n\n"
    )

    if bullish:
        struct_section += f"### {_BULL} Bullish {_DASH} HH + HL ({len(bullish)} stocks)\n\n"
        struct_section += "".join(_swing_paragraph(s) for s in bullish)
    if bearish:
        struct_section += f"### {_BEAR} Bearish {_DASH} LH + LL ({len(bearish)} stocks)\n\n"
        struct_section += "".join(_swing_paragraph(s) for s in bearish)
    if not bullish and not bearish:
        struct_section += "_No clear structure identified today._\n"

    footer = (
        "---\n"
        f"_Automated scan {_DASH} Nifty 500. Not financial advice. "
        "Verify on charts before trading._"
    )

    return (
        f"# NSE Supply/Demand Scanner {_DASH} {scan_date}\n\n"
        + new_section
        + resolved_section
        + struct_section
        + footer
    )
