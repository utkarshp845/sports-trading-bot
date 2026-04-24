"""
Kalshi NBA sports trading bot.

Run:
    python bot.py

Env vars required (via .env file or shell):
    KALSHI_API_KEY
    ODDS_API_KEY
"""

from __future__ import annotations

import sqlite3
import time
import logging
from datetime import datetime, timezone

import config
from kalshi_client import KalshiClient
from odds_feed import OddsFeed
import strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PATH = "trades.db"


# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            ticker      TEXT    NOT NULL,
            title       TEXT,
            team        TEXT,
            side        TEXT    NOT NULL,
            contracts   INTEGER NOT NULL,
            price_cents INTEGER NOT NULL,
            true_prob   REAL,
            edge        REAL,
            order_id    TEXT,
            status      TEXT    DEFAULT 'placed'
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date        TEXT PRIMARY KEY,
            start_bal   REAL,
            trades      INTEGER DEFAULT 0
        )
    """)
    con.commit()
    con.close()


def log_trade(trade: dict, order_id: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO trades
           (ts, ticker, title, team, side, contracts, price_cents, true_prob, edge, order_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            trade["ticker"],
            trade.get("title", ""),
            trade.get("team", ""),
            trade["side"],
            trade["contracts"],
            trade["price_cents"],
            trade["true_prob"],
            trade["edge"],
            order_id,
        ),
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    con.execute(
        "INSERT INTO daily_stats(date, trades) VALUES(?,1) "
        "ON CONFLICT(date) DO UPDATE SET trades=trades+1",
        (today,),
    )
    con.commit()
    con.close()


def today_trade_count() -> int:
    con = sqlite3.connect(DB_PATH)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = con.execute("SELECT trades FROM daily_stats WHERE date=?", (today,)).fetchone()
    con.close()
    return row[0] if row else 0


# ── Daily loss guard ──────────────────────────────────────────────────────────

_session_start_balance: float | None = None


def check_daily_loss(current_balance: float) -> bool:
    """Return True if we should halt trading for the day."""
    global _session_start_balance
    if _session_start_balance is None:
        return False
    loss_pct = (_session_start_balance - current_balance) / _session_start_balance
    if loss_pct >= config.DAILY_LOSS_LIMIT:
        log.warning(
            "Daily loss limit hit: down %.1f%% (%.2f → %.2f). Halting.",
            loss_pct * 100,
            _session_start_balance,
            current_balance,
        )
        return True
    return False


# ── Already-traded guard ──────────────────────────────────────────────────────

_traded_tickers: set[str] = set()


# ── Market filter ─────────────────────────────────────────────────────────────

NBA_KEYWORDS = {"nba", "basketball", "lakers", "celtics", "warriors", "heat",
                "bucks", "nuggets", "knicks", "76ers", "sixers", "thunder", "mavs",
                "mavericks", "cavaliers", "pacers", "nets", "bulls", "hawks",
                "clippers", "suns", "timberwolves", "kings", "grizzlies", "hornets",
                "pelicans", "spurs", "raptors", "jazz", "magic", "pistons", "rockets",
                "blazers", "wizards"}

GAME_WINNER_KEYWORDS = {"win", "winner", "ml", "moneyline", "beat", "defeat"}


def is_nba_game_winner(market: dict) -> bool:
    title = (market.get("title") or "").lower()
    subtitle = (market.get("subtitle") or "").lower()
    combined = title + " " + subtitle

    has_nba = any(k in combined for k in NBA_KEYWORDS)
    has_winner = any(k in combined for k in GAME_WINNER_KEYWORDS)
    return has_nba and has_winner


def is_pregame(market: dict) -> bool:
    """Return True if market closes far enough in the future to still trade."""
    close_ts = market.get("close_time") or market.get("expiration_time")
    if not close_ts:
        return True
    try:
        if isinstance(close_ts, str):
            close_dt = datetime.fromisoformat(close_ts.replace("Z", "+00:00"))
        else:
            close_dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)
        secs_left = (close_dt - datetime.now(timezone.utc)).total_seconds()
        return secs_left > config.PRE_GAME_CUTOFF_SECS
    except Exception:
        return True


# ── Main scan loop ────────────────────────────────────────────────────────────

def scan(kalshi: KalshiClient, odds: OddsFeed, bankroll: float):
    # 1. Fetch open Kalshi markets
    try:
        markets = kalshi.get_markets(status="open", limit=200)
    except Exception as e:
        log.error("Kalshi markets fetch failed: %s", e)
        return

    nba_markets = [m for m in markets if is_nba_game_winner(m) and is_pregame(m)]
    log.info("Open NBA game-winner markets: %d", len(nba_markets))

    if not nba_markets:
        return

    # 2. Fetch external sharp odds
    all_games: list[dict] = []
    for sport in config.SPORTS:
        try:
            all_games.extend(odds.get_games(sport))
        except Exception as e:
            log.error("Odds API error (%s): %s", sport, e)

    if not all_games:
        log.warning("No external games returned from Odds API.")
        return

    # 3. Build lookup: canonical_team → true_prob dict per game
    game_probs: list[dict[str, float]] = []
    for game in all_games:
        probs = odds.sharp_probs(game)
        if probs:
            game_probs.append(probs)

    log.info("Games with sharp odds: %d", len(game_probs))

    # 4. For each market, check for edge
    for market in nba_markets:
        ticker = market["ticker"]
        if ticker in _traded_tickers:
            continue

        signal = None
        for probs in game_probs:
            signal = strategy.find_edge(market, probs)
            if signal:
                break

        if not signal:
            continue

        # Size the bet
        contracts = strategy.kelly_contracts(
            signal["true_prob"], signal["price_cents"], bankroll
        )
        if contracts <= 0:
            continue

        signal["contracts"] = contracts
        cost = contracts * signal["price_cents"] / 100

        log.info(
            "EDGE FOUND  %s | %s %s @ %dc | true=%.1f%% edge=%.1f%% | "
            "$%.2f on %d contracts",
            ticker,
            signal["side"].upper(),
            signal["team"],
            signal["price_cents"],
            signal["true_prob"] * 100,
            signal["edge"] * 100,
            cost,
            contracts,
        )

        # 5. Place order
        try:
            result = kalshi.place_order(
                ticker=ticker,
                side=signal["side"],
                contracts=contracts,
                price_cents=signal["price_cents"],
            )
            order_id = result.get("order", {}).get("order_id", "unknown")
            log.info("Order placed: %s", order_id)
            log_trade(signal, order_id)
            _traded_tickers.add(ticker)
            bankroll -= cost  # optimistic deduction; real balance updated next poll
        except Exception as e:
            log.error("Order failed for %s: %s", ticker, e)


def run():
    global _session_start_balance

    log.info("=" * 60)
    log.info("Kalshi NBA Trading Bot starting")
    log.info("=" * 60)

    init_db()
    kalshi = KalshiClient()
    odds_feed = OddsFeed()

    balance = kalshi.get_balance()
    _session_start_balance = balance
    log.info("Account balance: $%.2f", balance)

    while True:
        try:
            balance = kalshi.get_balance()
            log.info("Balance: $%.2f | trades today: %d", balance, today_trade_count())

            if check_daily_loss(balance):
                log.info("Sleeping 1 hour before retry...")
                time.sleep(3600)
                _session_start_balance = kalshi.get_balance()
                continue

            scan(kalshi, odds_feed, balance)

        except KeyboardInterrupt:
            log.info("Shutting down.")
            break
        except Exception as e:
            log.exception("Unexpected error: %s", e)

        log.info("Sleeping %ds...", config.POLL_INTERVAL)
        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    run()
