"""Tests for the on-disk daily-snapshot cache of the portfolio scan."""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
HERMES_DIR = REPO_ROOT / "hermes"
for _p in (str(BACKEND_DIR), str(REPO_ROOT), str(HERMES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("FINNHUB_API_KEY", "test_key")


@pytest.fixture
def snapshot_path(tmp_path, monkeypatch):
    """Point the snapshot cache at a per-test tmp file."""
    p = tmp_path / "scan_snapshot.json"
    monkeypatch.setenv("SCAN_SNAPSHOT_PATH", str(p))
    yield p


@pytest.fixture(autouse=True)
def _clear_jobs():
    import portfolio_routes
    portfolio_routes._scan_jobs.clear()
    portfolio_routes._SCAN_CACHE.clear()
    yield
    portfolio_routes._scan_jobs.clear()
    portfolio_routes._SCAN_CACHE.clear()


def _fake_result():
    return {
        "scanned_at": "2026-05-28T00:00:00",
        "tickers_scanned": 2,
        "scanned": 2,
        "tickers_failed": 0,
        "portfolio_value": 1234.5,
        "skipped_symbols": [],
        "top_buys": [{"symbol": "AAPL", "composite_score": 8.0}],
        "top_sells": [{"symbol": "F", "composite_score": 2.0}],
        "top_holds": [],
        "ranked": [],
        "failed": [],
    }


@pytest.mark.asyncio
async def test_completed_scan_writes_snapshot_file(snapshot_path):
    import portfolio_routes

    async def fake_exec(top_n, include_thesis, refresh, progress_cb=None):
        if progress_cb:
            progress_cb(2, 2)
        return _fake_result()

    with patch.object(portfolio_routes, "_execute_scan", side_effect=fake_exec):
        resp = await portfolio_routes.start_scan_job(top_n=5, include_thesis=False, refresh=False)
        job_id = resp["job_id"]
        for _ in range(50):
            await asyncio.sleep(0.01)
            job = await portfolio_routes.get_scan_job(job_id)
            if job["status"] == "complete":
                break
        assert job["status"] == "complete"

    # File should now exist with the expected schema
    assert snapshot_path.exists(), "snapshot file was not written after scan completion"
    with open(snapshot_path) as f:
        data = json.load(f)
    assert set(data.keys()) >= {"saved_at", "saved_at_pt", "result"}
    # saved_at parses as ISO8601
    datetime.fromisoformat(data["saved_at"])
    datetime.fromisoformat(data["saved_at_pt"])
    # Result payload round-trips
    assert data["result"]["portfolio_value"] == 1234.5
    assert data["result"]["top_buys"][0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_get_latest_returns_404_when_missing(snapshot_path):
    import portfolio_routes
    # tmp path doesn't exist yet
    assert not snapshot_path.exists()
    resp = await portfolio_routes.get_scan_latest()
    # JSONResponse with 404 status
    assert resp.status_code == 404
    body = json.loads(resp.body)
    assert body == {"error": "no snapshot available yet"}


@pytest.mark.asyncio
async def test_get_latest_returns_snapshot_and_age_minutes(snapshot_path):
    import portfolio_routes

    # Write a snapshot manually with a saved_at 90 minutes in the past
    past_utc = datetime.now(timezone.utc) - timedelta(minutes=90)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": past_utc.isoformat(),
        "saved_at_pt": past_utc.astimezone(timezone(timedelta(hours=-7))).isoformat(),
        "result": _fake_result(),
    }
    with open(snapshot_path, "w") as f:
        json.dump(payload, f)

    resp = await portfolio_routes.get_scan_latest()
    # Endpoint returns a plain dict on success
    assert isinstance(resp, dict)
    assert resp["saved_at"] == payload["saved_at"]
    assert resp["saved_at_pt"] == payload["saved_at_pt"]
    assert resp["result"]["portfolio_value"] == 1234.5
    # Allow ±2 minute tolerance for clock drift inside test runtime
    assert 88 <= resp["age_minutes"] <= 92, f"age_minutes={resp['age_minutes']} not near 90"


def test_save_snapshot_is_atomic_and_overwrites(snapshot_path):
    import portfolio_routes
    portfolio_routes._save_scan_snapshot({"a": 1})
    assert snapshot_path.exists()
    portfolio_routes._save_scan_snapshot({"a": 2})
    with open(snapshot_path) as f:
        data = json.load(f)
    assert data["result"] == {"a": 2}
    # No stray temp files left behind
    leftovers = [p for p in snapshot_path.parent.iterdir() if p.name.startswith(".portfolio_scan_latest.")]
    assert leftovers == [], f"temp files leaked: {leftovers}"
