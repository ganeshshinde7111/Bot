# AI Algo-Trading Bot (MCP + Claude)

A fully automated, end-to-end algorithmic trading architecture where
**Claude, connected via the Model Context Protocol (MCP), acts as the
decision-making brain**: it reads chart/indicator signals from TradingView
or MetaTrader 5, checks portfolio risk and news sentiment, and executes
Buy/Sell/GTT orders through broker APIs -- all under hard, code-enforced
risk limits.

> **Status: starter kit / reference architecture.** The strategy shipped
> here (EMA crossover + RSI filter) is a foundation to prove the pipeline
> end-to-end, not a validated trading edge. Paper-trade
> (`LIVE_TRADING_ENABLED=false`, the default) before ever pointing this at
> real capital, and read `docs/MASTER_SYSTEM_PROMPT.md`'s risk rules in
> full.

## How it fits together

```
TradingView / MT5  --alert-->  webhook_listener (FastAPI + SQLite)
                                        |
                                        v
Claude  <--MCP tools-->  mcp_server (broker + risk + sentiment + signals)
  |
  v
Zerodha Kite Connect (orders, positions, margins)
```

Full diagram and rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

| Path | Purpose |
|---|---|
| `webhook_listener/` | Public FastAPI service that receives TradingView/MT5 alerts and stores them in SQLite. |
| `mcp_server/` | The MCP server Claude connects to: broker (Kite), risk math, signal reads, news sentiment tools. |
| `pine_scripts/ai_signal_bridge.pine` | Foundational TradingView Pine Script v5 strategy that emits JSON alerts. |
| `mql5/AI_Signal_EA.mq5` | Equivalent MT5 Expert Advisor using `WebRequest()`. |
| `docs/MASTER_SYSTEM_PROMPT.md` | Production system prompt for the Claude decision engine, with risk rules and output schema. |
| `docs/ARCHITECTURE.md` | Data-flow diagram and design rationale. |
| `docs/DEPLOYMENT.md` | Docker / docker-compose deployment guide for a Linux ARM VPS. |
| `claude_config/mcp_config.json` | Sample MCP config for Claude Desktop (local stdio) and a remote/tunneled setup. |
| `scripts/kite_login_helper.py` | Interactive helper for Kite's daily access-token refresh. |
| `docker/` | Dockerfiles, `docker-compose.yml`, Caddy reverse-proxy config. |

## Quickstart (local, paper mode)

```bash
cp .env.example .env        # fill in WEBHOOK_SHARED_SECRET at minimum
python -m venv .venv && source .venv/bin/activate

pip install -r webhook_listener/requirements.txt
pip install -r mcp_server/requirements.txt

# terminal 1
cd webhook_listener && uvicorn app:app --reload --port 8080

# terminal 2
export MCP_TRANSPORT=stdio SIGNALS_DB_PATH=$(pwd)/data/signals.db
python -m mcp_server.server
```

Point Claude Desktop at the server using `claude_config/mcp_config.json`,
set its system prompt to the contents of
`docs/MASTER_SYSTEM_PROMPT.md`, and fire a test signal:

```bash
curl -X POST http://localhost:8080/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<your WEBHOOK_SHARED_SECRET>","symbol":"NSE:INFY","action":"BUY","price":1500.5,"timeframe":"5","strategy":"ema_rsi_v1"}'
```

Ask Claude to run its standing decision cycle (`docs/MASTER_SYSTEM_PROMPT.md`,
section "Standing Workflow") and it should read the signal via
`get_latest_signals`.

## Production deployment (24/7 on a VPS)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) -- covers Ubuntu ARM setup,
Docker Compose, Caddy/TLS for the public webhook, the daily Kite
access-token refresh (Kite's login flow is interactive by design), and how
to drive the decision loop unattended via a scheduled Claude
Agent SDK / Claude Code job.

## Safety model

- **Paper mode by default.** `LIVE_TRADING_ENABLED=false` gates every
  order-placing tool call in code, independent of what the LLM decides.
- **Hard numeric ceilings**, not just prompt language:
  `MAX_ORDER_VALUE_INR`, `MAX_DAILY_LOSS_PCT`, `MAX_POSITION_RISK_PCT`,
  `MAX_OPEN_POSITIONS` (`mcp_server/config.py`, enforced in
  `mcp_server/tools/risk.py` and `broker_kite.py`).
- **No public exposure of the broker-connected process.** Only the signal
  webhook is public; the MCP server binds to loopback and is reached via
  SSH tunnel / private network.
- **Credentials only via environment variables** (`.env`, never committed
  -- see `.gitignore`).

## Extending

- **Another broker** (Groww, Hyperliquid, generic REST): add a sibling
  module to `mcp_server/tools/broker_kite.py` implementing the same tool
  names; the system prompt needs no changes.
- **More indicators / a different strategy**: edit
  `pine_scripts/ai_signal_bridge.pine` and `mql5/AI_Signal_EA.mq5`, or ask
  Claude to do it using the `get_pine_script_template` tool as a base.
