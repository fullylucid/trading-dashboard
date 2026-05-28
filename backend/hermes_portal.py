"""
Hermes Portal - Real-time Dashboard Screenshot Service
Provides on-demand and auto-refresh screenshot capabilities via FastAPI
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import base64

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
except ImportError:
    raise ImportError("playwright is required. Install with: pip install playwright")

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

PORTAL_TARGET_URL = os.getenv("PORTAL_TARGET_URL", "http://localhost:3000")
SCREENSHOT_TIMEOUT = 30000  # 30 seconds in milliseconds
SCREENSHOT_WIDTH = 1920
SCREENSHOT_HEIGHT = 1080

# Global browser instance (lazy-loaded)
_browser: Optional[Browser] = None
_browser_lock = asyncio.Lock()

# ============================================================================
# Response Models
# ============================================================================

class ScreenshotResponse(BaseModel):
    """Screenshot response model"""
    screenshot: str  # base64-encoded PNG
    url: str  # The URL that was captured
    timestamp: str  # ISO 8601 timestamp
    size: int  # Size in bytes (before encoding)
    resolution: dict  # {"width": 1920, "height": 1080}


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    playwright_ready: bool
    target_url: str
    timestamp: str


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: str
    timestamp: str


# ============================================================================
# Browser Management
# ============================================================================

async def get_browser() -> Browser:
    """
    Get or create a browser instance (lazy-loaded, singleton pattern)
    """
    global _browser
    
    async with _browser_lock:
        if _browser is None:
            logger.info("Initializing Playwright browser...")
            try:
                playwright = await async_playwright().start()
                _browser = await playwright.chromium.launch(headless=True)
                logger.info("Playwright browser initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Playwright: {e}")
                raise
    
    return _browser


async def close_browser():
    """Close the browser instance"""
    global _browser
    
    async with _browser_lock:
        if _browser is not None:
            try:
                await _browser.close()
                logger.info("Playwright browser closed")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            finally:
                _browser = None


# ============================================================================
# Screenshot Capture
# ============================================================================

async def capture_screenshot(url: str = PORTAL_TARGET_URL) -> dict:
    """
    Capture a screenshot of the specified URL
    
    Args:
        url: Target URL to capture (defaults to PORTAL_TARGET_URL)
    
    Returns:
        dict with:
            - screenshot: base64-encoded PNG
            - url: The captured URL
            - timestamp: ISO 8601 timestamp
            - size: PNG size in bytes
            - resolution: {"width": 1920, "height": 1080}
    
    Raises:
        Exception: If screenshot capture fails
    """
    logger.info(f"Capturing screenshot from: {url}")
    
    browser = await get_browser()
    context: Optional[BrowserContext] = None
    
    try:
        # Create a new context for isolation
        context = await browser.new_context(
            viewport={"width": SCREENSHOT_WIDTH, "height": SCREENSHOT_HEIGHT},
            extra_http_headers={
                "User-Agent": "Hermes Portal Screenshot Agent"
            }
        )
        
        page = await context.new_page()
        
        # Set timeout
        page.set_default_timeout(SCREENSHOT_TIMEOUT)
        page.set_default_navigation_timeout(SCREENSHOT_TIMEOUT)
        
        # Navigate to URL
        logger.debug(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle", timeout=SCREENSHOT_TIMEOUT)
        
        # Wait a bit for any animations/rendering
        await asyncio.sleep(1)
        
        # Capture screenshot
        logger.debug(f"Capturing screenshot for {url}...")
        png_bytes = await page.screenshot(full_page=False)
        
        # Encode to base64
        base64_str = base64.b64encode(png_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{base64_str}"
        
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Screenshot captured successfully from {url} ({len(png_bytes)} bytes)")
        
        return {
            "screenshot": data_url,
            "url": url,
            "timestamp": timestamp,
            "size": len(png_bytes),
            "resolution": {
                "width": SCREENSHOT_WIDTH,
                "height": SCREENSHOT_HEIGHT
            }
        }
    
    except asyncio.TimeoutError:
        error_msg = f"Timeout capturing screenshot from {url} (max {SCREENSHOT_TIMEOUT}ms)"
        logger.error(error_msg)
        raise TimeoutError(error_msg)
    
    except Exception as e:
        error_msg = f"Failed to capture screenshot from {url}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise
    
    finally:
        # Clean up context
        if context is not None:
            try:
                await context.close()
            except Exception as e:
                logger.warning(f"Error closing browser context: {e}")


# ============================================================================
# FastAPI Router
# ============================================================================

router = APIRouter(prefix="/api/portal", tags=["hermes-portal"])


@router.get("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(url: str = Query(PORTAL_TARGET_URL, description="Target URL to capture")):
    """
    Capture a screenshot of a specified URL
    
    Query Parameters:
        url: Target URL (defaults to PORTAL_TARGET_URL environment variable)
    
    Returns:
        ScreenshotResponse with base64-encoded PNG and metadata
    
    Example:
        GET /api/portal/screenshot?url=http://localhost:3000
    """
    try:
        # Validate URL
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        
        result = await capture_screenshot(url)
        return ScreenshotResponse(**result)
    
    except TimeoutError as e:
        logger.error(f"Screenshot timeout: {e}")
        raise HTTPException(
            status_code=504,
            detail=f"Screenshot capture timeout: {str(e)}"
        )
    
    except ValueError as e:
        logger.error(f"Invalid URL: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid URL: {str(e)}"
        )
    
    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Screenshot capture failed: {str(e)}"
        )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for Hermes Portal
    
    Returns:
        HealthResponse with status and Playwright readiness
    
    Example:
        GET /api/portal/health
    """
    try:
        # Test if browser can be initialized
        browser = await get_browser()
        playwright_ready = browser is not None
    except Exception as e:
        logger.error(f"Browser health check failed: {e}")
        playwright_ready = False
    
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    return HealthResponse(
        status="ok" if playwright_ready else "degraded",
        playwright_ready=playwright_ready,
        target_url=PORTAL_TARGET_URL,
        timestamp=timestamp
    )


# ============================================================================
# Lifecycle Management
# ============================================================================

async def startup_event():
    """Called when the FastAPI app starts"""
    logger.info("Hermes Portal startup - warming up browser...")
    try:
        await get_browser()
        logger.info("Hermes Portal ready")
    except Exception as e:
        logger.error(f"Failed to warm up browser: {e}")


async def shutdown_event():
    """Called when the FastAPI app shuts down"""
    logger.info("Hermes Portal shutdown - closing browser...")
    await close_browser()
