from __future__ import annotations

from datetime import datetime, timezone

import httpx
import config


class OddsFeed:
    def __init__(self, api_key: str = ""):
        key = api_key or config.ODDS_API_KEY
        if not key:
            raise ValueError("ODDS_API_KEY not set")
        self._key = key
        self._http = httpx.Client(
            base_url=config.ODDS_API_BASE,
            timeout=15.0,
            transport=httpx.HTTPTransport(retries=2),
        )

    def get_games(self, sport: str = "basketball_nba") -> list[dict]:
        """
        Returns a list of games with bookmaker h2h odds.
        Each game: {id, sport_key, commence_time, home_team, away_team, bookmakers: [...]}
        """
        r = self._http.get(
            f"/sports/{sport}/odds",
            params={
                "apiKey": self._key,
                "regions": "us",
                "markets": "h2h",
                "bookmakers": ",".join(config.PREFERRED_BOOKS),
                "oddsFormat": "american",
            },
        )
        r.raise_for_status()
        return r.json()

    def sharp_probs(self, game: dict) -> dict[str, float] | None:
        """
        Return {team_name: no_vig_probability} using a consensus of fresh books.
        Returns None if no usable odds found.
        """
        bookmakers = game.get("bookmakers", [])
        if not bookmakers:
            return None

        book_map = {b["key"]: b for b in bookmakers}
        ordered_books = [book_map[key] for key in config.PREFERRED_BOOKS if key in book_map]
        ordered_books.extend(
            b for b in bookmakers if b.get("key") not in set(config.PREFERRED_BOOKS)
        )

        snapshots = []
        for bookmaker in ordered_books:
            probs = _bookmaker_h2h_probs(bookmaker)
            if probs:
                snapshots.append(probs)

        if not snapshots:
            return None

        common_teams = set(snapshots[0])
        for probs in snapshots[1:]:
            common_teams &= set(probs)

        if len(common_teams) != 2:
            return snapshots[0]

        averaged = {
            team: sum(probs[team] for probs in snapshots) / len(snapshots)
            for team in common_teams
        }
        return _remove_vig(averaged)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _american_to_prob(odds: int) -> float:
    odds = int(odds)
    if odds >= 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def _remove_vig(raw: dict[str, float]) -> dict[str, float]:
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {team: prob / total for team, prob in raw.items()}


def _bookmaker_h2h_probs(bookmaker: dict) -> dict[str, float] | None:
    for market in bookmaker.get("markets", []):
        if market.get("key") != "h2h":
            continue
        if _is_stale(market.get("last_update") or bookmaker.get("last_update")):
            return None

        outcomes = market.get("outcomes", [])
        if len(outcomes) != 2:
            return None

        try:
            raw = {o["name"]: _american_to_prob(o["price"]) for o in outcomes}
        except (KeyError, TypeError, ValueError):
            return None

        no_vig = _remove_vig(raw)
        return no_vig or None

    return None


def _is_stale(last_update: str | None) -> bool:
    if not last_update:
        return False
    try:
        updated_at = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
    return age.total_seconds() > config.MAX_ODDS_AGE_SECS
