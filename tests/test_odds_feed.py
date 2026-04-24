import odds_feed


def test_sharp_probs_averages_fresh_books_and_removes_vig():
    feed = odds_feed.OddsFeed(api_key="test")
    game = {
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": -110},
                            {"name": "Boston Celtics", "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 120},
                            {"name": "Boston Celtics", "price": -140},
                        ],
                    }
                ],
            },
        ]
    }

    probs = feed.sharp_probs(game)

    assert probs is not None
    assert set(probs) == {"Los Angeles Lakers", "Boston Celtics"}
    assert abs(sum(probs.values()) - 1) < 0.000001
    assert 0.45 < probs["Los Angeles Lakers"] < 0.51
    assert 0.49 < probs["Boston Celtics"] < 0.55


def test_sharp_probs_ignores_stale_books():
    feed = odds_feed.OddsFeed(api_key="test")
    game = {
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2000-01-01T00:00:00Z",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": -110},
                            {"name": "Boston Celtics", "price": -110},
                        ],
                    }
                ],
            }
        ]
    }

    assert feed.sharp_probs(game) is None

