"""Signal formatting for Telegram, WebSocket, and Dashboard display."""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from .models import Signal, SignalCategory, SignalAction, SignalStrength


class SignalFormatter:
    """Format trading signals for various output channels."""
    
    # Emoji mappings for visual hierarchy
    EMOJI_MAP = {
        SignalCategory.DISCOVERY: "🔍",
        SignalCategory.TREND: "📈",
        SignalCategory.MOMENTUM: "🚀",
        SignalCategory.MEAN_REVERSION: "⏸️",
        SignalCategory.BREAKOUT: "💥",
        SignalCategory.SUPPORT_RESISTANCE: "📍",
        SignalCategory.VOLATILITY: "〰️",
        SignalCategory.DIVERGENCE: "⚠️",
        "industry": "🏢",
        "edge": "💎",
        "score": "📊",
        "price": "💰",
        "volume": "📈",
        "catalyst": "🎯",
        "action": "💡",
        "risk": "⛔",
        "reward": "🎁",
        "confirmation": "✅",
        "monitor": "👁️",
    }
    
    # Color codes for styling (hex values for dashboard)
    COLOR_MAP = {
        "positive": "#10B981",      # Green
        "negative": "#EF4444",      # Red
        "neutral": "#6B7280",       # Gray
        "bullish": "#3B82F6",       # Blue
        "bearish": "#F97316",       # Orange
        "warning": "#F59E0B",       # Amber
        "header": "#1F2937",        # Dark gray
        "card_bg": "#FFFFFF",       # White
        "border": "#E5E7EB",        # Light gray
    }
    
    @staticmethod
    def get_strength_emoji(strength: SignalStrength) -> str:
        """Get emoji for signal strength."""
        strength_emojis = {
            SignalStrength.WEAK: "⭐",
            SignalStrength.MODERATE: "⭐⭐",
            SignalStrength.STRONG: "⭐⭐⭐",
            SignalStrength.VERY_STRONG: "⭐⭐⭐⭐",
        }
        return strength_emojis.get(strength, "")
    
    @staticmethod
    def get_action_color(action: SignalAction) -> str:
        """Get color for action."""
        action_colors = {
            SignalAction.BUY: "positive",
            SignalAction.ACCUMULATE: "positive",
            SignalAction.SELL: "negative",
            SignalAction.REDUCE: "negative",
            SignalAction.HOLD: "neutral",
            SignalAction.MONITOR: "neutral",
            SignalAction.WAIT_CONFIRMATION: "warning",
        }
        return action_colors.get(action, "neutral")
    
    @staticmethod
    def format_price_change(price: float, change_percent: float) -> Tuple[str, str]:
        """Format price change with color indication.
        
        Returns:
            Tuple of (formatted_string, color_key)
        """
        direction = "+" if change_percent >= 0 else ""
        color = "positive" if change_percent >= 0 else "negative"
        formatted = f"{direction}{change_percent:+.1f}%"
        return formatted, color
    
    @staticmethod
    def format_volume(volume: float, avg_volume: float) -> str:
        """Format volume ratio."""
        if avg_volume == 0:
            return "N/A"
        ratio = volume / avg_volume
        if ratio >= 1_000_000:
            return f"{ratio/1_000_000:.1f}M x"
        elif ratio >= 1000:
            return f"{ratio/1000:.1f}K x"
        else:
            return f"{ratio:.1f}x"
    
    @staticmethod
    def format_market_cap(market_cap: Optional[str]) -> str:
        """Format market cap for display."""
        if not market_cap:
            return "N/A"
        return market_cap
    
    @staticmethod
    def format_risk_reward(risk_reward: float) -> str:
        """Format risk/reward ratio."""
        if risk_reward <= 0:
            return "N/A"
        return f"1:{risk_reward:.2f}"
    
    @classmethod
    def format_telegram_message(cls, signal: Signal) -> str:
        """Format signal for Telegram with markdown.
        
        Card-style format with emoji, clear hierarchy, structured fields.
        Designed to match OpenClaw signal format.
        """
        
        emoji_category = cls.EMOJI_MAP.get(signal.category, "📌")
        emoji_industry = cls.EMOJI_MAP["industry"]
        emoji_edge = cls.EMOJI_MAP["edge"]
        emoji_score = cls.EMOJI_MAP["score"]
        emoji_price = cls.EMOJI_MAP["price"]
        emoji_volume = cls.EMOJI_MAP["volume"]
        emoji_catalyst = cls.EMOJI_MAP["catalyst"]
        emoji_action = cls.EMOJI_MAP["action"]
        emoji_risk = cls.EMOJI_MAP["risk"]
        emoji_reward = cls.EMOJI_MAP["reward"]
        emoji_confirm = cls.EMOJI_MAP["confirmation"]
        
        # Header: Category, Ticker, Company
        header = (
            f"{emoji_category} **{signal.category.value.upper()}**\n"
            f"**${signal.ticker}** • {signal.name}\n"
        )
        
        # Price and change
        price_change, _ = cls.format_price_change(signal.current_price, signal.price_change_percent)
        price_section = (
            f"\n{emoji_price} **Price:** ${signal.current_price:,.2f} ({price_change})"
        )
        
        # Industry and fundamentals
        details = ""
        if signal.industry or signal.country or signal.market_cap:
            details += f"\n{emoji_industry} **Details:**"
            if signal.industry and signal.country:
                details += f"\n  {signal.industry} | {signal.country}"
            elif signal.industry:
                details += f"\n  {signal.industry}"
            if signal.market_cap:
                details += f"\n  Market Cap: {cls.format_market_cap(signal.market_cap)}"
        
        if signal.competitive_edge:
            details += f"\n{emoji_edge} **Edge:** {signal.competitive_edge}"
        
        # Score and strength
        strength_stars = cls.get_strength_emoji(signal.strength)
        score_section = (
            f"\n{emoji_score} **Score:** {signal.score}/100 | {strength_stars} {signal.strength.name}"
        )
        if signal.sector:
            score_section += f" | {signal.sector}"
        
        # Volume
        volume_formatted = cls.format_volume(signal.volume, signal.avg_volume)
        volume_section = f"\n{emoji_volume} **Volume:** {volume_formatted} avg"
        
        # Catalyst
        catalyst_section = f"\n{emoji_catalyst} **Catalyst:** {signal.catalyst}"
        
        # Confirmation signals
        confirmations = ""
        if signal.other_signals:
            confirmations = f"\n{emoji_confirm} **Confirmations:**"
            for sig in signal.other_signals[:5]:  # Limit to 5
                confirmations += f"\n  • {sig}"
        
        # Risk/Reward
        risk_reward = ""
        if signal.stop_loss > 0 and signal.risk_reward_ratio > 0:
            risk_reward_fmt = cls.format_risk_reward(signal.risk_reward_ratio)
            risk_reward = (
                f"\n{emoji_risk} **Risk/Reward:** {risk_reward_fmt}"
            )
            if signal.entry_price > 0:
                risk_reward += f"\n  Entry: ${signal.entry_price:,.2f} | SL: ${signal.stop_loss:,.2f}"
        
        # Position sizing
        position = ""
        if signal.position_size_percent > 0:
            position = f"\n  Position Size: {signal.position_size_percent:.1f}% of portfolio"
        
        # Take profit levels
        tp_section = ""
        if signal.take_profit_levels:
            tp_section = f"\n{emoji_reward} **Targets:**"
            for tp in signal.take_profit_levels[:3]:
                tp_section += f"\n  • {tp.label}: ${tp.price:,.2f}"
        
        # Action
        action_upper = signal.action.value.upper()
        action_section = f"\n{emoji_action} **Action:** {action_upper}"
        
        if signal.action_description:
            action_section += f"\n  {signal.action_description}"
        elif signal.confirmation_criteria:
            action_section += f"\n  Confirmation criteria:"
            for cc in signal.confirmation_criteria[:3]:
                status = "✓" if cc.met else "○"
                action_section += f"\n    {status} {cc.description}"
        
        # Timestamp
        time_str = signal.timestamp.strftime("%I:%M %p")
        footer = f"\n\n_Last updated: {time_str}_"
        
        # Assemble message
        message = (
            header +
            price_section +
            details +
            score_section +
            volume_section +
            catalyst_section +
            confirmations +
            risk_reward +
            position +
            tp_section +
            action_section +
            footer
        )
        
        return message
    
    @classmethod
    def format_dashboard_payload(cls, signal: Signal) -> Dict[str, Any]:
        """Format signal for WebSocket dashboard payload.
        
        Includes both raw data and pre-formatted fields for rendering.
        """
        
        price_change_str, change_color = cls.format_price_change(
            signal.current_price, 
            signal.price_change_percent
        )
        
        payload = {
            # Raw signal data
            "signal": signal.to_dict(),
            
            # Formatted fields for UI rendering
            "formatted": {
                "header": {
                    "category": signal.category.value.upper(),
                    "emoji": cls.EMOJI_MAP.get(signal.category, "📌"),
                    "ticker": signal.ticker,
                    "name": signal.name,
                },
                "price_section": {
                    "current": f"${signal.current_price:,.2f}",
                    "change": price_change_str,
                    "change_color": cls.COLOR_MAP[change_color],
                },
                "details": {
                    "industry": signal.industry or "N/A",
                    "country": signal.country or "N/A",
                    "market_cap": cls.format_market_cap(signal.market_cap),
                    "competitive_edge": signal.competitive_edge or "N/A",
                    "sector": signal.sector or "N/A",
                },
                "score": {
                    "value": signal.score,
                    "strength": signal.strength.name,
                    "strength_emoji": cls.get_strength_emoji(signal.strength),
                    "max": 100,
                },
                "volume": {
                    "current": f"{signal.volume:,.0f}",
                    "average": f"{signal.avg_volume:,.0f}",
                    "ratio": cls.format_volume(signal.volume, signal.avg_volume),
                },
                "catalyst": {
                    "description": signal.catalyst,
                    "emoji": cls.EMOJI_MAP["catalyst"],
                },
                "confirmations": [
                    {
                        "text": sig,
                        "emoji": cls.EMOJI_MAP["confirmation"],
                    }
                    for sig in signal.other_signals
                ],
                "risk_reward": {
                    "ratio": cls.format_risk_reward(signal.risk_reward_ratio),
                    "entry": f"${signal.entry_price:,.2f}" if signal.entry_price > 0 else "N/A",
                    "stop_loss": f"${signal.stop_loss:,.2f}" if signal.stop_loss > 0 else "N/A",
                },
                "position_sizing": {
                    "percent": signal.position_size_percent,
                    "size_str": f"{signal.position_size_percent:.1f}%",
                },
                "take_profits": [
                    {
                        "label": tp.label,
                        "price": f"${tp.price:,.2f}",
                        "raw_price": tp.price,
                    }
                    for tp in signal.take_profit_levels
                ],
                "action": {
                    "recommendation": signal.action.value.upper(),
                    "description": signal.action_description,
                    "color": cls.COLOR_MAP[cls.get_action_color(signal.action)],
                    "emoji": cls.EMOJI_MAP["action"],
                },
                "confirmation_criteria": [
                    {
                        "description": cc.description,
                        "metric": cc.metric,
                        "met": cc.met,
                        "weight": cc.weight,
                        "status_emoji": "✅" if cc.met else "⏳",
                    }
                    for cc in signal.confirmation_criteria
                ],
                "historical_context": {
                    "accuracy": (
                        f"{signal.historical_signal_accuracy:.1f}%" 
                        if signal.historical_signal_accuracy else "N/A"
                    ),
                    "recent_performance": signal.recent_performance or "No data",
                },
                "metadata": {
                    "timestamp": signal.timestamp.isoformat(),
                    "source": signal.source,
                    "tags": signal.tags,
                    "is_active": signal.is_active,
                },
            },
            
            # Styling
            "styling": {
                "colors": cls.COLOR_MAP,
                "emoji_map": cls.EMOJI_MAP,
            },
        }
        
        return payload
    
    @classmethod
    def format_html_card(cls, signal: Signal) -> str:
        """Generate HTML for signal card display.
        
        Mimics OpenClaw card format with green background, blue tickers.
        """
        
        action_color = cls.COLOR_MAP[cls.get_action_color(signal.action)]
        price_change_str, change_color = cls.format_price_change(
            signal.current_price, 
            signal.price_change_percent
        )
        change_color_hex = cls.COLOR_MAP[change_color]
        
        html = f"""
<div class="signal-card" style="
    background-color: {cls.COLOR_MAP['card_bg']};
    border-left: 4px solid {action_color};
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto;
">
    <!-- Header -->
    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
        <div>
            <span style="color: #6B7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">
                {cls.EMOJI_MAP.get(signal.category, "📌")} {signal.category.value}
            </span>
            <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
                <span style="color: #3B82F6; font-weight: bold; font-size: 18px;">${signal.ticker}</span>
                <span style="color: #4B5563; font-size: 14px;">{signal.name}</span>
            </div>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 16px; font-weight: bold; color: {cls.COLOR_MAP['header']};">
                ${signal.current_price:,.2f}
            </div>
            <div style="font-size: 12px; color: {change_color_hex}; font-weight: 500;">
                {price_change_str}
            </div>
        </div>
    </div>
    
    <!-- Score and Details -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid {cls.COLOR_MAP['border']};">
        <div>
            <div style="font-size: 11px; color: #6B7280; text-transform: uppercase;">📊 Score</div>
            <div style="font-size: 16px; font-weight: bold; color: {cls.COLOR_MAP['header']};">{signal.score}/100</div>
        </div>
        <div>
            <div style="font-size: 11px; color: #6B7280; text-transform: uppercase;">📈 Volume</div>
            <div style="font-size: 16px; font-weight: bold; color: {cls.COLOR_MAP['header']};">{cls.format_volume(signal.volume, signal.avg_volume)}</div>
        </div>
    </div>
    
    <!-- Catalyst and Action -->
    <div style="margin-bottom: 12px;">
        <div style="font-size: 11px; color: #6B7280; text-transform: uppercase; margin-bottom: 4px;">🎯 Catalyst</div>
        <div style="font-size: 13px; color: {cls.COLOR_MAP['header']};">{signal.catalyst}</div>
    </div>
    
    <div style="margin-bottom: 12px;">
        <div style="font-size: 11px; color: #6B7280; text-transform: uppercase; margin-bottom: 4px;">💡 Action</div>
        <div style="
            display: inline-block;
            padding: 4px 12px;
            background-color: {action_color};
            color: white;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        ">
            {signal.action.value.upper()}
        </div>
    </div>
    
    <!-- Risk/Reward if available -->
    {"" if not signal.risk_reward_ratio else f'''
    <div style="margin-bottom: 12px; padding: 8px; background-color: #F9FAFB; border-radius: 4px;">
        <div style="font-size: 11px; color: #6B7280; text-transform: uppercase; margin-bottom: 4px;">⛔ Risk/Reward</div>
        <div style="font-size: 13px; font-weight: bold; color: {cls.COLOR_MAP['header']};">
            {cls.format_risk_reward(signal.risk_reward_ratio)}
        </div>
        {f'<div style="font-size: 12px; color: #6B7280; margin-top: 4px;">SL: ${signal.stop_loss:,.2f}</div>' if signal.stop_loss > 0 else ''}
    </div>
    '''}
    
    <!-- Confirmations -->
    {"" if not signal.other_signals else f'''
    <div>
        <div style="font-size: 11px; color: #6B7280; text-transform: uppercase; margin-bottom: 4px;">✅ Signals</div>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            {chr(10).join(f'<span style="background-color: #ECFDF5; color: #065F46; padding: 4px 8px; border-radius: 3px; font-size: 12px;">✓ {sig}</span>' for sig in signal.other_signals[:3])}
        </div>
    </div>
    '''}
    
    <!-- Footer -->
    <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid {cls.COLOR_MAP['border']}; font-size: 11px; color: #9CA3AF;">
        Updated: {signal.timestamp.strftime("%I:%M %p")} | Source: {signal.source}
    </div>
</div>
"""
        return html
    
    @classmethod
    def format_csv_row(cls, signal: Signal) -> Dict[str, Any]:
        """Format signal as CSV-compatible dictionary."""
        
        price_change_str, _ = cls.format_price_change(
            signal.current_price,
            signal.price_change_percent
        )
        
        return {
            "Timestamp": signal.timestamp.isoformat(),
            "Ticker": signal.ticker,
            "Company": signal.name,
            "Category": signal.category.value,
            "Action": signal.action.value,
            "Score": signal.score,
            "Strength": signal.strength.name,
            "Price": f"${signal.current_price:,.2f}",
            "Change": price_change_str,
            "Volume": f"{signal.volume:,.0f}",
            "Volume Ratio": cls.format_volume(signal.volume, signal.avg_volume),
            "Industry": signal.industry or "",
            "Market Cap": signal.market_cap or "",
            "Catalyst": signal.catalyst,
            "Entry": f"${signal.entry_price:,.2f}" if signal.entry_price > 0 else "",
            "Stop Loss": f"${signal.stop_loss:,.2f}" if signal.stop_loss > 0 else "",
            "Risk/Reward": cls.format_risk_reward(signal.risk_reward_ratio),
            "Position %": signal.position_size_percent,
            "Confirmations": "; ".join(signal.other_signals),
            "Source": signal.source,
        }
