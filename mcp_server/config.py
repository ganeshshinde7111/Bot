"""All configuration comes from environment variables -- never hardcode
credentials in source. Populate these via .env / docker-compose env_file
or your shell before launching the server."""

import os


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # --- Active broker selection ---
    # "dhan" (default: free API, free data, no monthly subscription) or
    # "kite" (kept as a fully-implemented fallback -- flip this env var
    # and restart if Dhan has an outage or you prefer Zerodha). Only the
    # active broker's tools are registered under the canonical tool names
    # (get_positions, place_order, etc.) so there's never ambiguity about
    # which broker an order actually goes to -- switching brokers is a
    # deliberate restart, never a silent runtime fallback mid-trade.
    ACTIVE_BROKER = os.environ.get("ACTIVE_BROKER", "dhan").strip().lower()

    # --- Broker: DhanHQ ---
    DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
    DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")

    # --- Broker: Zerodha Kite Connect ---
    KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
    KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
    # Kite access tokens expire daily; regenerate via your login flow and
    # inject as an env var / secret, never commit it.
    KITE_ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

    # --- News / sentiment ---
    NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

    # --- Shared signal DB written by webhook_listener ---
    SIGNALS_DB_PATH = os.environ.get("SIGNALS_DB_PATH", "/app/data/signals.db")

    # --- Safety gates ---
    # Nothing places a real order unless this is explicitly true. Defaults
    # to paper mode so a misconfigured deployment can never fire live orders.
    LIVE_TRADING_ENABLED = _bool("LIVE_TRADING_ENABLED", default=False)

    # Hard risk ceilings enforced in code (not just in the LLM prompt),
    # because prompts can be argued with and code can't.
    MAX_ORDER_VALUE_INR = float(os.environ.get("MAX_ORDER_VALUE_INR", "25000"))
    MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "2.0"))
    MAX_POSITION_RISK_PCT = float(os.environ.get("MAX_POSITION_RISK_PCT", "1.0"))
    MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "5"))

    # --- MCP transport ---
    MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable-http")
    MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
    MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))


settings = Settings()
