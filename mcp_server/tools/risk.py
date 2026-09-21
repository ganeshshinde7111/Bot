"""Deterministic risk-management math, deliberately implemented in plain
Python rather than left to the LLM. Position sizing and stop-loss levels
are exactly the kind of arithmetic an LLM can silently get wrong; giving
Claude a tool that computes them removes that failure mode and gives it
a hard number to reason from and cite in its trade rationale.
"""

from mcp.server.fastmcp import FastMCP

from ..config import settings


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def calculate_position_size(
        account_equity: float,
        risk_pct_of_equity: float,
        entry_price: float,
        stop_loss_price: float,
    ) -> dict:
        """Compute share/lot quantity so that a stop-out loses no more than
        `risk_pct_of_equity`% of account_equity.

        Returns quantity, rupee risk per share, total risk amount, and
        whether the request breaches this deployment's configured
        MAX_POSITION_RISK_PCT ceiling (in which case it is clamped).
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return {"error": "entry_price and stop_loss_price must be positive"}
        per_share_risk = abs(entry_price - stop_loss_price)
        if per_share_risk == 0:
            return {"error": "entry_price and stop_loss_price cannot be equal"}

        effective_risk_pct = min(risk_pct_of_equity, settings.MAX_POSITION_RISK_PCT)
        clamped = effective_risk_pct < risk_pct_of_equity

        risk_amount = account_equity * (effective_risk_pct / 100.0)
        quantity = int(risk_amount // per_share_risk)
        order_value = quantity * entry_price

        return {
            "quantity": max(quantity, 0),
            "per_share_risk": round(per_share_risk, 4),
            "risk_amount_inr": round(risk_amount, 2),
            "estimated_order_value_inr": round(order_value, 2),
            "risk_pct_used": effective_risk_pct,
            "clamped_to_policy_max": clamped,
            "exceeds_max_order_value": order_value > settings.MAX_ORDER_VALUE_INR,
        }

    @mcp.tool()
    def calculate_atr_stop_loss(
        entry_price: float, atr: float, side: str, atr_multiplier: float = 1.5
    ) -> dict:
        """Volatility-based stop-loss: entry -/+ (ATR * multiplier).

        side: 'BUY' (long) places the stop below entry, 'SELL' (short)
        places it above entry.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"error": "side must be 'BUY' or 'SELL'"}
        offset = atr * atr_multiplier
        stop = entry_price - offset if side == "BUY" else entry_price + offset
        return {"stop_loss_price": round(stop, 4), "atr_offset": round(offset, 4)}

    @mcp.tool()
    def portfolio_risk_check(
        account_equity: float,
        open_positions_count: int,
        todays_realized_pnl: float,
        proposed_new_risk_pct: float,
    ) -> dict:
        """Gate check Claude MUST call before proposing any new entry.

        Blocks the trade if the daily loss limit is already breached, the
        max open-position count is reached, or the new position's risk
        would push total open risk past policy.
        """
        daily_loss_pct = (todays_realized_pnl / account_equity) * 100.0 if account_equity > 0 else 0.0
        reasons = []

        # Fail closed: with no (or negative) equity there is nothing to size a
        # position against, and the percentage checks below are meaningless.
        if account_equity <= 0:
            reasons.append(
                f"Account equity is {account_equity}; cannot size or approve any "
                "new position. Verify get_margins / fund the account."
            )

        if daily_loss_pct <= -settings.MAX_DAILY_LOSS_PCT:
            reasons.append(
                f"Daily loss limit breached: {daily_loss_pct:.2f}% <= "
                f"-{settings.MAX_DAILY_LOSS_PCT}%. No new entries today."
            )
        if open_positions_count >= settings.MAX_OPEN_POSITIONS:
            reasons.append(
                f"Max open positions reached ({open_positions_count}/"
                f"{settings.MAX_OPEN_POSITIONS})."
            )
        if proposed_new_risk_pct > settings.MAX_POSITION_RISK_PCT:
            reasons.append(
                f"Proposed risk {proposed_new_risk_pct}% exceeds policy max "
                f"{settings.MAX_POSITION_RISK_PCT}% per position."
            )

        return {
            "allowed": len(reasons) == 0,
            "blocking_reasons": reasons,
            "current_daily_pnl_pct": round(daily_loss_pct, 2),
            "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        }
