"""FastAPI listener that receives alerts from TradingView (webhook) or MT5
(via WebRequest from the EA) and stores them for the MCP tool layer to read.

This is the only piece of the stack that needs a public HTTPS endpoint.
Put it behind a reverse proxy (see docker/Caddyfile) and always validate
the shared-secret header below -- TradingView/MT5 webhooks are otherwise
unauthenticated and anyone who guesses the URL could inject fake signals.
"""

import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from db import init_db, insert_signal, latest_signals

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SHARED_SECRET", "")

app = FastAPI(title="Algo-Trading Signal Listener")


@app.on_event("startup")
def _startup() -> None:
    if not WEBHOOK_SECRET:
        raise RuntimeError(
            "WEBHOOK_SHARED_SECRET is not set. Refusing to start an "
            "unauthenticated public webhook endpoint."
        )
    init_db()


def _check_secret(provided: str | None) -> None:
    if not provided or provided != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="invalid or missing secret")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/tradingview")
async def tradingview_webhook(
    request: Request, x_webhook_secret: str | None = Header(default=None)
):
    """TradingView sends the alert message body as raw text/JSON.

    Configure the alert's "Message" field as JSON, e.g.:
        {
          "secret": "{{secret}}",
          "symbol": "{{ticker}}",
          "action": "BUY",
          "price": {{close}},
          "timeframe": "{{interval}}",
          "strategy": "ema_rsi_v1",
          "indicators": {"rsi": {{plot_0}}, "ema_fast": {{plot_1}}}
        }
    TradingView cannot set custom HTTP headers on free/basic alerts, so the
    secret is also accepted inside the JSON body under "secret".
    """
    raw = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail=f"body is not valid JSON: {raw[:200]!r}")

    secret = x_webhook_secret or payload.get("secret")
    _check_secret(secret)

    if "symbol" not in payload or "action" not in payload:
        raise HTTPException(status_code=422, detail="payload must include 'symbol' and 'action'")

    signal_id = insert_signal("tradingview", payload)
    return JSONResponse({"status": "stored", "id": signal_id})


@app.post("/webhook/mt5")
async def mt5_webhook(
    request: Request, x_webhook_secret: str | None = Header(default=None)
):
    """MT5 EAs post JSON via WebRequest() -- see mql5/AI_Signal_EA.mq5."""
    payload = await request.json()
    secret = x_webhook_secret or payload.get("secret")
    _check_secret(secret)

    if "symbol" not in payload or "action" not in payload:
        raise HTTPException(status_code=422, detail="payload must include 'symbol' and 'action'")

    signal_id = insert_signal("mt5", payload)
    return JSONResponse({"status": "stored", "id": signal_id})


@app.get("/signals")
def get_signals(symbol: str | None = None, limit: int = 20):
    """Debug/inspection endpoint -- the MCP server reads the DB directly,
    not this route, but it's useful for curl-ing the box during setup."""
    return {"signals": latest_signals(symbol=symbol, limit=limit)}
