"""Tiny SQLite-backed store for inbound TradingView / MT5 signals.

Kept deliberately simple (no ORM) so both the webhook listener and the
MCP server tool layer can read/write the same file with zero shared
in-process state, which is what lets them run as separate containers.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

# Must be an absolute, env-driven path -- inside the Docker image this
# module is flattened into /app (see docker/Dockerfile.webhook), so
# deriving it from __file__'s parents would point outside the /app/data
# bind mount and silently write to the container's ephemeral filesystem.
# Same default as mcp_server/config.py's SIGNALS_DB_PATH so both services
# agree on the shared file without extra config.
DB_PATH = Path(os.environ.get("SIGNALS_DB_PATH", "/app/data/signals.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    source TEXT NOT NULL,          -- 'tradingview' | 'mt5'
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,          -- BUY | SELL | HOLD | CLOSE
    strategy TEXT,
    price REAL,
    timeframe TEXT,
    indicators_json TEXT,          -- arbitrary indicator payload as JSON
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_received_at ON signals(received_at);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_signal(source: str, payload: dict) -> int:
    # The shared secret authenticates the request; it must never be stored,
    # because stored rows are later read back by the MCP tools (and so by
    # the LLM and its transcripts).
    payload = {k: v for k, v in payload.items() if k != "secret"}
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO signals
                (received_at, source, symbol, action, strategy, price, timeframe, indicators_json, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                source,
                str(payload.get("symbol", "UNKNOWN")).upper(),
                str(payload.get("action", "HOLD")).upper(),
                payload.get("strategy"),
                payload.get("price"),
                payload.get("timeframe"),
                json.dumps(payload.get("indicators", {})),
                json.dumps(payload),
            ),
        )
        return cur.lastrowid


def latest_signals(symbol: str | None = None, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
