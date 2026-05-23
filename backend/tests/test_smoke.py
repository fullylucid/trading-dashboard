"""Smoke tests for trading-dashboard backend API."""


def test_health_endpoint_returns_200(client):
    """/api/health returns 200 with a status field."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_watchlist_endpoint_shape(client):
    """/api/watchlist returns a list of symbols."""
    response = client.get("/api/watchlist")
    assert response.status_code == 200
    data = response.json()
    # Accept either a bare list or {"symbols": [...]} shape
    if isinstance(data, dict):
        assert "symbols" in data or "watchlist" in data
    else:
        assert isinstance(data, list)


def test_signal_endpoint_with_unknown_symbol(client):
    """/api/signals/{symbol} on a non-existent symbol returns 404 or empty."""
    response = client.get("/api/signals/UNKNOWN_SYMBOL_XYZ")
    # Tolerate any of: 404 (not in watchlist), 200 with neutral, 503 (not ready)
    assert response.status_code in (200, 404, 503)


def test_regime_endpoint(client):
    """/api/regime returns regime state when signal_bridge is ready."""
    response = client.get("/api/regime")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        data = response.json()
        assert "hmm_phase" in data or "volatility_regime" in data


def test_root_serves_frontend_or_404(client):
    """/ either serves the SPA shell or 404s when frontend isn't built."""
    response = client.get("/")
    assert response.status_code in (200, 404)
