from __future__ import annotations

import httpx
import config


class OddsFeed:
    def __init__(self, api_key: str = ""):
        key = api_key or config.ODDS_API_KEY
        if not key:
            raise ValueError("ODDS_API_KEY not set")
        self._key = key
        self._http = httpx.Client(base_url=config.ODDS_API_BASE, timeout=15.0)

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
        Return {team_name: no_vig_probability} using the sharpest available book.
        Returns None if no usable odds found.
        """
        bookmakers = game.get("bookmakers", [])
        if not bookmakers:
            return None

        # Pick sharpest available book in preference order
        book_map = {b["key"]: b for b in bookmakers}
        chosen = None
        for key in config.PREFERRED_BOOKS:
            if key in book_map:
                chosen = book_map[key]
                break
        if chosen is None:
            chosen = bookmakers[0]

        outcomes = None
        for market in chosen.get("markets", []):
            if market["key"] == "h2h":
                outcomes = market["outcomes"]
                break
        if not outcomes or len(outcomes) < 2:
            return None

        raw = {o["name"]: _american_to_prob(o["price"]) for o in outcomes}
        return _remove_vig(raw)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _american_to_prob(odds: int) -> float:
    if odds >= 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def _remove_vig(raw: dict[str, float]) -> dict[str, float]:
    total = sum(raw.values())
    return {team: prob / total for team, prob in raw.items()}
