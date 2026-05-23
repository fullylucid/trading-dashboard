#!/usr/bin/env python3
"""
Trading Dashboard - FastAPI Backend
Production-ready WebSocket streaming, signal generation, and analytics
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from pathlib import Path
import os

from fastapi import FastAPI, WebSocket, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel, Field
from pythonjsonlogger import jsonlogger

from slowapi import Limiter
from slowapi.util import get_remote_address

from data_fetcher import FinnhubPriceFetcher
from quant_bridge import QuantSignalBridge
from cache_manager import CacheManager
from config import Settings

# ============================================================================
# CONFIGURATION & LOGGING
# ============================================================================

settings = Settings()

# Configure structured JSON logging
log_dir = Path(settings.LOG_DIR)
log_dir.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("trading_dashboard")
logger.setLevel(logging.INFO)

# JSON handler for structured logs
json_handler = logging.FileHandler(log_dir / "dashboard.log")
json_formatter = jsonlogger.JsonFormatter()
json_handler.setFormatter(json_formatter)
logger.addHandler(json_handler)

# Console handler for development
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))
logger.addHandler(console_handler)

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Trading Dashboard API",
    description="Production WebSocket streaming, quant signals, and analytics",
    version="1.0.0"
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# DEPENDENCY INJECTION & INITIALIZATION
# ============================================================================

price_fetcher: Optional[FinnhubPriceFetcher] = None
signal_bridge: Optional[QuantSignalBridge] = None
cache_manager = CacheManager(settings.REDIS_URL)

# Track WebSocket connections
active_price_clients: Set[WebSocket] = set()
active_signal_clients: Set[WebSocket] = set()

# ============================================================================
# DATA MODELS
# ============================================================================

class PriceUpdate(BaseModel):
    """Real-time price data"""
    symbol: str
    price: float
    bid: float
    ask: float
    volume: int
    timestamp: datetime
    change_percent: float

class SignalUpdate(BaseModel):
    """Trading signal data"""
    symbol: str
    timestamp: datetime
    momentum_score: float
    momentum_confidence: float
    reversion_score: float
    reversion_confidence: float
    volatility_regime: str
    volatility_score: float
    pattern_score: float
    regime_score: float
    correlation_score: float
    leading_indicator_score: float
    aggregate_confidence: float
    signal_type: str  # "buy", "sell", "neutral"
    trigger_reason: str

class WatchlistItem(BaseModel):
    """Watchlist entry with live data"""
    symbol: str
    price: float
    change_percent: float
    volume: int
    bid: float
    ask: float
    alert_status: str  # "triggered", "watchful", "disabled"
    last_price_update: datetime

class RegimeState(BaseModel):
    """Market regime analysis"""
    hmm_phase: int
    volatility_regime: str
    market_heat: float
    trend_direction: str
    estimated_probability: float
    timestamp: datetime

class SignalHistory(BaseModel):
    """Historical signal data"""
    total_signals_24h: int
    buy_signals: int
    sell_signals: int
    conversion_rate: float
    avg_confidence: float
    confidence_distribution: Dict[str, int]  # "high", "medium", "low" -> count
    top_signals: List[SignalUpdate]

class PnLMetric(BaseModel):
    """P&L tracking"""
    realized_pnl: float
    unrealized_pnl: float
    total_return: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float

class ChartData(BaseModel):
    """OHLCV data for charting"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None

# ============================================================================
# INITIALIZATION & LIFECYCLE
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize data fetchers and bridges"""
    global price_fetcher, signal_bridge
    
    try:
        # Initialize Finnhub price streamer
        price_fetcher = FinnhubPriceFetcher(
            api_key=settings.FINNHUB_API_KEY,
            watchlist=await load_watchlist(),
            logger=logger
        )
        
        # Initialize quant signal bridge
        signal_bridge = QuantSignalBridge(
            quant_toolkit_path=settings.QUANT_TOOLKIT_PATH,
            logger=logger,
            cache_manager=cache_manager
        )
        
        # Start background tasks
        asyncio.create_task(price_fetcher.stream_prices())
        asyncio.create_task(signal_generator_loop())
        
        logger.info("Dashboard backend initialized successfully", extra={
            "watchlist_count": len(price_fetcher.watchlist)
        })
    except Exception as e:
        logger.error(f"Startup error: {e}", exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    if price_fetcher:
        await price_fetcher.close()
    logger.info("Dashboard backend shut down")

# ============================================================================
# BACKGROUND TASKS
# ============================================================================

async def signal_generator_loop():
    """Continuously generate signals from price data and broadcast to clients"""
    while True:
        try:
            if not price_fetcher:
                await asyncio.sleep(5)
                continue
            
            for symbol in price_fetcher.watchlist:
                # Get latest OHLCV data
                ohlcv = await price_fetcher.get_ohlcv(symbol)
                if not ohlcv:
                    continue
                
                # Generate signal
                signal = await signal_bridge.generate_signal(symbol, ohlcv)
                
                # Cache signal
                await cache_manager.set(f"signal:{symbol}", json.dumps(signal))
                
                # Broadcast to clients
                await broadcast_signal(signal)
                
                # Log signal
                log_signal(signal)
            
            await asyncio.sleep(settings.SIGNAL_UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Signal generator error: {e}", exc_info=True)
            await asyncio.sleep(5)

async def broadcast_signal(signal: Dict):
    """Send signal to all connected signal WebSocket clients"""
    disconnected = set()
    for client in active_signal_clients:
        try:
            await client.send_json(signal)
        except Exception as e:
            logger.warning(f"Failed to send signal to client: {e}")
            disconnected.add(client)
    
    # Clean up disconnected clients
    for client in disconnected:
        active_signal_clients.discard(client)

async def broadcast_price(price_update: Dict):
    """Send price update to all connected price WebSocket clients"""
    disconnected = set()
    for client in active_price_clients:
        try:
            await client.send_json(price_update)
        except Exception as e:
            logger.warning(f"Failed to send price to client: {e}")
            disconnected.add(client)
    
    # Clean up disconnected clients
    for client in disconnected:
        active_price_clients.discard(client)

def log_signal(signal: Dict):
    """Log signal to analytics file"""
    try:
        log_file = Path(settings.LOG_DIR) / "signals.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps({
                **signal,
                "logged_at": datetime.utcnow().isoformat()
            }) + "\n")
    except Exception as e:
        logger.error(f"Failed to log signal: {e}")

# ============================================================================
# REST API ENDPOINTS
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "price_fetcher_active": price_fetcher is not None,
        "signal_bridge_active": signal_bridge is not None,
        "connected_price_clients": len(active_price_clients),
        "connected_signal_clients": len(active_signal_clients)
    }

@app.get("/api/watchlist", response_model=List[WatchlistItem])
async def get_watchlist():
    """Get current watchlist with live prices"""
    if not price_fetcher:
        raise HTTPException(status_code=503, detail="Price fetcher not ready")
    
    watchlist = []
    for symbol in price_fetcher.watchlist:
        price_data = await cache_manager.get(f"price:{symbol}")
        if price_data:
            data = json.loads(price_data)
            watchlist.append(WatchlistItem(
                symbol=symbol,
                price=data.get("price", 0),
                change_percent=data.get("change_percent", 0),
                volume=data.get("volume", 0),
                bid=data.get("bid", 0),
                ask=data.get("ask", 0),
                alert_status=data.get("alert_status", "watchful"),
                last_price_update=datetime.fromisoformat(data.get("timestamp", ""))
            ))
    
    return watchlist

@app.get("/api/signals/{symbol}", response_model=SignalUpdate)
async def get_signal(symbol: str):
    """Get latest signal for a symbol"""
    signal_data = await cache_manager.get(f"signal:{symbol}")
    if not signal_data:
        raise HTTPException(status_code=404, detail=f"No signal for {symbol}")
    
    return json.loads(signal_data)

@app.get("/api/regime", response_model=RegimeState)
async def get_regime():
    """Get current market regime analysis"""
    if not signal_bridge:
        raise HTTPException(status_code=503, detail="Signal bridge not ready")
    
    regime = await signal_bridge.get_regime_state()
    return RegimeState(
        hmm_phase=regime.get("hmm_phase", 0),
        volatility_regime=regime.get("volatility_regime", "unknown"),
        market_heat=regime.get("market_heat", 0),
        trend_direction=regime.get("trend_direction", "neutral"),
        estimated_probability=regime.get("estimated_probability", 0),
        timestamp=datetime.utcnow()
    )

@app.get("/api/signals-history", response_model=SignalHistory)
async def get_signals_history():
    """Get signal history from last 24 hours"""
    history_file = Path(settings.LOG_DIR) / "signals.jsonl"
    
    if not history_file.exists():
        return SignalHistory(
            total_signals_24h=0,
            buy_signals=0,
            sell_signals=0,
            conversion_rate=0,
            avg_confidence=0,
            confidence_distribution={},
            top_signals=[]
        )
    
    signals = []
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    
    with open(history_file, "r") as f:
        for line in f:
            try:
                sig = json.loads(line)
                sig_time = datetime.fromisoformat(sig.get("logged_at", ""))
                if sig_time > cutoff_time:
                    signals.append(sig)
            except json.JSONDecodeError:
                continue
    
    # Analyze signals
    buy_count = sum(1 for s in signals if s.get("signal_type") == "buy")
    sell_count = sum(1 for s in signals if s.get("signal_type") == "sell")
    
    confidence_dist = {"high": 0, "medium": 0, "low": 0}
    total_confidence = 0
    
    for s in signals:
        conf = s.get("aggregate_confidence", 0)
        total_confidence += conf
        if conf > 0.75:
            confidence_dist["high"] += 1
        elif conf > 0.5:
            confidence_dist["medium"] += 1
        else:
            confidence_dist["low"] += 1
    
    return SignalHistory(
        total_signals_24h=len(signals),
        buy_signals=buy_count,
        sell_signals=sell_count,
        conversion_rate=buy_count / max(len(signals), 1),
        avg_confidence=total_confidence / max(len(signals), 1),
        confidence_distribution=confidence_dist,
        top_signals=[SignalUpdate(**s) for s in signals[:10]]
    )

@app.get("/api/pnl", response_model=PnLMetric)
async def get_pnl():
    """Get P&L metrics (mock data for now)"""
    # This would integrate with actual trading system
    return PnLMetric(
        realized_pnl=0,
        unrealized_pnl=0,
        total_return=0,
        win_rate=0,
        sharpe_ratio=0,
        max_drawdown=0
    )

@app.get("/api/chart-data/{symbol}")
async def get_chart_data(
    symbol: str,
    lookback_days: int = Query(30, ge=1, le=365)
):
    """Get OHLCV chart data for a symbol"""
    if not price_fetcher:
        raise HTTPException(status_code=503, detail="Price fetcher not ready")
    
    chart_data = await price_fetcher.get_chart_data(symbol, lookback_days)
    if not chart_data:
        raise HTTPException(status_code=404, detail=f"No chart data for {symbol}")
    
    return chart_data

# ============================================================================
# WEBSOCKET ENDPOINTS
# ============================================================================

@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """WebSocket for real-time price updates"""
    await websocket.accept()
    active_price_clients.add(websocket)
    logger.info("Price client connected", extra={"clients": len(active_price_clients)})
    
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception as e:
        logger.warning(f"Price WebSocket error: {e}")
    finally:
        active_price_clients.discard(websocket)
        logger.info("Price client disconnected", extra={"clients": len(active_price_clients)})

@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    """WebSocket for real-time signal updates"""
    await websocket.accept()
    active_signal_clients.add(websocket)
    logger.info("Signal client connected", extra={"clients": len(active_signal_clients)})
    
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception as e:
        logger.warning(f"Signal WebSocket error: {e}")
    finally:
        active_signal_clients.discard(websocket)
        logger.info("Signal client disconnected", extra={"clients": len(active_signal_clients)})

# ============================================================================
# STATIC FILES & SPA ROUTING
# ============================================================================

# Serve React frontend
frontend_dir = Path(__file__).parent.parent / "frontend" / "build"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir / "static"), name="static")

@app.get("/")
async def serve_frontend():
    """Serve React SPA"""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built yet"}

@app.get("/{path:path}")
async def serve_spa(path: str):
    """Serve React SPA for all routes"""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built yet"}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

async def load_watchlist() -> List[str]:
    """Load watchlist from MEMORY.md"""
    try:
        memory_file = Path.home() / ".hermes" / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text()
            # Parse watchlist symbols from markdown
            symbols = []
            for line in content.split("\n"):
                if line.startswith("**") and line.endswith("**"):
                    symbol = line.strip("*").split("(")[0].strip()
                    if len(symbol) <= 5 and symbol.isupper():
                        symbols.append(symbol)
            return symbols
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
    
    # Default watchlist
    return ["SMCI", "AMD", "PLTR", "INTC", "GLW"]

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
        }
    )
