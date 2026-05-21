"""
Cache management for Trading Dashboard
Fallback to in-memory cache if Redis unavailable
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

class CacheManager:
    """Handle caching with Redis fallback to in-memory"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.in_memory_cache: Dict[str, tuple] = {}  # (value, expiry_time)
        self.logger = logging.getLogger("cache_manager")
        
        # Try to connect to Redis
        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()
                self.logger.info("Connected to Redis")
            except Exception as e:
                self.logger.warning(f"Redis connection failed, using in-memory cache: {e}")
                self.redis_client = None
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if self.redis_client:
            try:
                return self.redis_client.get(key)
            except Exception as e:
                self.logger.warning(f"Redis get failed: {e}")
        
        # Fallback to in-memory
        if key in self.in_memory_cache:
            value, expiry = self.in_memory_cache[key]
            if expiry > datetime.utcnow():
                return value
            else:
                del self.in_memory_cache[key]
        
        return None
    
    async def set(self, key: str, value: str, ttl: int = 300) -> bool:
        """Set value in cache with TTL"""
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl, value)
                return True
            except Exception as e:
                self.logger.warning(f"Redis set failed: {e}")
        
        # Fallback to in-memory
        expiry = datetime.utcnow() + timedelta(seconds=ttl)
        self.in_memory_cache[key] = (value, expiry)
        return True
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if self.redis_client:
            try:
                self.redis_client.delete(key)
                return True
            except Exception as e:
                self.logger.warning(f"Redis delete failed: {e}")
        
        if key in self.in_memory_cache:
            del self.in_memory_cache[key]
            return True
        
        return False
    
    async def get_json(self, key: str) -> Optional[Dict]:
        """Get JSON value from cache"""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
    
    async def set_json(self, key: str, value: Dict, ttl: int = 300) -> bool:
        """Set JSON value in cache"""
        return await self.set(key, json.dumps(value), ttl)
    
    async def cleanup(self):
        """Cleanup expired in-memory cache entries"""
        expired_keys = [
            k for k, (_, expiry) in self.in_memory_cache.items()
            if expiry <= datetime.utcnow()
        ]
        for key in expired_keys:
            del self.in_memory_cache[key]
