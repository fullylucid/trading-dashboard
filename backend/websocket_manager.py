"""
WebSocket Manager
Real-time signal streaming via WebSocket connections
"""

import logging
import json
import asyncio
from datetime import datetime
from typing import Set, Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class WebSocketConnection:
    """Track WebSocket connection metadata"""
    websocket: WebSocket
    client_id: str
    connected_at: str
    subscriptions: Set[str]  # symbols the client is subscribed to
    
    async def send_json(self, data: Dict[str, Any]) -> bool:
        """Send JSON to client"""
        try:
            await self.websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning(f"Failed to send to {self.client_id}: {e}")
            return False


class WebSocketManager:
    """Manage WebSocket connections and signal distribution"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocketConnection] = {}
        self.logger = logger
    
    async def connect(self, websocket: WebSocket, client_id: str) -> WebSocketConnection:
        """
        Register new WebSocket connection
        
        Args:
            websocket: WebSocket connection
            client_id: Unique client identifier
            
        Returns:
            WebSocketConnection object
        """
        await websocket.accept()
        
        connection = WebSocketConnection(
            websocket=websocket,
            client_id=client_id,
            connected_at=datetime.utcnow().isoformat(),
            subscriptions=set(),
        )
        
        self.active_connections[client_id] = connection
        self.logger.info(f"WebSocket connected: {client_id} (total: {len(self.active_connections)})")
        
        return connection
    
    async def disconnect(self, client_id: str) -> None:
        """
        Unregister WebSocket connection
        
        Args:
            client_id: Client identifier
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            self.logger.info(f"WebSocket disconnected: {client_id} (total: {len(self.active_connections)})")
    
    async def subscribe(self, client_id: str, symbols: list) -> bool:
        """
        Subscribe client to symbols
        
        Args:
            client_id: Client identifier
            symbols: List of ticker symbols
            
        Returns:
            True if successful
        """
        if client_id not in self.active_connections:
            return False
        
        connection = self.active_connections[client_id]
        for symbol in symbols:
            # Channel-style subscriptions (e.g. "chat:<uuid>") are case-sensitive
            # identifiers and must NOT be uppercased; only ticker symbols are.
            connection.subscriptions.add(symbol if ":" in symbol else symbol.upper())

        self.logger.debug(f"{client_id} subscribed to {symbols}")
        return True
    
    async def unsubscribe(self, client_id: str, symbols: list) -> bool:
        """
        Unsubscribe client from symbols
        
        Args:
            client_id: Client identifier
            symbols: List of ticker symbols
            
        Returns:
            True if successful
        """
        if client_id not in self.active_connections:
            return False
        
        connection = self.active_connections[client_id]
        for symbol in symbols:
            connection.subscriptions.discard(symbol if ":" in symbol else symbol.upper())
        
        return True
    
    async def broadcast_signal(self, signal_data: Dict[str, Any]) -> int:
        """
        Broadcast signal to all interested clients
        
        Args:
            signal_data: Signal dict with symbol
            
        Returns:
            Number of clients notified
        """
        symbol = signal_data.get("symbol", "").upper()
        disconnected = []
        notified = 0
        
        for client_id, connection in self.active_connections.items():
            # Check if client is subscribed to this symbol
            if symbol not in connection.subscriptions and "*" not in connection.subscriptions:
                continue
            
            # Send signal
            success = await connection.send_json({
                "type": "signal",
                "data": signal_data,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            if success:
                notified += 1
            else:
                disconnected.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)
        
        if notified > 0:
            self.logger.debug(f"Signal {signal_data.get('id')} broadcast to {notified} clients")
        
        return notified

    async def broadcast_chat(self, conversation_id: str, payload: Dict[str, Any]) -> int:
        """
        Broadcast an agent chat event to clients subscribed to a conversation.

        Clients subscribe with the channel token ``chat:{conversation_id}``
        (via the same ``subscribe`` action used for symbols). Mirrors
        broadcast_signal but keys off conversation_id instead of symbol.

        Args:
            conversation_id: Conversation the event belongs to
            payload: Event dict (chunk/final/error/title_update)

        Returns:
            Number of clients notified
        """
        channel = f"chat:{conversation_id}"
        disconnected = []
        notified = 0

        for client_id, connection in self.active_connections.items():
            if channel not in connection.subscriptions and "*" not in connection.subscriptions:
                continue

            success = await connection.send_json({
                "type": "chat",
                "channel": channel,
                "data": payload,
                "timestamp": datetime.utcnow().isoformat(),
            })

            if success:
                notified += 1
            else:
                disconnected.append(client_id)

        for client_id in disconnected:
            await self.disconnect(client_id)

        try:
            subbed = sum(
                1 for c in self.active_connections.values()
                if channel in c.subscriptions or "*" in c.subscriptions
            )
            logging.getLogger("websocket_manager").info(
                f"broadcast_chat channel={channel} conns={len(self.active_connections)} "
                f"subscribed={subbed} notified={notified}"
            )
        except Exception:
            pass

        return notified

    async def broadcast_hermes_signal(self, signal) -> int:
        """
        Broadcast a Hermes Signal object (rich format) to all clients.
        Converts the Hermes Signal to dict + adds Telegram card.
        """
        from hermes_signals.formatter import SignalFormatter

        formatter = SignalFormatter()
        payload = {
            "type": "hermes_signal",
            "data": signal.to_dict(),
            "telegram_card": formatter.format_telegram_message(signal),
            "timestamp": datetime.utcnow().isoformat(),
        }

        notified = 0
        for client_id, connection in self.active_connections.items():
            success = await connection.send_json(payload)
            if success:
                notified += 1
        return notified
    
    async def broadcast_price_update(self, symbol: str, price_data: Dict[str, Any]) -> int:
        """
        Broadcast price update to interested clients
        
        Args:
            symbol: Stock ticker
            price_data: Price dict with price, bid, ask, volume, etc.
            
        Returns:
            Number of clients notified
        """
        symbol = symbol.upper()
        disconnected = []
        notified = 0
        
        for client_id, connection in self.active_connections.items():
            # Check subscription
            if symbol not in connection.subscriptions and "*" not in connection.subscriptions:
                continue
            
            success = await connection.send_json({
                "type": "price",
                "symbol": symbol,
                "data": price_data,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            if success:
                notified += 1
            else:
                disconnected.append(client_id)
        
        # Clean up
        for client_id in disconnected:
            await self.disconnect(client_id)
        
        return notified
    
    async def send_notification(
        self,
        client_id: str,
        title: str,
        message: str,
        level: str = "info",
    ) -> bool:
        """
        Send notification to specific client
        
        Args:
            client_id: Client identifier
            title: Notification title
            message: Notification message
            level: Severity level (info, warning, error)
            
        Returns:
            True if sent successfully
        """
        if client_id not in self.active_connections:
            return False
        
        connection = self.active_connections[client_id]
        
        return await connection.send_json({
            "type": "notification",
            "title": title,
            "message": message,
            "level": level,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def handle_connection(self, websocket: WebSocket, client_id: str) -> None:
        """
        Handle WebSocket connection lifecycle
        
        Args:
            websocket: WebSocket connection
            client_id: Client identifier
        """
        connection = await self.connect(websocket, client_id)

        try:
            while True:
                # Receive and process messages
                data = await websocket.receive_text()

                try:
                    message = json.loads(data)
                    action = message.get("action", "")

                    if action == "subscribe":
                        symbols = message.get("symbols", [])
                        await self.subscribe(client_id, symbols)
                        await connection.send_json({
                            "type": "subscription_confirmed",
                            "symbols": list(connection.subscriptions),
                        })
                    
                    elif action == "unsubscribe":
                        symbols = message.get("symbols", [])
                        await self.unsubscribe(client_id, symbols)
                        await connection.send_json({
                            "type": "unsubscription_confirmed",
                            "symbols": list(connection.subscriptions),
                        })
                    
                    elif action == "ping":
                        await connection.send_json({"type": "pong"})
                    
                    else:
                        self.logger.warning(f"Unknown action: {action}")
                
                except json.JSONDecodeError:
                    self.logger.warning(f"Invalid JSON from {client_id}: {data[:100]}")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
        
        except WebSocketDisconnect:
            await self.disconnect(client_id)
        except Exception as e:
            self.logger.error(f"WebSocket error for {client_id}: {e}")
            await self.disconnect(client_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get WebSocket manager statistics"""
        total_subs = sum(len(c.subscriptions) for c in self.active_connections.values())
        
        return {
            "connected_clients": len(self.active_connections),
            "total_subscriptions": total_subs,
            "clients": [
                {
                    "client_id": cid,
                    "connected_at": conn.connected_at,
                    "subscriptions": list(conn.subscriptions),
                }
                for cid, conn in self.active_connections.items()
            ]
        }
