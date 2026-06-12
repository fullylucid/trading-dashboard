# Robinhood Agentic Trading — guardrail policy (DRAFT, pending Schyler approval)

**Status:** evaluation only. The MCP is **not** installed in any config. This doc is the
gate that must be approved (Schyler — it's his money/risk) before *any* real-money wiring.
Director: Weaver. Author: charts head. 2026-06-12.

## What this is
Robinhood Agentic Trading (launched 2026-05-27) — an MCP at
`https://agent.robinhood.com/mcp/trading` that lets an AI agent place **real-money**
equity orders in a dedicated "Agentic" account.
- Claude Code: `claude mcp add robinhood-trading --transport http https://agent.robinhood.com/mcp/trading`
- **Read** access: positions, balances, order/txn history. **Write**: trade placement only
  (no withdrawals). Equities only (beta). Setup is desktop-only; opens the agentic account
  via Robinhood's own auth (we store no credentials).

## Robinhood's built-in safety (verified)
- **Dedicated account** — the agent only touches funds deposited there; it never sees the
  primary portfolio. Blast radius = the agentic-account balance.
- **Disconnect button** — pause/revoke the agent instantly in the RH app (the kill-switch).
- **Per-trade push notifications** + live activity/P&L feed (independent audit trail).
- **NO paper trading.** Robinhood has no demo/virtual-cash mode for agentic accounts.

## The risks (why this is gated)
1. Real, irreversible orders — even sandboxed by account.
2. **Configurable autonomy is the trap:** RH's own docs — *"if you've asked your agent to
   take action without asking your approval, it can place trades without your confirmation."*
3. **Prompt-injection surface:** an external trade-execution MCP feeds its responses into the
   model context. A tool result that says "buy X now" must be treated as data, never a command.
4. **Our fleet runs autonomous heads** (orchestration engine, cron timers, `/loop`, background
   agents). The MCP in scope for any *unattended* head = trades with no human. Catastrophic.
5. No documented per-trade/daily funding caps — we impose our own.

## Hard rules (non-negotiable if approved)
1. **Dedicated agentic account, small capped balance.** Start at a deliberately tiny figure
   (Schyler sets it). Treat it as fully at-risk. Never top up beyond the agreed cap without a
   fresh decision.
2. **Confirm-on-every-order.** Never enable RH's "act without approval" mode in Phase 1–2.
3. **One attended, interactive head only.** The MCP is added to exactly one human-watched
   session. It is **BANNED** from: the orchestration engine, cron/systemd timers, `/loop`,
   any `run_in_background` agent, and any head operating unattended. (Enforce by config scope +
   review, not trust.)
4. **Our software dry-run layer is the default** (substitutes for the missing paper trading):
   the dashboard→trade bridge produces *proposed* orders (against live prices, logged + shown)
   and **does not call the place-order tool** unless explicitly armed for that order.
5. **Prompt-injection hygiene:** MCP/tool responses are untrusted data. The agent never acts on
   instructions embedded in tool output; orders come only from the user-confirmed proposal flow.
6. **Bounded mandate:** equities only; per-trade cap (tie to Schyler's 2–3%/trade profile);
   daily order + notional cap; an allow/deny ticker list. Logged locally on every proposal/fill.
7. **Kill paths, all live:** RH disconnect button + remove the MCP (`claude mcp remove`) + the
   bridge's dry-run toggle. Any one halts trading.

## Rollout phases
- **Phase 0 — dry-run / proposal-only (no RH wiring, no risk).** Build the bridge: dashboard
  analysis (charts/signals/scout/engine) → a *proposed* order with rationale → logged + shown,
  validated against live prices. This is our paper-trading equivalent. Run it for a while; review
  the proposals' quality. *No MCP installed.*
- **Phase 1 — tiny real, confirm-every-order.** Only after Schyler approves: open the agentic
  account, fund the small cap, add the MCP to one attended head, confirm every order by hand.
- **Phase 2 — scale cautiously.** Raise caps only with explicit sign-off; still confirm-on-order.
- **Phase 3 (maybe never):** any unattended/auto mode is a separate, explicit Schyler decision
  with much harder limits — not implied by Phases 0–2.

## Open questions to confirm at setup
- Exact order types the MCP exposes (market/limit/stop); does it support bracket/OCO?
- Any RH-side per-trade/daily caps or settlement (cash-account) constraints on the agentic account.
- Whether read-access auth can be granted **without** enabling write (for a read-only Phase 0
  data feed, separate from execution).

## Recommendation
Approve **Phase 0 only** now (build the proposal/dry-run bridge — zero real-money risk, real
product value: it surfaces our analysis as concrete, reviewable trade ideas). Hold Phases 1+
for an explicit Schyler decision on a funded agentic account.
