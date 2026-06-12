# Robinhood Agentic Trading — guardrail policy

**Status (2026-06-12):** **Phase 0 APPROVED by Schyler** — the software dry-run / proposal-only
bridge (no real-money wiring, no MCP installed). **Phases 1+ remain GATED** behind a separate,
explicit Schyler decision on a funded agentic account. The MCP is **not** installed in any config.
Director/owner: Weaver. Original draft: charts head. Policy of record (PR #122, merged).

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
   - **Physical client isolation (preferred enforcement, Phase 1).** The RH MCP is a standard
     Streamable HTTP MCP that works in *any* client (Codex CLI, Cursor, Claude Code — verified
     from RH's own setup docs). Rather than scope it inside our Claude fleet's shared
     `~/.claude.json` (a leak path into an unattended Claude head), run the one attended
     execution session in a **separate client (e.g. Codex CLI)** with the MCP in *that* client's
     config only. Then it is *architecturally impossible* for the trade-exec tool to appear in
     any Claude Code head — "banned by construction," not by discipline.
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

## Phase 0 — build spec (APPROVED, Weaver owns)
The dry-run / proposal-only bridge. Zero real-money risk; no MCP. It is the **first consumer of the
Signal Web** — the read side that turns our analysis into a concrete, reviewable trade idea.

- **`backend/proposals.py`** (pure, unit-tested): `build_proposal(symbol, signal, account_value, cfg)
  -> ProposedOrder`. Fuses an upstream per-ticker signal (Quanticus's Signal-Web contract — coordinate
  the exact shape with Quanticus; until it lands, read `analytics/alerts.py` confluence + `signals.py`)
  into a structured order: `{symbol, side, qty, notional, order_type, entry, stop, target, rationale[],
  confidence, dry_run: true, ts}`. Sizing reuses `analytics/position.py` (ATR stop + Kelly/risk-%),
  bounded by the policy's per-trade cap (2–3% of account) + allow/deny list. **Never** calls any
  place-order tool — `dry_run` is structurally always true in Phase 0.
- **Endpoint** `backend/proposal_routes.py` — `GET /api/proposals` (recent), `POST /api/proposals/{sym}`
  (generate one from current analysis). Read-only; emits + logs proposals, never executes.
- **Log** — append-only proposal journal (Redis `proposals:journal` + optional file) so we can review
  proposal quality over time (the "run it for a while" validation before any Phase 1 decision).
- **Frontend** (follow-up slice) — a proposals panel: the proposed order, its rationale (which signals
  fired), and an explicit *disabled* "arm" affordance (greyed, Phase 1+).
- **Tests** — `backend/tests/test_proposals.py`: sizing within caps, allow/deny enforced, dry_run always
  true, rationale captures the contributing signals.

Hold Phases 1+ for an explicit Schyler decision on a funded agentic account.
