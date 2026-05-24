"""
Robinhood Portfolio Tracker
Real-time portfolio data from Robinhood integrated with trading dashboard
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio
from functools import lru_cache

try:
    import robin_stocks.robinhood as rh
except ImportError:
    rh = None

logger = logging.getLogger(__name__)


class RobinhoodPortfolio:
    """Robinhood portfolio tracker and data provider"""
    
    def __init__(self, username: str = None, password: str = None, mfa_code: Optional[str] = None):
        """
        Initialize Robinhood connection
        
        Args:
            username: Robinhood username (or env: ROBINHOOD_USERNAME)
            password: Robinhood password (or env: ROBINHOOD_PASSWORD)
            mfa_code: Optional 2FA code
        """
        if not rh:
            raise ImportError("robin_stocks not installed. Run: pip install robin_stocks")
        
        self.username = username or os.getenv('ROBINHOOD_USERNAME')
        self.password = password or os.getenv('ROBINHOOD_PASSWORD')
        self.mfa_code = mfa_code
        self.authenticated = False
        self._cache = {}
        self._cache_timestamp = {}
        self._cache_ttl = 300  # 5 minutes
        
        logger.info("RobinhoodPortfolio initialized")
    
    async def authenticate(self) -> bool:
        """
        Authenticate with Robinhood
        Uses 2FA if available
        """
        if not self.username or not self.password:
            logger.error("ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD not configured")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            
            # Run blocking rh.login in executor to avoid blocking
            if self.mfa_code:
                await loop.run_in_executor(
                    None,
                    rh.login,
                    self.username,
                    self.password,
                    None,  # expiresIn
                    self.mfa_code,  # mfa_code
                )
            else:
                await loop.run_in_executor(
                    None,
                    rh.login,
                    self.username,
                    self.password,
                )
            
            self.authenticated = True
            logger.info(f"✅ Authenticated with Robinhood as {self.username}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Robinhood authentication failed: {e}")
            self.authenticated = False
            return False
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still valid"""
        if key not in self._cache_timestamp:
            return False
        
        age = datetime.now() - self._cache_timestamp[key]
        return age.total_seconds() < self._cache_ttl
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached data if valid"""
        if self._is_cache_valid(key):
            return self._cache[key]
        return None
    
    def _set_cached(self, key: str, value: Any):
        """Cache data with timestamp"""
        self._cache[key] = value
        self._cache_timestamp[key] = datetime.now()
    
    async def get_portfolio(self) -> Dict[str, Any]:
        """
        Get complete portfolio summary
        
        Returns:
            {
                "account_value": float,
                "buying_power": float,
                "cash": float,
                "positions": [...],
                "summary": {...},
                "timestamp": datetime
            }
        """
        if not self.authenticated:
            await self.authenticate()
            if not self.authenticated:
                return {"error": "Not authenticated", "positions": []}
        
        cached = self._get_cached('portfolio')
        if cached:
            return cached
        
        try:
            loop = asyncio.get_event_loop()
            
            # Fetch all data in parallel
            portfolio = await asyncio.gather(
                loop.run_in_executor(None, self._get_account_info),
                loop.run_in_executor(None, self._get_positions),
                loop.run_in_executor(None, self._get_watchlist),
            )
            
            account_info, positions, watchlist = portfolio
            
            # Calculate summary
            summary = self._calculate_summary(account_info, positions)
            
            result = {
                "account_value": account_info.get('account_equity', 0),
                "buying_power": account_info.get('buying_power', 0),
                "cash": account_info.get('cash', 0),
                "positions": positions,
                "watchlist": watchlist,
                "summary": summary,
                "timestamp": datetime.now().isoformat(),
            }
            
            self._set_cached('portfolio', result)
            return result
            
        except Exception as e:
            logger.error(f"❌ Error fetching portfolio: {e}")
            return {
                "error": str(e),
                "positions": [],
                "timestamp": datetime.now().isoformat(),
            }
    
    def _get_account_info(self) -> Dict[str, float]:
        """Fetch account information"""
        try:
            account = rh.get_account()
            
            return {
                "account_equity": float(account.get('account_number', 0)),
                "buying_power": float(account.get('buying_power', 0)),
                "cash": float(account.get('cash', 0)),
                "portfolio_value": float(account.get('portfolio_value', 0)),
                "account_number": account.get('account_number', 'N/A'),
                "portfolio_cash": float(account.get('portfolio_cash', 0)),
            }
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            return {}
    
    def _get_positions(self) -> List[Dict[str, Any]]:
        """Fetch all open positions"""
        try:
            positions_data = rh.get_open_stock_positions()
            positions = []
            
            for position in positions_data:
                try:
                    instrument = rh.get_instrument_by_url(position.get('instrument'))
                    quote = rh.get_quotes(instrument.get('symbol'))[0] if instrument else None
                    
                    if quote:
                        qty = float(position.get('quantity', 0))
                        current_price = float(quote.get('last_trade_price', 0))
                        avg_buy_price = float(position.get('average_buy_price', 0))
                        
                        current_value = qty * current_price
                        cost_basis = qty * avg_buy_price
                        gain_loss = current_value - cost_basis
                        gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis > 0 else 0
                        
                        positions.append({
                            "symbol": instrument.get('symbol'),
                            "quantity": qty,
                            "current_price": current_price,
                            "average_buy_price": avg_buy_price,
                            "current_value": current_value,
                            "cost_basis": cost_basis,
                            "gain_loss": gain_loss,
                            "gain_loss_pct": gain_loss_pct,
                            "last_trade_price": float(quote.get('last_trade_price', 0)),
                            "bid_price": float(quote.get('bid_price', 0)),
                            "ask_price": float(quote.get('ask_price', 0)),
                            "pe_ratio": quote.get('pe_ratio'),
                            "market_cap": quote.get('market_cap'),
                        })
                
                except Exception as e:
                    logger.warning(f"Error processing position: {e}")
                    continue
            
            return sorted(positions, key=lambda x: x['current_value'], reverse=True)
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def _get_watchlist(self) -> List[Dict[str, Any]]:
        """Fetch watchlist items"""
        try:
            watchlist = rh.get_watchlist_by_name('Default')
            items = []
            
            if watchlist and 'results' in watchlist:
                for item in watchlist.get('results', [])[:20]:  # Limit to 20
                    try:
                        symbol = item.get('symbol')
                        quote = rh.get_quotes(symbol)[0] if symbol else None
                        
                        if quote:
                            items.append({
                                "symbol": symbol,
                                "last_trade_price": float(quote.get('last_trade_price', 0)),
                                "bid_price": float(quote.get('bid_price', 0)),
                                "ask_price": float(quote.get('ask_price', 0)),
                                "previous_close": float(quote.get('previous_close', 0)),
                                "change_pct": float(quote.get('ask_price', 0)) / float(quote.get('previous_close', 1) or 1) - 1,
                            })
                    except Exception as e:
                        logger.warning(f"Error fetching watchlist item {symbol}: {e}")
                        continue
            
            return items
            
        except Exception as e:
            logger.warning(f"Error fetching watchlist: {e}")
            return []
    
    def _calculate_summary(self, account: Dict, positions: List[Dict]) -> Dict[str, Any]:
        """Calculate portfolio summary statistics"""
        
        if not positions:
            return {
                "total_positions": 0,
                "portfolio_value": 0,
                "total_gain_loss": 0,
                "total_gain_loss_pct": 0,
                "top_position": None,
                "sector_breakdown": {},
            }
        
        total_positions = len(positions)
        portfolio_value = sum(p['current_value'] for p in positions)
        total_gain_loss = sum(p['gain_loss'] for p in positions)
        total_gain_loss_pct = (total_gain_loss / sum(p['cost_basis'] for p in positions if p['cost_basis'] > 0)) * 100
        
        # Find top position
        top_position = max(positions, key=lambda x: x['current_value']) if positions else None
        
        return {
            "total_positions": total_positions,
            "portfolio_value": portfolio_value,
            "total_gain_loss": total_gain_loss,
            "total_gain_loss_pct": total_gain_loss_pct,
            "top_position": {
                "symbol": top_position['symbol'],
                "value": top_position['current_value'],
                "pct_of_portfolio": (top_position['current_value'] / portfolio_value * 100) if portfolio_value > 0 else 0,
            } if top_position else None,
        }
    
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get specific position details"""
        portfolio = await self.get_portfolio()
        positions = portfolio.get('positions', [])
        
        for pos in positions:
            if pos['symbol'] == symbol:
                return pos
        
        return None
    
    async def get_performance(self, days: int = 30) -> Dict[str, Any]:
        """Get portfolio performance over time (simplified)"""
        
        if not self.authenticated:
            await self.authenticate()
            if not self.authenticated:
                return {}
        
        cached = self._get_cached(f'performance_{days}')
        if cached:
            return cached
        
        try:
            loop = asyncio.get_event_loop()
            orders = await loop.run_in_executor(None, rh.get_all_orders)
            
            # Filter recent orders
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_orders = []
            
            for order in orders:
                try:
                    created_at = datetime.fromisoformat(order.get('created_at', '').replace('Z', '+00:00'))
                    if created_at > cutoff_date:
                        recent_orders.append({
                            "symbol": order.get('symbol'),
                            "side": order.get('side'),  # buy/sell
                            "quantity": float(order.get('quantity', 0)),
                            "price": float(order.get('price', 0)),
                            "state": order.get('state'),
                            "created_at": created_at.isoformat(),
                        })
                except Exception as e:
                    logger.warning(f"Error processing order: {e}")
                    continue
            
            result = {
                "recent_orders": recent_orders[:20],  # Last 20 orders
                "buy_orders": len([o for o in recent_orders if o['side'] == 'buy']),
                "sell_orders": len([o for o in recent_orders if o['side'] == 'sell']),
            }
            
            self._set_cached(f'performance_{days}', result)
            return result
            
        except Exception as e:
            logger.error(f"Error fetching performance: {e}")
            return {}
    
    async def logout(self):
        """Logout from Robinhood"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, rh.logout)
            self.authenticated = False
            logger.info("Logged out from Robinhood")
        except Exception as e:
            logger.error(f"Error logging out: {e}")


# Global instance
_portfolio_instance: Optional[RobinhoodPortfolio] = None


async def get_portfolio_instance() -> RobinhoodPortfolio:
    """Get or create global portfolio instance"""
    global _portfolio_instance
    
    if _portfolio_instance is None:
        _portfolio_instance = RobinhoodPortfolio()
        authenticated = await _portfolio_instance.authenticate()
        if not authenticated:
            logger.error("Failed to authenticate with Robinhood")
    
    return _portfolio_instance


async def clear_portfolio_cache():
    """Clear portfolio cache"""
    global _portfolio_instance
    if _portfolio_instance:
        _portfolio_instance._cache.clear()
        _portfolio_instance._cache_timestamp.clear()
