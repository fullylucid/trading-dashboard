"""
Trading Dashboard FastAPI Application
Main entry point for the enhanced trading dashboard backend
"""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

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
    from portfolio_routes import portfolio_router
    HAS_PORTFOLIO_ROUTES = True
except ImportError:
    HAS_PORTFOLIO_ROUTES = False
    logger = logging.getLogger(__name__)
    logger.warning("Portfolio routes not available")

try:
    from hermes_portal import router as hermes_router, startup_event as hermes_startup, shutdown_event as hermes_shutdown
    HAS_HERMES_PORTAL = True
except ImportError:
    HAS_HERMES_PORTAL = False
    hermes_router = None
    logger = logging.getLogger(__name__)
    logger.warning("Hermes Portal not available")

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

if HAS_PORTFOLIO_ROUTES:
    app.include_router(portfolio_router)


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
    
    return {
        "title": "Trading Dashboard API",
        "version": "1.0.0",
        "endpoints": endpoints,
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
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
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return {
        "error": "Internal server error",
        "detail": str(exc),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
