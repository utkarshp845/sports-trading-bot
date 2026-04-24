"""Daily report generation for the Kalshi trading bot."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = "trades.db"
REPORTS_DIR = "reports"


def generate_daily_report(date_str: str) -> str:
    con = sqlite3.connect(DB_PATH)

    row = con.execute(
        "SELECT start_bal, end_bal, trades FROM daily_stats WHERE date=?",
        (date_str,),
    ).fetchone()

    start_bal = float(row[0]) if row and row[0] is not None else 0.0
    end_bal = float(row[1]) if row and row[1] is not None else start_bal
    trades_count = int(row[2]) if row and row[2] is not None else 0

    trades = con.execute(
        """SELECT ts, ticker, team, side, contracts, price_cents, edge, order_id, status
           FROM trades WHERE ts LIKE ? ORDER BY ts""",
        (f"{date_str}%",),
    ).fetchall()
    con.close()

    net_pnl = end_bal - start_bal
    net_pct = (net_pnl / start_bal * 100) if start_bal > 0 else 0.0
    total_wagered = sum(t[4] * t[5] / 100 for t in trades)

    sign = "+" if net_pnl >= 0 else ""
    lines = [
        "=" * 65,
        f"  Kalshi Trading Bot — Daily Report  {date_str}",
        "=" * 65,
        "",
        f"  Balance      ${start_bal:>8.2f}  →  ${end_bal:>8.2f}",
        f"  Net P&L      {sign}${net_pnl:.2f}  ({sign}{net_pct:.1f}%)",
        f"  Trades       {trades_count}",
        f"  Wagered      ${total_wagered:.2f}",
        "",
    ]

    if trades:
        hdr = f"  {'Time':8}  {'Ticker':<28}  {'Team':<22}  {'S':4}  {'Qty':>3}  {'Price':>5}  {'Edge':>6}  {'Cost':>6}"
        lines += [
            "  Trades",
            "  " + "-" * 90,
            hdr,
            "  " + "-" * 90,
        ]
        for t in trades:
            ts, ticker, team, side, contracts, price_cents, edge, order_id, status = t
            time_str = ts[11:19] if len(ts) >= 19 else ts
            cost = contracts * price_cents / 100
            edge_pct = (edge or 0.0) * 100
            lines.append(
                f"  {time_str}  {ticker:<28}  {(team or ''):<22}  "
                f"{side.upper():4}  {contracts:>3}  {price_cents:>3}¢  "
                f"{edge_pct:>5.1f}%  ${cost:>5.2f}"
            )
        lines.append("")
    else:
        lines += ["  No trades placed today.", ""]

    lines += [
        f"  Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 65,
    ]
    return "\n".join(lines)


def save_daily_report(date_str: str) -> str:
    """Write the report to reports/<date>.txt and return the path."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report = generate_daily_report(date_str)
    path = os.path.join(REPORTS_DIR, f"{date_str}.txt")
    with open(path, "w") as f:
        f.write(report)
        f.write("\n")
    return path
