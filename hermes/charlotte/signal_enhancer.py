#!/usr/bin/env python3
"""Enhanced Signal Engine: Merge projections with technical signals.

Combines:
- DCFProjector price targets (projection_score: 0-10)
- TroughDetector, MomentumTrimDetector, SecularTopDetector (technical_score: 0-10)
- Weighted average: (technical * 0.60) + (projection * 0.40)

Output: Merged signal with trigger reasons and price targets.

Public API:
    EnhancedSignalEngine(symbol)
        .combine_signals(projection_target, current_price) → {type, confidence, trigger, target}
        .calculate_combined_score() → float (0-10)
        .get_sell_signals() → list of strong_sell signals
        .get_buy_signals() → list of strong_buy signals
"""
import sys
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import numpy as np

try:
    from hermes.charlotte import data_fetch as df_mod
    from hermes.charlotte import indicators as ind
    from hermes.charlotte import multi_factor_scorer as scorer
    from hermes.charlotte.projections import DCFProjector
    from hermes.charlotte.narrative_projector import NarrativeProjector
    from hermes.charlotte.trough_detector import analyze as trough_analyze
    from hermes.charlotte.momentum_trim_detector import analyze as peak_analyze
    from hermes.charlotte.secular_top_detector import analyze as top_analyze
except ImportError:
    from charlotte import data_fetch as df_mod
    from charlotte import indicators as ind
    from charlotte import multi_factor_scorer as scorer
    from charlotte.projections import DCFProjector
    from charlotte.narrative_projector import NarrativeProjector
    from charlotte.trough_detector import analyze as trough_analyze
    from charlotte.momentum_trim_detector import analyze as peak_analyze
    from charlotte.secular_top_detector import analyze as top_analyze


class EnhancedSignalEngine:
    """Merge technical detectors with DCF projections."""
    
    def __init__(self, symbol: str):
        """Initialize signal engine with symbol.
        
        Args:
            symbol: Stock ticker
        """
        self.symbol = symbol.upper()
        self.technical_signal: Optional[Dict] = None
        self.projection: Optional[Dict] = None
        self.narrative_projection: Optional[Dict] = None
        self._evaluate_signals()
    
    def _evaluate_signals(self) -> None:
        """Evaluate all technical signals and projections."""
        # Get technical signals from existing detectors
        try:
            # Try trough (buy signal)
            self.trough_signal = trough_analyze(self.symbol, force=False)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError):
            self.trough_signal = None
        
        try:
            # Try peak/trim (sell signal)
            self.peak_signal = peak_analyze(self.symbol, force=False, min_pillars=3)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError):
            self.peak_signal = None
        
        try:
            # Try secular top (strong sell signal)
            self.top_signal = top_analyze(self.symbol, force=False)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError):
            self.top_signal = None
        
        # Get DCF projections
        try:
            projector = DCFProjector(self.symbol, quarters_ahead=12)
            targets = projector.calculate_price_targets()
            
            if targets and 'bull' in targets and 'bear' in targets:
                self.projection = {
                    'bull': targets['bull'],
                    'base': targets['base'],
                    'bear': targets['bear'],
                    'current_price': targets['current_price'],
                    'projector': projector,
                }
        except (ValueError, KeyError, AttributeError, ConnectionError):
            self.projection = None

        # Narrative projection (Jeremy Lefebvre / 1000xstocks-style forward valuation)
        try:
            np_proj = NarrativeProjector(self.symbol, horizon_years=5)
            self.narrative_projection = np_proj.calculate_narrative_targets()
        except (ValueError, KeyError, AttributeError, ConnectionError, TypeError):
            self.narrative_projection = None

    def _calculate_narrative_score(self) -> Tuple[float, str]:
        """Calculate narrative score (0-10) from forward TAM/capture/PS targets.

        Returns:
            (score, reason) tuple
        """
        if not self.narrative_projection:
            return 5.0, 'no_narrative'

        score = 5.0
        reason_parts = []
        x_base = self.narrative_projection.get('x_bagger_base', 1.0)
        x_bull = self.narrative_projection.get('x_bagger_bull', 1.0)

        if x_base >= 3.0:
            score += 2.5
            reason_parts.append('3x_base')
        elif x_base >= 2.0:
            score += 1.5
            reason_parts.append('2x_base')
        elif x_base < 1.2:
            score -= 1.5
            reason_parts.append('overvalued_story')

        if x_bull >= 10.0:
            score += 1.5
            reason_parts.append('10x_bull')

        score = max(0.0, min(10.0, score))
        reason = '+'.join(reason_parts) if reason_parts else 'baseline'
        return round(score, 2), reason
    
    def _calculate_technical_score(self) -> Tuple[float, str]:
        """Calculate technical score (0-10) from detector signals.
        
        Returns:
            (score, reason) tuple
        """
        score = 5.0  # Neutral baseline
        reason_parts = []
        
        # Bearish signals (momentum_trim / secular_top)
        if self.peak_signal and self.peak_signal.get('confidence', 0) >= 6:
            conf = self.peak_signal['confidence']
            score += min(3.0, conf * 0.3)  # Peak signal adds up to 3
            reason_parts.append(f"peak({conf:.1f})")
        
        if self.top_signal and self.top_signal.get('confidence', 0) >= 6:
            conf = self.top_signal['confidence']
            score += min(2.5, conf * 0.25)  # Secular top adds up to 2.5
            reason_parts.append(f"top({conf:.1f})")
        
        # Bullish signals (trough)
        if self.trough_signal and self.trough_signal.get('confidence', 0) >= 5:
            conf = self.trough_signal['confidence']
            # Bullish reduces bearish score
            score = max(0, score - min(2.0, (10 - conf) * 0.2))
            reason_parts.append(f"trough({conf:.1f})")
        
        reason = '+'.join(reason_parts) if reason_parts else 'baseline'
        return round(min(10.0, score), 2), reason
    
    def _calculate_projection_score(self) -> Tuple[float, str]:
        """Calculate projection score (0-10) from DCF targets.
        
        Returns:
            (score, reason) tuple
        """
        if not self.projection:
            return 5.0, 'no_projection'
        
        score = 5.0  # Neutral baseline
        reason_parts = []
        current = self.projection.get('current_price', 1)
        
        if current <= 0:
            return 5.0, 'invalid_price'
        
        bear = self.projection.get('bear', current)
        base = self.projection.get('base', current)
        bull = self.projection.get('bull', current)
        
        # Bearish scenario: bear target is significantly below current
        bear_downside = (bear - current) / current if current > 0 else 0
        if bear_downside < -0.20:  # >20% downside
            score += 2.5
            reason_parts.append(f'bear_-{abs(bear_downside)*100:.0f}%')
        elif bear_downside < -0.10:  # >10% downside
            score += 1.5
            reason_parts.append(f'bear_-{abs(bear_downside)*100:.0f}%')
        elif bear_downside < 0:  # Any downside
            score += 0.5
            reason_parts.append('bear_down')
        
        # Bullish scenario: bull target significantly above current
        bull_upside = (bull - current) / current if current > 0 else 0
        if bull_upside > 0.30:  # >30% upside
            score = max(0, score - 3.0)
            reason_parts.append(f'bull_+{bull_upside*100:.0f}%')
        elif bull_upside > 0.15:  # >15% upside
            score = max(0, score - 2.0)
            reason_parts.append(f'bull_+{bull_upside*100:.0f}%')
        elif bull_upside > 0:  # Any upside
            score = max(0, score - 1.0)
            reason_parts.append('bull_up')
        
        # Base case judgment
        base_deviation = abs(base - current) / current if current > 0 else 0
        if base_deviation < 0.05:  # Within 5% = fair value
            pass  # No adjustment
        
        reason = '+'.join(reason_parts) if reason_parts else 'neutral'
        return round(min(10.0, max(0.0, score)), 2), reason
    
    def calculate_combined_score(self) -> Dict:
        """Calculate weighted combined score: 60% technical + 40% projection.
        
        Returns:
            Dict with keys:
                combined_score: Final score (0-10)
                technical_score: Score from detectors (0-10)
                projection_score: Score from DCF (0-10)
                signal_type: 'strong_sell', 'sell', 'hold', 'buy', 'strong_buy'
                reasoning: Human-readable explanation
        """
        tech_score, tech_reason = self._calculate_technical_score()
        proj_score, proj_reason = self._calculate_projection_score()
        narr_score, narr_reason = self._calculate_narrative_score()

        # Weighted average: tech 0.50 + projection 0.30 + narrative 0.20.
        # If narrative is unavailable, redistribute its 0.20 weight to tech/proj
        # proportionally (0.50/0.30 → 0.625/0.375).
        if self.narrative_projection:
            w_tech, w_proj, w_narr = 0.50, 0.30, 0.20
            combined = (tech_score * w_tech) + (proj_score * w_proj) + (narr_score * w_narr)
        else:
            w_tech, w_proj, w_narr = 0.625, 0.375, 0.0
            combined = (tech_score * w_tech) + (proj_score * w_proj)
        combined = round(min(10.0, max(0.0, combined)), 2)
        
        # Classify
        if combined >= 8.0:
            signal_type = 'strong_sell'
        elif combined >= 6.0:
            signal_type = 'sell'
        elif combined >= 4.0:
            signal_type = 'hold'
        elif combined >= 2.0:
            signal_type = 'buy'
        else:
            signal_type = 'strong_buy'
        
        return {
            'combined_score': combined,
            'technical_score': tech_score,
            'projection_score': proj_score,
            'narrative_score': narr_score,
            'signal_type': signal_type,
            'reasoning': {
                'technical': tech_reason,
                'projection': proj_reason,
                'narrative': narr_reason,
            },
            'weights': {
                'technical': w_tech,
                'projection': w_proj,
                'narrative': w_narr,
            },
        }
    
    def combine_signals(self, current_price: Optional[float] = None) -> Dict:
        """Return merged signal with confidence and target.
        
        Args:
            current_price: Override current price (optional)
        
        Returns:
            Dict with keys:
                symbol: Stock ticker
                type: Signal type (strong_sell, sell, hold, buy, strong_buy)
                confidence: Confidence score (0-10)
                trigger: Reason (combination of detector signals)
                target: Price target if applicable
                breakdown: Dict with detector scores and reasons
        """
        combined = self.calculate_combined_score()
        
        triggers = []
        targets_list = []
        
        # Collect triggers from technical signals
        if self.peak_signal and self.peak_signal.get('confidence', 0) >= 6:
            triggers.append('momentum_peak_trim')
            # Use trim target as partial price target
            if self.peak_signal.get('current_price'):
                peak_target = self.peak_signal['current_price'] * (1 - self.peak_signal.get('trim_pct', 30) / 100)
                targets_list.append(peak_target)
        
        if self.top_signal and self.top_signal.get('confidence', 0) >= 6:
            triggers.append('secular_top_detected')
        
        if self.trough_signal and self.trough_signal.get('confidence', 0) >= 5:
            triggers.append('trough_accumulation')
            if self.trough_signal.get('current_price'):
                # Assume 20% upside from trough
                trough_target = self.trough_signal['current_price'] * 1.20
                targets_list.append(trough_target)
        
        # Add projection-based target
        if self.projection:
            if combined['signal_type'] in ('strong_sell', 'sell'):
                targets_list.append(self.projection['bear'])
                triggers.append('dcf_bear_scenario')
            elif combined['signal_type'] in ('buy', 'strong_buy'):
                targets_list.append(self.projection['bull'])
                triggers.append('dcf_bull_scenario')
            else:
                targets_list.append(self.projection['base'])
        
        # Calculate average target
        target = round(np.mean(targets_list), 2) if targets_list else None
        
        trigger_str = '+'.join(triggers) if triggers else 'technical+projection_merger'
        
        return {
            'symbol': self.symbol,
            'type': combined['signal_type'],
            'confidence': combined['combined_score'],
            'trigger': trigger_str,
            'target': target,
            'breakdown': {
                'technical': {
                    'score': combined['technical_score'],
                    'reason': combined['reasoning']['technical'],
                },
                'projection': {
                    'score': combined['projection_score'],
                    'reason': combined['reasoning']['projection'],
                },
                'narrative': {
                    'score': combined['narrative_score'],
                    'reason': combined['reasoning']['narrative'],
                    'targets': self.narrative_projection,
                },
            },
            'timestamp': datetime.now().isoformat(),
        }
    
    def get_sell_signals(self) -> List[Dict]:
        """Get strong sell signals when projection=bear AND peak detector fires.
        
        Returns:
            List of sell signal dicts with confidence >= 7
        """
        sell_signals = []
        
        # Check for projection bear + peak overlap
        if self.projection and self.peak_signal:
            peak_conf = self.peak_signal.get('confidence', 0)
            
            if peak_conf >= 6:
                signal = {
                    'symbol': self.symbol,
                    'type': 'strong_sell',
                    'confidence': min(10.0, 7.5 + (peak_conf - 6) * 0.3),
                    'trigger': 'projection_bear+peak_overlap',
                    'target': self.projection['bear'],
                    'reason': f"Peak detector ({peak_conf:.1f}) + DCF bear scenario (${self.projection['bear']:.2f})",
                }
                sell_signals.append(signal)
        
        # Check for secular top signal
        if self.top_signal:
            top_conf = self.top_signal.get('confidence', 0)
            if top_conf >= 7:
                signal = {
                    'symbol': self.symbol,
                    'type': 'strong_sell',
                    'confidence': top_conf,
                    'trigger': 'secular_top_confirmed',
                    'target': self.top_signal.get('trim_target'),
                    'reason': f"Secular top detected with {top_conf:.1f} confidence",
                }
                sell_signals.append(signal)
        
        return sorted(sell_signals, key=lambda x: -x['confidence'])
    
    def get_buy_signals(self) -> List[Dict]:
        """Get strong buy signals when projection=bull AND trough detector fires.
        
        Returns:
            List of buy signal dicts with confidence >= 7
        """
        buy_signals = []
        
        # Check for projection bull + trough overlap
        if self.projection and self.trough_signal:
            trough_conf = self.trough_signal.get('confidence', 0)
            
            if trough_conf >= 5:
                signal = {
                    'symbol': self.symbol,
                    'type': 'strong_buy',
                    'confidence': min(10.0, 7.0 + (trough_conf - 5) * 0.4),
                    'trigger': 'projection_bull+trough_overlap',
                    'target': self.projection['bull'],
                    'reason': f"Trough detector ({trough_conf:.1f}) + DCF bull scenario (${self.projection['bull']:.2f})",
                    'add_pct': self.trough_signal.get('add_pct', 10),
                }
                buy_signals.append(signal)
        
        return sorted(buy_signals, key=lambda x: -x['confidence'])
    
    def get_full_analysis(self) -> Dict:
        """Return complete enhanced signal analysis.
        
        Returns:
            Dict with all signal data and metrics.
        """
        merged = self.combine_signals()
        sell_sigs = self.get_sell_signals()
        buy_sigs = self.get_buy_signals()
        
        return {
            'symbol': self.symbol,
            'timestamp': datetime.now().isoformat(),
            'merged_signal': merged,
            'sell_signals': sell_sigs,
            'buy_signals': buy_sigs,
            'detector_status': {
                'trough': bool(self.trough_signal),
                'peak': bool(self.peak_signal),
                'secular_top': bool(self.top_signal),
                'projection': bool(self.projection),
                'narrative': bool(self.narrative_projection),
            },
        }
