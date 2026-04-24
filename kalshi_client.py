import uuid
import httpx
import config


class KalshiClient:
    def __init__(self, api_key: str = ""):
        key = api_key or config.KALSHI_API_KEY
        if not key:
            raise ValueError("KALSHI_API_KEY not set")
        self._http = httpx.Client(
            base_url=config.KALSHI_BASE,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=15.0,
            transport=httpx.HTTPTransport(retries=2),
        )

    # ── Account ──────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Return available balance in dollars."""
        r = self._http.get("/portfolio/balance")
        r.raise_for_status()
        return r.json()["balance"] / 100  # Kalshi returns cents

    def get_positions(self) -> list[dict]:
        r = self._http.get("/portfolio/positions")
        r.raise_for_status()
        return r.json().get("market_positions", [])

    def get_fills(self, limit: int = 100) -> list[dict]:
        r = self._http.get("/portfolio/fills", params={"limit": limit})
        r.raise_for_status()
        return r.json().get("fills", [])

    # ── Markets ───────────────────────────────────────────────────────────────

    def get_markets(self, status: str = "open", limit: int = 200) -> list[dict]:
        params = {"status": status, "limit": limit}
        r = self._http.get("/markets", params=params)
        r.raise_for_status()
        return r.json().get("markets", [])

    def get_market(self, ticker: str) -> dict:
        r = self._http.get(f"/markets/{ticker}")
        r.raise_for_status()
        return r.json()["market"]

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        ticker: str,
        side: str,       # "yes" or "no"
        contracts: int,
        price_cents: int,  # 1–99
    ) -> dict:
        """Place a limit buy order. price_cents is the price for `side`."""
        if side == "yes":
            yes_price, no_price = price_cents, 100 - price_cents
        else:
            no_price, yes_price = price_cents, 100 - price_cents

        payload = {
            "action": "buy",
            "client_order_id": str(uuid.uuid4()),
            "count": contracts,
            "side": side,
            "ticker": ticker,
            "type": "limit",
            "yes_price": yes_price,
            "no_price": no_price,
        }
        r = self._http.post("/portfolio/orders", json=payload)
        r.raise_for_status()
        return r.json()

    def cancel_order(self, order_id: str) -> dict:
        r = self._http.delete(f"/portfolio/orders/{order_id}")
        r.raise_for_status()
        return r.json()

    def get_orders(self, status: str = "resting") -> list[dict]:
        r = self._http.get("/portfolio/orders", params={"status": status})
        r.raise_for_status()
        return r.json().get("orders", [])
