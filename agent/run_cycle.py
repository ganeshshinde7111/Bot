#!/usr/bin/env python3
"""Run ONE autonomous decision cycle: headless Claude + the algo-trading MCP
server + docs/MASTER_SYSTEM_PROMPT.md. Meant to be fired on a schedule (see
deploy/algo-cycle.timer) -- it is a single-shot, not a daemon, so a crash
or hang can never leave a runaway trading loop behind.

Containment (why this can't wander off and touch your other bots):
  * --tools ""            -> every built-in tool (Bash/Read/Edit/...) is off
  * --strict-mcp-config   -> only the algo-trading MCP server is loaded
  * --allowedTools        -> pre-approves that one server; anything else is
                             denied automatically in non-interactive mode
Order safety is NOT delegated to this script: LIVE_TRADING_ENABLED and the
MAX_* ceilings are enforced inside the MCP server (mcp_server/tools/).

Usage:
    python3 agent/run_cycle.py             # respects market-hours guard
    python3 agent/run_cycle.py --force     # run outside market hours (test)
    python3 agent/run_cycle.py --dry-run   # print the command, run nothing
"""

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PROMPT_DOC = ROOT / "docs" / "MASTER_SYSTEM_PROMPT.md"
MCP_CONFIG = ROOT / "agent" / "mcp_client_config.json"
LOG_DIR = ROOT / "logs" / "cycles"
LOCK_FILE = ROOT / "logs" / "cycle.lock"

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)

MODEL = os.environ.get("CYCLE_MODEL", "sonnet")
TIMEOUT_S = int(os.environ.get("CYCLE_TIMEOUT_SECONDS", "600"))
WATCHLIST = os.environ.get("CYCLE_WATCHLIST", "")  # e.g. "INFY,TCS,RELIANCE"


def load_system_prompt() -> str:
    """The prompt lives in a ```fenced``` block inside the .md doc."""
    lines = PROMPT_DOC.read_text().splitlines()
    fences = [i for i, ln in enumerate(lines) if ln.strip() == "```"]
    if len(fences) < 2:
        sys.exit(f"could not find fenced prompt block in {PROMPT_DOC}")
    return "\n".join(lines[fences[0] + 1 : fences[-1]])


def market_is_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return MARKET_OPEN <= hm <= MARKET_CLOSE


def services_up() -> str | None:
    """Return an error string if the stack isn't reachable, else None.
    Cheaper to bail here than to spend a Claude run discovering it."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5):
            pass
    except Exception as e:
        return f"webhook /health unreachable: {e}"
    try:
        socket.create_connection(("127.0.0.1", 8000), timeout=5).close()
    except Exception as e:
        return f"MCP server :8000 unreachable: {e}"
    return None


def build_prompt(now: datetime) -> str:
    watch = (
        f"Watchlist for this cycle: {WATCHLIST}."
        if WATCHLIST
        else "No fixed watchlist: work from get_latest_signals."
    )
    return (
        f"Run one standing decision cycle now. Current time: "
        f"{now.strftime('%Y-%m-%d %H:%M IST (%A)')}. {watch} "
        "Follow your Standing Workflow exactly. If any broker tool errors "
        "(missing credentials, auth, network), report the raw error and "
        "stop -- do not retry more than once and do not guess account "
        "state. Finish with the structured decision block for each symbol "
        "considered, then one final line: CYCLE_SUMMARY: <one sentence>."
    )


def build_command(now: datetime) -> list[str]:
    return [
        "claude", "-p", build_prompt(now),
        "--model", MODEL,
        "--tools", "",
        "--strict-mcp-config",
        "--mcp-config", str(MCP_CONFIG),
        "--allowedTools", "mcp__algo-trading-bot",
        "--append-system-prompt", load_system_prompt(),
        "--output-format", "text",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="skip market-hours guard")
    ap.add_argument("--dry-run", action="store_true", help="print command, do nothing")
    args = ap.parse_args()

    now = datetime.now(IST)

    if args.dry_run:
        cmd = build_command(now)
        i = cmd.index("--append-system-prompt") + 1
        cmd[i] = f"<{len(cmd[i])} chars from {PROMPT_DOC.name}>"
        print(json.dumps(cmd, indent=2))
        return 0

    if not args.force and not market_is_open(now):
        print(f"[{now:%F %T}] market closed (IST) -- skipping. Use --force to override.")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("previous cycle still running -- skipping this tick.")
        return 0

    log_path = LOG_DIR / f"{now:%Y-%m-%d}.log"
    with log_path.open("a") as log:
        log.write(f"\n===== CYCLE {now:%F %T} IST =====\n")

        problem = services_up()
        if problem:
            log.write(f"ABORT: {problem}\n")
            print(f"ABORT: {problem}", file=sys.stderr)
            return 2

        try:
            proc = subprocess.run(
                build_command(now), cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            log.write(f"ABORT: cycle exceeded {TIMEOUT_S}s and was killed.\n")
            print("ABORT: timeout", file=sys.stderr)
            return 3

        log.write(proc.stdout)
        if proc.stderr.strip():
            log.write(f"\n--- stderr ---\n{proc.stderr}")
        log.write(f"\n===== END (exit {proc.returncode}) =====\n")

    print(proc.stdout)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
