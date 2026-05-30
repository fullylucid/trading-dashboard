"""
Trading Dashboard FastAPI Application
Main entry point for the enhanced trading dashboard backend
"""

import logging
import os
import sys
from pathlib import Path

# --- sys.path bootstrap -----------------------------------------------------
# Charlotte modules use two import styles depending on era:
#   - Legacy detectors do `from charlotte import X`  -> needs hermes/ on path
#   - Phase 2 modules do `from hermes.charlotte.X`   -> needs repo root on path
# Add both so research_routes.py imports resolve from a single uvicorn entry.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_HERMES_DIR = _REPO_ROOT / "hermes"
for _p in (str(_REPO_ROOT), str(_HERMES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# ----------------------------------------------------------------------------

import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from news_aggregator import NewsAggregator
from earnings_calendar import EarningsCalendar
from market_data import MarketData
from research_agent import ResearchAgent
from research_routes import (
    news_router,
    research_router,
    earnings_router,
    market_router,
    initialize_services,
)

try:
    from signal_routes import signal_router
    HAS_SIGNAL_ROUTES = True
except ImportError:
    HAS_SIGNAL_ROUTES = False
    logger = logging.getLogger(__name__)
    logger.warning("Signal routes not available")

try:
    from deep_dive_routes import deep_dive_router
    HAS_DEEP_DIVE_ROUTES = True
except ImportError as _dd_err:
    HAS_DEEP_DIVE_ROUTES = False
    logging.getLogger(__name__).warning(f"Deep dive routes not available: {_dd_err}")

try:
    from portfolio_routes import portfolio_router
    HAS_PORTFOLIO_ROUTES = True
except ImportError:
    HAS_PORTFOLIO_ROUTES = False
    logger = logging.getLogger(__name__)
    logger.warning("Portfolio routes not available")

try:
    from sector_rotation_routes import sector_rotation_router
    HAS_SECTOR_ROTATION_ROUTES = True
except Exception as _sr_err:  # broad: package pulls optional data deps lazily
    HAS_SECTOR_ROTATION_ROUTES = False
    sector_rotation_router = None
    logging.getLogger(__name__).warning(f"Sector-rotation routes not available: {_sr_err!r}")

try:
    from hermes_portal import router as hermes_router, startup_event as hermes_startup, shutdown_event as hermes_shutdown
    HAS_HERMES_PORTAL = True
except Exception as _hp_err:
    HAS_HERMES_PORTAL = False
    hermes_router = None
    logger = logging.getLogger(__name__)
    logger.warning(f"Hermes Portal not available: {_hp_err!r}")

try:
    from agent_bridge import (
        router as agent_router,
        startup_event as agent_startup,
        shutdown_event as agent_shutdown,
        set_ws_manager as agent_set_ws_manager,
        verify_ws_ticket as agent_verify_ws_ticket,
    )
    HAS_AGENT_BRIDGE = True
except Exception as _ab_err:
    HAS_AGENT_BRIDGE = False
    agent_router = None
    logging.getLogger(__name__).warning(f"Agent bridge not available: {_ab_err!r}")

from websocket_manager import WebSocketManager

# Shared WebSocket manager singleton (used by the agent bridge live stream).
ws_manager = WebSocketManager()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

class Settings:
    """Application settings"""
    
    # API Keys (load from environment)
    FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
    ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    FMP_API_KEY = os.getenv("FMP_API_KEY", "")
    
    # Ollama Cloud Configuration
    OLLAMA_CLOUD_BASE_URL = os.getenv(
        "OLLAMA_CLOUD_BASE_URL", "https://api.ollama.cloud/v1"
    )
    OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")
    OLLAMA_CLOUD_MODEL = os.getenv("OLLAMA_CLOUD_MODEL", "kimi-k-3-70b")

    # Agent bridge (messenger -> local Claude) secrets
    OWNER_PASSWORD_HASH = os.getenv("OWNER_PASSWORD_HASH", "")
    SESSION_SECRET = os.getenv("SESSION_SECRET", "")
    AGENT_WORKER_TOKEN = os.getenv("AGENT_WORKER_TOKEN", "")
    
    # API Settings
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",  # Vite default
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]


settings = Settings()

# ============================================================================
# Initialize Services on Startup
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle
    Startup: Initialize services
    Shutdown: Cleanup resources
    """
    # Startup
    logger.info("Starting Trading Dashboard Backend...")
    
    # Initialize API clients
    api_keys = {
        "finnhub": settings.FINNHUB_API_KEY,
        "alpha_vantage": settings.ALPHA_VANTAGE_API_KEY,
        "fmp": settings.FMP_API_KEY,
    }
    
    # Initialize service instances
    news_agg = NewsAggregator(api_keys)
    earnings_cal = EarningsCalendar(api_keys)
    market_dat = MarketData(api_keys)
    research_ag = ResearchAgent(
        {
            "base_url": settings.OLLAMA_CLOUD_BASE_URL,
            "api_key": settings.OLLAMA_CLOUD_API_KEY,
            "model": settings.OLLAMA_CLOUD_MODEL,
        }
    )
    
    # Initialize routes with service instances
    initialize_services(news_agg, earnings_cal, market_dat, research_ag)
    
    # Initialize Hermes Portal if available
    if HAS_HERMES_PORTAL:
        try:
            await hermes_startup()
            logger.info("Hermes Portal initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Hermes Portal: {e}")

    # Initialize Agent Bridge if available (fail loud: the bus must reach Redis)
    if HAS_AGENT_BRIDGE:
        try:
            await agent_startup()
            agent_set_ws_manager(ws_manager)
            logger.info("Agent bridge initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Agent bridge: {e}")

    logger.info("All services initialized successfully")
    logger.info(f"CORS origins: {settings.CORS_ORIGINS}")
    
    # Validate API keys
    if not api_keys.get("finnhub"):
        logger.warning("FINNHUB_API_KEY not configured")
    if not api_keys.get("alpha_vantage"):
        logger.warning("ALPHA_VANTAGE_API_KEY not configured")
    if not api_keys.get("fmp"):
        logger.warning("FMP_API_KEY not configured")
    if not settings.OLLAMA_CLOUD_API_KEY:
        logger.warning("OLLAMA_CLOUD_API_KEY not configured - research features disabled")
    
    yield  # Application runs here
    
    # Shutdown
    logger.info("Shutting down Trading Dashboard Backend...")
    
    # Shutdown Hermes Portal if available
    if HAS_HERMES_PORTAL:
        try:
            await hermes_shutdown()
            logger.info("Hermes Portal shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down Hermes Portal: {e}")

    # Shutdown Agent Bridge if available
    if HAS_AGENT_BRIDGE:
        try:
            await agent_shutdown()
            logger.info("Agent bridge shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down Agent bridge: {e}")

    await news_agg.clear_cache()
    await earnings_cal.clear_cache()
    await market_dat.clear_cache()
    await research_ag.clear_cache()
    logger.info("Cleanup complete")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Trading Dashboard API",
    description="Comprehensive trading dashboard with news, research, earnings, and market data",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Register Routes
# ============================================================================

app.include_router(news_router)
app.include_router(research_router)
app.include_router(earnings_router)
app.include_router(market_router)

if HAS_SIGNAL_ROUTES:
    app.include_router(signal_router)

if HAS_DEEP_DIVE_ROUTES:
    app.include_router(deep_dive_router)
    logging.getLogger(__name__).info("Deep dive router registered at /api/research/deep/*")

if HAS_PORTFOLIO_ROUTES:
    app.include_router(portfolio_router)
if HAS_SECTOR_ROTATION_ROUTES and sector_rotation_router is not None:
    app.include_router(sector_rotation_router)
    logger.info("Sector-rotation router registered at /api/sector-rotation")
if HAS_HERMES_PORTAL and hermes_router is not None:
    app.include_router(hermes_router)
    logger.info("Hermes Portal router registered at /api/portal/*")

if HAS_AGENT_BRIDGE and agent_router is not None:
    app.include_router(agent_router)
    logger.info("Agent bridge router registered at /api/agent/*")


# ============================================================================
# Agent live-stream WebSocket
# ============================================================================

@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    """
    Live stream of agent chat events to the browser.

    Authenticated by a short-lived ticket (issued from GET /api/agent/ws-ticket
    by an already-session-authenticated browser) passed as ?ticket=...; the
    session cookie is not reliably readable in the WS handshake.

    After connecting, the client subscribes to its conversation channel(s) with
    {"action": "subscribe", "symbols": ["chat:<conversation_id>"]}.
    """
    ticket = websocket.query_params.get("ticket", "")
    if not (HAS_AGENT_BRIDGE and agent_verify_ws_ticket(ticket)):
        await websocket.close(code=4401)
        return
    client_id = f"agent-{uuid.uuid4().hex[:12]}"
    await ws_manager.handle_connection(websocket, client_id)


# ============================================================================
# Root Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint - API overview"""
    endpoints = {
        "news": "/api/news",
        "research": "/api/research",
        "earnings": "/api/earnings",
        "market": "/api/market",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
    
    if HAS_SIGNAL_ROUTES:
        endpoints["signals"] = "/api/signals"
    
    if HAS_PORTFOLIO_ROUTES:
        endpoints["portfolio"] = "/api/portfolio"

    if HAS_SECTOR_ROTATION_ROUTES:
        endpoints["sector_rotation"] = "/api/sector-rotation"

    return {
        "title": "Trading Dashboard API",
        "version": "1.0.0",
        "endpoints": endpoints,
    }


@app.get("/health")
@app.get("/api/health")
async def health():
    """Health check endpoint (served at both /health and /api/health;
    DigitalOcean ingress forwards /api/* to this service with the prefix preserved)."""
    return {
        "status": "healthy",
        "service": "Trading Dashboard API",
        "version": "1.0.0",
    }


@app.get("/api/stats")
async def get_stats():
    """Get API statistics"""
    return {
        "service": "Trading Dashboard",
        "version": "1.0.0",
        "features": [
            "Market News & Articles",
            "Research Summaries (Kimi K)",
            "Earnings Calendar",
            "Market Data & Breadth",
            "Sector Performance",
            "Sentiment Analysis",
        ],
        "status": "operational",
    }


# ============================================================================
# Custom OpenAPI Schema
# ============================================================================

def custom_openapi():
    """Custom OpenAPI schema"""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Trading Dashboard API",
        version="1.0.0",
        description="Enhanced trading dashboard with comprehensive market research and data",
        routes=app.routes,
    )

    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# ============================================================================
# Error Handling
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler.

    Log the full trace server-side only; return a generic 500 so tracebacks
    (which may contain tokens/secrets) never reach the client.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
