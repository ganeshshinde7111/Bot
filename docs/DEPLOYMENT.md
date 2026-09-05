# Deployment Guide -- Ubuntu ARM VPS (4 OCPU / 24 GB), Docker Compose

Tested assumptions: an Oracle Cloud "Ampere A1" style shape (arm64,
4 OCPU, 24 GB RAM) running Ubuntu 22.04/24.04. All images used below are
multi-arch (`python:3.11-slim`, `caddy:2.8-alpine`) so this works unmodified
on arm64.

## 1. Base server setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg ufw fail2ban

# Docker Engine + Compose plugin (official repo, arm64-compatible)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Firewall: only SSH, HTTP, HTTPS from the outside. Everything else
# (webhook debug port, MCP server) stays behind the firewall / loopback.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

sudo systemctl enable --now fail2ban
```

## 2. Clone and configure

```bash
git clone https://github.com/<your-fork>/Bot.git
cd Bot
cp .env.example .env
nano .env   # fill in WEBHOOK_SHARED_SECRET, KITE_API_KEY/SECRET, etc.
mkdir -p data
```

Generate a strong shared secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. DNS + TLS (only needed for the public webhook endpoint)

Point an A/AAAA record for `your-vps-domain.example` at the VPS's public
IP. Edit `docker/Caddyfile` to use your real domain. Caddy handles
Let's Encrypt certificate issuance and renewal automatically -- no manual
certbot steps.

## 4. Bring the stack up

```bash
cd docker
docker compose build
docker compose up -d webhook mcp-server
# once DNS has propagated:
docker compose --profile proxy up -d caddy
docker compose ps
```

Verify:

```bash
curl http://localhost:8080/health           # {"status":"ok"}
curl https://your-vps-domain.example/health # once Caddy + DNS are live
```

The `mcp-server` container is bound to `127.0.0.1:8000` on purpose (see
`docker/docker-compose.yml`) -- it holds broker credentials and can place
real orders. Reach it from your workstation via an SSH tunnel:

```bash
ssh -L 8000:localhost:8000 user@your-vps-domain.example
# then point Claude (Agent SDK / Desktop remote MCP) at http://localhost:8000/mcp
```

## 5. Wire up TradingView / MT5

- **TradingView**: open the chart with `pine_scripts/ai_signal_bridge.pine`
  loaded, create an alert on it, set the webhook URL to
  `https://your-vps-domain.example/webhook/tradingview`, and paste the JSON
  message template from the script's comments (with your real secret).
- **MT5**: whitelist your webhook URL under
  *Tools > Options > Expert Advisors > Allow WebRequest for listed URL*,
  then attach `mql5/AI_Signal_EA.mq5` to a chart with `WebhookURL` and
  `WebhookSecret` set to match your `.env`.

## 6. Daily Kite access-token refresh

Kite Connect's login flow is interactive by design (no fully headless
option without additional TOTP automation). Each trading morning:

```bash
docker compose exec mcp-server python -m scripts.kite_login_helper \
  || python3 scripts/kite_login_helper.py  # if running it from your workstation instead
```

Follow the printed login URL, paste back the `request_token`, copy the
resulting `access_token` into `.env` as `KITE_ACCESS_TOKEN`, then:

```bash
docker compose up -d --force-recreate mcp-server
```

Automate this further with a TOTP-based auto-login (pyotp + Kite's
programmatic login endpoints) once you're comfortable with the manual flow
-- keep it as a scheduled job (`cron` or a `create_trigger` Routine if
you're driving this from Claude Code) that runs before market open.

## 7. Running Claude 24/7 against this stack

This repo provides the **infrastructure** (signal intake, broker tools,
risk gates) -- the decision loop itself needs something to invoke Claude on
a schedule with `docs/MASTER_SYSTEM_PROMPT.md` as the system prompt and the
MCP server attached. Two common ways to drive that loop unattended:

- **Claude Agent SDK script**: a small Python/TypeScript script using the
  Agent SDK, run as a systemd timer or cron job every N minutes during
  market hours, that opens a session, attaches the MCP server (via the
  tunnel/VPN address), sends a "run the standing decision cycle" prompt,
  and logs the transcript to disk.
- **Claude Code on the web / a scheduled Routine**: if you're already
  running this from Claude Code, a recurring trigger (cron-style) that
  fires into a session with this MCP server attached achieves the same
  effect without you writing a custom scheduler.

Either way: log every transcript, alert yourself (email/Slack/webhook) on
any blocked-trade or tool-error report from the system prompt's mandatory
per-cycle summary, and start in paper mode (`LIVE_TRADING_ENABLED=false`)
for at least a few weeks of forward-testing before enabling live orders.

## 8. Updates & maintenance

```bash
cd ~/Bot
git pull
cd docker
docker compose build
docker compose up -d
```

Back up `data/signals.db` periodically (`docker compose cp mcp-server:/app/data/signals.db ./backup/`)
-- it's your signal history, not just cache.

## 9. Resource footprint on 4 OCPU / 24 GB

This stack is intentionally light: FastAPI + SQLite + a Python MCP server
use well under 1 GB RAM combined at idle. The 24 GB headroom is there for
you to add a local vector store, a backtesting engine, or a larger news/
data pipeline later without needing a bigger box.
