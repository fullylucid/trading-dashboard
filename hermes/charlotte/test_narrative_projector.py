#!/usr/bin/env python3
"""Unit tests for NarrativeProjector."""
import pytest

from hermes.charlotte.narrative_projector import (
    NarrativeProjector,
    SECTOR_TAM_TABLE,
    DEFAULT_TAM,
    NARRATIVE_DISCOUNT_RATE,
)


def _stub_loader(self):
    """Default stub: PLTR-like Technology story stock."""
    self.current_price = 25.0
    self.shares_outstanding = 2_000_000_000.0  # 2B shares
    self.current_revenue_ttm = 2_500_000_000.0  # $2.5B
    self.sector = 'Technology'
    self.industry = 'Software'


@pytest.fixture(autouse=True)
def patch_loader(monkeypatch):
    monkeypatch.setattr(NarrativeProjector, '_load_data', _stub_loader)


# ------------------------------------------------------------------ TAM tests
def test_estimate_tam_known_sector():
    p = NarrativeProjector('PLTR', horizon_years=5)
    tam = p.estimate_tam()
    expected = 1500.0 * (1.18 ** 5)
    assert tam == pytest.approx(expected, rel=1e-6)


def test_estimate_tam_with_sector_overrides():
    p = NarrativeProjector('PLTR', horizon_years=5)
    tam = p.estimate_tam(sector_overrides={'tam_b': 2000.0, 'cagr': 0.25})
    expected = 2000.0 * (1.25 ** 5)
    assert tam == pytest.approx(expected, rel=1e-6)


def test_estimate_tam_unknown_sector_falls_back_to_default(monkeypatch):
    def loader(self):
        _stub_loader(self)
        self.sector = 'Quantum Bananas'
    monkeypatch.setattr(NarrativeProjector, '_load_data', loader)
    p = NarrativeProjector('XYZ', horizon_years=5)
    tam = p.estimate_tam()
    expected = DEFAULT_TAM['tam_b'] * ((1 + DEFAULT_TAM['cagr']) ** 5)
    assert tam == pytest.approx(expected, rel=1e-6)


def test_tam_future_compounds_correctly():
    p = NarrativeProjector('PLTR', horizon_years=3)
    tam = p.estimate_tam()
    base = SECTOR_TAM_TABLE['Technology']
    assert tam == pytest.approx(base['tam_b'] * ((1 + base['cagr']) ** 3), rel=1e-9)


# ----------------------------------------------------------- top-down revenue
def test_project_revenue_topdown_math():
    p = NarrativeProjector('PLTR', horizon_years=5)
    tam = p.estimate_tam()
    rev = p.project_revenue_topdown(0.01)
    assert rev == pytest.approx(tam * 0.01, rel=1e-9)


# ------------------------------------------------------- narrative targets
def test_calculate_narrative_targets_has_expected_keys():
    p = NarrativeProjector('PLTR', horizon_years=5)
    out = p.calculate_narrative_targets()
    for k in ('bear', 'base', 'bull', 'current_price',
              'x_bagger_base', 'x_bagger_bull',
              'horizon_years', 'tam_billions_future', 'assumptions'):
        assert k in out, f"missing key {k}"


def test_bear_base_bull_ordering():
    p = NarrativeProjector('PLTR', horizon_years=5)
    out = p.calculate_narrative_targets()
    assert out['bear'] < out['base'] < out['bull']
    assert out['bear_future'] < out['base_future'] < out['bull_future']


def test_x_bagger_computed_correctly():
    p = NarrativeProjector('PLTR', horizon_years=5)
    out = p.calculate_narrative_targets()
    expected_base = round(out['base_future'] / out['current_price'], 1)
    expected_bull = round(out['bull_future'] / out['current_price'], 1)
    assert out['x_bagger_base'] == expected_base
    assert out['x_bagger_bull'] == expected_bull


def test_missing_shares_returns_none(monkeypatch):
    def loader(self):
        _stub_loader(self)
        self.shares_outstanding = None
    monkeypatch.setattr(NarrativeProjector, '_load_data', loader)
    p = NarrativeProjector('PLTR')
    assert p.calculate_narrative_targets() is None


def test_missing_price_returns_none(monkeypatch):
    def loader(self):
        _stub_loader(self)
        self.current_price = None
    monkeypatch.setattr(NarrativeProjector, '_load_data', loader)
    p = NarrativeProjector('PLTR')
    assert p.calculate_narrative_targets() is None


def test_custom_horizon_changes_targets_monotonically():
    p5 = NarrativeProjector('PLTR', horizon_years=5).calculate_narrative_targets()
    p10 = NarrativeProjector('PLTR', horizon_years=10).calculate_narrative_targets()
    # Longer horizon → TAM compounds more → higher future revenue → higher PVs
    # (even after discounting, because sector CAGR 18% > discount 12%)
    assert p10['tam_billions_future'] > p5['tam_billions_future']
    assert p10['base'] > p5['base']
    assert p10['horizon_years'] == 10


def test_get_summary_returns_flat_dict():
    p = NarrativeProjector('PLTR', horizon_years=5)
    s = p.get_summary()
    for k in ('symbol', 'current_price', 'bear_pv', 'base_pv', 'bull_pv',
              'x_bagger_base', 'x_bagger_bull', 'tam_today_b', 'tam_future_b',
              'horizon_years', 'sector'):
        assert k in s
    # No nested dicts
    assert all(not isinstance(v, dict) for v in s.values())


def test_sector_overrides_in_targets():
    p = NarrativeProjector('PLTR', horizon_years=5)
    base_out = p.calculate_narrative_targets()
    boosted = p.calculate_narrative_targets(
        sector_overrides={'tam_b': 5000.0, 'cagr': 0.30}
    )
    assert boosted['base'] > base_out['base']
    assert boosted['tam_billions_future'] > base_out['tam_billions_future']


def test_discount_rate_applied():
    """PV should equal future / (1.12 ** horizon)."""
    p = NarrativeProjector('PLTR', horizon_years=5)
    out = p.calculate_narrative_targets()
    discount = (1 + NARRATIVE_DISCOUNT_RATE) ** 5
    assert out['base'] == pytest.approx(out['base_future'] / discount, abs=0.02)
