"""Validate the Attention Score replaces the arbitrary fixed-% threshold sensibly."""
from crack_a_dawn.scoring import (
    Config, MoverInput, score_mover, rank_movers,
    TIER_ACT, TIER_KNOW, TIER_NOTE, TIER_UNEXPLAINED,
)

# A calm baseline: ~1% daily moves -> std ~1%. A wild baseline: ~5% daily.
CALM = [0.8, -1.1, 0.5, -0.6, 1.2, -0.9, 0.7, -0.4, 1.0, -1.3,
        0.6, -0.7, 0.9, -1.0, 0.5, -0.8, 1.1, -0.5, 0.7, -0.9,
        0.8, -0.6, 1.0, -1.2, 0.4, -0.7, 0.9, -0.5, 1.1, -0.8]
WILD = [r * 5 for r in CALM]  # same shape, 5x the volatility


def test_same_6pct_move_is_huge_for_calm_stock_noise_for_wild_one():
    """The whole point: 6% is context-relative, not absolute."""
    calm = score_mover(MoverInput("KO", move_pct=6.0, hist_returns=CALM))
    wild = score_mover(MoverInput("MEME", move_pct=6.0, hist_returns=WILD))
    assert abs(calm.sigma) > 5             # ~6sigma on a calm name
    assert abs(wild.sigma) < 1.5           # noise on a volatile name
    assert calm.abnormality > wild.abnormality
    assert calm.tier in (TIER_KNOW, TIER_ACT, TIER_UNEXPLAINED)
    assert wild.tier == TIER_NOTE


def test_beta_residual_separates_market_move_from_idiosyncratic():
    # market down 5%, beta 1.2 -> ~6% of the move is "expected"; raw -6% is mostly beta.
    market = score_mover(MoverInput("XYZ", move_pct=-6.0, hist_returns=CALM,
                                    market_move_pct=-5.0, beta=1.2))
    # same -6% but market flat -> pure idiosyncratic.
    idio = score_mover(MoverInput("XYZ", move_pct=-6.0, hist_returns=CALM,
                                  market_move_pct=0.0, beta=1.2))
    assert abs(idio.residual_pct) > abs(market.residual_pct)
    assert idio.idiosyncrasy > market.idiosyncrasy


def test_thin_volume_discounts_the_move():
    heavy = score_mover(MoverInput("AAA", move_pct=6.0, hist_returns=CALM,
                                   premarket_volume=300, avg_volume=100))   # 3x
    thin = score_mover(MoverInput("AAA", move_pct=6.0, hist_returns=CALM,
                                  premarket_volume=10, avg_volume=100))     # 0.1x
    assert heavy.volume_conviction > thin.volume_conviction
    assert heavy.significance > thin.significance


def test_at_stop_forces_ACT_even_on_modest_move():
    s = score_mover(MoverInput("HELD", move_pct=-3.0, hist_returns=CALM,
                               held=True, weight=0.12, level_flag="at_stop"))
    assert s.relevance == 1.0
    assert s.tier == TIER_ACT


def test_held_position_outranks_watchlist_twitch():
    held = score_mover(MoverInput("OWN", move_pct=5.0, hist_returns=CALM,
                                  held=True, weight=0.15))
    watch = score_mover(MoverInput("WCH", move_pct=5.0, hist_returns=CALM, held=False))
    assert held.relevance > watch.relevance
    assert held.composite > watch.composite


def test_high_sigma_no_catalyst_is_flagged_unexplained():
    s = score_mover(MoverInput("LEAK", move_pct=7.0, hist_returns=CALM, catalyst_found=False))
    assert s.tier == TIER_UNEXPLAINED


def test_trajectory_building_boosts_fading_discounts():
    # Moderate (~2.5sigma) so significance isn't saturated and trajectory has headroom
    # both ways — trajectory is meant to matter at the margins, not on screaming moves.
    base = score_mover(MoverInput("T", move_pct=2.2, hist_returns=CALM))
    building = score_mover(MoverInput("T", move_pct=2.2, hist_returns=CALM, trajectory=1.0))
    fading = score_mover(MoverInput("T", move_pct=2.2, hist_returns=CALM, trajectory=-1.0))
    assert 0 < base.significance < 1.0      # not saturated
    assert building.significance > base.significance > fading.significance


def test_ranking_puts_act_first_then_by_composite():
    inputs = [
        MoverInput("NOTE", move_pct=1.0, hist_returns=WILD),                         # noise
        MoverInput("ACT", move_pct=-4.0, hist_returns=CALM, held=True,
                   weight=0.2, level_flag="at_stop"),                                # forced ACT
        MoverInput("KNOW", move_pct=6.0, hist_returns=CALM),                         # abnormal
    ]
    ranked = rank_movers(inputs)
    assert ranked[0].ticker == "ACT"
    assert ranked[-1].ticker == "NOTE"
