"""
Telegram Bot Integration
Sends trading signals and alerts to Telegram users
"""

import logging
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
import aiohttp
from dataclasses import dataclass
from signal_formatter import SignalCard, SignalFormatterUtil

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Telegram bot configuration"""
    bot_token: str
    chat_id: str = None  # Default chat ID, can be overridden per message
    api_base_url: str = "https://api.telegram.org"
    retry_attempts: int = 3
    retry_delay: float = 1.0


class TelegramBot:
    """Send trading alerts and signals via Telegram"""
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.message_queue: List[Dict[str, Any]] = []
        self.retry_backoff = {}
    
    async def initialize(self) -> bool:
        """Initialize bot and verify token"""
        try:
            self.session = aiohttp.ClientSession()
            
            # Test bot token
            url = f"{self.config.api_base_url}/bot{self.config.bot_token}/getMe"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Telegram bot initialized: {data['result']['username']}")
                    return True
                else:
                    logger.error(f"Invalid Telegram bot token: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            return False
    
    async def send_signal_alert(
        self,
        symbol: str,
        signal_data: Dict[str, Any],
        chat_id: Optional[str] = None,
    ) -> bool:
        """
        Send trading signal alert to Telegram
        
        Args:
            symbol: Stock ticker
            signal_data: Signal result dict
            chat_id: Override default chat ID
            
        Returns:
            True if sent successfully
        """
        chat_id = chat_id or self.config.chat_id
        if not chat_id:
            logger.warning("No chat_id configured, skipping Telegram send")
            return False
        
        # Format message
        message = self._format_signal_message(symbol, signal_data)
        
        # Try to send
        for attempt in range(self.config.retry_attempts):
            try:
                success = await self.send_message(chat_id, message)
                if success:
                    logger.info(f"Signal alert sent for {symbol} to {chat_id}")
                    return True
                else:
                    await asyncio.sleep(self.config.retry_delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Failed to send signal alert (attempt {attempt + 1}): {e}")
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay * (2 ** attempt))
        
        # Queue for retry
        self.message_queue.append({
            "type": "signal",
            "chat_id": chat_id,
            "symbol": symbol,
            "data": signal_data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return False
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "MarkdownV2",
    ) -> bool:
        """
        Send raw message to Telegram
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            parse_mode: "Markdown", "MarkdownV2", or "HTML"
            
        Returns:
            True if sent successfully
        """
        if not self.session:
            logger.warning("Telegram session not initialized")
            return False
        
        try:
            url = f"{self.config.api_base_url}/bot{self.config.bot_token}/sendMessage"
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return True
                else:
                    error_data = await resp.text()
                    logger.error(f"Telegram send failed: {resp.status} - {error_data}")
                    return False
        except asyncio.TimeoutError:
            logger.error("Telegram send timeout")
            return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
    
    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: str = "",
    ) -> bool:
        """
        Send document/file to Telegram
        
        Args:
            chat_id: Telegram chat ID
            file_path: Path to file
            caption: Optional caption
            
        Returns:
            True if sent successfully
        """
        if not self.session:
            logger.warning("Telegram session not initialized")
            return False
        
        try:
            url = f"{self.config.api_base_url}/bot{self.config.bot_token}/sendDocument"
            
            with open(file_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", chat_id)
                data.add_field("document", f)
                if caption:
                    data.add_field("caption", caption)
                
                async with self.session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to send document: {e}")
            return False
    
    async def process_message_queue(self) -> None:
        """Process queued messages with exponential backoff"""
        while self.message_queue:
            msg = self.message_queue.pop(0)
            
            try:
                if msg["type"] == "signal":
                    success = await self.send_signal_alert(
                        msg["symbol"],
                        msg["data"],
                        msg["chat_id"]
                    )
                    
                    if not success:
                        # Re-queue with backoff
                        self.message_queue.append(msg)
                        await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Failed to process queued message: {e}")
    
    async def close(self) -> None:
        """Close Telegram session"""
        if self.session:
            await self.session.close()
            logger.info("Telegram session closed")
    
    def _format_signal_message(self, symbol: str, signal_data: Dict[str, Any]) -> str:
        """
        Format signal data for Telegram message
        
        Using MarkdownV2 formatting (legacy format)
        """
        signal = signal_data.get("signal", "HOLD").upper()
        confidence = signal_data.get("confidence", 0)
        timestamp = signal_data.get("timestamp", "")[:16]
        reason = signal_data.get("reason", "")
        
        # Emoji indicators
        emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}.get(signal.lower(), "⚪")
        
        # Build message
        lines = [
            f"{emoji} *{signal}* \\- {symbol}",
            f"Confidence: `{confidence:.0f}%`",
            f"Time: `{timestamp}`",
        ]
        
        if reason:
            # Escape special characters for MarkdownV2
            safe_reason = self._escape_markdown(reason)
            lines.append(f"\\n__{safe_reason}__")
        
        # Add scanner details if available
        scanners = signal_data.get("scanners_used", [])
        if scanners:
            scanner_list = ", ".join(scanners)
            lines.append(f"\\nScanners: `{scanner_list}`")
        
        return "\n".join(lines)
    
    def format_signal_card(self, signal_card: SignalCard) -> str:
        """
        Format signal as an enhanced card (matches OpenClaw format)
        
        Returns HTML-formatted message for Telegram
        """
        return signal_card.to_telegram()
    
    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f"\\{char}")
        return text


class TelegramWebhookHandler:
    """Handle incoming Telegram webhook messages"""
    
    def __init__(self, bot: TelegramBot):
        self.bot = bot
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle Telegram webhook payload
        
        Args:
            payload: Webhook data from Telegram
            
        Returns:
            Response dict for Telegram
        """
        try:
            if "message" not in payload:
                return {"status": "ok"}
            
            message = payload["message"]
            text = message.get("text", "").lower()
            chat_id = str(message["chat"]["id"])
            
            # Handle commands
            if text == "/start":
                await self.bot.send_message(
                    chat_id,
                    "Welcome to Trading Signal Bot\\! Send /help for commands\\."
                )
            elif text == "/help":
                await self.bot.send_message(
                    chat_id,
                    "Available commands:\n"
                    "/start \\- Start bot\n"
                    "/help \\- Show this help\n"
                    "/status \\- Get system status"
                )
            elif text == "/status":
                await self.bot.send_message(
                    chat_id,
                    f"Bot active\\. Queue: {len(self.bot.message_queue)} messages"
                )
            
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Webhook handling error: {e}")
            return {"status": "error", "message": str(e)}
