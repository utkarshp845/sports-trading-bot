import os
from dotenv import load_dotenv

load_dotenv()

KALSHI_API_KEY = os.getenv("KALSHI_API_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Which sports to scan (The Odds API keys)
SPORTS = ["basketball_nba"]

# Prefer Pinnacle (sharpest book); fall back to consensus
PREFERRED_BOOKS = ["pinnacle", "draftkings", "fanduel", "betmgm"]

# Edge & sizing
EDGE_THRESHOLD = 0.04      # minimum edge after fees to place a trade
KELLY_FRACTION = 0.25      # fractional Kelly (25% of full Kelly)
MAX_BET_FRACTION = 0.05    # hard cap: max 5% of current bankroll per trade
MIN_BET_DOLLARS = 1.00     # skip if Kelly says bet less than $1
MIN_PRICE_CENTS = 5        # skip very long-shot asks with poor fill quality
MAX_PRICE_CENTS = 95       # skip nearly-certain asks with poor upside
MAX_SPREAD_CENTS = 8       # skip illiquid/wide markets when bid data is available
TRUE_PROB_SHRINK = 0.15    # shrink model probability toward market break-even
MAX_TRADES_PER_DAY = 5     # hard daily trade cap

# Fees: Kalshi charges ~7% of net profit on winning side
KALSHI_FEE_RATE = 0.07

# Risk
DAILY_LOSS_LIMIT = 0.10    # halt for the day if down 10%

# Timing
POLL_INTERVAL = 600         # seconds between scans
PRE_GAME_CUTOFF_SECS = 1800 # stop trading a market 30 min before tip-off
MAX_ODDS_AGE_SECS = 900     # ignore sportsbook quotes older than 15 minutes
