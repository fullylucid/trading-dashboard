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

## In review (PR #69)
- **Re-homes** (backend `/api/chart/{symbol}/full` already computes these; rendered on KLineChart via a "layers" toggle):
  1. Fib + Support/Resistance level overlays ✅
  2. Buy/sell signal markers + insider markers ✅
  3. Relative-strength-vs-SPY line ✅
- 4. **Multi-timeframe dashboard** ✅ — "MTF" toggle; trend + RSI(14) + last price across 15m/1H/1D/1W, computed per-TF via the indicator engine (absorbs his HTF-levels feature)

## Shipped (cont.)
- 5. **Volume Profile + Point of Control** ✅ — "VolProfile" toggle; volume-by-price histogram (DOM overlay positioned via `convertToPixel`, viewport-synced) + POC / Value-Area-High / Value-Area-Low horizontal lines via the reliable render path

- 6. **VWAP + Anchored VWAP** ✅ — added engine `cumsum` op; VWAP = `cumsum(hlc3·vol)/cumsum(vol)` as a spec. "VWAP" toggle (session over all bars) + click-a-bar anchored VWAP (computed over bars sliced from the anchor); also an example spec in the picker.

- 7. **Auto session key levels** ✅ — "KeyLevels" toggle; prior-day H/L/close, today's open, prior-week H/L, prior-month H/L, 52-week H/L as horizontal lines (computed from daily bars, cached per symbol)

- 8. **Sessions / kill-zones shading** ✅ — "Sessions" toggle (intraday only); translucent vertical bands for Asia/London/NY sessions + London/NY kill zones, positioned via `convertToPixel` (x-axis), viewport-synced

- 9. **Chart-condition smart alerts** ✅ — alert = indicator spec + condition (gt/lt/cross↑/cross↓) on a plot, evaluated server-side against the symbol's latest bars, delivered via Telegram (existing SIGNAL_BOT_*). Redis store + evaluator (dedup per bar) + `POST /api/alerts/check` (driven by a systemd timer, deployment/chart-alerts.*). "Alerts" panel for price-level alerts; engine supports arbitrary specs.

- 10. **Chart-integrated multi-symbol screener** ✅ — "Screen" toggle/panel; run a price condition (gt/lt/cross↑/cross↓) across a watchlist, matches-first results. `POST /api/indicator/screen` reuses the engine + the alert evaluator's bar-fetch/condition helpers.

## Queued (optional / later)
11. **(optional)** "Build my chart" preset wizard + curated arsenal bundles (MA suite, ICT/sessions, volume kit)

## Also queued (pre-existing Phase-3 backlog)
- AI copilot side-panel (explain/advise via ai-read + /ws/agent) — the NL-control analog to his TradingView-MCP, but on our own engine
- Rebuild PortfolioScan compare + portfolio-equity modes on KLineChart
- Wire the scout's Reddit/X source adapters once those CLIs are live/published

Notes: #6 needs indicator-engine op additions; #5 and #8 are dedicated overlays outside the
per-bar spec grammar. #1–3 are the cheapest wins — the server already computes the data.
