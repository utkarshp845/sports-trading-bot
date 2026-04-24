"""
Edge detection and bet sizing.

Core idea:
  - Convert external sharp odds → true no-vig probabilities
  - Compare to Kalshi yes_ask price (what you pay to buy YES)
  - If true_prob > break_even_prob by EDGE_THRESHOLD → bet YES
  - If (1 - true_prob) > break_even_prob(NO side) by EDGE_THRESHOLD → bet NO
  - Size with fractional Kelly, capped at MAX_BET_FRACTION of bankroll
"""

from __future__ import annotations

import re
import config

# ── NBA team alias table ──────────────────────────────────────────────────────
# Maps lowercase fragments found in Kalshi titles → canonical Odds-API team name

_ALIASES: dict[str, str] = {
    "hawks": "Atlanta Hawks", "atlanta": "Atlanta Hawks",
    "celtics": "Boston Celtics", "boston": "Boston Celtics",
    "nets": "Brooklyn Nets", "brooklyn": "Brooklyn Nets",
    "hornets": "Charlotte Hornets", "charlotte": "Charlotte Hornets",
    "bulls": "Chicago Bulls", "chicago": "Chicago Bulls",
    "cavaliers": "Cleveland Cavaliers", "cavs": "Cleveland Cavaliers", "cleveland": "Cleveland Cavaliers",
    "mavericks": "Dallas Mavericks", "mavs": "Dallas Mavericks", "dallas": "Dallas Mavericks",
    "nuggets": "Denver Nuggets", "denver": "Denver Nuggets",
    "pistons": "Detroit Pistons", "detroit": "Detroit Pistons",
    "warriors": "Golden State Warriors", "golden state": "Golden State Warriors",
    "rockets": "Houston Rockets", "houston": "Houston Rockets",
    "pacers": "Indiana Pacers", "indiana": "Indiana Pacers",
    "clippers": "Los Angeles Clippers", "la clippers": "Los Angeles Clippers",
    "lakers": "Los Angeles Lakers", "la lakers": "Los Angeles Lakers",
    "grizzlies": "Memphis Grizzlies", "memphis": "Memphis Grizzlies",
    "heat": "Miami Heat", "miami": "Miami Heat",
    "bucks": "Milwaukee Bucks", "milwaukee": "Milwaukee Bucks",
    "timberwolves": "Minnesota Timberwolves", "wolves": "Minnesota Timberwolves", "minnesota": "Minnesota Timberwolves",
    "pelicans": "New Orleans Pelicans", "new orleans": "New Orleans Pelicans",
    "knicks": "New York Knicks", "new york": "New York Knicks",
    "thunder": "Oklahoma City Thunder", "okc": "Oklahoma City Thunder", "oklahoma city": "Oklahoma City Thunder",
    "magic": "Orlando Magic", "orlando": "Orlando Magic",
    "76ers": "Philadelphia 76ers", "sixers": "Philadelphia 76ers", "philadelphia": "Philadelphia 76ers",
    "suns": "Phoenix Suns", "phoenix": "Phoenix Suns",
    "trail blazers": "Portland Trail Blazers", "blazers": "Portland Trail Blazers", "portland": "Portland Trail Blazers",
    "kings": "Sacramento Kings", "sacramento": "Sacramento Kings",
    "spurs": "San Antonio Spurs", "san antonio": "San Antonio Spurs",
    "raptors": "Toronto Raptors", "toronto": "Toronto Raptors",
    "jazz": "Utah Jazz", "utah": "Utah Jazz",
    "wizards": "Washington Wizards", "washington": "Washington Wizards",
}


def parse_team_from_title(title: str) -> str | None:
    """
    Try to extract the 'yes team' from a Kalshi market title.
    Handles patterns like:
      "Will the Lakers win?"
      "Lakers to win vs Celtics"
      "NBA: Lakers ML"
    Returns canonical team name or None.
    """
    low = title.lower()

    # "will the <team> win" pattern
    m = re.search(r"will (?:the )?(.+?) win", low)
    if m:
        candidate = m.group(1).strip()
        mapped = _resolve(candidate)
        if mapped:
            return mapped

    # "<team> to win" or "<team> win" or "<team> ml"
    for pattern in [r"([\w\s]+?) to win", r"([\w\s]+?) win", r"([\w\s]+?) ml"]:
        m = re.search(pattern, low)
        if m:
            candidate = m.group(1).strip()
            mapped = _resolve(candidate)
            if mapped:
                return mapped

    # Direct alias scan (longest match first to avoid "heat" matching "charlotte")
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in low:
            return _ALIASES[alias]

    return None


def _resolve(text: str) -> str | None:
    text = text.strip()
    if text in _ALIASES:
        return _ALIASES[text]
    # Try last word (nickname only)
    last = text.split()[-1] if text.split() else ""
    return _ALIASES.get(last)


# ── Edge & sizing ─────────────────────────────────────────────────────────────

def break_even_prob(price_cents: int) -> float:
    """
    Minimum true probability needed to profit buying at price_cents,
    accounting for Kalshi fee on winnings.
    """
    p = price_cents / 100
    fee = config.KALSHI_FEE_RATE
    # Net profit if win = (1-p)*(1-fee); loss if lose = p
    # Break-even: q*(1-p)*(1-fee) = (1-q)*p  →  solve for q
    profit_per_win = (1 - p) * (1 - fee)
    return p / (profit_per_win + p)


def compute_edge(true_prob: float, price_cents: int) -> float:
    """Edge = true_prob - break_even_prob. Positive means we have an edge."""
    return true_prob - break_even_prob(price_cents)


def kelly_contracts(
    true_prob: float,
    price_cents: int,
    bankroll: float,
) -> int:
    """
    Return number of contracts to buy, using fractional Kelly capped at MAX_BET_FRACTION.
    Returns 0 if below minimum bet size.
    """
    p = price_cents / 100
    fee = config.KALSHI_FEE_RATE
    b = (1 - p) * (1 - fee) / p  # net odds per dollar risked

    full_kelly = (true_prob * b - (1 - true_prob)) / b
    if full_kelly <= 0:
        return 0

    fraction = full_kelly * config.KELLY_FRACTION
    fraction = min(fraction, config.MAX_BET_FRACTION)

    dollar_bet = bankroll * fraction
    if dollar_bet < config.MIN_BET_DOLLARS:
        return 0

    contracts = int(dollar_bet / p)
    return max(contracts, 0)


def find_edge(
    market: dict,
    true_probs: dict[str, float],
) -> dict | None:
    """
    Given a Kalshi market dict and {team: true_prob} from sharp odds,
    return a trade signal dict or None.

    Signal: {ticker, side, contracts, price_cents, true_prob, edge, team}
    Caller must pass bankroll separately via kelly_contracts.
    """
    title = market.get("title", "")
    yes_ask = market.get("yes_ask")   # cents: what you pay to buy YES
    no_ask = market.get("no_ask")     # cents: what you pay to buy NO

    if yes_ask is None or no_ask is None:
        return None
    if yes_ask <= 0 or yes_ask >= 100:
        return None

    yes_team = parse_team_from_title(title)
    if not yes_team:
        return None

    # Find the matching true probability for yes_team
    yes_true = None
    for team, prob in true_probs.items():
        if team.lower() == yes_team.lower():
            yes_true = prob
            break
    if yes_true is None:
        return None

    no_true = 1 - yes_true

    yes_edge = compute_edge(yes_true, yes_ask)
    no_edge = compute_edge(no_true, no_ask)

    if yes_edge >= config.EDGE_THRESHOLD:
        return {
            "ticker": market["ticker"],
            "side": "yes",
            "price_cents": yes_ask,
            "true_prob": yes_true,
            "edge": yes_edge,
            "team": yes_team,
            "title": title,
        }
    if no_edge >= config.EDGE_THRESHOLD:
        no_team = next((t for t in true_probs if t.lower() != yes_team.lower()), "opponent")
        return {
            "ticker": market["ticker"],
            "side": "no",
            "price_cents": no_ask,
            "true_prob": no_true,
            "edge": no_edge,
            "team": no_team,
            "title": title,
        }

    return None
