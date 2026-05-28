# Hermes Memory - Trading & System Intelligence

Long-term memory for your trading and system operations. Continuity across sessions.

---

## 📈 Trading Watchlist (Active Theses)

### High Conviction Watches

**SMCI (Super Micro Computer)**
- Status: Deep value play with DOJ/governance overhang
- Entry: $25.97, Alert: $22 (support break) / $30 (breakout)
- Thesis: Once scandal resolves, 3-5x potential
- Catalyst: May 26 class action deadline, DOJ resolution timeline
- Risk: Nvidia allocation decision, regulatory overhang

**CRDO (Cerro Dynamics)**
- Status: DustPhotonics acquisition ($750M)
- Jefferies PT: $175
- Catalyst: Conference call 4/14 10 AM ET
- Alert: Major announcement + earnings

**GLW (Corning Inc)**
- Status: AI optics supercycle play, $6B Meta deal
- Entry thesis: Pullback below $135, ideal entry $120-125
- Alert: $135 (pullback start) / $125 (full position)
- Upside: Analyst consensus strong on AI optics trend

**GFS (Gridley Goldfields)** — *Status: Research required*
- Insider cluster buy $43-$48 (Mar 30 - Apr 17)
- Earnings May 5 + Investor Day May 7
- Binary event potential

### Thematic Watches (Sorted by Conviction)

**AMD (Advanced Micro Devices)**
- AI GPU momentum, MI400 launch
- Alert: <$210 support, >$260 breakout
- Analyst upside: 32% forecast

**PLTR (Palantir)**
- Defense AI play: Gotham/AIP for military, $2.2T defense budget
- Trump endorsement, military AI accelerating
- Watch: New defense contracts, government revenue guidance

**INTC (Intel)**
- Foundry turnaround: 18A HVM, Terafab AI chip
- Apollo Ireland buyback ($14.2B), CHIPS Act backing
- Alert: <$45 support, >$65 breakout

**USAR (USA Rare Earth)**
- Rare earth defense supply (Round Top mine)
- $1.5B PIPE financing completed April 8
- Carester 12.5% stake with 15-year offtake
- Watch: DoD rare earth contracts, Oklahoma facility scale-up
- Alert: <$13 support, >$22 breakout

**AMSC (American Superconductor)**
- Grid power / naval systems pivot
- Transitioning from research to revenue-generating power systems
- Watch: Grid modernization contracts, naval defense

**XNDU (Xanadu Quantum)**
- Newly public (March 2026), world's first modular photonic quantum computer
- $302M proceeds + $390M CAD government investment
- Trading began March 27 on Nasdaq/TSX
- Watch: Photonic quantum breakthroughs, enterprise partnerships

**NBIS (Nebius Group)**
- AI infrastructure hyperscaler: +600% YoY
- Nvidia $2B strategic investment
- Watch: Finland factory progress (310MW AI factory), AI21 integration

---

## 🎯 Key Lessons Learned

### DO ✅

- **LIVE DATA FIRST** — Always pull Finnhub/yfinance quotes BEFORE analysis. Stale data = bad trades.
- **Delegate code work** — Never edit `.py` files yourself. Spawn coder subagent.
- **Use cron for scheduling** — No infinite daemon loops. Each run exits cleanly.
- **Log everything** — All cron output to `logs/cron-trades.log` for debugging.
- **Use alert toggles** — Never spam disabled watches; check toggle state first.

### DON'T ❌

- **Mixed models** — Use consistent models. Fail-fast instead of fallbacks.
- **Trust stale search results** — Web search is always stale. Use APIs for prices.
- **Make decisions on incomplete data** — Always cross-reference multiple sources.
- **Manually fix infrastructure** — Document and delegate to coders.
- **Run infinite loops** — Schedule everything with cron, let jobs exit cleanly.

---

## 📋 API Keys & Credentials

All trading API keys are stored in Hermes config.yaml:

- **Alpha Vantage**: FW49LWKXQ9FOBYOF (free tier – 5 calls/min, 500/day)
- **Finnhub**: d7276q1r01qjeeeg64cgd7276q1r01qjeeeg64d0 (free tier – 60 calls/min)
- **Alpaca**: Paper trading enabled, configured in config.yaml
- **Telegram**: @Tradeskeebot bot token configured

---

## 🕷️ Tradeskeebot Model Routing

**Strategy/Planning:** claude-haiku-4-5-20251001 (primary), xAI grok-4 (fallback)
**Coding:** Delegate to coder subagents only (qwen3-coder, claude-code, or similar)
**Research:** kimi-k2.6:cloud if available, otherwise use Haiku

---

## 📅 System Status Checks

### Daily Heartbeat
- [ ] Verify cron jobs are scheduled: `crontab -l`
- [ ] Check system monitor log: `tail ~/.hermes/logs/system-monitor.log`
- [ ] Review trading alerts: Check Telegram @Tradeskeebot

### Weekly
- [ ] Review watchlist theses — update above if theses change
- [ ] Validate API keys (test one call from each)
- [ ] Check cron job output — look for errors in logs

---

_Last updated: 2026-05-21 by Hermes consolidation_
