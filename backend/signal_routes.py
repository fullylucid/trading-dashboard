"""
Signal API Routes
FastAPI endpoints for signal generation and scanner details
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

# Hermes integration
from hermes_signals.models import Signal
from hermes_signals.formatter import SignalFormatter

logger = logging.getLogger(__name__)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ScannerComponentsModel(BaseModel):
    """Scanner output components"""
    pass  # Dynamic based on scanner


class ScannerResultModel(BaseModel):
    """Single scanner result"""
    scanner: str
    symbol: str
    signal: str
    confidence: float
    components: Dict[str, Any]
    reason: str
    error: Optional[str] = None


class SignalModel(BaseModel):
    """Complete signal result"""
    id: str
    timestamp: str
    symbol: str
    signal: str  # "buy", "sell", "hold"
    confidence: float  # 0-100
    scanners_used: List[str]
    components: Dict[str, Any]
    reason: str
    alerts_sent: List[str] = []


class SignalFeedModel(BaseModel):
    """Signal feed entry (recent alerts)"""
    id: str
    timestamp: str
    symbol: str
    signal: str
    confidence: float


class ScannerHealthModel(BaseModel):
    """Scanner health status"""
    scanner: str
    active: bool
    failures: int
    circuit_broken: bool


class SystemHealthModel(BaseModel):
    """Overall system health"""
    timestamp: str
    scanners: Dict[str, ScannerHealthModel]


# ============================================================================
# ROUTER SETUP
# ============================================================================

def create_signal_routes(signal_engine, cache_manager):
    """Create signal API routes"""
    router = APIRouter(prefix="/api/signals", tags=["signals"])
    
    # ========================================================================
    # GET ENDPOINTS
    # ========================================================================
    
    @router.get("/", response_model=List[SignalFeedModel])
    async def get_recent_signals(
        limit: int = Query(20, ge=1, le=100),
        minutes: int = Query(60, ge=5, le=1440),
    ):
        """
        Get recent signals (last N minutes)
        
        Args:
            limit: Max signals to return
            minutes: Look back window (default 60 minutes)
            
        Returns:
            List of recent signals
        """
        try:
            # Get signals from cache or log file
            signals = []
            cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
            
            # In production: read from signals.jsonl
            # For now: return from cache
            
            return signals
        except Exception as e:
            logger.error(f"Failed to get recent signals: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve signals")
    
    @router.get("/{symbol}", response_model=SignalModel)
    async def get_signal_for_symbol(symbol: str):
        """
        Get latest signal for a specific symbol
        
        Args:
            symbol: Stock ticker (e.g., AAPL, TSLA)
            
        Returns:
            Latest signal with all scanner components
        """
        try:
            # Get from cache
            cached = await cache_manager.get(f"signal:{symbol}")
            if cached:
                import json
                return json.loads(cached)
            
            raise HTTPException(status_code=404, detail=f"No signal found for {symbol}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get signal for {symbol}: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve signal")
    
    @router.get("/{symbol}/history", response_model=List[SignalFeedModel])
    async def get_signal_history(
        symbol: str,
        limit: int = Query(50, ge=1, le=500),
        hours: int = Query(24, ge=1, le=168),
    ):
        """
        Get signal history for a symbol
        
        Args:
            symbol: Stock ticker
            limit: Max results
            hours: Lookback window
            
        Returns:
            List of historical signals
        """
        try:
            signals = []
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # In production: query signals.jsonl or Redis list
            
            return signals[:limit]
        except Exception as e:
            logger.error(f"Failed to get signal history for {symbol}: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve history")

    @router.get("/hermes/{symbol}", response_model=Dict[str, Any])
    async def get_hermes_signal(
        symbol: str,
        score: float = Query(75.0, ge=0, le=100),
        action: str = Query("BUY"),
    ):
        """
        Generate a Hermes-formatted professional signal for a symbol.
        Uses the enhanced Hermes signal model and multi-channel formatter.
        """
        try:
            from hermes_signals.engine import SignalEngine
            from hermes_signals.models import SignalAction, SignalCategory, SignalStrength

            engine = SignalEngine()
            signal = engine.create_signal(
                ticker=symbol.upper(),
                name=symbol.upper(),
                category=SignalCategory.MOMENTUM,
                action=SignalAction[action.upper()] if action.upper() in ["BUY", "SELL", "HOLD"] else SignalAction.BUY,
                score=int(score),
                strength=SignalStrength.STRONG if score >= 70 else SignalStrength.MODERATE,
                current_price=0.0,
                price_change_percent=0.0,
                volume=0.0,
                avg_volume=0.0,
                catalyst="Hermes-enhanced signal via trading-dashboard",
            )

            formatter = SignalFormatter()
            telegram_card = formatter.format_telegram_message(signal)
            rest_payload = signal.to_dict()

            return {
                "hermes_signal": rest_payload,
                "telegram_card": telegram_card,
                "channels": ["telegram", "websocket", "rest", "react"],
            }
        except Exception as e:
            logger.error(f"Hermes signal generation failed for {symbol}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # ========================================================================
    # SCANNER DETAIL ENDPOINTS
    # ========================================================================
    
    @router.get("/scanner/{scanner_type}", response_model=ScannerResultModel)
    async def get_scanner_output(
        scanner_type: str,
        symbol: str = Query(...),
    ):
        """
        Get detailed output from specific scanner
        
        Args:
            scanner_type: Scanner name (smart_money, options, sec, sentiment, etc.)
            symbol: Stock ticker
            
        Returns:
            Scanner output with components and confidence
        """
        valid_scanners = [
            "sec",
            "quant_ensemble",
            "technical",
        ]
        
        if scanner_type not in valid_scanners:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scanner: {scanner_type}. Valid options: {', '.join(valid_scanners)}"
            )
        
        try:
            # Get details from signal engine
            details = await signal_engine.get_scanner_details(scanner_type, symbol)
            if not details:
                raise HTTPException(status_code=404, detail=f"Scanner {scanner_type} not found")
            
            return details
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get scanner output: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve scanner output")
    
    @router.get("/scanner/{scanner_type}/health", response_model=ScannerHealthModel)
    async def get_scanner_health(scanner_type: str):
        """
        Get health status of specific scanner
        
        Args:
            scanner_type: Scanner name
            
        Returns:
            Health status with failure count
        """
        try:
            health = await signal_engine.get_health_status()
            if scanner_type not in health.get("scanners", {}):
                raise HTTPException(status_code=404, detail=f"Scanner {scanner_type} not found")
            
            scanner_health = health["scanners"][scanner_type]
            return ScannerHealthModel(
                scanner=scanner_type,
                **scanner_health
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get scanner health: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve health")
    
    @router.get("/health/status", response_model=SystemHealthModel)
    async def get_health_status():
        """
        Get health status of all scanners
        
        Returns:
            System health with all scanner statuses
        """
        try:
            health = await signal_engine.get_health_status()
            
            # Convert to response model
            scanners = {}
            for name, status in health.get("scanners", {}).items():
                scanners[name] = ScannerHealthModel(
                    scanner=name,
                    **status
                )
            
            return SystemHealthModel(
                timestamp=health["timestamp"],
                scanners=scanners
            )
        except Exception as e:
            logger.error(f"Failed to get health status: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve health")
    
    return router


# ============================================================================
# WEBHOOK ROUTES
# ============================================================================

def create_telegram_webhook_routes(telegram_bot):
    """Create Telegram webhook routes"""
    router = APIRouter(prefix="/api/telegram", tags=["telegram"])
    
    @router.post("/webhook")
    async def telegram_webhook(payload: Dict[str, Any]):
        """
        Handle Telegram webhook
        
        Args:
            payload: Telegram update payload
            
        Returns:
            OK response
        """
        try:
            result = await telegram_bot.handle_webhook(payload)
            return result
        except Exception as e:
            logger.error(f"Telegram webhook error: {e}")
            raise HTTPException(status_code=500, detail="Webhook processing failed")
    
    return router


# ============================================================================
# MODULE-LEVEL EXPORT (required for main.py import)
# ============================================================================

# Create the signal router at import time so `from signal_routes import signal_router`
# succeeds and all routes (including /hermes/{symbol}) are registered.
signal_router = create_signal_routes(None, None)
