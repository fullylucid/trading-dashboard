# MASTER BLUEPRINT — Trading Dashboard

> **The DNA.** The single canonical map of every component, algorithm, integration, and design pattern in this system. Continuously edited (not append-only). When something is built, changed, or retired, **update this file in the same PR.**
>
> For the chronological *fossil record* of how we got here, see `~/.claude/WORKLOG.md`.
>
> **This file is canonical.** It supersedes the ~39 scattered top-level `*.md` files (`BUILD_COMPLETE`, `FINAL_SUMMARY`, `*_CHECKLIST`, `SYSTEM_*`, etc.) — those are historical build artifacts; trust this.

**Status legend:** 🟢 LIVE (in prod) · 🟡 PARTIAL/DORMANT (code exists, not wired) · 🔵 PLANNED · ⚪ IDEA

_Last updated: 2026-05-28_

---

## 1. System at a glance

| | |
|---|---|
| **What** | Swing/day-trading intelligence dashboard — signals, research, portfolio, market data |
| **Repo** | `Fullylucid/trading-dashboard` (git remote = SSH) |
| **Local path** | `/home/user/.hermes/workspace/trading-dashboard/` |
| **Backend** | FastAPI (Python), entry `backend/main.py`, `uvicorn main:app` |
| **Frontend** | React + Zustand, axios REST, `npm run build` → `serve` |
| **Datastore** | Redis 7 (managed, DO) — **caching only today**; no queues/pubsub yet |
| **Deploy** | DigitalOcean App Platform, `app.yaml`, **auto-deploy on push to `main`** |
| **Auth** | 🔴 **NONE today** (no inbound auth on any endpoint — see §7) |

---

## 2. Architecture (layers)

```
 React (pages + components + Zustand store)
        │ axios REST (relative URLs, same-origin in prod)
        ▼
 FastAPI (main.py) ── routers ──► data/signal/portfolio modules
        │                              │
        │                              ├─► external APIs (Finnhub, SnapTrade, Robinhood, SEC)
        ▼                              ▼
 Redis (cache_manager)          Charlotte signal engine + quant toolkit + scanners
        ▲
 websocket_manager.py 🟡 (built, NOT registered)
```

---

## 3. Component catalog

### Backend routers (`backend/main.py` registers these) 🟢
| Prefix | File | Purpose |
|---|---|---|
| `/api/news` | `research_routes.py` | market/sector/symbol/category news |
| `/api/research` | `research_routes.py` | analyze/{symbol}, summarize, sentiment |
| `/api/research/deep` | `deep_dive_routes.py` | deep-dive research endpoints |
| `/api/earnings` | `research_routes.py` | calendar, upcoming, surprises, history |
| `/api/market` | `research_routes.py` | overview, sectors, breadth, vix, treasuries, commodities |
| `/api/signals` | `signal_routes.py` | signals, history, scanner/{type}, webhook (POST) |
| `/api/portfolio` | `portfolio_routes.py` | positions, watchlist, performance, scan, SnapTrade connect |
| `/api/portal` | `hermes_portal.py` | screenshot, health (Playwright screenshotter) |
| `/`, `/health`, `/api/stats` | `main.py` | health/overview |

### Backend modules 🟢
- **Signal engine:** `signal_engine.py`, `signal_scheduler.py`, `signal_formatter.py`, `hermes_signals/` (Signal models + formatter)
- **Charlotte:** modular detector/scorer engine (see §4)
- **Quant:** `quant_bridge.py`, `quant_toolkit.py` (vendored)
- **Scanners** (`backend/scanners/`): `news`, `sentiment`, `options`, `technical`, `sec`, `short_interest`, `smart_money`, `quant_ensemble`
- **Data:** `data_fetcher.py` (Finnhub **WebSocket client** for live prices), `market_data.py`, `news_aggregator.py`, `earnings_calendar.py`
- **Portfolio:** `snaptrade_portfolio.py` (source of truth), `robinhood_portfolio.py`
- **Delivery:** `telegram_bot.py` (primary alert channel)
- **Infra:** `cache_manager.py` (Redis, sync), `config.py` (`REDIS_URL` @ line 28, API keys), `websocket_manager.py` 🟡

### Frontend (`frontend/src/`) 🟢
- **Pages:** `Dashboard`, `ChartView`, `SignalHistory`, `HermesPortal` (screenshot tool), `PortfolioScan`
- **Components:** `Navigation`, `Watchlist`, `QuantScoreboard`, `MarketRegime`
- **Store:** `store/useStore.js` (Zustand) — has `priceWsConnected`/`signalWsConnected` placeholders but **no socket client exists yet** 🟡

### Datastore 🟢
- Redis via `cache_manager.py` (`redis.from_url(REDIS_URL)`), KV + JSON helpers, TTL default 300s, in-memory fallback. **No pub/sub, lists, or streams in use today.**

---

## 4. Algorithms & signal logic

- **Charlotte detectors** 🟢 — ~14 single-pattern detectors (e.g. `TroughDetector`, `MomentumTrimDetector`, `SecularTopDetector`, …), each returns a structured signal + confidence.
- **MultiFactorScorer** 🟢 — aggregates detector signals into a weighted composite.
- **Quant 7-strategy ensemble** 🟢 — pattern-recognition ensemble (`quant_toolkit` / `quant_ensemble` scanner).
- **HMM regime detection** 🔵/🟡 — Hidden Markov Model for market-regime switching (skill `tradeskeebot-hmm-regime-detection`; integration status TBD — verify before relying on it).
- **Confidence thresholds (convention):** >80% → immediate alert · 60–80% → watchlist/monitor · <60% → log-only/pattern-learning. These gates are the **escalation boundary** reused by the planned scanner tier (§6).

---

## 5. Integrations & tools

| Integration | Use | Notes |
|---|---|---|
| **Finnhub** | live quotes, news | `FINNHUB_API_KEY`; `data_fetcher.py` keeps a WS client to Finnhub |
| **SnapTrade** | portfolio (source of truth) | scan every ticker before analysis — foundational rule |
| **Robinhood** | portfolio (secondary) | `robinhood_portfolio.py` |
| **SEC EDGAR** | Form 4 / 8-K insider + material events | `scanners/sec`, skill `trading-insider-detection` |
| **Telegram** | alert delivery | primary channel (Discord disabled — 100-cmd cap) |
| **DigitalOcean** | host | App Platform, managed Redis, `app.yaml` |

---

## 6. Design patterns — the reusable "genes"

These are the recurring architectural decisions we standardize on. New work should conform or consciously deviate (and note why here).

- **🔵 Redis job-bus** — `agent:*` namespaced list/hash/zset schema as the nervous-system bus between cloud and local worker. (Spec in plan `jolly-gliding-yao.md`.)
- **🔵 Tiered-approval PR gate** — agent authority caps at "open a PR"; human merge is the trust boundary; PR-vs-auto decided by deterministic worker-side allow/deny lists, never by LLM self-assessment.
- **Escalation thresholds** — zero-token scripts do the always-on watching; the LLM is woken only when signal beats the 80/60 confidence gates. Keeps an always-on system from being an always-on bill.
- **🔵 Two-credential auth** — browser session cookie (enqueue/history/approve) vs worker bearer token (next/result); never overlapping; constant-time compare.
- **🔵 Continuity via `HOME`** — local worker runs Claude with `HOME=/home/user` so `CLAUDE.md` soul + `~/.claude/.../memory/` load; durable transcripts mirrored to disk.
- **Live-data-first** — always pull real-time quotes before analysis; never trust stale web prices.
- **Never YOLO into `main`** — code changes go branch → PR → review → merge; deploy is a deliberate, reviewed step.
- **Cost-conscious automation** — prefer 0-token script watchdogs for recurring checks; weigh token cost before agentic loops.

---

## 7. Known issues / tech debt

- 🔴 **No inbound auth** on any API endpoint (only CORS, which is moot same-origin in prod). Gating issue before any sensitive endpoint ships. → Cloudflare Access + bcrypt session (planned).
- 🔴 **`main` not branch-protected** + `deploy_on_push: true` → anything reaching `main` deploys live, ungated.
- 🟢 **`backend/main.py` global exception handler** — *fixed in the agent-bridge PR*: no longer returns `str(exc)`; logs server-side + generic 500.
- 🟠 **GitHub PAT over-scoped** — classic `ghp_` with full `repo`+`gist`; should be fine-grained, this-repo-only. (Prereq for agent-bridge go-live.)
- 🟢 **`websocket_manager.py`** — *wired in the agent-bridge PR*: `/ws/agent` registered (ticket-auth), `broadcast_chat()` added.
- 🟠 **Frontend half-migrated** — duplicate `App.jsx`/`App.tsx` + `index.jsx`/`index.tsx`; live entry is `index.tsx → App.tsx` (Vite). The `.jsx` pair + `useStore.js` are orphaned cruft; candidates for cleanup.
- 🟠 **Doc sprawl** — ~39 redundant top-level `*.md`. This blueprint supersedes them; candidates for cleanup.

---

## 8. In-flight / planned

- 🟡 **Agent-bridge + in-app messenger** — always-on Redis job-bus (`agent_bridge.py`, db /1, `agent:` namespace) + WSL2 local worker (`worker/agent_worker.py`, headless Claude under Max) + floating multi-conversation messenger widget (`MessengerWidget/*.tsx`, zustand + react-rnd). Routes Schyler's requests (code edits→PR, data summaries, brainstorm, trigger scans) to Claude on the box. **Plan:** `~/.claude/plans/jolly-gliding-yao.md`. **Status: PR OPEN, reviewed, NOT merged** — gated on prereqs: Cloudflare Access, branch-protect `main`, fine-grained PAT, DO secrets (`AGENT_WORKER_TOKEN`/`SESSION_SECRET`/`OWNER_PASSWORD_HASH`), confirm managed Redis exposes db /1 (else set `AGENT_BUS_REDIS_DB=0`). Live-validate: `claude -p` JSON `session_id` extraction + `acceptEdits`-grants-Bash in headless mode.
- 🔵 **Scanner nervous-system tier** — zero-token scanners → escalate via the bus on threshold → worker → Telegram/messenger.

---

## 9. June 2026 — Charlotte-on-the-box era (current state)
_Sections 1–8 above describe the DigitalOcean-era app through PR #13. Everything below is the current reality; where it conflicts, this section wins._

### Hosting & ops (moved off DigitalOcean)
- **Runs on the box** — ThinkStation **P350 Tiny**, 24/7. `docker-compose.box.yml` → `tdbox-{redis,backend,frontend,nginx}`. Ingress = **Cloudflare Tunnel** (`--protocol http2`, NOT QUIC — QUIC drops server-initiated WS) → nginx loopback `:8080`, behind **Cloudflare Access** (owner SSO; `AGENT_AUTH_DISABLED=true` makes Access the sole gate). **Local Redis** (db0 cache, db1 agent bus) — real BLPOP. **DigitalOcean fully decommissioned 2026-06-01.**
- **Deploy:** `git pull && docker compose -f docker-compose.box.yml up -d --build [service]` (no more `deploy_on_push`).
- **Reboot-proof:** Windows auto-login (Autologon, LSA-encrypted) → 3 logon tasks (WSL Autostart, SysWatch Collector, LibreHardwareMonitor) → systemd brings up docker/cloudflared/tailscaled/agent-bridge@1-5/2chainz/timers. **Tailscale SSH** for phone→box shell.
- **Agent bus:** `/next` now uses **real BLPOP long-poll** (workers hold one request vs 1s-polling — was causing an idle fan-spool); dedicated no-socket-timeout redis client for the block. 5 workers `agent-bridge@1-5`.

### New backend routers (additive, `main.py` try/except-registered)
- `/api/options/*` (`options_routes.py`) — chains/Greeks/strategies/income/multileg/wheel (yfinance + Black-Scholes; `options_cli/`).
- `/api/system/*` (`system_routes.py`) — host-metrics ingest (token-gated) + z-score spike detection + `/explain` via the Opus pool. Fed by Windows-side `scripts/syswatch.ps1`.
- `/api/fintube/*` (`fintube_routes.py`, `fintube/`) — YouTube distillation + alpha leaderboard; `yt-dlp` transcripts → Opus pool.
- `/api/udf/*` (`udf_routes.py`) — TradingView Advanced-Charts datafeed (OHLCV from yfinance).
- `/api/brief/*` (Crack-a-Dawn), `/api/agent/*` (the messenger bus — **now LIVE**, supersedes §8's "PR open").

### New frontend (`frontend/src/pages/`, inline-styled terminal-green)
HomeDashboard (feed+portfolio, stale-while-revalidate), OptionsEngine, FinTube, SystemMonitor (global top banner), Markets (TradingView widgets), CrackADawn. `components/TVWidget.tsx` (reusable TV embed). PWA-installable (manifest + apple-touch icons) — **the app path since Schyler has no Mac**; native SwiftUI shell in `ios/` (mirrors the web).

### Autonomous agents
Crack-a-Dawn (6am brief), 2Chainz (@Siiigggbot strategist), FinTube scout — all on the free Opus worker pool, gated trades.

### Parallel dev (hydra)
`~/.local/bin/hydra` (tmux + git worktrees) spins parallel Charlotte heads, remote-controlled from the Claude app. **Memory is git-tracked**; conductor head = aggregator; per-head deep archives at `~/.hydra-archives/`.

### Resolved from §7/§8
- 🟢 Inbound auth → **Cloudflare Access** (sole gate). 🟢 messenger → **LIVE**. 🟠 `main` branch-protection still not enforced (mitigated: box deploy is manual, not push-triggered).

### In-flight
- 🟡 **TradingView Advanced Charts** — datafeed done (`/api/udf/*`); gated on Schyler's library-access application. Then: embed + AI charting copilot (explain/advise/**write custom indicators** via sandboxed spec).
