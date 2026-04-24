import base64
import time
import uuid

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import config


class _KalshiAuth(httpx.Auth):
    """RSA-PSS request signing for the Kalshi elections API."""

    def __init__(self, key_id: str, private_key_path: str):
        if not key_id:
            raise ValueError("KALSHI_API_KEY_ID not set")
        if not private_key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not set")
        with open(private_key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        self._key_id = key_id

    def auth_flow(self, request: httpx.Request):
        ts = str(int(time.time() * 1000))
        path = request.url.path  # no query string
        message = f"{ts}{request.method}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        request.headers["KALSHI-ACCESS-KEY"] = self._key_id
        request.headers["KALSHI-ACCESS-TIMESTAMP"] = ts
        request.headers["KALSHI-ACCESS-SIGNATURE"] = base64.b64encode(signature).decode()
        yield request


class KalshiClient:
    def __init__(self):
        auth = _KalshiAuth(config.KALSHI_API_KEY_ID, config.KALSHI_PRIVATE_KEY_PATH)
        self._http = httpx.Client(
            base_url=config.KALSHI_BASE,
            auth=auth,
            headers={"Content-Type": "application/json"},
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
        side: str,
        contracts: int,
        price_cents: int,
    ) -> dict:
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
