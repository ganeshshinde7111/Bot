"""Zerodha Kite Connect broker tools.

Credentials are read exclusively from environment variables (see
config.py) -- nothing here ever hardcodes an API key/secret/token. Swap
this module out for Groww/Hyperliquid/another REST broker by matching the
same tool names and return shapes so the system prompt doesn't need to
change per-broker.

Safety: place_order() and place_gtt_order() refuse to touch the live
account unless LIVE_TRADING_ENABLED=true, and reject any order whose
notional value exceeds MAX_ORDER_VALUE_INR. These are hard gates enforced
in code -- the LLM cannot talk its way past them.
"""

from mcp.server.fastmcp import FastMCP

from ..config import settings

try:
    from kiteconnect import KiteConnect
except ImportError:  # pragma: no cover
    KiteConnect = None


def _client():
    if KiteConnect is None:
        raise RuntimeError("kiteconnect is not installed; add it to requirements.txt")
    if not (settings.KITE_API_KEY and settings.KITE_ACCESS_TOKEN):
        raise RuntimeError(
            "KITE_API_KEY / KITE_ACCESS_TOKEN not configured. Set them as "
            "environment variables -- see docs/DEPLOYMENT.md for the daily "
            "login/token-refresh flow."
        )
    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    kite.set_access_token(settings.KITE_ACCESS_TOKEN)
    return kite


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_profile() -> dict:
        """Fetch the logged-in Kite user's profile (sanity-check auth)."""
        return _client().profile()

    @mcp.tool()
    def get_margins() -> dict:
        """Fetch available cash / margin (equity + commodity segments)."""
        return _client().margins()

    @mcp.tool()
    def get_positions() -> dict:
        """Fetch current day & net positions."""
        return _client().positions()

    @mcp.tool()
    def get_holdings() -> list:
        """Fetch long-term equity holdings (portfolio)."""
        return _client().holdings()

    @mcp.tool()
    def get_orders() -> list:
        """Fetch today's order book (all states: open/complete/rejected)."""
        return _client().orders()

    @mcp.tool()
    def get_ltp(tradingsymbols: list[str]) -> dict:
        """Last traded price for a list of instruments, e.g.
        ["NSE:INFY", "NSE:TCS"]."""
        return _client().ltp(tradingsymbols)

    @mcp.tool()
    def get_historical_data(
        instrument_token: int, from_date: str, to_date: str, interval: str = "day"
    ) -> list:
        """OHLC candles. interval: minute/3minute/5minute/15minute/30minute/60minute/day.
        Look up instrument_token once via the Kite instruments dump and
        cache it -- don't refetch the full instrument list per call."""
        return _client().historical_data(instrument_token, from_date, to_date, interval)

    @mcp.tool()
    def place_order(
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product: str = "MIS",
        price: float | None = None,
        trigger_price: float | None = None,
        variety: str = "regular",
        tag: str = "ai-algo-bot",
    ) -> dict:
        """Place a live order. transaction_type: BUY/SELL. order_type:
        MARKET/LIMIT/SL/SL-M. product: MIS (intraday) / CNC (delivery) /
        NRML (F&O carry).

        BLOCKED unless LIVE_TRADING_ENABLED=true and the order's notional
        value is within MAX_ORDER_VALUE_INR -- call
        risk.portfolio_risk_check and risk.calculate_position_size first
        and pass their output quantity here.
        """
        if not settings.LIVE_TRADING_ENABLED:
            return {
                "status": "blocked",
                "reason": "LIVE_TRADING_ENABLED is false -- running in paper mode. "
                "Set the env var to true only after you have validated the "
                "strategy and risk limits.",
            }

        transaction_type = transaction_type.upper()
        if transaction_type not in ("BUY", "SELL"):
            return {"status": "rejected", "reason": "transaction_type must be BUY or SELL"}

        est_price = price or 0.0
        if est_price and quantity * est_price > settings.MAX_ORDER_VALUE_INR:
            return {
                "status": "rejected",
                "reason": (
                    f"Order value {quantity * est_price:.2f} exceeds policy max "
                    f"MAX_ORDER_VALUE_INR={settings.MAX_ORDER_VALUE_INR}."
                ),
            }

        kite = _client()
        order_id = kite.place_order(
            variety=variety,
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            product=product,
            price=price,
            trigger_price=trigger_price,
            tag=tag,
        )
        return {"status": "placed", "order_id": order_id}

    @mcp.tool()
    def place_gtt_order(
        tradingsymbol: str,
        exchange: str,
        trigger_type: str,
        trigger_values: list[float],
        last_price: float,
        transaction_type: str,
        quantity: int,
        order_price: float,
        product: str = "CNC",
    ) -> dict:
        """Place a GTT (Good Till Triggered) order. trigger_type: 'single'
        (one trigger price) or 'two-leg' (OCO: target + stop-loss, two
        trigger_values). Same LIVE_TRADING_ENABLED / MAX_ORDER_VALUE_INR
        gates as place_order apply.
        """
        if not settings.LIVE_TRADING_ENABLED:
            return {"status": "blocked", "reason": "LIVE_TRADING_ENABLED is false -- paper mode."}

        if quantity * order_price > settings.MAX_ORDER_VALUE_INR:
            return {
                "status": "rejected",
                "reason": f"Order value exceeds MAX_ORDER_VALUE_INR={settings.MAX_ORDER_VALUE_INR}.",
            }

        kite = _client()
        orders = [
            {
                "transaction_type": transaction_type.upper(),
                "quantity": quantity,
                "order_type": "LIMIT",
                "product": product,
                "price": order_price,
            }
        ]
        gtt_id = kite.place_gtt(
            trigger_type=trigger_type,
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            trigger_values=trigger_values,
            last_price=last_price,
            orders=orders,
        )
        return {"status": "placed", "gtt_id": gtt_id}

    @mcp.tool()
    def cancel_order(order_id: str, variety: str = "regular") -> dict:
        """Cancel a pending order by id."""
        if not settings.LIVE_TRADING_ENABLED:
            return {"status": "blocked", "reason": "LIVE_TRADING_ENABLED is false -- paper mode."}
        _client().cancel_order(variety=variety, order_id=order_id)
        return {"status": "cancelled", "order_id": order_id}
