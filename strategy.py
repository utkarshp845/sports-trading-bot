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

import math
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

    teams = parse_teams_from_text(low)
    if len(teams) == 1:
        return teams[0]
    if teams:
        return teams[0]

    return None


def _resolve(text: str) -> str | None:
    text = text.strip()
    if text in _ALIASES:
        return _ALIASES[text]
    # Try last word (nickname only)
    last = text.split()[-1] if text.split() else ""
    return _ALIASES.get(last)


def parse_teams_from_text(text: str) -> list[str]:
    """Return canonical NBA teams mentioned in text, preserving first mention order."""
    low = text.lower()
    matches: list[tuple[int, int, str]] = []
    for alias, team in _ALIASES.items():
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        for match in re.finditer(pattern, low):
            matches.append((match.start(), -len(alias), team))

    teams: list[str] = []
    for _, _, team in sorted(matches):
        if team not in teams:
            teams.append(team)
    return teams


# ── Edge & sizing ─────────────────────────────────────────────────────────────

def break_even_prob(price_cents: int) -> float:
    """
    Minimum true probability needed to profit buying at price_cents,
    accounting for Kalshi fee on winnings.
    """
    if price_cents <= 0 or price_cents >= 100:
        raise ValueError("price_cents must be between 1 and 99")
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
    if bankroll <= 0 or true_prob <= 0 or true_prob >= 1:
        return 0

    price_cents = _coerce_price(price_cents)
    if price_cents is None:
        return 0

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

    contracts = math.floor(dollar_bet / p)
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
    subtitle = market.get("subtitle", "")
    market_text = f"{title} {subtitle}"
    yes_ask = _coerce_price(market.get("yes_ask"))   # cents: what you pay to buy YES
    no_ask = _coerce_price(market.get("no_ask"))     # cents: what you pay to buy NO

    yes_team = parse_team_from_title(market_text)
    if not yes_team:
        return None

    if not _market_matches_game(market_text, true_probs):
        return None

    yes_true = _team_probability(true_probs, yes_team)
    if yes_true is None:
        return None

    no_true = 1 - yes_true

    candidates = []
    yes_signal = _build_signal(market, title, "yes", yes_team, yes_true, yes_ask)
    if yes_signal:
        candidates.append(yes_signal)

    no_team = next((t for t in true_probs if t.lower() != yes_team.lower()), "opponent")
    no_signal = _build_signal(market, title, "no", no_team, no_true, no_ask)
    if no_signal:
        candidates.append(no_signal)

    if candidates:
        return max(candidates, key=lambda signal: signal["edge"])

    return None


def _build_signal(
    market: dict,
    title: str,
    side: str,
    team: str,
    true_prob: float,
    price_cents: int | None,
) -> dict | None:
    if price_cents is None:
        return None
    if price_cents < config.MIN_PRICE_CENTS or price_cents > config.MAX_PRICE_CENTS:
        return None
    if _side_spread_too_wide(market, side, price_cents):
        return None

    implied = break_even_prob(price_cents)
    adjusted_true = _shrink_probability(true_prob, implied)
    edge = adjusted_true - implied
    if edge < config.EDGE_THRESHOLD:
        return None

    return {
        "ticker": market["ticker"],
        "side": side,
        "price_cents": price_cents,
        "true_prob": adjusted_true,
        "raw_true_prob": true_prob,
        "edge": edge,
        "team": team,
        "title": title,
    }


def _coerce_price(value: object) -> int | None:
    try:
        price = int(value)
    except (TypeError, ValueError):
        return None
    if price <= 0 or price >= 100:
        return None
    return price


def _team_probability(true_probs: dict[str, float], team_name: str) -> float | None:
    for team, prob in true_probs.items():
        if team.lower() == team_name.lower():
            return float(prob)
    return None


def _market_matches_game(market_text: str, true_probs: dict[str, float]) -> bool:
    odds_teams = {team.lower() for team in true_probs}
    title_teams = parse_teams_from_text(market_text)
    if not title_teams:
        return False

    mentioned_odds_teams = {team.lower() for team in title_teams} & odds_teams
    if len(title_teams) >= 2:
        return len(mentioned_odds_teams) >= 2
    return len(mentioned_odds_teams) == 1


def _side_spread_too_wide(market: dict, side: str, ask: int) -> bool:
    bid_key = "yes_bid" if side == "yes" else "no_bid"
    bid = _coerce_price(market.get(bid_key))
    if bid is None:
        return False
    return ask - bid > config.MAX_SPREAD_CENTS


def _shrink_probability(true_prob: float, implied_prob: float) -> float:
    shrink = min(max(config.TRUE_PROB_SHRINK, 0), 1)
    return true_prob * (1 - shrink) + implied_prob * shrink
