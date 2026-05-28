"""Signal data models with enhanced metadata for dashboard and messaging."""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
import json


class SignalCategory(Enum):
    """Signal categories for classification."""
    DISCOVERY = "discovery"          # New stock discovery
    TREND = "trend"                  # Trend signal
    MOMENTUM = "momentum"            # Momentum signal
    MEAN_REVERSION = "mean_reversion"  # Mean reversion setup
    BREAKOUT = "breakout"           # Breakout signal
    SUPPORT_RESISTANCE = "support_resistance"  # Key levels
    VOLATILITY = "volatility"       # Vol expansion/contraction
    DIVERGENCE = "divergence"       # Price/volume divergence


class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class SignalAction(Enum):
    """Recommended actions based on signal."""
    BUY = "buy"
    SELL = "sell"
    ACCUMULATE = "accumulate"
    REDUCE = "reduce"
    HOLD = "hold"
    MONITOR = "monitor"
    WAIT_CONFIRMATION = "wait_confirmation"


@dataclass
class PriceLevel:
    """Price level with label."""
    price: float
    label: str  # e.g., "Entry", "Stop Loss", "Take Profit 1"


@dataclass
class ConfirmationCriteria:
    """Specific criteria to confirm the signal."""
    description: str
    metric: str  # e.g., "RSI > 70", "Volume > 2x avg"
    met: bool
    weight: float = 1.0  # importance weight


@dataclass
class Signal:
    """Enhanced trading signal with formatted output fields."""
    
    # Core identification (required)
    ticker: str
    name: str  # Company/asset name
    category: SignalCategory
    strength: SignalStrength
    action: SignalAction
    score: int  # 0-100
    
    # Market data (required)
    current_price: float
    price_change_percent: float  # Daily %
    volume: float  # Current volume
    avg_volume: float  # Average volume
    
    # Technical trigger (required)
    catalyst: str  # Primary reason for signal
    
    # Optional fields with defaults
    signal_id: str = field(default_factory=lambda: f"signal_{int(datetime.now().timestamp())}") 
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Fundamental (if available)
    market_cap: Optional[str] = None  # e.g., "$15.2B"
    industry: Optional[str] = None
    country: Optional[str] = None
    competitive_edge: Optional[str] = None
    sector: Optional[str] = None
    
    # Other signals list
    other_signals: List[str] = field(default_factory=list)  # Confirmations
    
    # Risk/Reward
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_levels: List[PriceLevel] = field(default_factory=list)
    risk_reward_ratio: float = 0.0  # 1:X format
    position_size_percent: float = 0.0  # % of portfolio
    
    # Action details
    confirmation_criteria: List[ConfirmationCriteria] = field(default_factory=list)
    action_description: str = ""  # Detailed action steps
    
    # Historical context
    historical_signal_accuracy: Optional[float] = None  # % accuracy of similar signals
    recent_performance: Optional[str] = None  # e.g., "This pattern worked 8/10 times"
    
    # Real-time updates
    last_update: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    
    # Metadata
    source: str = "ensemble"  # Algorithm that generated signal
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert signal to dictionary, handling special types."""
        data = asdict(self)
        
        # Convert datetime objects to ISO format
        data['timestamp'] = self.timestamp.isoformat()
        data['last_update'] = self.last_update.isoformat()
        
        # Convert enums to strings
        data['category'] = self.category.value
        data['strength'] = self.strength.name
        data['action'] = self.action.value
        
        # Convert dataclass objects to dicts
        if data['take_profit_levels']:
            data['take_profit_levels'] = [asdict(tp) for tp in self.take_profit_levels]
        if data['confirmation_criteria']:
            data['confirmation_criteria'] = [asdict(cc) for cc in self.confirmation_criteria]
        
        return data
    
    def to_json(self) -> str:
        """Serialize signal to JSON."""
        return json.dumps(self.to_dict(), indent=2)
    
    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Signal({self.ticker} {self.action.value.upper()} "
            f"@${self.current_price:.2f} Score:{self.score}/100 "
            f"Strength:{self.strength.name})"
        )
