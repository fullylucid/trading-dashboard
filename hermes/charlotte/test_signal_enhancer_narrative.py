#!/usr/bin/env python3
"""Tests for narrative integration in EnhancedSignalEngine."""
import pytest

from hermes.charlotte import signal_enhancer as se_mod
from hermes.charlotte.signal_enhancer import EnhancedSignalEngine


@pytest.fixture
def engine(monkeypatch):
    """Build an EnhancedSignalEngine with all data sources stubbed."""

    def fake_eval(self):
        self.trough_signal = None
        self.peak_signal = None
        self.top_signal = None
        # Bullish DCF projection (current $100, bull $150)
        self.projection = {
            'bull': 150.0,
            'base': 110.0,
            'bear': 90.0,
            'current_price': 100.0,
            'projector': None,
        }
        # Big-narrative 3x base case
        self.narrative_projection = {
            'bear': 80.0,
            'base': 200.0,
            'bull': 600.0,
            'bear_future': 140.0,
            'base_future': 350.0,
            'bull_future': 1050.0,
            'current_price': 100.0,
            'x_bagger_base': 3.5,
            'x_bagger_bull': 10.5,
            'horizon_years': 5,
            'tam_billions_future': 3000.0,
            'assumptions': {},
        }

    monkeypatch.setattr(EnhancedSignalEngine, '_evaluate_signals', fake_eval)
    return EnhancedSignalEngine('PLTR')


def test_narrative_score_high_for_3x_base(engine):
    score, reason = engine._calculate_narrative_score()
    # baseline 5 + 2.5 (3x_base) + 1.5 (10x_bull) = 9.0
    assert score == 9.0
    assert '3x_base' in reason
    assert '10x_bull' in reason


def test_three_way_weights_applied_when_narrative_present(engine):
    out = engine.calculate_combined_score()
    assert out['weights'] == {'technical': 0.50, 'projection': 0.30, 'narrative': 0.20}
    expected = (
        out['technical_score'] * 0.50
        + out['projection_score'] * 0.30
        + out['narrative_score'] * 0.20
    )
    assert out['combined_score'] == pytest.approx(round(expected, 2), abs=0.01)


def test_weights_redistributed_when_narrative_none(monkeypatch):
    def fake_eval(self):
        self.trough_signal = None
        self.peak_signal = None
        self.top_signal = None
        self.projection = {
            'bull': 150.0, 'base': 110.0, 'bear': 90.0,
            'current_price': 100.0, 'projector': None,
        }
        self.narrative_projection = None
    monkeypatch.setattr(EnhancedSignalEngine, '_evaluate_signals', fake_eval)
    eng = EnhancedSignalEngine('XYZ')
    out = eng.calculate_combined_score()
    assert out['weights'] == {'technical': 0.625, 'projection': 0.375, 'narrative': 0.0}
    expected = out['technical_score'] * 0.625 + out['projection_score'] * 0.375
    assert out['combined_score'] == pytest.approx(round(expected, 2), abs=0.01)


def test_breakdown_has_narrative_key(engine):
    out = engine.combine_signals()
    assert 'narrative' in out['breakdown']
    assert 'score' in out['breakdown']['narrative']
    assert 'reason' in out['breakdown']['narrative']
    assert out['breakdown']['narrative']['targets'] is engine.narrative_projection


def test_backward_compat_keys_still_present(engine):
    out = engine.combine_signals()
    for k in ('symbol', 'type', 'confidence', 'trigger', 'target', 'breakdown', 'timestamp'):
        assert k in out
    # legacy breakdown still has technical + projection
    assert 'technical' in out['breakdown']
    assert 'projection' in out['breakdown']


def test_full_analysis_reports_narrative_status(engine):
    full = engine.get_full_analysis()
    assert full['detector_status']['narrative'] is True
