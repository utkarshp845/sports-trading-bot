import config
import strategy


def test_find_edge_requires_same_matchup_when_two_teams_are_named():
    market = {
        "ticker": "NBA-LALBOS",
        "title": "Will the Lakers beat the Celtics?",
        "yes_ask": 45,
        "no_ask": 60,
        "yes_bid": 43,
        "no_bid": 58,
    }
    wrong_game = {
        "Los Angeles Lakers": 0.62,
        "Golden State Warriors": 0.38,
    }

    assert strategy.find_edge(market, wrong_game) is None


def test_find_edge_returns_best_trade_for_clean_matchup():
    market = {
        "ticker": "NBA-LALBOS",
        "title": "Will the Lakers beat the Celtics?",
        "yes_ask": 45,
        "no_ask": 60,
        "yes_bid": 43,
        "no_bid": 58,
    }
    probs = {
        "Los Angeles Lakers": 0.62,
        "Boston Celtics": 0.38,
    }

    signal = strategy.find_edge(market, probs)

    assert signal is not None
    assert signal["side"] == "yes"
    assert signal["team"] == "Los Angeles Lakers"
    assert signal["price_cents"] == 45
    assert signal["raw_true_prob"] == 0.62
    assert signal["edge"] >= config.EDGE_THRESHOLD


def test_find_edge_skips_wide_spread_market():
    market = {
        "ticker": "NBA-LALBOS",
        "title": "Will the Lakers beat the Celtics?",
        "yes_ask": 50,
        "no_ask": 55,
        "yes_bid": 35,
        "no_bid": 52,
    }
    probs = {
        "Los Angeles Lakers": 0.70,
        "Boston Celtics": 0.30,
    }

    assert strategy.find_edge(market, probs) is None


def test_kelly_contracts_respects_max_bet_fraction():
    contracts = strategy.kelly_contracts(true_prob=0.70, price_cents=50, bankroll=100)
    max_contracts = int((100 * config.MAX_BET_FRACTION) / 0.50)

    assert 0 < contracts <= max_contracts

