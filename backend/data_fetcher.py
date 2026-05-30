"""
Finnhub WebSocket data fetcher
Real-time price streaming and OHLCV data management
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar
from pathlib import Path

import aiohttp
import websockets
from cache_manager import CacheManager

# Retry policy for external Finnhub HTTP calls.
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5          # seconds (first backoff)
_RETRY_MAX_DELAY = 4.0           # seconds (per-attempt cap)
_RETRY_TOTAL_BUDGET = 12.0       # seconds (total time across retries)

_T = TypeVar("_T")


async def _retry_async(
    func: Callable[[], Awaitable[_T]],
    *,
    op: str,
    logger: logging.Logger,
    attempts: int = _RETRY_ATTEMPTS,
    base_delay: float = _RETRY_BASE_DELAY,
    max_delay: float = _RETRY_MAX_DELAY,
    total_budget: float = _RETRY_TOTAL_BUDGET,
) -> _T:
    """Run an async callable with bounded exponential-backoff + jitter.

    Retries transient failures (incl. timeouts) up to ``attempts`` times,
    capping both the per-attempt sleep and total wall-clock time. Logs on
    each retry and on final giveup, then re-raises the last exception.
    """
    loop = asyncio.get_event_loop()
    started = loop.time()
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            remaining = total_budget - (loop.time() - started)
            if remaining <= 0:
                logger.warning(
                    "%s: retry budget (%.1fs) exhausted after %d attempt(s)",
                    op, total_budget, attempt,
                )
                break
            backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = min(remaining, backoff + random.uniform(0, base_delay))
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                op, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    logger.error("%s giving up after %d attempt(s): %s", op, attempts, last_exc)
    assert last_exc is not None
    raise last_exc

class FinnhubPriceFetcher:
    """Stream live prices from Finnhub WebSocket"""
    
    FINNHUB_WS_URL = "wss://ws.finnhub.io?token={token}"
    FINNHUB_REST_URL = "https://finnhub.io/api/v1"
    
    def __init__(self, api_key: str, watchlist: List[str], logger: logging.Logger):
        self.api_key = api_key
        self.watchlist = watchlist
        self.logger = logger
        self.cache = CacheManager()
        self.session: Optional[aiohttp.ClientSession] = None
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.price_history: Dict[str, List[float]] = {s: [] for s in watchlist}
        self.ohlcv_data: Dict[str, Dict] = {}
        
    async def stream_prices(self):
        """
        Connect to Finnhub WebSocket and stream prices for watchlist symbols
        """
        self.session = aiohttp.ClientSession()
        
        while True:
            try:
                self.logger.info("Connecting to Finnhub WebSocket...")
                
                async with websockets.connect(
                    self.FINNHUB_WS_URL.format(token=self.api_key)
                ) as websocket:
                    self.websocket = websocket
                    self.logger.info("Connected to Finnhub")
                    
                    # Subscribe to watchlist
                    for symbol in self.watchlist:
                        await self._subscribe(symbol)
                    
                    # Receive messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self._process_price_update(data)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            self.logger.error(f"Error processing message: {e}")
                            
            except Exception as e:
                self.logger.error(f"WebSocket connection error: {e}")
                await asyncio.sleep(5)  # Reconnect after delay
            finally:
                self.websocket = None
    
    async def _subscribe(self, symbol: str):
        """Subscribe to symbol updates"""
        if not self.websocket:
            return
        
        try:
            subscribe_msg = json.dumps({"type": "subscribe", "symbol": symbol})
            await self.websocket.send(subscribe_msg)
            self.logger.debug(f"Subscribed to {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to subscribe to {symbol}: {e}")
    
    async def _process_price_update(self, data: Dict):
        """Process incoming price data"""
        if "data" not in data:
            return
        
        for trade in data.get("data", []):
            symbol = trade.get("s")
            if not symbol or symbol not in self.watchlist:
                continue
            
            price = trade.get("p", 0)
            timestamp = trade.get("t", 0)
            
            # Update price history
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            
            self.price_history[symbol].append(price)
            # Keep only last 500 prices
            if len(self.price_history[symbol]) > 500:
                self.price_history[symbol] = self.price_history[symbol][-500:]
            
            # Cache current price
            price_data = {
                "symbol": symbol,
                "price": price,
                "timestamp": datetime.fromtimestamp(timestamp / 1000).isoformat(),
                "change_percent": await self._calculate_change(symbol, price),
                "bid": trade.get("bp", 0),
                "ask": trade.get("ap", 0),
                "volume": trade.get("v", 0),
                "alert_status": "watchful"  # TODO: Integrate with alert rules
            }
            
            await self.cache.set(f"price:{symbol}", json.dumps(price_data), ttl=30)
    
    async def _calculate_change(self, symbol: str, current_price: float) -> float:
        """Calculate percentage change from previous close"""
        try:
            # Try to get from cache first
            cached = await self.cache.get(f"prev_close:{symbol}")
            if cached:
                prev_close = float(cached)
            else:
                # Fetch previous close from REST API
                prev_close = await self._fetch_previous_close(symbol)
                if prev_close:
                    await self.cache.set(f"prev_close:{symbol}", str(prev_close), ttl=3600)
            
            if prev_close:
                return ((current_price - prev_close) / prev_close) * 100
            return 0
        except Exception as e:
            self.logger.warning(f"Failed to calculate change for {symbol}: {e}")
            return 0
    
    async def _fetch_previous_close(self, symbol: str) -> Optional[float]:
        """Fetch previous close price from Finnhub REST API"""
        if not self.session:
            return None
        
        url = f"{self.FINNHUB_REST_URL}/quote"
        params = {"symbol": symbol, "token": self.api_key}

        async def _call() -> Optional[float]:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pc")  # Previous close
                return None

        try:
            return await _retry_async(
                _call, op=f"finnhub_quote[{symbol}]", logger=self.logger
            )
        except Exception as e:
            self.logger.warning(f"Failed to fetch previous close for {symbol}: {e}")

        return None
    
    async def get_ohlcv(self, symbol: str, period: int = "5") -> Optional[Dict]:
        """
        Get OHLCV data for a symbol
        Integrates with Finnhub or cached data
        """
        try:
            if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
                return None
            
            # Use cached historical data
            prices = self.price_history[symbol]
            
            return {
                "symbol": symbol,
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "volume": len(prices),  # Approximation
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Failed to get OHLCV for {symbol}: {e}")
            return None
    
    async def get_chart_data(self, symbol: str, lookback_days: int = 30) -> Optional[List[Dict]]:
        """Get historical OHLCV data for charting"""
        if not self.session:
            return None
        
        # Fetch from Finnhub candle endpoint
        url = f"{self.FINNHUB_REST_URL}/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": int((datetime.utcnow() - timedelta(days=lookback_days)).timestamp()),
            "to": int(datetime.utcnow().timestamp()),
            "token": self.api_key
        }

        async def _call() -> Optional[List[Dict]]:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    candles = []
                    for i in range(len(data.get("t", []))):
                        candles.append({
                            "timestamp": datetime.fromtimestamp(data["t"][i]).isoformat(),
                            "open": data["o"][i],
                            "high": data["h"][i],
                            "low": data["l"][i],
                            "close": data["c"][i],
                            "volume": data["v"][i],
                            "sma_20": None,  # Calculated by frontend or signal bridge
                            "sma_50": None,
                            "sma_200": None
                        })

                    return candles
                return None

        try:
            return await _retry_async(
                _call, op=f"finnhub_candle[{symbol}]", logger=self.logger
            )
        except Exception as e:
            self.logger.error(f"Failed to get chart data for {symbol}: {e}")

        return None
    
    async def close(self):
        """Close connections"""
        if self.websocket:
            await self.websocket.close()
        if self.session:
            await self.session.close()
