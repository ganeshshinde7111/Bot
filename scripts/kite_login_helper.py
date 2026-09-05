"""One-time-per-day helper to turn a Kite Connect request_token into an
access_token. Kite Connect requires an interactive browser login every
trading day -- there is no fully headless way around this by design of
their auth flow. Run this manually each morning (or wire it to a small
TOTP-based auto-login script using pyotp + Kite's login endpoints, which
many community projects document, if you want it unattended).

Usage:
    python scripts/kite_login_helper.py
    # 1. Opens/prints the Kite login URL.
    # 2. Log in in your browser, get redirected to your redirect_url with
    #    ?request_token=XXXX in the query string.
    # 3. Paste that request_token back when prompted.
    # 4. Prints the resulting access_token -- put it in .env as
    #    KITE_ACCESS_TOKEN and restart the mcp-server container.
"""

import os

from kiteconnect import KiteConnect

API_KEY = os.environ.get("KITE_API_KEY", "")
API_SECRET = os.environ.get("KITE_API_SECRET", "")

if not (API_KEY and API_SECRET):
    raise SystemExit("Set KITE_API_KEY and KITE_API_SECRET in your environment first.")

kite = KiteConnect(api_key=API_KEY)
print("Login URL:", kite.login_url())

request_token = input("Paste the request_token from the redirect URL: ").strip()
session = kite.generate_session(request_token, api_secret=API_SECRET)
print("\nAccess token (put this in .env as KITE_ACCESS_TOKEN):")
print(session["access_token"])
