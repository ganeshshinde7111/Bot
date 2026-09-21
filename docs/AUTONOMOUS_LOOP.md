# Autonomous Decision Loop

`agent/run_cycle.py` is the piece that makes the bot run without a human in
the chat: each tick it launches headless Claude (`claude -p`) with
`docs/MASTER_SYSTEM_PROMPT.md` and the `algo-trading-bot` MCP server, runs
one standing decision cycle, logs the transcript, and exits.

```
systemd timer (every 15 min)
   -> agent/run_cycle.py   (market-hours guard, lock, health check)
        -> claude -p       (built-in tools OFF, only the MCP server allowed)
             -> mcp_server :8000 -> broker / risk / signals / sentiment
```

## Containment

- `--tools ""` disables Bash/Read/Edit/etc., so the agent cannot touch any
  file on the host -- only call trading MCP tools.
- `--strict-mcp-config` loads only `agent/mcp_client_config.json`.
- Order safety lives in the MCP server, not here: `LIVE_TRADING_ENABLED`
  and the `MAX_*` ceilings are enforced in `mcp_server/tools/`.
- Single-shot with a 600 s timeout and a lock file: overlapping or hung
  runs cannot stack up.
- Skips outside NSE hours (Mon-Fri 09:15-15:30 IST). NSE holidays are NOT
  calendar-aware; on a holiday the broker tools/no-signals will make the
  cycle HOLD.

## Try it manually

```bash
python3 agent/run_cycle.py --dry-run   # show the command only
python3 agent/run_cycle.py --force     # one real cycle, any time of day
tail -f logs/cycles/$(date +%F).log
```

## Enable the schedule (needs sudo; NOT installed by default)

Do this only after paper-mode results look right:

```bash
sudo cp deploy/algo-cycle.service deploy/algo-cycle.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now algo-cycle.timer
systemctl list-timers algo-cycle.timer
```

Disable: `sudo systemctl disable --now algo-cycle.timer`.

Each cycle consumes Claude usage on the account `claude` is logged in as
(~15 s and a few tool calls per cycle); ~26 market-hours ticks per day.

## Go-live checklist (things only you can do)

1. **Dhan credentials**: put `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` in
   `.env` (Dhan web console > Profile > DhanHQ Trading APIs), then
   `cd docker && docker compose up -d --force-recreate mcp-server`.
   Dhan access tokens expire -- plan a refresh routine.
2. Run `python3 agent/run_cycle.py --force` during market hours; confirm
   the cycle reads real margins/positions and produces sane HOLD/BUY/SELL.
3. Keep `LIVE_TRADING_ENABLED=false` and paper-trade for a few weeks.
4. **Signals in**: to receive TradingView/MT5 alerts the webhook must be
   publicly reachable over HTTPS -- needs a domain + the Caddy profile
   (`docs/DEPLOYMENT.md` §3-4) and port 80/443 open in the Oracle Cloud
   security list. Until then, only manually inserted signals exist.
5. Only then: `LIVE_TRADING_ENABLED=true` with a small `MAX_ORDER_VALUE_INR`.
