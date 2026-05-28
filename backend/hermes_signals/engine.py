"""Signal generation and management engine."""

from typing import List, Optional, Dict, Any
from datetime import datetime
from .models import Signal, SignalCategory, SignalAction, SignalStrength
from .formatter import SignalFormatter


class SignalEngine:
    """Generate and manage trading signals from strategy ensemble."""
    
    def __init__(self):
        """Initialize signal engine."""
        self.active_signals: Dict[str, Signal] = {}
        self.signal_history: List[Signal] = []
        self.formatter = SignalFormatter()
    
    def create_signal(
        self,
        ticker: str,
        name: str,
        category: SignalCategory,
        action: SignalAction,
        current_price: float,
        price_change_percent: float,
        volume: float,
        avg_volume: float,
        score: int,
        strength: SignalStrength,
        catalyst: str,
        **kwargs
    ) -> Signal:
        """Create a new trading signal with all required fields.
        
        Args:
            ticker: Stock ticker symbol
            name: Company/asset name
            category: Signal category (DISCOVERY, TREND, etc.)
            action: Recommended action
            current_price: Current market price
            price_change_percent: Daily price change %
            volume: Current volume
            avg_volume: Average volume
            score: Signal quality score (0-100)
            strength: Signal strength level
            catalyst: Primary trigger description
            **kwargs: Optional fields (market_cap, industry, entry_price, etc.)
        
        Returns:
            Signal object
        """
        
        signal_id = f"{ticker}_{category.value}_{datetime.now().timestamp()}"
        
        signal = Signal(
            ticker=ticker,
            name=name,
            signal_id=signal_id,
            timestamp=datetime.now(),
            category=category,
            strength=strength,
            action=action,
            score=score,
            current_price=current_price,
            price_change_percent=price_change_percent,
            volume=volume,
            avg_volume=avg_volume,
            catalyst=catalyst,
            **kwargs
        )
        
        return signal
    
    def register_signal(self, signal: Signal) -> None:
        """Register a signal as active."""
        key = f"{signal.ticker}_{signal.category.value}"
        self.active_signals[key] = signal
        self.signal_history.append(signal)
    
    def deactivate_signal(self, ticker: str, category: SignalCategory) -> None:
        """Deactivate a signal."""
        key = f"{ticker}_{category.value}"
        if key in self.active_signals:
            self.active_signals[key].is_active = False
    
    def get_active_signals(self, ticker: Optional[str] = None) -> List[Signal]:
        """Get all active signals, optionally filtered by ticker."""
        signals = [s for s in self.active_signals.values() if s.is_active]
        if ticker:
            signals = [s for s in signals if s.ticker == ticker]
        return sorted(signals, key=lambda s: s.score, reverse=True)
    
    def format_signal_for_telegram(self, signal: Signal) -> str:
        """Format signal for Telegram messaging."""
        return self.formatter.format_telegram_message(signal)
    
    def format_signal_for_dashboard(self, signal: Signal) -> Dict[str, Any]:
        """Format signal for WebSocket dashboard."""
        return self.formatter.format_dashboard_payload(signal)
    
    def format_signal_html(self, signal: Signal) -> str:
        """Format signal as HTML card."""
        return self.formatter.format_html_card(signal)
    
    def batch_format_dashboard(self, signals: List[Signal]) -> List[Dict[str, Any]]:
        """Format multiple signals for dashboard transmission."""
        return [self.format_signal_for_dashboard(s) for s in signals]
    
    def get_signal_summary(self, signal: Signal) -> Dict[str, Any]:
        """Get a summary of signal key metrics."""
        return {
            "ticker": signal.ticker,
            "action": signal.action.value,
            "score": signal.score,
            "strength": signal.strength.name,
            "catalyst": signal.catalyst,
            "price": signal.current_price,
            "change": signal.price_change_percent,
            "risk_reward": signal.risk_reward_ratio,
            "position_size": signal.position_size_percent,
            "confirmations": len(signal.confirmation_criteria),
            "timestamp": signal.timestamp.isoformat(),
        }
    
    def generate_signals_report(self, signals: List[Signal]) -> str:
        """Generate a text report of signals for analysis."""
        
        report = f"🔍 SIGNAL REPORT - {datetime.now().strftime('%I:%M %p')}\n"
        report += f"{'=' * 60}\n\n"
        
        # Group by action
        buy_signals = [s for s in signals if s.action == SignalAction.BUY]
        sell_signals = [s for s in signals if s.action == SignalAction.SELL]
        monitor_signals = [s for s in signals if s.action == SignalAction.MONITOR]
        hold_signals = [s for s in signals if s.action == SignalAction.HOLD]
        
        if buy_signals:
            report += f"🟢 BUY SIGNALS ({len(buy_signals)}):\n"
            for sig in sorted(buy_signals, key=lambda s: s.score, reverse=True)[:5]:
                report += f"  • {sig.ticker} ({sig.score}/100) - {sig.catalyst}\n"
            report += "\n"
        
        if sell_signals:
            report += f"🔴 SELL SIGNALS ({len(sell_signals)}):\n"
            for sig in sorted(sell_signals, key=lambda s: s.score, reverse=True)[:5]:
                report += f"  • {sig.ticker} ({sig.score}/100) - {sig.catalyst}\n"
            report += "\n"
        
        if monitor_signals:
            report += f"👁️ MONITOR ({len(monitor_signals)}):\n"
            for sig in sorted(monitor_signals, key=lambda s: s.score, reverse=True)[:3]:
                report += f"  • {sig.ticker} ({sig.score}/100)\n"
            report += "\n"
        
        # Summary stats
        avg_score = sum(s.score for s in signals) / len(signals) if signals else 0
        strong_signals = len([s for s in signals if s.strength == SignalStrength.STRONG])
        
        report += f"{'=' * 60}\n"
        report += f"Total Active: {len(signals)} | Avg Score: {avg_score:.0f}/100\n"
        report += f"Strong Signals: {strong_signals}\n"
        
        return report
