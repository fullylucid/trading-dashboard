"""
Configuration management for Trading Dashboard
Loads from environment variables with sensible defaults
"""

import os
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    """Application settings from environment"""
    
    # Server
    HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("DASHBOARD_PORT", "8000"))
    ENV: str = os.getenv("DASHBOARD_ENV", "development")
    
    # API Keys
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    
    # Paths
    HERMES_HOME: str = os.path.expanduser("~/.hermes")
    LOG_DIR: str = os.path.expanduser("~/.hermes/logs")
    QUANT_TOOLKIT_PATH: str = os.path.expanduser("~/.hermes/scripts/quant-toolkit.py")
    MEMORY_FILE: str = os.path.expanduser("~/.hermes/MEMORY.md")
    
    # Cache
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL: int = 300  # 5 minutes
    
    # WebSocket
    SIGNAL_UPDATE_INTERVAL: int = 5  # seconds
    PRICE_UPDATE_INTERVAL: float = 0.5  # seconds
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
        os.getenv("FRONTEND_URL", "http://localhost:3000")
    ]
    
    # Rate limiting
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    
    # Telegram (for alerts)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
