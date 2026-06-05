# Charts — feature roadmap

Living backlog for the KLineChart-based Charts tab + indicator engine. Distilled from
the TradingView-Max feature set (Lewis Jackson, "TradingView paid features for free via
Claude/Pine Script", 2026-06-02) diffed against what we already ship. Our architecture is
ahead of his (we own the chart engine + a sandboxed AI→spec engine + arsenal + scout, no
TradingView/Pine dependency); these are the concrete *features* he showed that we lacked.

## Shipped
- KLineChart engine on Charts + PortfolioScan (candles, volume, MA/BOLL/MACD/RSI/VOL, drawing tools, timeframe selector)
- Constrained indicator-spec engine (no-eval) + render adapter + arsenal (approved-spec library)
- Charting-ideas scout (dedicated discovery; YouTube + arXiv live, Reddit/X CLIs handed off)
- (existing) PortfolioScan full scan; Telegram/scan alerts

## In progress
- **Re-homes** (backend `/api/chart/{symbol}/full` already computes these; render on KLineChart):
  1. Fib + Support/Resistance level overlays
  2. Buy/sell signal markers + insider markers
  3. Relative-strength-vs-SPY line

## Queued (priority order)
4. **Multi-timeframe dashboard** — trend + RSI + MA across 1H/D/W/M on one chart (absorbs HTF-levels overlay)
5. **Volume Profile + Point of Control** — volume-by-price histogram for S/R zones (needs price-bin compute)
6. **VWAP + Anchored VWAP** — requires new engine ops (`cumsum` + vwap/anchor) + an anchor picker
7. **Auto session key levels** — prev day/week/month H/L, today's open; auto-updating
8. **Sessions / kill-zones shading** — London/NY/Asia open-close + volatility windows (rebuild on KLineChart)
9. **Chart-condition smart alerts** — one alert over all enabled conditions → Telegram/Slack/Discord/email (reuse agent-bridge + messenger)
10. **Chart-integrated multi-symbol screener** — run an indicator spec / criteria across a watchlist (reuse the indicator engine)
11. **(optional)** "Build my chart" preset wizard + curated arsenal bundles (MA suite, ICT/sessions, volume kit)

## Also queued (pre-existing Phase-3 backlog)
- AI copilot side-panel (explain/advise via ai-read + /ws/agent) — the NL-control analog to his TradingView-MCP, but on our own engine
- Rebuild PortfolioScan compare + portfolio-equity modes on KLineChart
- Wire the scout's Reddit/X source adapters once those CLIs are live/published

Notes: #6 needs indicator-engine op additions; #5 and #8 are dedicated overlays outside the
per-bar spec grammar. #1–3 are the cheapest wins — the server already computes the data.
