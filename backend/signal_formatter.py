"""
Signal Formatter - Converts raw signal data to visual card format for Telegram and Dashboard

Matches/improves upon OpenClaw signal card design:
- Clear data hierarchy
- Strategic emoji usage
- Mobile-optimized layout
- Multiple signal sources highlighted
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class SignalCard:
    """Enhanced signal card with formatted output"""
    
    # Core identification
    symbol: str
    company_name: str
    signal_type: str  # "DISCOVERY", "MOMENTUM", "REVERSAL", "SQUEEZE"
    
    # Company data
    industry: str
    country: str
    market_cap: str  # e.g., "$842.2B"
    
    # Investment thesis
    edge: str  # Competitive advantage explanation
    
    # Scoring
    score: int  # 0-100
    sector: str
    
    # Current market state
    price: float
    price_change_pct: float
    volume_ratio: float  # e.g., 1.6
    
    # Catalyst & triggers
    primary_catalyst: str  # Main reason for signal
    other_signals: List[str]  # ["50-day new high", "Gap +4.6%", "ATR breakout"]
    
    # Risk/Reward
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward_ratio: float
    
    # Action & timing
    action: str  # "BUY", "MONITOR", "WAIT"
    confirmation_criteria: str  # Specific entry confirmation
    position_size: str  # "1-3%", "3-5%", etc.
    
    # Metadata
    timestamp: datetime
    signal_confidence: Dict[str, float]  # {"smart_money": 0.68, "options": 0.75, ...}
    days_to_catalyst: Optional[int] = None  # Days until catalyst event
    
    def to_telegram(self) -> str:
        """Format as Telegram message with emojis and hierarchy"""
        
        # Build the message with strategic emoji placement
        lines = []
        
        # Header with category and ticker
        lines.append(f"🔍 {self.signal_type.upper()}")
        lines.append(f"<b>${self.symbol}</b> • {self.company_name}")
        lines.append("")
        
        # Company info section
        lines.append(f"🏢 {self.industry} | {self.country}")
        lines.append(f"💰 Market Cap: {self.market_cap}")
        lines.append("")
        
        # Investment thesis
        lines.append(f"💎 Edge: {self.edge}")
        lines.append("")
        
        # Score and metrics
        score_bar = self._build_score_bar(self.score)
        lines.append(f"📊 Signal Score: {self.score}/100 {score_bar}")
        lines.append(f"📈 Price: <b>${self.price:.2f}</b> <code>({self.price_change_pct:+.1f}%)</code>")
        lines.append(f"📊 Volume: <b>{self.volume_ratio:.1f}x avg</b>")
        lines.append("")
        
        # Catalyst section
        lines.append(f"🎯 Catalyst: {self.primary_catalyst}")
        if self.other_signals:
            for signal in self.other_signals:
                lines.append(f"   ⚪ {signal}")
        lines.append("")
        
        # Risk/Reward
        lines.append(f"🎯 Entry: ${self.entry_price:.2f}")
        lines.append(f"🛑 Stop: ${self.stop_loss:.2f}")
        lines.append(f"🚀 Target: ${self.target_price:.2f}")
        lines.append(f"📊 Risk/Reward: <b>1:{self.risk_reward_ratio:.1f}</b>")
        lines.append(f"💡 Position Size: <b>{self.position_size}</b>")
        lines.append("")
        
        # Component breakdown
        components_str = self._build_components_string()
        lines.append(f"🔬 Signal Breakdown:")
        lines.append(components_str)
        lines.append("")
        
        # Action
        action_emoji = "✅" if self.action == "BUY" else "⏸️" if self.action == "MONITOR" else "⏳"
        lines.append(f"{action_emoji} Action: <b>{self.action}</b>")
        lines.append(f"   Confirmation: {self.confirmation_criteria}")
        lines.append("")
        
        # Footer with timestamp
        time_str = self.timestamp.strftime("%I:%M %p")
        lines.append(f"⏰ {time_str}")
        
        return "\n".join(lines)
    
    def to_html_card(self) -> str:
        """Format as HTML card for dashboard display"""
        
        score_color = self._get_score_color(self.score)
        price_color = "green" if self.price_change_pct > 0 else "red"
        
        html = f"""
        <div class="signal-card" style="border-left: 4px solid {score_color};">
            <div class="card-header">
                <div class="signal-type">🔍 {self.signal_type}</div>
                <div class="ticker" style="color: #0066cc;">${self.symbol}</div>
                <div class="company">{self.company_name}</div>
            </div>
            
            <div class="card-body">
                <div class="company-info">
                    <span>🏢 {self.industry}</span> | 
                    <span>{self.country}</span> | 
                    <span>💰 {self.market_cap}</span>
                </div>
                
                <div class="edge">
                    <strong>💎 Edge:</strong> {self.edge}
                </div>
                
                <div class="metrics">
                    <div class="metric">
                        <span>📊 Score: <strong>{self.score}/100</strong></span>
                        <div class="score-bar">
                            <div class="score-fill" style="width: {self.score}%; background: {score_color};"></div>
                        </div>
                    </div>
                    <div class="metric">
                        <span>💰 Price: <strong>${self.price:.2f}</strong></span>
                        <span style="color: {price_color};">({self.price_change_pct:+.1f}%)</span>
                    </div>
                    <div class="metric">
                        <span>📈 Volume: <strong>{self.volume_ratio:.1f}x avg</strong></span>
                    </div>
                </div>
                
                <div class="catalyst">
                    <strong>🎯 Catalyst:</strong> {self.primary_catalyst}
                    {self._html_other_signals()}
                </div>
                
                <div class="risk-reward">
                    <div class="rr-item">Entry: ${self.entry_price:.2f}</div>
                    <div class="rr-item">Stop: ${self.stop_loss:.2f}</div>
                    <div class="rr-item">Target: ${self.target_price:.2f}</div>
                    <div class="rr-item"><strong>Risk/Reward: 1:{self.risk_reward_ratio:.1f}</strong></div>
                </div>
                
                <div class="components">
                    <strong>🔬 Signal Components:</strong>
                    {self._html_components()}
                </div>
                
                <div class="action">
                    <strong>💡 Action: {self.action}</strong>
                    <div>{self.confirmation_criteria}</div>
                    <div>Position: {self.position_size}</div>
                </div>
            </div>
            
            <div class="card-footer">
                {self.timestamp.strftime("%I:%M %p")}
            </div>
        </div>
        """
        
        return html
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API/WebSocket response"""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "signal_type": self.signal_type,
            "industry": self.industry,
            "country": self.country,
            "market_cap": self.market_cap,
            "edge": self.edge,
            "score": self.score,
            "price": self.price,
            "price_change_pct": self.price_change_pct,
            "volume_ratio": self.volume_ratio,
            "primary_catalyst": self.primary_catalyst,
            "other_signals": self.other_signals,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "action": self.action,
            "confirmation_criteria": self.confirmation_criteria,
            "position_size": self.position_size,
            "timestamp": self.timestamp.isoformat(),
            "signal_confidence": self.signal_confidence,
            "days_to_catalyst": self.days_to_catalyst,
            # Pre-formatted for display
            "telegram_message": self.to_telegram(),
            "score_color": self._get_score_color(self.score),
        }
    
    # Helper methods
    def _build_score_bar(self, score: int) -> str:
        """Build visual score bar using Unicode characters"""
        filled = score // 10
        empty = 10 - filled
        return f"[{'█' * filled}{'░' * empty}]"
    
    def _get_score_color(self, score: int) -> str:
        """Get color based on score"""
        if score >= 75:
            return "#00aa00"  # Green
        elif score >= 60:
            return "#ffaa00"  # Orange
        elif score >= 50:
            return "#ffff00"  # Yellow
        else:
            return "#ff0000"  # Red
    
    def _build_components_string(self) -> str:
        """Build component breakdown for Telegram"""
        if not self.signal_confidence:
            return "No component data"
        
        lines = []
        # Sort by confidence (highest first)
        sorted_components = sorted(
            self.signal_confidence.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for component, confidence in sorted_components:
            bar = self._build_score_bar(int(confidence * 100))
            pct = int(confidence * 100)
            lines.append(f"   {component.replace('_', ' ').title()}: {pct}% {bar}")
        
        return "\n".join(lines)
    
    def _html_other_signals(self) -> str:
        """Build HTML for other signals"""
        if not self.other_signals:
            return ""
        
        signals_html = "".join(
            f"<li>⚪ {signal}</li>"
            for signal in self.other_signals
        )
        return f"<ul>{signals_html}</ul>"
    
    def _html_components(self) -> str:
        """Build HTML component breakdown"""
        if not self.signal_confidence:
            return "<p>No component data</p>"
        
        sorted_components = sorted(
            self.signal_confidence.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        component_html = "".join(
            f"<div class='component'>"
            f"<span>{name.replace('_', ' ').title()}: {int(confidence * 100)}%</span>"
            f"</div>"
            for name, confidence in sorted_components
        )
        
        return f"<div class='components-list'>{component_html}</div>"


class SignalFormatterUtil:
    """Utility functions for signal formatting"""
    
    @staticmethod
    def create_signal_card(
        signal_data: Dict,
        company_data: Dict,
        market_data: Dict,
        analysis_data: Dict,
    ) -> SignalCard:
        """
        Create a SignalCard from various data sources
        
        Args:
            signal_data: {signal, confidence, signal_type}
            company_data: {name, industry, country, market_cap, edge}
            market_data: {price, price_change_pct, volume_ratio}
            analysis_data: {catalyst, other_signals, entry, stop, target, components}
        """
        
        # Calculate risk/reward
        entry = analysis_data.get("entry_price", market_data["price"])
        stop = analysis_data.get("stop_loss", market_data["price"] * 0.95)
        target = analysis_data.get("target_price", market_data["price"] * 1.10)
        
        risk = abs(entry - stop)
        reward = abs(target - entry)
        risk_reward = reward / risk if risk > 0 else 0
        
        # Determine action based on confidence
        confidence = signal_data.get("confidence", 50)
        if confidence >= 70:
            action = "BUY"
        elif confidence >= 60:
            action = "MONITOR"
        else:
            action = "WAIT"
        
        return SignalCard(
            symbol=signal_data["symbol"],
            company_name=company_data["name"],
            signal_type=signal_data.get("signal_type", "DISCOVERY"),
            industry=company_data.get("industry", "Unknown"),
            country=company_data.get("country", "USA"),
            market_cap=company_data.get("market_cap", "N/A"),
            edge=company_data.get("edge", "Strong competitive position"),
            score=int(confidence),
            sector=company_data.get("sector", "Unknown sector"),
            price=market_data["price"],
            price_change_pct=market_data["price_change_pct"],
            volume_ratio=market_data.get("volume_ratio", 1.0),
            primary_catalyst=analysis_data.get("catalyst", "Strong momentum"),
            other_signals=analysis_data.get("other_signals", []),
            entry_price=entry,
            stop_loss=stop,
            target_price=target,
            risk_reward_ratio=risk_reward,
            action=action,
            confirmation_criteria=analysis_data.get("confirmation", "Price holds above moving average"),
            position_size=analysis_data.get("position_size", "2%"),
            timestamp=datetime.now(),
            signal_confidence=analysis_data.get("components", {}),
            days_to_catalyst=analysis_data.get("days_to_catalyst"),
        )
    
    @staticmethod
    def format_batch_signals(signals: List[Dict]) -> str:
        """Format multiple signals for telegram feed"""
        if not signals:
            return "No signals generated"
        
        messages = []
        for i, signal_data in enumerate(signals[:5], 1):  # Top 5 signals
            # Build minimal card for batch
            messages.append(
                f"{i}. 🔍 ${signal_data['symbol']} - {signal_data['company_name']}\n"
                f"   Score: {signal_data['score']}/100 | "
                f"Price: ${signal_data['price']:.2f} ({signal_data['price_change_pct']:+.1f}%)\n"
                f"   Catalyst: {signal_data.get('catalyst', 'Strong momentum')}"
            )
        
        return "\n\n".join(messages)


# CSS for signal cards (can be injected into React component)
SIGNAL_CARD_CSS = """
<style>
.signal-card {
    background: white;
    border-radius: 8px;
    padding: 16px;
    margin: 12px 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
}

.card-header {
    border-bottom: 2px solid #f0f0f0;
    padding-bottom: 12px;
    margin-bottom: 12px;
}

.signal-type {
    font-size: 12px;
    color: #666;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.5px;
}

.ticker {
    font-size: 24px;
    font-weight: 700;
    margin: 8px 0;
    color: #0066cc;
}

.company {
    font-size: 14px;
    color: #333;
}

.company-info {
    font-size: 13px;
    color: #666;
    margin-bottom: 12px;
}

.edge {
    background: #f9f9f9;
    padding: 10px 12px;
    border-radius: 4px;
    font-size: 14px;
    margin-bottom: 12px;
    line-height: 1.4;
}

.metrics {
    display: grid;
    gap: 8px;
    margin-bottom: 12px;
}

.metric {
    display: flex;
    justify-content: space-between;
    font-size: 14px;
    align-items: center;
}

.score-bar {
    width: 100px;
    height: 4px;
    background: #e0e0e0;
    border-radius: 2px;
    overflow: hidden;
    margin-left: 8px;
}

.score-fill {
    height: 100%;
    transition: width 0.3s ease;
}

.catalyst {
    margin: 12px 0;
    font-size: 14px;
    line-height: 1.5;
}

.catalyst ul {
    list-style: none;
    padding-left: 20px;
    margin: 8px 0 0 0;
}

.catalyst li {
    margin: 4px 0;
    color: #555;
}

.risk-reward {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 12px 0;
    font-size: 13px;
    background: #f5f5f5;
    padding: 10px;
    border-radius: 4px;
}

.rr-item {
    display: flex;
    justify-content: space-between;
}

.components {
    margin: 12px 0;
    font-size: 13px;
}

.components-list {
    display: grid;
    gap: 4px;
    margin-top: 8px;
}

.component {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    border-bottom: 1px solid #f0f0f0;
}

.action {
    background: #f0f9ff;
    padding: 10px 12px;
    border-radius: 4px;
    margin: 12px 0;
    font-size: 14px;
    border-left: 3px solid #0066cc;
}

.action strong {
    display: block;
    margin-bottom: 6px;
}

.card-footer {
    text-align: right;
    font-size: 12px;
    color: #999;
    padding-top: 12px;
    border-top: 1px solid #f0f0f0;
    margin-top: 12px;
}

@media (prefers-color-scheme: dark) {
    .signal-card {
        background: #1e1e1e;
        color: #e0e0e0;
    }
    
    .card-header {
        border-bottom-color: #333;
    }
    
    .ticker {
        color: #00d4ff;
    }
    
    .company-info, .company {
        color: #999;
    }
    
    .edge {
        background: #2a2a2a;
    }
    
    .score-bar {
        background: #333;
    }
    
    .action {
        background: #1a3a4a;
        border-left-color: #00d4ff;
    }
}
</style>
"""
