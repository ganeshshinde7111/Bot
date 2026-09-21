"""Reads signals produced by TradingView Pine alerts / MT5 EAs, which the
webhook_listener service already validated and stored in shared SQLite.
Also exposes a Pine Script template generator so Claude can hand back a
ready-to-paste strategy when asked to design a new one.
"""

import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import settings

PINE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "pine_scripts" / "ai_signal_bridge.pine"


# Explicit column list: raw_json is deliberately excluded. It duplicates the
# parsed fields and, on rows stored before the secret was stripped at insert
# time, could contain the webhook shared secret.
SIGNAL_COLUMNS = (
    "id, received_at, source, symbol, action, strategy, price, timeframe, indicators_json"
)


def _conn():
    return sqlite3.connect(settings.SIGNALS_DB_PATH)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_latest_signals(symbol: str | None = None, limit: int = 20) -> list[dict]:
        """Read the most recent alert-driven signals stored from
        TradingView/MT5 (symbol, action, price, indicators, timeframe,
        timestamp). Use this before making a decision on a symbol you
        have an active alert on -- it's cheaper and more current than
        asking for a fresh chart read."""
        conn = _conn()
        conn.row_factory = sqlite3.Row
        try:
            if symbol:
                rows = conn.execute(
                    f"SELECT {SIGNAL_COLUMNS} FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                    (symbol.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {SIGNAL_COLUMNS} FROM signals ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @mcp.tool()
    def get_watchlist_snapshot(symbols: list[str]) -> dict:
        """For each symbol, return its single most recent stored signal.
        Useful for a quick multi-symbol scan across a watchlist."""
        conn = _conn()
        conn.row_factory = sqlite3.Row
        try:
            out = {}
            for sym in symbols:
                row = conn.execute(
                    f"SELECT {SIGNAL_COLUMNS} FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                    (sym.upper(),),
                ).fetchone()
                out[sym.upper()] = dict(row) if row else None
            return out
        finally:
            conn.close()

    @mcp.tool()
    def get_pine_script_template() -> str:
        """Return the repo's foundational Pine Script v5 strategy
        (EMA-crossover + RSI filter that fires JSON-formatted alerts).
        Use this as a base when asked to draft or modify a TradingView
        strategy -- edit and hand back full script text, don't describe
        changes in prose."""
        return PINE_TEMPLATE_PATH.read_text()
