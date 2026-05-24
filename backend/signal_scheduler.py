"""
Signal Scheduler - Delivers trading signals to Telegram via bot

Sends daily signals on schedule:
- 6:30 AM ET: Pre-market scan
- 9:30 AM ET: Market open scan
- Hourly: Live updates (10 AM-3 PM)
- 4:15 PM ET: Post-market analysis
"""

import os
import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class SignalScheduler:
    """Scheduled signal delivery via Telegram bot"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.logger = logging.getLogger(__name__)
    
    async def send_daily_signals(self, symbols: Optional[List[str]] = None, limit: int = 5):
        """Send top signals daily at scheduled times"""
        try:
            # Try to fetch from local API first
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        'http://localhost:8000/api/signals',
                        params={'limit': limit, 'symbols': ','.join(symbols) if symbols else ''}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            signals = data.get('signals', [])
                        else:
                            signals = []
            except Exception as e:
                self.logger.warning(f"Local API failed, using mock data: {e}")
                signals = []
            
            if not signals:
                # Send placeholder message
                msg = f"📊 **Signal Scan - {datetime.now().strftime('%I:%M %p ET')}**\n\nNo signals generated at this time."
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='Markdown'
                )
                return
            
            # Send each signal
            for signal_data in signals[:limit]:
                message = self._format_signal_message(signal_data)
                
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='HTML'
                )
                
                # Rate limit
                await asyncio.sleep(1)
            
            self.logger.info(f"✅ Sent {len(signals)} signals to Telegram at {datetime.now()}")
            
        except Exception as e:
            self.logger.error(f"❌ Error sending signals: {e}")
            await self._send_error_alert(str(e))
    
    async def send_signal(self, signal_data: dict):
        """Send single signal immediately"""
        try:
            message = self._format_signal_message(signal_data)
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            
            self.logger.info(f"✅ Signal sent: {signal_data.get('symbol', 'UNKNOWN')}")
        except Exception as e:
            self.logger.error(f"❌ Error sending signal: {e}")
    
    def _format_signal_message(self, signal: Dict) -> str:
        """Format signal as HTML Telegram message"""
        
        symbol = signal.get('symbol', 'UNKNOWN')
        score = signal.get('score', 0)
        catalyst = signal.get('catalyst', 'N/A')
        entry = signal.get('entry', 0)
        stop = signal.get('stop', 0)
        target = signal.get('target', 0)
        risk_reward = signal.get('risk_reward', 'N/A')
        news_count = signal.get('news_count', 0)
        
        # Score bar (50 chars, filled based on score)
        filled = int(score / 2)  # 100 → 50 chars
        bar = '█' * filled + '░' * (50 - filled)
        
        # Scanners
        scanners = signal.get('scanners', {})
        scanner_text = '\n'.join([
            f"  <b>{name}</b>: {value:.2f}" 
            for name, value in sorted(scanners.items(), key=lambda x: x[1], reverse=True)[:5]
        ])
        
        # Format message
        msg = f"""🔍 <b>DISCOVERY</b> - ${symbol}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Score:</b> {score:.0f}/100

💡 <b>Edge:</b> {catalyst}

🎯 <b>Entry:</b> ${entry:.2f}
🛑 <b>Stop:</b> ${stop:.2f}
🚀 <b>Target:</b> ${target:.2f}

📈 <b>Risk/Reward:</b> {risk_reward}

{bar}

📰 <b>News:</b> {news_count} articles

🔧 <b>Top Scanners:</b>
{scanner_text}

⏰ {datetime.now().strftime('%Y-%m-%d %I:%M %p ET')}"""
        
        return msg
    
    async def _send_error_alert(self, error: str):
        """Send error notification"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"⚠️ <b>Signal Engine Error</b>\n\n{error}",
                parse_mode='HTML'
            )
        except Exception as e:
            self.logger.error(f"Failed to send error alert: {e}")
    
    async def health_check(self):
        """Send health check message"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🟢 <b>Signal Bot Online</b>\n\nSignal scheduler is active and ready to deliver.",
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False


async def main():
    """Main entry point for scheduled delivery"""
    
    # Get credentials
    bot_token = os.getenv('SIGNAL_BOT_TOKEN') or '8641115158:AAHDz2nB0K-m5xHc_BID9zfWwxvf2qUQRu0'
    chat_id = os.getenv('SIGNAL_BOT_CHAT_ID') or '5696824719'
    
    # Initialize scheduler
    scheduler = SignalScheduler(bot_token, chat_id)
    
    # Health check
    health = await scheduler.health_check()
    if not health:
        logger.error("❌ Bot connection failed")
        return
    
    # Send daily signals
    await scheduler.send_daily_signals(limit=5)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
