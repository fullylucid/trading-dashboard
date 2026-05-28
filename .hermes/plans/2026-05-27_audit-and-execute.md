# Audit Report + Execution Plan — Charlotte v4 / Portal / Phase 2

**Date:** 2026-05-27
**Author:** Tradeskeebot (Opus, post-Haiku-confabulation cleanup)
**Workspace:** `/home/user/.hermes/workspace/trading-dashboard/`

---

## TL;DR

The code we wrote today is **real and on disk**. Tests really pass (51/51, verified
just now). Commits really landed (`8fbab13` on `origin/main`). What did **not**
happen is anything that makes the work *visible or useful*:

- Backend isn't running.
- Frontend was never rebuilt — the deployed bundle is from **May 22**.
- Cron jobs still point at a `/tmp/` copy of the repo that gets wiped on reboot.
- Four `.md` deliverables sitting uncommitted.
- Nothing deployed past localhost.

This plan executes the "make it actually exist for the user" pass.

---

## Audit Findings (verified, not claimed)

| # | Claim from session | Reality on disk |
|---|---|---|
| 1 | `hermes/portal/screenshot_handler.py` exists | ✅ 247 lines, present |
| 2 | `backend/research_routes.py` import fixes | ✅ Present, 595 lines |
| 3 | Phase 2 modules in `hermes/charlotte/` | ✅ projections.py (472), visualizer.py (372), signal_enhancer.py (382), signal_engine_v2.py (171) |
| 4 | Tests pass | ✅ **Re-ran just now: 51 passed in 21.19s** (real yfinance, 0 mocks) |
| 5 | Portal router registered in `main.py` | ✅ patched and committed (`8fbab13`) |
| 6 | HermesPortal.jsx frontend component | ✅ `frontend/src/pages/HermesPortal.jsx` (247 lines), wired into `App.jsx` at `/portal` route |
| 7 | Charlotte cron firing on Tradeskeebot schedule | ⚠️ Cron entries exist BUT point at `/tmp/trading-dashboard/` — a **stale copy**, not the canonical repo. `/tmp` is volatile. |
| 8 | Backend running on :8000 | ❌ HTTP 000 — uvicorn was killed end of last session, never restarted |
| 9 | Frontend reflects today's changes | ❌ `frontend/build/index.html` dated **May 22 21:36** — predates ALL of today's work |
| 10 | Charlotte alerts using new Phase 2 signal enhancer | ❌ Cron calls `charlotte.alert_synthesizer` from `/tmp/...` — old code, no signal_enhancer integration |
| 11 | Deliverable docs committed | ❌ `CHARLOTTE_PHASE2_BUILD.md`, `DEPLOYMENT_MANIFEST.md`, `FINAL_SUMMARY.md`, `QUICK_START.md` are untracked |
| 12 | "Core detectors / scorer / regime gate untouched" | ✅ verified — `multi_factor_scorer.py`, `momentum_trim_detector.py`, `secular_top_detector.py`, `trough_detector.py`, `data_fetch.spy_bull_regime()` unmodified |

**Bottom line:** Code is built. Nothing is wired up to actually run.

---

## Goal

Take everything that exists in the repo and **actually deploy it** end-to-end so that:

1. Backend serves Phase 2 + Portal endpoints on a stable port.
2. Frontend bundle contains today's HermesPortal + ResearchPanel work.
3. Cron jobs run today's code from a stable path (not `/tmp`).
4. Alert pipeline goes through `signal_enhancer.py` (Phase 2) before hitting Telegram.
5. Repo is clean (docs committed, build artifacts gitignored).
6. There's a verifiable smoke test the user can run any morning to confirm
   it's still alive.

---

## Constraints (carried from prior session, re-verified)

- **Ollama:** `:cloud` suffix only. Primary `kimi-k2.6:cloud`, secondary `qwen3-coder:480b-cloud`.
- **Coder delegation:** All non-trivial code changes via hydra-protocol subagent → PR → review.
  Direct edits only for config, glue, and verification.
- **Trading core untouched:** detectors, multi_factor_scorer, regime gate (data_fetch.spy_bull_regime), backtests must not be modified.
- **Telegram is canonical alert sink.** Bot @Siiigggbot, chat 5696824719.
- **Confidence threshold:** 6.0.
- **Repo path is canonical:** `/home/user/.hermes/workspace/trading-dashboard/`. Never `/tmp/`.

---

## Execution Plan

### Phase A — Restore the running state (today, 30 min)

**A1. Verify backend boots cleanly from canonical path**

```bash
cd /home/user/.hermes/workspace/trading-dashboard/backend
source venv/bin/activate
PYTHONPATH="..:../hermes" python -m uvicorn main:app --host 0.0.0.0 --port 8000 \
  > /tmp/uvicorn-$(date +%Y%m%d).log 2>&1 &
echo $! > /tmp/uvicorn.pid
sleep 5
curl -sf http://localhost:8000/api/portal/health        || echo PORTAL_FAIL
curl -sf http://localhost:8000/api/research/projections/PLTR | head -c 200
```

**Pass criteria:** both curls return HTTP 200 with JSON, log file shows
`"Hermes Portal router registered"` line.

**A2. Convert ad-hoc startup into a systemd-style supervised process**

Create `~/.hermes/workspace/trading-dashboard/scripts/run-backend.sh` (idempotent,
kills prior uvicorn, restarts, writes pid file). Will be invoked by `@reboot` cron.

```
#!/usr/bin/env bash
set -euo pipefail
REPO=/home/user/.hermes/workspace/trading-dashboard
pkill -f "uvicorn.*main:app" || true
sleep 1
cd "$REPO/backend"
source venv/bin/activate
exec env PYTHONPATH="..:../hermes" \
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Wrap it with `nohup` from a `@reboot` cron entry, log to `~/.hermes/logs/backend.log`.

**Files touched:** `scripts/run-backend.sh` (new), crontab.

---

### Phase B — Frontend rebuild + verify HermesPortal renders (today, 20 min)

**B1. Rebuild the bundle**

```bash
cd /home/user/.hermes/workspace/trading-dashboard/frontend
npm ci          # only if node_modules is stale / missing
npm run build
ls -la build/index.html         # mtime should be NOW
```

**B2. Smoke test the new bundle**

If the frontend is served by the FastAPI backend (check `backend/main.py` for
`StaticFiles` mount), no extra step. Otherwise, restart whatever serves `frontend/build/`.

```bash
# Open the built app's portal route
curl -s http://localhost:8000/portal | grep -o '<title>.*</title>'
# Then via Playwright (already installed):
PYTHONPATH=. python -m hermes.portal.screenshot_handler \
  --target http://localhost:8000/portal --no-render
# Expect: PNG saved to /tmp/hermes-portal/, file command confirms PNG image data
```

**Pass criteria:** screenshot of `/portal` route saves successfully and shows
the HermesPortal UI, not the May-22 default dashboard.

**Files touched:** `frontend/build/` regenerated. Source unchanged.

---

### Phase C — Fix the cron / kill the `/tmp/` ghost (today, 15 min)

This is the bug that probably matters most to the user. Charlotte's pre-market
and after-hours alerts are running **stale code** from `/tmp/trading-dashboard/`
that doesn't include Phase 2.

**C1. Re-point both cron entries**

Replace:

```cron
0 3  * * Mon-Fri cd /tmp/trading-dashboard/hermes && PYTHONPATH=/tmp/trading-dashboard/hermes /tmp/trading-dashboard/backend/.venv/bin/python3 -m charlotte.alert_synthesizer > /tmp/charlotte-premarket.log  2>&1
0 13 * * Mon-Fri cd /tmp/trading-dashboard/hermes && PYTHONPATH=/tmp/trading-dashboard/hermes /tmp/trading-dashboard/backend/.venv/bin/python3 -m charlotte.alert_synthesizer > /tmp/charlotte-afterhours.log 2>&1
```

With (PT, matching M–F market hours from ET schedule in SOUL.md):

```cron
30 3  * * 1-5 /home/user/.hermes/workspace/trading-dashboard/scripts/run-charlotte.sh premarket   >> /home/user/.hermes/logs/charlotte-premarket.log   2>&1
30 6  * * 1-5 /home/user/.hermes/workspace/trading-dashboard/scripts/run-charlotte.sh open        >> /home/user/.hermes/logs/charlotte-open.log        2>&1
0  10-15 * * 1-5 /home/user/.hermes/workspace/trading-dashboard/scripts/run-charlotte.sh hourly   >> /home/user/.hermes/logs/charlotte-hourly.log      2>&1
15 13 * * 1-5 /home/user/.hermes/workspace/trading-dashboard/scripts/run-charlotte.sh afterhours  >> /home/user/.hermes/logs/charlotte-afterhours.log  2>&1
@reboot  /home/user/.hermes/workspace/trading-dashboard/scripts/run-backend.sh                    >> /home/user/.hermes/logs/backend.log              2>&1
```

**C2. Create `scripts/run-charlotte.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-premarket}"
REPO=/home/user/.hermes/workspace/trading-dashboard
cd "$REPO"
source backend/venv/bin/activate
export PYTHONPATH="$REPO:$REPO/hermes"
exec python -m hermes.charlotte.alert_synthesizer --mode "$MODE"
```

(If `alert_synthesizer.py` doesn't accept `--mode`, fall back to plain invocation
and let the synth pick the right window from clock. Verify with `--help` first.)

**C3. Tear down the `/tmp` copy**

```bash
# Sanity: nothing else depends on /tmp/trading-dashboard?
grep -rn "/tmp/trading-dashboard" /home/user/.hermes/ 2>/dev/null | grep -v plans/
# If clean:
rm -rf /tmp/trading-dashboard
```

**Pass criteria:** `crontab -l` shows new entries, `/tmp/trading-dashboard` gone,
manual run of `scripts/run-charlotte.sh premarket` writes to the new log path and
ends with a real Telegram message (or "no signals above threshold" if quiet).

**Files touched:** crontab, `scripts/run-charlotte.sh` (new), `scripts/run-backend.sh` (new).

---

### Phase D — Commit the loose ends (today, 10 min)

**D1. Decide on the 4 untracked `.md` files**

```
CHARLOTTE_PHASE2_BUILD.md
DEPLOYMENT_MANIFEST.md
FINAL_SUMMARY.md
QUICK_START.md
```

Two of these (`FINAL_SUMMARY.md`, `DEPLOYMENT_MANIFEST.md`) were likely written by
Haiku and may contain fabricated claims ("24 tests passing" pattern). **Action:**
read each, fact-check against this audit, delete or rewrite. Commit the survivors
under `docs/`:

```bash
mkdir -p docs
mv CHARLOTTE_PHASE2_BUILD.md docs/    # if accurate
mv QUICK_START.md            docs/    # if accurate
rm FINAL_SUMMARY.md DEPLOYMENT_MANIFEST.md   # if fabricated
git add docs/ && git commit -m "docs: phase 2 build notes + quick start (audited)"
```

**D2. Tag the actually-running state**

```bash
git tag -a v2.1-deployed -m "Backend + frontend + cron all running canonical paths"
git push --tags
```

---

### Phase E — Validation morning loop (recurring)

**E1. Add a watchdog cronjob (no_agent, 0 tokens)**

A simple bash script run every 15 min via Hermes cronjob (not crontab) that:

1. `curl -fs http://localhost:8000/api/portal/health || alert`
2. checks last Charlotte log mtime is < 90 min during market hours
3. Stays SILENT when everything is green (per system-monitoring skill)

Skill to follow: `system-monitoring` (already in skills list).

**E2. One-shot morning smoke test**

`scripts/smoke.sh`:

```bash
#!/usr/bin/env bash
set -e
echo "Backend health:"
curl -fs http://localhost:8000/api/portal/health | head -c 200 ; echo
echo "Projections live:"
curl -fs http://localhost:8000/api/research/projections/SPY | python3 -c \
  'import sys,json; d=json.load(sys.stdin); print(" SPY DCF fair value:", d.get("dcf",{}).get("fair_value","??"))'
echo "Portal screenshot:"
cd /home/user/.hermes/workspace/trading-dashboard && source backend/venv/bin/activate
PYTHONPATH=. python -m hermes.portal.screenshot_handler \
  --target http://localhost:8000/portal --no-render | tail -3
echo "Recent Charlotte alerts (last 24h):"
find /home/user/.hermes/logs -name 'charlotte-*.log' -mtime -1 -print
```

User can run `./scripts/smoke.sh` any morning. If anything breaks, exit code ≠ 0.

---

## Files Likely to Change

| Path | Action |
|---|---|
| `scripts/run-backend.sh` | NEW |
| `scripts/run-charlotte.sh` | NEW |
| `scripts/smoke.sh` | NEW |
| `crontab -l` | REPLACED |
| `frontend/build/*` | REBUILT (not committed — gitignored) |
| `docs/CHARLOTTE_PHASE2_BUILD.md` | MOVED + fact-checked |
| `docs/QUICK_START.md` | MOVED + fact-checked |
| `FINAL_SUMMARY.md`, `DEPLOYMENT_MANIFEST.md` | DELETED if fabricated |
| `/tmp/trading-dashboard/` | REMOVED |
| Hermes cronjob (watchdog) | NEW via `cronjob` tool |

**Files NOT touched** (trading core, per constraint):
- `hermes/charlotte/multi_factor_scorer.py`
- `hermes/charlotte/momentum_trim_detector.py`
- `hermes/charlotte/secular_top_detector.py`
- `hermes/charlotte/trough_detector.py`
- `hermes/charlotte/data_fetch.py` (regime gate lives here)
- `hermes/charlotte/backtest.py`, `scale_out_backtest.py`, `secular_top_backtest.py`

---

## Risks & Open Questions

1. **`alert_synthesizer.py` CLI shape** — needs `--help` check before assuming
   `--mode` flag. Fallback: invoke bare and let clock-aware logic handle window.

2. **`backend/main.py` StaticFiles mount** — unverified. If FastAPI doesn't
   serve `frontend/build/`, we need either an Nginx step or a `StaticFiles`
   patch. Will inspect first.

3. **`backend/venv` portability** — currently committed-then-gitignored. If a
   user clones fresh they get no venv. Add `requirements.txt` regeneration step
   (`pip freeze > backend/requirements.txt`) before tagging `v2.1-deployed`.

4. **Telegram delivery in production** — needs `TELEGRAM_BOT_TOKEN` in
   `backend/.env` and same env loaded by `run-charlotte.sh`. Need to confirm
   the cron-launched bash inherits the right secrets (it won't, by default —
   bash cron has minimal env). Fix: `set -a; source /home/user/.hermes/workspace/trading-dashboard/.env; set +a` in `run-charlotte.sh`.

5. **Phase 2 signal_enhancer integration with alert_synthesizer** — needs
   inspection. If `alert_synthesizer.py` calls the old `signal_engine` directly,
   we may need a one-line patch to route through `signal_enhancer.py` instead.
   This is the only place where today's code might need an additional edit.

6. **Confabulation risk on docs** — `FINAL_SUMMARY.md` and `DEPLOYMENT_MANIFEST.md`
   were almost certainly written by Haiku and may contain false claims like the
   debunked "24/24 passing" line. Read both with skepticism.

---

## Verification Checklist (when this plan is executed)

- [ ] `curl http://localhost:8000/api/portal/health` returns 200
- [ ] `curl http://localhost:8000/api/portal/screenshot?url=https://example.com` returns 200 with `screenshot` key
- [ ] `curl http://localhost:8000/api/research/projections/PLTR` returns DCF JSON
- [ ] `curl http://localhost:8000/portal` returns HTML containing the HermesPortal app shell (not May-22 dashboard)
- [ ] `frontend/build/index.html` mtime is today
- [ ] `crontab -l` shows new entries pointing to `/home/user/.hermes/workspace/trading-dashboard/`
- [ ] `/tmp/trading-dashboard/` is gone
- [ ] `pytest hermes/charlotte/test_projections.py` → 51 passed
- [ ] Manual `scripts/run-charlotte.sh premarket` writes a log and (optionally) sends a Telegram message
- [ ] Hermes watchdog cronjob installed and on first tick reports green (silent)
- [ ] `git status` is clean
- [ ] `git tag -l` includes `v2.1-deployed`
- [ ] `./scripts/smoke.sh` exits 0

---

## Estimated Execution Time

- Phase A: 30 min
- Phase B: 20 min
- Phase C: 15 min (most error-prone — secrets + cron env)
- Phase D: 10 min
- Phase E: 15 min

**Total:** ~90 min, single session, no subagent needed (no new code generation —
just glue, scripts, cron, and verification).

If `alert_synthesizer` needs a Phase-2 enhancer hookup (Phase C / open question 5)
that *is* a code change → delegate to hydra-protocol per constraint.

---

## Ready to Execute?

This plan **does not execute anything**. Approval flow:

> Schyler — read this plan. Tell me:
> 1. Approve as-is → I run Phase A through E
> 2. Modify (specify which phase / step)
> 3. Skip something (e.g. "don't touch cron yet")
> 4. Add something I missed
