"""GitHub Issues reporter.

Strategy:
- Label all scanner issues with 'nse-scanner-report'
- On each run: archive issues older than 7 days, close previous open, create today's
- Uses GITHUB_TOKEN (zero extra secrets)
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


def _close_previous_open_issues():
    today_str = str(date.today())
    for issue in _get_scanner_issues():
        if issue["state"] == "open" and today_str not in issue["title"]:
            _gh_request("PATCH", f"/repos/{REPO}/issues/{issue['number']}",
                        {"state": "closed"})
            log.info("Closed previous issue #%d", issue["number"])


def send_daily_report(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict] = None,
):
    if not GITHUB_TOKEN or not REPO:
        log.error("GITHUB_TOKEN or GITHUB_REPOSITORY not set")
        return

    _ensure_label()
    _archive_old_issues()
    _close_previous_open_issues()

    title = f"NSE Scanner — {scan_date} | {len(new_signals)} new setup(s)"
    body  = _build_body(new_signals, resolved_signals, scan_date, structure_data or [])

    issue = _gh_request("POST", f"/repos/{REPO}/issues", {
        "title": title, "body": body, "labels": [LABEL_NAME],
    })
    if issue:
        log.info("Issue created: #%d — %s", issue["number"], issue["html_url"])
    else:
        log.error("Failed to create GitHub issue")


def _swing_paragraph(s: dict) -> str:
    sym    = s["symbol"].replace(".NS", "")
    cmp    = s["current_price"]
    highs  = s["pivot_highs"]
    lows   = s["pivot_lows"]
    zl, zh = s.get("zone_low"), s.get("zone_high")
    entry  = s.get("entry")
    stop   = s.get("stop")
    target = s.get("target")
    rr     = s.get("rr")
    weekly = s["weekly_structure"]

    # Trade levels line
    if entry and stop and target:
        levels_line = (
            f"- **Entry:** {entry} &nbsp;|&nbsp; "
            f"**Stop:** {stop} &nbsp;|&nbsp; "
            f"**Target:** {target} &nbsp;|&nbsp; "
            f"**R:R** {rr}R\n"
        )
    else:
        levels_line = "- _No zone close enough to price for level calculation_\n"

    # Zone line
    zone_line = (
        f"- Zone: **{zl} – {zh}**\n" if zl
        else "- Zone: _none identified_\n"
    )

    if s["daily_structure"] == "bullish":
        hh = " → ".join(f"**{p}** ({d})" for d, p in highs)
        hl = " → ".join(f"**{p}** ({d})" for d, p in lows)
        weekly_note = (
            "Weekly also bullish — high conviction 🟢" if weekly == "bullish" else
            "Weekly neutral — daily leading ⚪" if weekly == "neutral" else
            "Weekly bearish — counter-trend caution 🔴"
        )
        return (
            f"**{sym}** &nbsp;`CMP {cmp}` &nbsp;`BULLISH`\n"
            f"- HH: {hh}\n"
            f"- HL: {hl}\n"
            + zone_line
            + levels_line
            + f"- {weekly_note}\n\n"
        )
    else:
        lh = " → ".join(f"**{p}** ({d})" for d, p in highs)
        ll = " → ".join(f"**{p}** ({d})" for d, p in lows)
        weekly_note = (
            "Weekly also bearish — high conviction 🔴" if weekly == "bearish" else
            "Weekly neutral — daily leading ⚪" if weekly == "neutral" else
            "Weekly bullish — counter-trend caution 🟢"
        )
        return (
            f"**{sym}** &nbsp;`CMP {cmp}` &nbsp;`BEARISH`\n"
            f"- LH: {lh}\n"
            f"- LL: {ll}\n"
            + zone_line
            + levels_line
            + f"- {weekly_note}\n\n"
        )


def _build_body(
    new_signals: List[dict],
    resolved_signals: List[dict],
    scan_date: date,
    structure_data: List[dict],
) -> str:

    # -- New signals ----------------------------------------------------------
    if new_signals:
        rows = "| Symbol | Side | Confirm Date | Entry | Stop | Target | R:R | Zone | Retest# | Score |\n"
        rows += "|---|---|---|---|---|---|---|---|---|---|\n"
        for s in new_signals:
            rr = ""
            if s.get("target_price") and s.get("stop_loss") and s.get("entry_price"):
                risk   = abs(s["entry_price"] - s["stop_loss"])
                reward = abs(s["target_price"] - s["entry_price"])
                rr     = f"{reward/risk:.1f}R" if risk > 0 else "-"
            rows += (
                f"| **{s['symbol'].replace('.NS','')}** "
                f"| {'🟢 LONG' if s['side']=='long' else '🔴 SHORT'} "
                f"| {s.get('confirmation_date', s['scan_date'])} "
                f"| **{s['entry_price']}** "
                f"| {s['stop_loss']} "
                f"| {s.get('target_price','—')} "
                f"| {rr} "
                f"| {s['zone_low']} – {s['zone_high']} "
                f"| {s.get('retest_number',1)} "
                f"| {s.get('quality_score','')} |\n"
            )
        new_section = f"## 🆕 New Confirmed Setups\n\n{rows}\n"
    else:
        new_section = "## 🆕 New Confirmed Setups\n\n_No new confirmed setups today._\n\n"

    # -- Resolved -------------------------------------------------------------
    if resolved_signals:
        rows = "| Symbol | Side | Rec. On | Resolved On | Status | Reason |\n"
        rows += "|---|---|---|---|---|---|\n"
        for s in resolved_signals:
            status_emoji = (
                "✅ Target Hit" if s.get("status") == "target_hit" else
                "❌ Stop Hit"   if s.get("status") == "stop_hit"   else
                "⚪ Invalidated"
            )
            rows += (
                f"| **{s['symbol'].replace('.NS','')}** "
                f"| {s['side'].upper()} "
                f"| {s['scan_date']} "
                f"| {s.get('resolved_at','—')} "
                f"| {status_emoji} "
                f"| {s.get('resolution_reason','')} |\n"
            )
        resolved_section = f"## 📋 Updates on Open Setups\n\n{rows}\n"
    else:
        resolved_section = "## 📋 Updates on Open Setups\n\n_No updates on open setups today._\n\n"

    # -- Structure narrative --------------------------------------------------
    bullish = [s for s in structure_data if s["daily_structure"] == "bullish"][:MAX_PER_SIDE]
    bearish = [s for s in structure_data if s["daily_structure"] == "bearish"][:MAX_PER_SIDE]

    struct_section = "## 📊 Market Structure Review — for backtesting\n\n"
    struct_section += (
        f"> Up to {MAX_PER_SIDE} stocks per side. "
        "**Entry** = projected zone entry | **Stop** = below/above zone + ATR buffer | "
        "**Target** = nearest opposite zone or 2R. Verify on charts before acting.\n\n"
    )

    if bullish:
        struct_section += f"### ▲ Bullish — HH + HL ({len(bullish)} stocks)\n\n"
        struct_section += "".join(_swing_paragraph(s) for s in bullish)

    if bearish:
        struct_section += f"### ▼ Bearish — LH + LL ({len(bearish)} stocks)\n\n"
        struct_section += "".join(_swing_paragraph(s) for s in bearish)

    if not bullish and not bearish:
        struct_section += "_No clear structure identified today._\n"

    footer = (
        "---\n"
        "_Automated scan — Nifty 500. Not financial advice. Verify on charts before trading._"
    )

    return (
        f"# NSE Supply/Demand Scanner — {scan_date}\n\n"
        + new_section
        + resolved_section
        + struct_section
        + footer
    )
