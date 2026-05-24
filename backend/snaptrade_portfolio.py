"""
SnapTrade Portfolio Client

OAuth-based brokerage portfolio access via SnapTrade
(https://snaptrade.com). Replaces direct Robinhood credential storage —
users connect their broker (Robinhood, Schwab, IBKR, Fidelity, etc.)
through SnapTrade's OAuth flow, and we read positions / balances via
SnapTrade's REST API.

Environment variables:
    SNAPTRADE_CLIENT_ID      - Your SnapTrade Client ID (from dashboard)
    SNAPTRADE_CONSUMER_KEY   - Your SnapTrade Consumer Key (secret)
    SNAPTRADE_USER_ID        - Per-end-user ID (created during register)
    SNAPTRADE_USER_SECRET    - Per-end-user secret (returned at register)

If USER_ID / USER_SECRET are not set, calling `ensure_user()` (or any
data method on first use) will auto-register a new SnapTrade user and
print the credentials to stdout so the operator can paste them into the
`.env` file. After registration the user must complete the broker
connection flow (see PORTFOLIO_SETUP.md).

Interface mirrors RobinhoodPortfolio so portfolio_routes.py is a
drop-in replacement.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from snaptrade_client import SnapTrade
except ImportError:  # pragma: no cover - import guard
    SnapTrade = None  # type: ignore

logger = logging.getLogger(__name__)


CACHE_TTL_SECONDS = 60


class SnapTradeNotConfigured(RuntimeError):
    """Raised when SnapTrade client credentials are missing."""


class SnapTradeUserNotRegistered(RuntimeError):
    """Raised when no SnapTrade end-user is registered yet."""


class SnapTradePortfolio:
    """
    Async wrapper around the official `snaptrade-python-sdk`.

    All SDK calls are sync, so they are dispatched through
    `asyncio.to_thread` to keep FastAPI's event loop responsive.
    Results are cached in-memory for 60 seconds to avoid rate-limit
    churn on the free tier.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        consumer_key: Optional[str] = None,
        user_id: Optional[str] = None,
        user_secret: Optional[str] = None,
    ) -> None:
        if SnapTrade is None:
            raise ImportError(
                "snaptrade-python-sdk not installed. "
                "Run: pip install snaptrade-python-sdk"
            )

        self.client_id = client_id or os.getenv("SNAPTRADE_CLIENT_ID")
        self.consumer_key = consumer_key or os.getenv("SNAPTRADE_CONSUMER_KEY")
        self.user_id = user_id or os.getenv("SNAPTRADE_USER_ID")
        self.user_secret = user_secret or os.getenv("SNAPTRADE_USER_SECRET")

        if not self.client_id or not self.consumer_key:
            raise SnapTradeNotConfigured(
                "SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY must be set "
                "in environment. Get them from https://dashboard.snaptrade.com"
            )

        self.client = SnapTrade(
            client_id=self.client_id,
            consumer_key=self.consumer_key,
        )

        self.authenticated: bool = bool(self.user_id and self.user_secret)
        # Compatibility shim: portfolio_routes.py reads `.username`
        self.username: Optional[str] = self.user_id

        self._cache: Dict[str, Any] = {}
        self._cache_ts: Dict[str, datetime] = {}
        self._cache_ttl = CACHE_TTL_SECONDS

        logger.info(
            "SnapTradePortfolio initialized (user_registered=%s)",
            self.authenticated,
        )

    # ------------------------------------------------------------------ #
    # cache helpers
    # ------------------------------------------------------------------ #
    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_ts:
            return False
        return (datetime.now() - self._cache_ts[key]).total_seconds() < self._cache_ttl

    def _get_cached(self, key: str) -> Optional[Any]:
        if self._is_cache_valid(key):
            return self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache_ts[key] = datetime.now()

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_ts.clear()

    # ------------------------------------------------------------------ #
    # user registration
    # ------------------------------------------------------------------ #
    async def register_user(self, user_id: Optional[str] = None) -> Dict[str, str]:
        """
        Register a brand-new SnapTrade end-user.

        Prints the returned credentials so the operator can persist them
        in `.env`. Returns the {userId, userSecret} dict.
        """
        new_user_id = user_id or f"trading-dashboard-{uuid.uuid4().hex[:12]}"

        def _register() -> Any:
            return self.client.authentication.register_snap_trade_user(
                user_id=new_user_id,
            )

        try:
            response = await asyncio.to_thread(_register)
        except Exception as exc:
            logger.error("SnapTrade user registration failed: %s", exc)
            raise

        body = getattr(response, "body", response)
        if isinstance(body, dict):
            new_secret = body.get("userSecret") or body.get("user_secret")
            ret_uid = body.get("userId") or body.get("user_id") or new_user_id
        else:  # SDK returns a typed object in some versions
            new_secret = getattr(body, "userSecret", None) or getattr(body, "user_secret", None)
            ret_uid = getattr(body, "userId", None) or getattr(body, "user_id", None) or new_user_id

        if not new_secret:
            raise RuntimeError(f"SnapTrade did not return a userSecret: {body!r}")

        # Persist into the running instance
        self.user_id = ret_uid
        self.user_secret = new_secret
        self.username = ret_uid
        self.authenticated = True

        # Loud console banner for the operator
        banner = (
            "\n" + "=" * 70 + "\n"
            "  SnapTrade user registered!  Paste these into your .env file:\n"
            f"     SNAPTRADE_USER_ID={ret_uid}\n"
            f"     SNAPTRADE_USER_SECRET={new_secret}\n"
            "  Then visit /api/portfolio/connect-url to link your broker.\n"
            + "=" * 70 + "\n"
        )
        print(banner, flush=True)
        logger.warning(
            "SnapTrade user registered: user_id=%s (secret printed to stdout)",
            ret_uid,
        )

        return {"userId": ret_uid, "userSecret": new_secret}

    async def ensure_user(self) -> None:
        """Ensure a SnapTrade user is registered; auto-register if not."""
        if self.authenticated:
            return
        logger.warning(
            "No SNAPTRADE_USER_ID / SNAPTRADE_USER_SECRET found — "
            "auto-registering a new SnapTrade user."
        )
        await self.register_user()

    def _require_user(self) -> None:
        if not (self.user_id and self.user_secret):
            raise SnapTradeUserNotRegistered(
                "No SnapTrade end-user registered. Run portfolio setup: "
                "POST /api/portfolio/refresh or call ensure_user(). "
                "See PORTFOLIO_SETUP.md."
            )

    # ------------------------------------------------------------------ #
    # connection / OAuth helpers
    # ------------------------------------------------------------------ #
    async def get_connection_url(self, broker: Optional[str] = None) -> str:
        """
        Get a SnapTrade Connection Portal URL — the end-user opens this
        in a browser to link their broker (Robinhood, Schwab, etc.).
        """
        await self.ensure_user()

        def _call() -> Any:
            return self.client.authentication.login_snap_trade_user(
                user_id=self.user_id,
                user_secret=self.user_secret,
                broker=broker,
            )

        response = await asyncio.to_thread(_call)
        body = getattr(response, "body", response)
        if isinstance(body, dict):
            return body.get("redirectURI") or body.get("redirect_uri") or ""
        return getattr(body, "redirectURI", "") or getattr(body, "redirect_uri", "")

    # ------------------------------------------------------------------ #
    # raw API fetchers (sync, run via to_thread)
    # ------------------------------------------------------------------ #
    def _fetch_accounts(self) -> List[Dict[str, Any]]:
        resp = self.client.account_information.list_user_accounts(
            user_id=self.user_id,
            user_secret=self.user_secret,
        )
        body = getattr(resp, "body", resp)
        return list(body) if body else []

    def _fetch_holdings(self) -> List[Dict[str, Any]]:
        """Fetch holdings for all connected accounts (aggregated).

        The legacy `get_all_user_holdings` endpoint is now HTTP 410 Gone.
        We rebuild the same shape by iterating accounts and pulling
        positions + balance via the current per-account endpoints.
        """
        accounts = self._fetch_accounts()
        aggregated: List[Dict[str, Any]] = []
        for acct in accounts:
            aid = acct.get("id")
            if not aid:
                continue
            # Positions
            try:
                pres = self.client.account_information.get_user_account_positions(
                    account_id=aid,
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                )
                positions = list(getattr(pres, "body", pres) or [])
            except Exception as exc:
                logger.warning("positions fetch failed for %s: %s", aid, exc)
                positions = []
            # Balances
            try:
                bres = self.client.account_information.get_user_account_balance(
                    account_id=aid,
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                )
                balances = list(getattr(bres, "body", bres) or [])
            except Exception as exc:
                logger.warning("balance fetch failed for %s: %s", aid, exc)
                balances = []
            aggregated.append({
                "account": acct,
                "balances": balances,
                "positions": positions,
                "total_value": acct.get("balance", {}).get("total", {}) or {},
            })
        return aggregated

    def _fetch_activities(self, days: int = 30) -> List[Dict[str, Any]]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days)
        resp = self.client.transactions_and_reporting.get_activities(
            user_id=self.user_id,
            user_secret=self.user_secret,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        body = getattr(resp, "body", resp)
        return list(body) if body else []

    # ------------------------------------------------------------------ #
    # public methods (mirrors RobinhoodPortfolio)
    # ------------------------------------------------------------------ #
    async def authenticate(self) -> bool:
        """
        SnapTrade has no login step — auth is per-request via
        clientId / consumerKey / userId / userSecret. This just verifies
        that an end-user is registered and the credentials work.
        """
        try:
            await self.ensure_user()
        except Exception as exc:
            logger.error("SnapTrade ensure_user failed: %s", exc)
            self.authenticated = False
            return False

        try:
            await asyncio.to_thread(self._fetch_accounts)
            self.authenticated = True
            logger.info("✅ SnapTrade authenticated (user_id=%s)", self.user_id)
            return True
        except Exception as exc:
            logger.error("❌ SnapTrade authentication check failed: %s", exc)
            self.authenticated = False
            return False

    async def get_portfolio(self) -> Dict[str, Any]:
        """
        Full portfolio snapshot. Shape matches RobinhoodPortfolio so
        portfolio_routes.py works unchanged.
        """
        try:
            self._require_user()
        except SnapTradeUserNotRegistered as exc:
            return {
                "error": str(exc),
                "positions": [],
                "watchlist": [],
                "timestamp": datetime.now().isoformat(),
            }

        cached = self._get_cached("portfolio")
        if cached:
            return cached

        try:
            holdings_payload = await asyncio.to_thread(self._fetch_holdings)
        except Exception as exc:
            logger.error("Error fetching SnapTrade holdings: %s", exc)
            return {
                "error": str(exc),
                "positions": [],
                "watchlist": [],
                "timestamp": datetime.now().isoformat(),
            }

        account_value = 0.0
        buying_power = 0.0
        cash = 0.0
        positions: List[Dict[str, Any]] = []

        # `holdings_payload` is a list, one entry per connected account.
        for acct_holdings in holdings_payload:
            balances = acct_holdings.get("balances") or []
            for bal in balances:
                amt = _as_float(bal.get("cash"))
                cash += amt
                buying_power += _as_float(bal.get("buying_power", amt))

            tot = acct_holdings.get("total_value") or {}
            account_value += _as_float(tot.get("amount"))

            for pos in acct_holdings.get("positions") or []:
                sym_obj = pos.get("symbol") or {}
                inner = sym_obj.get("symbol") or sym_obj  # SDK nests it
                symbol = (
                    inner.get("symbol")
                    or inner.get("raw_symbol")
                    or sym_obj.get("symbol")
                    or "?"
                )
                qty = _as_float(pos.get("units") or pos.get("quantity"))
                avg = _as_float(pos.get("average_purchase_price"))
                price = _as_float(pos.get("price"))
                market_value = qty * price
                cost_basis = qty * avg
                pl = market_value - cost_basis
                pl_pct = (pl / cost_basis * 100) if cost_basis > 0 else 0.0

                positions.append({
                    "symbol": symbol,
                    "quantity": qty,
                    "average_buy_price": avg,
                    "avg_cost": avg,
                    "current_price": price,
                    "current_value": market_value,
                    "market_value": market_value,
                    "cost_basis": cost_basis,
                    "gain_loss": pl,
                    "unrealized_pl": pl,
                    "gain_loss_pct": pl_pct,
                    "unrealized_pl_pct": pl_pct,
                    # extras some frontend components may read:
                    "bid_price": price,
                    "ask_price": price,
                    "last_trade_price": price,
                    "pe_ratio": None,
                    "market_cap": None,
                    "currency": (inner.get("currency") or {}).get("code")
                                if isinstance(inner, dict) else None,
                    "exchange": (inner.get("exchange") or {}).get("code")
                                if isinstance(inner, dict) else None,
                    "type": (inner.get("type") or {}).get("description")
                            if isinstance(inner, dict) else None,
                })

        # Compute weights now that we have total market value
        total_mv = sum(p["market_value"] for p in positions) or 1.0
        for p in positions:
            p["weight"] = p["market_value"] / total_mv

        positions.sort(key=lambda x: x["current_value"], reverse=True)
        summary = _calc_summary(positions)

        result = {
            "account_value": account_value or total_mv + cash,
            "buying_power": buying_power,
            "cash": cash,
            "positions": positions,
            "watchlist": [],  # SnapTrade has no native watchlist
            "summary": summary,
            "timestamp": datetime.now().isoformat(),
        }
        self._set_cached("portfolio", result)
        return result

    async def get_account_summary(self) -> Dict[str, Any]:
        """High-level account numbers (equity, cash, day change)."""
        data = await self.get_portfolio()
        positions = data.get("positions", [])
        equity = data.get("account_value", 0.0)
        cash = data.get("cash", 0.0)

        # SnapTrade exposes 'open_pnl' on positions = today's P&L when
        # available. Aggregate as a best-effort day change.
        day_change = sum(_as_float(p.get("unrealized_pl")) for p in positions)
        day_change_pct = (day_change / equity * 100) if equity else 0.0

        return {
            "equity": equity,
            "cash": cash,
            "buying_power": data.get("buying_power", 0.0),
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "timestamp": data.get("timestamp"),
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        data = await self.get_portfolio()
        return data.get("positions", [])

    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for p in await self.get_positions():
            if p.get("symbol", "").upper() == symbol.upper():
                return p
        return None

    async def get_holdings_breakdown(self) -> Dict[str, Any]:
        """Asset-class / position-size breakdown."""
        positions = await self.get_positions()
        if not positions:
            return {
                "total_value": 0,
                "positions_count": 0,
                "largest_position_pct": 0,
                "concentration": "N/A",
                "by_asset_class": {},
            }

        total = sum(p["current_value"] for p in positions)
        by_asset: Dict[str, float] = {}
        for p in positions:
            cls = p.get("type") or "Equity"
            by_asset[cls] = by_asset.get(cls, 0.0) + p["current_value"]

        return {
            "total_value": total,
            "positions_count": len(positions),
            "by_asset_class": {
                k: {"value": v, "pct": (v / total * 100) if total else 0}
                for k, v in by_asset.items()
            },
        }

    async def get_performance(self, days: int = 30) -> Dict[str, Any]:
        """Trading activity / cashflow over the given window."""
        try:
            self._require_user()
        except SnapTradeUserNotRegistered as exc:
            return {"error": str(exc)}

        cache_key = f"performance_{days}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            raw = await asyncio.to_thread(self._fetch_activities, days)
        except Exception as exc:
            logger.error("Error fetching SnapTrade activities: %s", exc)
            return {"error": str(exc)}

        orders = []
        buys = sells = 0
        for act in raw:
            atype = (act.get("type") or "").upper()
            sym_obj = act.get("symbol") or {}
            inner = sym_obj.get("symbol") or sym_obj
            symbol = (
                (inner.get("symbol") if isinstance(inner, dict) else None)
                or sym_obj.get("symbol")
                or act.get("description")
                or "?"
            )
            side = "buy" if atype == "BUY" else "sell" if atype == "SELL" else atype.lower()
            if side == "buy":
                buys += 1
            elif side == "sell":
                sells += 1
            orders.append({
                "symbol": symbol,
                "side": side,
                "quantity": _as_float(act.get("units")),
                "price": _as_float(act.get("price")),
                "amount": _as_float(act.get("amount")),
                "state": "filled",
                "created_at": act.get("trade_date") or act.get("settlement_date"),
            })

        result = {
            "recent_orders": orders[:20],
            "buy_orders": buys,
            "sell_orders": sells,
        }
        self._set_cached(cache_key, result)
        return result

    async def get_watchlist(self) -> List[Dict[str, Any]]:
        """SnapTrade does not expose a watchlist endpoint."""
        logger.warning("SnapTrade has no watchlist endpoint; returning [].")
        return []

    async def health_check(self) -> Dict[str, str]:
        if not self.user_id or not self.user_secret:
            return {"status": "unregistered", "user": "not configured"}
        ok = await self.authenticate()
        return {
            "status": "connected" if ok else "disconnected",
            "user": self.user_id,
        }

    async def logout(self) -> None:
        """No persistent session — just clear cache."""
        self.clear_cache()


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _as_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _calc_summary(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not positions:
        return {
            "total_positions": 0,
            "portfolio_value": 0,
            "total_gain_loss": 0,
            "total_gain_loss_pct": 0,
            "top_position": None,
        }
    pv = sum(p["current_value"] for p in positions)
    pl = sum(p["gain_loss"] for p in positions)
    cb = sum(p["cost_basis"] for p in positions if p["cost_basis"] > 0)
    pl_pct = (pl / cb * 100) if cb > 0 else 0.0
    top = max(positions, key=lambda x: x["current_value"])
    return {
        "total_positions": len(positions),
        "portfolio_value": pv,
        "total_gain_loss": pl,
        "total_gain_loss_pct": pl_pct,
        "top_position": {
            "symbol": top["symbol"],
            "value": top["current_value"],
            "pct_of_portfolio": (top["current_value"] / pv * 100) if pv > 0 else 0,
        },
    }


# ---------------------------------------------------------------------- #
# module-level singleton (matches RobinhoodPortfolio interface)
# ---------------------------------------------------------------------- #
_portfolio_instance: Optional[SnapTradePortfolio] = None


async def get_portfolio_instance() -> SnapTradePortfolio:
    global _portfolio_instance
    if _portfolio_instance is None:
        _portfolio_instance = SnapTradePortfolio()
        try:
            await _portfolio_instance.authenticate()
        except Exception as exc:
            logger.error("SnapTrade initial authenticate failed: %s", exc)
    return _portfolio_instance


async def clear_portfolio_cache() -> None:
    global _portfolio_instance
    if _portfolio_instance is not None:
        _portfolio_instance.clear_cache()
