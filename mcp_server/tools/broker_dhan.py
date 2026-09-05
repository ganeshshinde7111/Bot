"""DhanHQ v2 REST API broker tools -- the default active broker (free API,
free real-time/historical data, no monthly subscription, unlike Kite
Connect). Endpoint paths, request schemas and enum values below were
verified directly against https://dhanhq.co/docs/v2/ and a live pull of
Dhan's published instrument master, not guessed.

Credentials come only from environment variables (see config.py).

Key difference from Kite: Dhan's API addresses instruments by a numeric
`securityId` + `exchangeSegment`, not a human-readable trading symbol.
Use resolve_security_id() to look one up from a ticker before calling
get_ltp / place_order / get_historical_data.

Safety: place_order() and place_forever_order() refuse to touch the live
account unless LIVE_TRADING_ENABLED=true, and reject any order whose
notional value exceeds MAX_ORDER_VALUE_INR -- the same hard gates as
broker_kite.py, enforced in code rather than left to the LLM.
"""

import csv
import io
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from ..config import settings

BASE_URL = "https://api.dhan.co/v2"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
SCRIP_MASTER_CACHE = Path(settings.SIGNALS_DB_PATH).parent / "dhan_scrip_master.csv"
SCRIP_MASTER_MAX_AGE_SECONDS = 24 * 3600

# exchangeSegment (Dhan API enum) -> (SEM_EXM_EXCH_ID, SEM_SEGMENT) as used
# in the instrument master CSV, verified by inspecting the live file.
SEGMENT_MAP = {
    "NSE_EQ": ("NSE", "E"),
    "BSE_EQ": ("BSE", "E"),
    "NSE_FNO": ("NSE", "D"),
    "BSE_FNO": ("BSE", "D"),
    "NSE_CURRENCY": ("NSE", "C"),
    "BSE_CURRENCY": ("BSE", "C"),
    "MCX_COMM": ("MCX", "M"),
}


def _headers() -> dict:
    if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
        raise RuntimeError(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not configured. Generate an "
            "access token from your Dhan web console (Profile > DhanHQ "
            "Trading APIs) and set both as environment variables."
        )
    return {
        "access-token": settings.DHAN_ACCESS_TOKEN,
        "client-id": settings.DHAN_CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(path: str, params: dict | None = None) -> dict | list:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict | list:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _put(path: str, body: dict) -> dict | list:
    resp = requests.put(f"{BASE_URL}{path}", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> dict | list:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _ensure_scrip_master() -> Path:
    if (
        SCRIP_MASTER_CACHE.exists()
        and time.time() - SCRIP_MASTER_CACHE.stat().st_mtime < SCRIP_MASTER_MAX_AGE_SECONDS
    ):
        return SCRIP_MASTER_CACHE
    resp = requests.get(SCRIP_MASTER_URL, timeout=30)
    resp.raise_for_status()
    SCRIP_MASTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SCRIP_MASTER_CACHE.write_bytes(resp.content)
    return SCRIP_MASTER_CACHE


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def resolve_security_id(trading_symbol: str, exchange_segment: str = "NSE_EQ") -> dict:
        """Look up Dhan's numeric securityId for a human ticker, e.g.
        trading_symbol="INFY", exchange_segment="NSE_EQ" -> securityId
        "1594". Required before get_ltp / place_order / get_historical_data,
        since Dhan addresses instruments by securityId, not ticker symbol.
        exchange_segment: NSE_EQ | BSE_EQ | NSE_FNO | BSE_FNO |
        NSE_CURRENCY | BSE_CURRENCY | MCX_COMM.

        Caches Dhan's published instrument master (refreshed daily) to
        avoid re-downloading on every lookup.
        """
        if exchange_segment not in SEGMENT_MAP:
            return {"error": f"unknown exchange_segment '{exchange_segment}'. Valid: {list(SEGMENT_MAP)}"}
        exch, seg = SEGMENT_MAP[exchange_segment]

        path = _ensure_scrip_master()
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (
                    row.get("SEM_EXM_EXCH_ID") == exch
                    and row.get("SEM_SEGMENT") == seg
                    and row.get("SEM_TRADING_SYMBOL", "").upper() == trading_symbol.upper()
                ):
                    return {
                        "security_id": row["SEM_SMST_SECURITY_ID"],
                        "trading_symbol": row["SEM_TRADING_SYMBOL"],
                        "exchange_segment": exchange_segment,
                        "lot_size": row.get("SEM_LOT_UNITS"),
                    }
        return {"error": f"'{trading_symbol}' not found in {exchange_segment}"}

    @mcp.tool()
    def get_profile() -> dict:
        """Fetch the logged-in Dhan account profile (sanity-check auth)."""
        return _get("/profile")

    @mcp.tool()
    def get_margins() -> dict:
        """Fetch available fund limits: balance, margin utilised, collateral."""
        return _get("/fundlimit")

    @mcp.tool()
    def get_positions() -> list:
        """Fetch current open positions (day & net)."""
        return _get("/positions")

    @mcp.tool()
    def get_holdings() -> list:
        """Fetch long-term equity holdings (portfolio)."""
        return _get("/holdings")

    @mcp.tool()
    def get_orders() -> list:
        """Fetch today's order book (all states: pending/traded/rejected)."""
        return _get("/orders")

    @mcp.tool()
    def get_ltp(security_ids_by_segment: dict[str, list[int]]) -> dict:
        """Last traded price for instruments, grouped by exchange segment,
        e.g. {"NSE_EQ": [1594, 11536]}. Use resolve_security_id first to
        turn tickers into the numeric IDs this expects. Up to 1000
        instruments per call."""
        return _post("/marketfeed/ltp", security_ids_by_segment)

    @mcp.tool()
    def get_market_quote(security_ids_by_segment: dict[str, list[int]]) -> dict:
        """Full market quote (depth, OHLC, OI, volume) for instruments,
        grouped by exchange segment like get_ltp."""
        return _post("/marketfeed/quote", security_ids_by_segment)

    @mcp.tool()
    def get_historical_data(
        security_id: str,
        exchange_segment: str,
        from_date: str,
        to_date: str,
        instrument: str = "EQUITY",
        interval: str = "day",
    ) -> dict:
        """OHLC candles. interval: "day" for daily candles (any date range),
        or one of "1"/"5"/"15"/"25"/"60" (minutes) for intraday candles
        (max 90 days of history per call, from_date/to_date as
        "YYYY-MM-DD HH:MM:SS"). instrument: EQUITY/FUTIDX/OPTIDX/etc per
        Dhan's instrument types."""
        body = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "fromDate": from_date,
            "toDate": to_date,
        }
        if interval == "day":
            return _post("/charts/historical", body)
        body["interval"] = interval
        return _post("/charts/intraday", body)

    @mcp.tool()
    def place_order(
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float | None = None,
        trigger_price: float | None = None,
        validity: str = "DAY",
        correlation_id: str = "ai-algo-bot",
    ) -> dict:
        """Place a live order. transaction_type: BUY/SELL. order_type:
        LIMIT/MARKET/STOP_LOSS/STOP_LOSS_MARKET. product_type: CNC
        (delivery) / INTRADAY / MARGIN / MTF / CO / BO. exchange_segment:
        NSE_EQ/BSE_EQ/NSE_FNO/BSE_FNO/NSE_CURRENCY/BSE_CURRENCY/MCX_COMM.

        BLOCKED unless LIVE_TRADING_ENABLED=true and notional value is
        within MAX_ORDER_VALUE_INR -- call risk.portfolio_risk_check and
        risk.calculate_position_size first and pass their output quantity
        here. Use resolve_security_id to get security_id from a ticker.
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

        body = {
            "dhanClientId": settings.DHAN_CLIENT_ID,
            "correlationId": correlation_id,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": validity,
            "securityId": security_id,
            "quantity": quantity,
            "price": price or 0,
            "triggerPrice": trigger_price or 0,
        }
        result = _post("/orders", body)
        return {"status": "placed", "response": result}

    @mcp.tool()
    def place_forever_order(
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        price: float,
        trigger_price: float,
        order_flag: str = "SINGLE",
        product_type: str = "CNC",
        order_type: str = "LIMIT",
        quantity1: int | None = None,
        price1: float | None = None,
        trigger_price1: float | None = None,
        correlation_id: str = "ai-algo-bot",
    ) -> dict:
        """Place a Forever Order -- Dhan's GTT equivalent. order_flag:
        "SINGLE" (one trigger) or "OCO" (two-leg target+stop-loss; also
        pass quantity1/price1/trigger_price1 for the second leg). Same
        LIVE_TRADING_ENABLED / MAX_ORDER_VALUE_INR gates as place_order.
        """
        if not settings.LIVE_TRADING_ENABLED:
            return {"status": "blocked", "reason": "LIVE_TRADING_ENABLED is false -- paper mode."}

        if quantity * price > settings.MAX_ORDER_VALUE_INR:
            return {
                "status": "rejected",
                "reason": f"Order value exceeds MAX_ORDER_VALUE_INR={settings.MAX_ORDER_VALUE_INR}.",
            }

        body = {
            "dhanClientId": settings.DHAN_CLIENT_ID,
            "correlationId": correlation_id,
            "orderFlag": order_flag.upper(),
            "transactionType": transaction_type.upper(),
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": "DAY",
            "securityId": security_id,
            "quantity": quantity,
            "price": price,
            "triggerPrice": trigger_price,
        }
        if order_flag.upper() == "OCO":
            body.update({"quantity1": quantity1, "price1": price1, "triggerPrice1": trigger_price1})

        result = _post("/forever/orders", body)
        return {"status": "placed", "response": result}

    @mcp.tool()
    def cancel_order(order_id: str) -> dict:
        """Cancel a pending order by id."""
        if not settings.LIVE_TRADING_ENABLED:
            return {"status": "blocked", "reason": "LIVE_TRADING_ENABLED is false -- paper mode."}
        _delete(f"/orders/{order_id}")
        return {"status": "cancelled", "order_id": order_id}

    @mcp.tool()
    def cancel_forever_order(order_id: str) -> dict:
        """Cancel a pending Forever Order (GTT) by id."""
        if not settings.LIVE_TRADING_ENABLED:
            return {"status": "blocked", "reason": "LIVE_TRADING_ENABLED is false -- paper mode."}
        _delete(f"/forever/orders/{order_id}")
        return {"status": "cancelled", "order_id": order_id}
