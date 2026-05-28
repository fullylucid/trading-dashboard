"""Unit tests for the POST/GET background-job pattern on /api/portfolio/scan."""

import asyncio
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
HERMES_DIR = REPO_ROOT / "hermes"
for _p in (str(BACKEND_DIR), str(REPO_ROOT), str(HERMES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("FINNHUB_API_KEY", "test_key")

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


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
        "tickers_scanned": 3,
        "scanned": 3,
        "tickers_failed": 0,
        "portfolio_value": 3000.0,
        "skipped_symbols": [],
        "top_buys": [{"symbol": "AAPL", "composite_score": 7.5}],
        "top_sells": [{"symbol": "NVDA", "composite_score": 3.0}],
        "top_holds": [{"symbol": "MSFT", "composite_score": 5.5}],
        "ranked": [],
        "failed": [],
    }


@pytest.mark.asyncio
async def test_post_returns_202_with_uuid_job_id():
    import portfolio_routes

    # Stub execute_scan so the background task is fast and harmless
    async def fake_exec(top_n, include_thesis, refresh):
        return _fake_result()

    with patch.object(portfolio_routes, "_execute_scan", side_effect=fake_exec):
        resp = await portfolio_routes.start_scan_job(top_n=10, include_thesis=False, refresh=False)

    assert resp["status"] == "queued"
    assert resp["message"] == "Scan started"
    assert UUID_RE.match(resp["job_id"])
    assert resp["job_id"] in portfolio_routes._scan_jobs

    # Drain the spawned task before the test ends
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_get_unknown_job_returns_404():
    import portfolio_routes
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await portfolio_routes.get_scan_job("does-not-exist")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_right_after_post_returns_queued_or_running():
    import portfolio_routes

    # Make execute_scan hang on an event so the job stays in-flight
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_exec(top_n, include_thesis, refresh):
        started.set()
        await release.wait()
        return _fake_result()

    with patch.object(portfolio_routes, "_execute_scan", side_effect=slow_exec):
        resp = await portfolio_routes.start_scan_job()
        job_id = resp["job_id"]

        # Immediately fetch — should be queued or running
        job = await portfolio_routes.get_scan_job(job_id)
        assert job["status"] in ("queued", "running")
        assert job["result"] is None

        # Let it finish to keep test clean
        await started.wait()
        release.set()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_job_completes_with_result():
    import portfolio_routes

    async def fake_exec(top_n, include_thesis, refresh):
        return _fake_result()

    with patch.object(portfolio_routes, "_execute_scan", side_effect=fake_exec):
        resp = await portfolio_routes.start_scan_job(top_n=5, include_thesis=False, refresh=True)
        job_id = resp["job_id"]

        # Yield until the background task completes
        for _ in range(50):
            await asyncio.sleep(0.01)
            job = await portfolio_routes.get_scan_job(job_id)
            if job["status"] == "complete":
                break

        assert job["status"] == "complete"
        assert job["result"] is not None
        assert "top_buys" in job["result"]
        assert "top_sells" in job["result"]
        assert "top_holds" in job["result"]
        assert job["progress"]["scanned"] == 3


@pytest.mark.asyncio
async def test_job_error_path():
    import portfolio_routes

    async def boom(top_n, include_thesis, refresh):
        raise RuntimeError("kaboom")

    with patch.object(portfolio_routes, "_execute_scan", side_effect=boom):
        resp = await portfolio_routes.start_scan_job()
        job_id = resp["job_id"]

        for _ in range(50):
            await asyncio.sleep(0.01)
            job = await portfolio_routes.get_scan_job(job_id)
            if job["status"] == "error":
                break

        assert job["status"] == "error"
        assert "kaboom" in job["error"]
        assert "RuntimeError" in job["error"]
        assert job["result"] is None
