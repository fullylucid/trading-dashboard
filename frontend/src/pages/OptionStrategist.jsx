import React, { useState, useMemo, useEffect } from "react";
import {
  Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, ComposedChart,
} from "recharts";
import useMessengerStore from "../store/messengerStore";

/* ============================================================
   OPTIONS STRATEGIST  —  regime-aware strategy generator + lab
   Math: Black–Scholes pricing & Greeks, multi-expiry payoff engine.
   Live data: /api/options/* (yfinance). Opportunity finder hands a
   deterministic snapshot to Claude (WSL2) via the agent bridge.
   Educational only — not investment advice.
   ============================================================ */

/* ---------- math core ---------- */
const normPDF = (x) => Math.exp((-x * x) / 2) / Math.sqrt(2 * Math.PI);
const normCDF = (x) => {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2);
  let p =
    d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x > 0 ? 1 - p : p;
};
function bs(S, K, T, r, sig, type) {
  if (T <= 1e-9 || sig <= 0) {
    const intr = type === "call" ? Math.max(S - K, 0) : Math.max(K - S, 0);
    return {
      price: intr,
      delta: type === "call" ? (S > K ? 1 : 0) : S < K ? -1 : 0,
      gamma: 0, theta: 0, vega: 0,
    };
  }
  const sq = Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r + (sig * sig) / 2) * T) / (sig * sq);
  const d2 = d1 - sig * sq;
  const nd1 = normPDF(d1);
  let price, delta, theta;
  if (type === "call") {
    price = S * normCDF(d1) - K * Math.exp(-r * T) * normCDF(d2);
    delta = normCDF(d1);
    theta = (-S * nd1 * sig) / (2 * sq) - r * K * Math.exp(-r * T) * normCDF(d2);
  } else {
    price = K * Math.exp(-r * T) * normCDF(-d2) - S * normCDF(-d1);
    delta = normCDF(d1) - 1;
    theta = (-S * nd1 * sig) / (2 * sq) + r * K * Math.exp(-r * T) * normCDF(-d2);
  }
  return {
    price,
    delta,
    gamma: nd1 / (S * sig * sq),
    vega: (S * nd1 * sq) / 100,     // per 1 vol point
    theta: theta / 365,             // per calendar day
  };
}

/* ---------- payoff engine (legs may have independent expiries) ---------- */
const MULT = 100; // one option contract controls 100 shares
const legMult = (leg) => (leg.type === "stock" ? 1 : MULT);
const legVal = (leg, S, elapsed, sc) => {
  if (leg.type === "stock") return S;
  const remT = Math.max(leg.dte - elapsed, 0) / 365;
  return bs(S, leg.strike, remT, sc.r, sc.sigma, leg.type).price;
};
const legPnL = (leg, S, elapsed, sc) =>
  (leg.position === "long" ? 1 : -1) * leg.qty * legMult(leg) * (legVal(leg, S, elapsed, sc) - leg.entry);
const payoff = (legs, S, elapsed, sc) => legs.reduce((a, l) => a + legPnL(l, S, elapsed, sc), 0);

const niceStep = (S) =>
  S < 25 ? 1 : S < 60 ? 2.5 : S < 120 ? 5 : S < 300 ? 5 : S < 800 ? 10 : 25;
const roundStrike = (x, S) => {
  const st = niceStep(S);
  return Math.round(x / st) * st;
};

/* Re-time a built strategy onto a chosen expiration (timeframe awareness).
   The shortest-dated leg snaps to `dte`; longer legs (e.g. the back month of a
   calendar) keep their original offset, preserving the structure. */
function retimeLegs(legs, dte) {
  if (!dte) return legs;
  const opt = legs.filter((l) => l.type !== "stock");
  if (!opt.length) return legs;
  const m = Math.min(...opt.map((l) => l.dte));
  return legs.map((l) =>
    l.type === "stock" ? l : { ...l, dte: Math.max(1, Math.round(dte + (l.dte - m))) }
  );
}
const buildLegs = (strat, sc) => retimeLegs(strat.build(sc.S), sc.dte);

/* set entry premium for each leg from the entry scenario */
function priceLegs(legs, sc) {
  return legs.map((l) => ({
    ...l,
    entry:
      l.type === "stock"
        ? sc.S
        : +bs(sc.S, l.strike, l.dte / 365, sc.r, sc.sigma, l.type).price.toFixed(2),
  }));
}

/* full stats for a positioned strategy */
function analyze(legs, sc) {
  const pl = priceLegs(legs, sc);
  const netCost = pl.reduce((a, l) => a + (l.position === "long" ? 1 : -1) * l.entry * l.qty * legMult(l), 0);
  const expDay = Math.min(...pl.map((l) => l.dte));

  // wide grid for accurate stats (captures S->0 losses for stock-based plays)
  const wLo = sc.S * 0.001, wHi = sc.S * 3;
  const WN = 600;
  const wide = [];
  for (let i = 0; i <= WN; i++) {
    const S = wLo + ((wHi - wLo) * i) / WN;
    wide.push({ S, v: payoff(pl, S, expDay, sc) });
  }
  // focused grid for the chart
  const lo = sc.S * 0.5, hi = sc.S * 1.55;
  const N = 200;
  const expCurve = [], todayCurve = [];
  for (let i = 0; i <= N; i++) {
    const S = lo + ((hi - lo) * i) / N;
    expCurve.push({ S, v: payoff(pl, S, expDay, sc) });
    todayCurve.push(payoff(pl, S, 0, sc));
  }
  // breakevens from the wide grid
  const bes = [];
  for (let i = 1; i < wide.length; i++) {
    const a = wide[i - 1].v, b = wide[i].v;
    if ((a < 0 && b >= 0) || (a > 0 && b <= 0)) {
      const Sa = wide[i - 1].S, Sb = wide[i].S;
      bes.push(+(Sa + ((Sb - Sa) * (0 - a)) / (b - a)).toFixed(2));
    }
  }
  // max/min over the wide grid
  let maxP = -Infinity, minP = Infinity;
  wide.forEach((p) => { if (p.v > maxP) maxP = p.v; if (p.v < minP) minP = p.v; });
  // unbounded detection from slope at the far edge
  const tail = wide[wide.length - 1].v - wide[wide.length - 2].v;
  const hasNakedCallUp = pl.some((l) => l.type === "call" && l.position === "short") &&
    pl.filter((l) => l.type === "call").reduce((a, l) => a + (l.position === "long" ? 1 : -1) * l.qty, 0) < 0;
  const hasShortStock = pl.some((l) => l.type === "stock" && l.position === "short");
  const unlimitedProfit = tail > 0.01 && (pl.some((l) => l.type === "call" && l.position === "long") &&
    pl.filter((l) => l.type === "call").reduce((a, l) => a + (l.position === "long" ? 1 : -1) * l.qty, 0) > 0);
  const unlimitedLoss = (tail < -0.01 && (hasNakedCallUp || hasShortStock));

  // net greeks at entry (t0)
  const g = { delta: 0, gamma: 0, theta: 0, vega: 0 };
  pl.forEach((l) => {
    const s = l.position === "long" ? 1 : -1;
    if (l.type === "stock") { g.delta += s * l.qty; return; }
    const gg = bs(sc.S, l.strike, l.dte / 365, sc.r, sc.sigma, l.type);
    const m = s * l.qty * MULT;
    g.delta += m * gg.delta;
    g.gamma += m * gg.gamma;
    g.theta += m * gg.theta;
    g.vega += m * gg.vega;
  });

  return {
    legs: pl, netCost, expDay,
    chart: expCurve.map((p, i) => ({ S: +p.S.toFixed(2), exp: +p.v.toFixed(2), today: +todayCurve[i].toFixed(2) })),
    breakevens: bes,
    maxProfit: unlimitedProfit ? Infinity : maxP,
    maxLoss: unlimitedLoss ? -Infinity : minP,
    greeks: g,
  };
}

/* ---------- strategy library ---------- */
// dir: directional bias (-2 strong bear .. +2 strong bull); vega: + long vol, - short vol
// need: "move" wants a big move, "still" wants range-bound, "drift" mild trend
const ATM = (S) => roundStrike(S, S);
const OTMc = (S, p) => roundStrike(S * (1 + p), S);
const OTMp = (S, p) => roundStrike(S * (1 - p), S);

const STRATS = [
  {
    id: "long-call", name: "Long Call", cat: "Directional · Single Leg",
    dir: 2, vega: 1, need: "drift", defined: true,
    tag: "Bullish · pay premium",
    build: (S) => [{ type: "call", position: "long", strike: ATM(S), qty: 1, dte: 45 }],
    edu: {
      construction: "Buy 1 call, usually at- or slightly out-of-the-money.",
      outlook: "Directional bullish. You want the underlying up, ideally before time decay eats the premium.",
      profit: "Unlimited above the strike. P/L per share = max(S−K,0) − premium.",
      loss: "Limited to the premium paid (the debit).",
      breakeven: "Strike + premium paid.",
      greeks: "Long delta (+), long gamma (+), long vega (+), negative theta (−). You pay to be long convexity and volatility.",
      useWhen: "Strong conviction up, especially when IV is low (options are cheap) and a catalyst is expected. Defined risk, leveraged upside.",
      watchOut: "Theta bleed: even if right on direction, slow moves lose to decay. High IV inflates the premium and the breakeven.",
    },
  },
  {
    id: "long-put", name: "Long Put", cat: "Directional · Single Leg",
    dir: -2, vega: 1, need: "drift", defined: true,
    tag: "Bearish · pay premium",
    build: (S) => [{ type: "put", position: "long", strike: ATM(S), qty: 1, dte: 45 }],
    edu: {
      construction: "Buy 1 put, at- or slightly out-of-the-money.",
      outlook: "Directional bearish, or portfolio insurance against a drop.",
      profit: "Large (capped only at S=0). P/L = max(K−S,0) − premium.",
      loss: "Limited to the premium paid.",
      breakeven: "Strike − premium paid.",
      greeks: "Short delta (−), long gamma (+), long vega (+), negative theta (−). Gains as price falls and as IV expands.",
      useWhen: "Bearish view or hedging. Puts are especially valuable when IV is low relative to the downside risk you're protecting.",
      watchOut: "Downside crashes spike IV — buying puts after the drop is expensive. Buy protection when it's cheap, not after.",
    },
  },
  {
    id: "csp", name: "Cash-Secured Put", cat: "Income · Premium Selling",
    dir: 1, vega: -1, need: "still", defined: false,
    tag: "Mild bullish · collect premium",
    build: (S) => [{ type: "put", position: "short", strike: OTMp(S, 0.05), qty: 1, dte: 35 }],
    edu: {
      construction: "Sell 1 OTM put, holding enough cash to buy 100 shares at the strike if assigned.",
      outlook: "Neutral-to-bullish. You're paid to agree to buy the stock cheaper than today.",
      profit: "Capped at the premium received.",
      loss: "Large: down to (strike − premium) × 100 if the stock collapses — same downside as owning 100 shares from the strike.",
      breakeven: "Strike − premium received.",
      greeks: "Long delta (+), short vega (−), positive theta (+). You're short volatility and long time decay.",
      useWhen: "You'd happily own the stock at the strike. Best when IV rank is elevated so the premium is fat. The income engine behind 'the wheel'.",
      watchOut: "Undefined-ish downside. A gap-down assigns you a falling stock. Size to the cash you can actually deploy.",
    },
  },
  {
    id: "covered-call", name: "Covered Call", cat: "Income · Premium Selling",
    dir: 1, vega: -1, need: "still", defined: false,
    tag: "Mild bullish · yield on shares",
    build: (S) => [
      { type: "stock", position: "long", strike: 0, qty: 100, dte: 45 },
      { type: "call", position: "short", strike: OTMc(S, 0.05), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "Own 100 shares, sell 1 OTM call against them.",
      outlook: "Neutral-to-mildly-bullish. Trade away upside beyond the strike for income now.",
      profit: "Capped at (strike − cost basis + premium). You keep the premium plus gains up to the strike.",
      loss: "The stock's downside, cushioned by the premium collected.",
      breakeven: "Stock cost basis − premium received.",
      greeks: "Net long delta (less than the shares alone), short vega (−), positive theta (+).",
      useWhen: "You hold shares, expect a grind or chop, and want yield. Sell calls when IV is high to maximize the premium.",
      watchOut: "Caps your upside — a sharp rally gets called away. You still own all the downside below your cushion.",
    },
  },
  {
    id: "bull-call", name: "Bull Call Spread", cat: "Vertical Spreads",
    dir: 1, vega: 0, need: "drift", defined: true,
    tag: "Bullish · debit · capped",
    build: (S) => [
      { type: "call", position: "long", strike: ATM(S), qty: 1, dte: 45 },
      { type: "call", position: "short", strike: OTMc(S, 0.1), qty: 1, dte: 45 },
    ],
    edu: {
      construction: "Buy a lower-strike call, sell a higher-strike call (same expiry). Net debit.",
      outlook: "Moderately bullish to a target price (the short strike).",
      profit: "Capped at (width of strikes − net debit).",
      loss: "Limited to the net debit.",
      breakeven: "Long strike + net debit.",
      greeks: "Long delta (+), near vega-neutral, modest theta. The short leg finances the long and cuts IV exposure.",
      useWhen: "Bullish but want to cut cost and define a target. Cheaper and lower-theta than a naked long call; great when IV is moderate-to-high.",
      watchOut: "Upside is capped — you give up the home run. Spreads widen slowly; needs the move before expiry.",
    },
  },
  {
    id: "bear-put", name: "Bear Put Spread", cat: "Vertical Spreads",
    dir: -1, vega: 0, need: "drift", defined: true,
    tag: "Bearish · debit · capped",
    build: (S) => [
      { type: "put", position: "long", strike: ATM(S), qty: 1, dte: 45 },
      { type: "put", position: "short", strike: OTMp(S, 0.1), qty: 1, dte: 45 },
    ],
    edu: {
      construction: "Buy a higher-strike put, sell a lower-strike put (same expiry). Net debit.",
      outlook: "Moderately bearish to a downside target.",
      profit: "Capped at (width of strikes − net debit).",
      loss: "Limited to the net debit.",
      breakeven: "Long strike − net debit.",
      greeks: "Short delta (−), roughly vega-neutral, modest theta.",
      useWhen: "Bearish with a defined target; cheaper than a long put and less IV-sensitive.",
      watchOut: "Capped downside profit. If the drop overshoots your short strike, extra move doesn't help.",
    },
  },
  {
    id: "bull-put", name: "Bull Put Spread", cat: "Vertical Spreads",
    dir: 1, vega: -1, need: "still", defined: true,
    tag: "Bullish · credit · defined risk",
    build: (S) => [
      { type: "put", position: "short", strike: OTMp(S, 0.05), qty: 1, dte: 35 },
      { type: "put", position: "long", strike: OTMp(S, 0.12), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "Sell a put, buy a further-OTM put (same expiry). Net credit. Also called a 'put credit spread'.",
      outlook: "Neutral-to-bullish — you profit if the stock stays above the short strike.",
      profit: "Capped at the net credit received.",
      loss: "Limited to (width − credit).",
      breakeven: "Short strike − net credit.",
      greeks: "Long delta (+), short vega (−), positive theta (+). A defined-risk way to sell premium.",
      useWhen: "Bullish/neutral with high IV rank. You collect premium and let time decay work, with a known max loss.",
      watchOut: "Win rate is high but losers are bigger than winners — risk/reward is skewed. One gap can erase many wins.",
    },
  },
  {
    id: "bear-call", name: "Bear Call Spread", cat: "Vertical Spreads",
    dir: -1, vega: -1, need: "still", defined: true,
    tag: "Bearish · credit · defined risk",
    build: (S) => [
      { type: "call", position: "short", strike: OTMc(S, 0.05), qty: 1, dte: 35 },
      { type: "call", position: "long", strike: OTMc(S, 0.12), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "Sell a call, buy a further-OTM call (same expiry). Net credit ('call credit spread').",
      outlook: "Neutral-to-bearish — profit if the stock stays below the short strike.",
      profit: "Capped at the net credit.",
      loss: "Limited to (width − credit).",
      breakeven: "Short strike + net credit.",
      greeks: "Short delta (−), short vega (−), positive theta (+).",
      useWhen: "Bearish/neutral, elevated IV. Defined-risk premium selling against resistance.",
      watchOut: "Same skewed risk/reward as all credit spreads; rallies through the short strike hurt fast.",
    },
  },
  {
    id: "long-straddle", name: "Long Straddle", cat: "Volatility",
    dir: 0, vega: 2, need: "move", defined: true,
    tag: "Big move · either direction",
    build: (S) => [
      { type: "call", position: "long", strike: ATM(S), qty: 1, dte: 40 },
      { type: "put", position: "long", strike: ATM(S), qty: 1, dte: 40 },
    ],
    edu: {
      construction: "Buy an ATM call and an ATM put, same strike and expiry.",
      outlook: "You expect a large move but don't know which way (earnings, FDA, macro print).",
      profit: "Large in either direction once the move exceeds the combined premium.",
      loss: "Limited to total premium paid — but that's a hefty debit; max loss if it pins the strike.",
      breakeven: "Strike ± total premium (two breakevens).",
      greeks: "Delta-neutral at entry, long gamma (+), strongly long vega (+), heavy negative theta (−).",
      useWhen: "Before a known catalyst when IV is still low, or when you expect realized vol to exceed implied.",
      watchOut: "The 'IV crush' after the event can lose money even on a decent move. You're paying for vol — only wins if the move (or IV rise) beats what you paid.",
    },
  },
  {
    id: "long-strangle", name: "Long Strangle", cat: "Volatility",
    dir: 0, vega: 2, need: "move", defined: true,
    tag: "Big move · cheaper than straddle",
    build: (S) => [
      { type: "call", position: "long", strike: OTMc(S, 0.06), qty: 1, dte: 40 },
      { type: "put", position: "long", strike: OTMp(S, 0.06), qty: 1, dte: 40 },
    ],
    edu: {
      construction: "Buy an OTM call and an OTM put, same expiry. Cheaper than a straddle.",
      outlook: "Expect a big move; need it bigger than a straddle would, but it costs less.",
      profit: "Large in either direction beyond the breakevens.",
      loss: "Limited to total premium; max loss across the whole zone between the strikes.",
      breakeven: "Call strike + total premium, and put strike − total premium.",
      greeks: "Delta-neutral, long gamma (+), long vega (+), negative theta (−).",
      useWhen: "Cheaper volatility play when you expect an outsized move and want lower upfront cost.",
      watchOut: "Wider dead zone — needs a bigger move to pay. Same IV-crush risk around events.",
    },
  },
  {
    id: "short-strangle", name: "Short Strangle", cat: "Volatility",
    dir: 0, vega: -2, need: "still", defined: false,
    tag: "Range-bound · sell premium",
    build: (S) => [
      { type: "call", position: "short", strike: OTMc(S, 0.08), qty: 1, dte: 35 },
      { type: "put", position: "short", strike: OTMp(S, 0.08), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "Sell an OTM call and an OTM put. Net credit.",
      outlook: "Expect the underlying to stay range-bound and IV to fall.",
      profit: "Capped at the credit; widest profit zone of the premium-selling family.",
      loss: "Unlimited on the upside (short call) and very large on the downside.",
      breakeven: "Call strike + credit, put strike − credit.",
      greeks: "Delta-neutral, short gamma (−), strongly short vega (−), positive theta (+).",
      useWhen: "High IV rank, no catalyst, expecting mean reversion in volatility. The classic premium-selling income trade.",
      watchOut: "Undefined risk both ways. A gap or vol spike can produce losses many times the credit. Margin-intensive; demands active management.",
    },
  },
  {
    id: "iron-condor", name: "Iron Condor", cat: "Neutral · Range",
    dir: 0, vega: -1, need: "still", defined: true,
    tag: "Range-bound · defined risk",
    build: (S) => [
      { type: "put", position: "short", strike: OTMp(S, 0.06), qty: 1, dte: 35 },
      { type: "put", position: "long", strike: OTMp(S, 0.12), qty: 1, dte: 35 },
      { type: "call", position: "short", strike: OTMc(S, 0.06), qty: 1, dte: 35 },
      { type: "call", position: "long", strike: OTMc(S, 0.12), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "A bull put spread + a bear call spread on the same underlying. Four legs, net credit.",
      outlook: "Neutral; you want the price to stay inside the short strikes through expiry.",
      profit: "Capped at the net credit (full credit if price stays between short strikes).",
      loss: "Limited to (wing width − credit) on whichever side is breached.",
      breakeven: "Short put − credit, and short call + credit.",
      greeks: "Delta-neutral, short vega (−), positive theta (+), short gamma (−).",
      useWhen: "The workhorse of range-bound, high-IV markets. Defined risk, high probability of profit, time decay as the engine.",
      watchOut: "Small capped profit vs. larger capped loss. Trends through a short strike are the enemy; manage at ~50% of max profit or roll.",
    },
  },
  {
    id: "iron-butterfly", name: "Iron Butterfly", cat: "Neutral · Range",
    dir: 0, vega: -1, need: "still", defined: true,
    tag: "Pin the strike · defined risk",
    build: (S) => [
      { type: "put", position: "short", strike: ATM(S), qty: 1, dte: 35 },
      { type: "put", position: "long", strike: OTMp(S, 0.1), qty: 1, dte: 35 },
      { type: "call", position: "short", strike: ATM(S), qty: 1, dte: 35 },
      { type: "call", position: "long", strike: OTMc(S, 0.1), qty: 1, dte: 35 },
    ],
    edu: {
      construction: "Sell an ATM straddle, buy OTM wings for protection. Larger credit, narrower profit tent than a condor.",
      outlook: "Strongly neutral — you expect the price to pin near the center strike.",
      profit: "Capped; maximized if price lands exactly at the center strike.",
      loss: "Limited to (wing width − credit).",
      breakeven: "Center ± credit.",
      greeks: "Delta-neutral, short vega (−), positive theta (+), short gamma (−). More vega/theta than a condor.",
      useWhen: "High IV, very tight range expectation. Bigger credit than a condor but a smaller margin for error.",
      watchOut: "Narrow profit zone — small moves away from center cut the payoff quickly.",
    },
  },
  {
    id: "call-calendar", name: "Call Calendar", cat: "Advanced · Time",
    dir: 0, vega: 1, need: "still", defined: true,
    tag: "Neutral · long vega · sell time",
    build: (S) => [
      { type: "call", position: "short", strike: ATM(S), qty: 1, dte: 25 },
      { type: "call", position: "long", strike: ATM(S), qty: 1, dte: 60 },
    ],
    edu: {
      construction: "Sell a near-dated option, buy a longer-dated option at the same strike. Net debit.",
      outlook: "Neutral near-term, but you want IV to rise and price to sit near the strike at the front expiry.",
      profit: "Maximized when price is near the strike at the near-term expiration (peak tent). Capped/diffuse.",
      loss: "Limited to the net debit if price runs far in either direction.",
      breakeven: "Two breakevens around the strike (no clean closed form — depends on remaining IV/time).",
      greeks: "Long vega (+) — the long-dated leg dominates — positive theta from the short leg, short gamma near the strike.",
      useWhen: "Low IV that you expect to rise, with price expected to stay near the strike short-term. A vega + theta hybrid.",
      watchOut: "Payoff depends on what IV does to the back-month leg after the front expires; diagram assumes IV holds constant.",
    },
  },
  {
    id: "protective-put", name: "Protective Put (Married Put)", cat: "Hedging",
    dir: 1, vega: 1, need: "drift", defined: true,
    tag: "Own stock · buy insurance",
    build: (S) => [
      { type: "stock", position: "long", strike: 0, qty: 100, dte: 60 },
      { type: "put", position: "long", strike: OTMp(S, 0.05), qty: 1, dte: 60 },
    ],
    edu: {
      construction: "Own 100 shares and buy 1 put as a floor.",
      outlook: "Bullish but want a hard floor against a crash — like an insurance policy with a deductible.",
      profit: "Full upside of the stock, minus the put premium.",
      loss: "Limited below the put strike: max loss = (cost basis − strike) + premium.",
      breakeven: "Stock cost basis + premium paid.",
      greeks: "Net long delta, long vega (+) from the put, negative theta (−) — you pay carry for protection.",
      useWhen: "Protecting gains into uncertainty (earnings, macro) without selling the shares and triggering taxes.",
      watchOut: "The premium is a recurring drag if you keep rolling it. Cheapest to buy when IV is low.",
    },
  },
  {
    id: "collar", name: "Collar", cat: "Hedging",
    dir: 1, vega: 0, need: "still", defined: true,
    tag: "Own stock · floor financed by cap",
    build: (S) => [
      { type: "stock", position: "long", strike: 0, qty: 100, dte: 60 },
      { type: "put", position: "long", strike: OTMp(S, 0.05), qty: 1, dte: 60 },
      { type: "call", position: "short", strike: OTMc(S, 0.05), qty: 1, dte: 60 },
    ],
    edu: {
      construction: "Own 100 shares, buy a protective put, sell a call to pay for it. Often near-zero net cost.",
      outlook: "Protect a position cheaply, accepting a cap on upside in exchange.",
      profit: "Capped at the short call strike.",
      loss: "Floored at the long put strike.",
      breakeven: "Roughly the cost basis ± the net option cost.",
      greeks: "Reduced delta, low net vega (long put vs short call offset), small theta.",
      useWhen: "You want protection but don't want to pay net premium — the call finances the put. Common for concentrated holdings.",
      watchOut: "You give away the upside above the call. A defensive, not opportunistic, structure.",
    },
  },
  {
    id: "short-put-ladder", name: "Put Ratio / 'Wheel' note", cat: "Advanced · Time",
    dir: 1, vega: -1, need: "still", defined: false,
    tag: "Bullish income · advanced",
    build: (S) => [
      { type: "put", position: "short", strike: OTMp(S, 0.04), qty: 1, dte: 30 },
    ],
    edu: {
      construction: "Shown here as a single cash-secured put — the first leg of 'the wheel': sell puts until assigned, then sell covered calls on the shares.",
      outlook: "Mildly bullish, income-oriented, willing to own the stock.",
      profit: "Premium each cycle; capped per trade.",
      loss: "Large if the stock falls hard while you're assigned.",
      breakeven: "Strike − cumulative premium collected.",
      greeks: "Long delta, short vega, positive theta.",
      useWhen: "Range-bound or slow-uptrend names you want to accumulate, with elevated IV to fatten premiums.",
      watchOut: "It's only attractive on stocks you actually want to own; a sustained downtrend turns 'income' into a bag of falling shares.",
    },
  },
];

/* ---------- regime → strategy scoring ---------- */
function scoreStrategy(s, o) {
  // o: {dir:-2..2, move:-1 still | 0 normal | 1 big, ivRank:0-100, definedOnly:bool, conviction:0-2}
  let score = 0; const why = [];
  // hard filter
  if (o.definedOnly && !s.defined) return { score: -999, why: ["needs undefined risk"] };

  // direction match
  const dd = Math.abs(o.dir - s.dir);
  const dScore = 3 - 1.4 * dd;
  score += dScore;
  if (dd <= 0.5) why.push("matches your directional view");
  else if (dd >= 2.5) why.push("fights your directional view");

  // movement / range expectation
  if (s.need === "move") {
    if (o.move === 1) { score += 3; why.push("built for the big move you expect"); }
    else if (o.move === -1) { score -= 3; why.push("needs movement you don't expect"); }
  } else if (s.need === "still") {
    if (o.move === -1) { score += 3; why.push("profits from the range-bound tape you expect"); }
    else if (o.move === 1) { score -= 3; why.push("loses if the big move you expect happens"); }
  } else { // drift
    if (o.move === 1) score += 0.5;
    if (o.move === -1) score -= 0.5;
  }

  // IV-rank fit
  const ivHi = (o.ivRank - 50) / 25; // -2..+2
  if (s.vega < 0) { score += ivHi * 1.3; if (o.ivRank >= 55) why.push("sells expensive premium (high IV rank)"); else if (o.ivRank <= 35) why.push("premium is cheap to sell right now"); }
  else if (s.vega > 0) { score -= ivHi * 1.3; if (o.ivRank <= 35) why.push("buys cheap premium (low IV rank)"); else if (o.ivRank >= 65) why.push("premium is expensive to buy right now"); }

  // conviction → prefer defined risk at low conviction, allow leverage at high
  if (o.conviction <= 0 && !s.defined) score -= 1.2;
  if (o.conviction >= 2 && (s.id === "long-call" || s.id === "long-put")) score += 0.8;

  return { score: +score.toFixed(2), why: why.slice(0, 3) };
}

/* ---------- UI helpers ---------- */
const fmt = (x) => (x === Infinity ? "Unlimited" : x === -Infinity ? "Unlimited" : `$${x.toFixed(2)}`);
const fmtSigned = (x, d = 3) => (x >= 0 ? "+" : "") + x.toFixed(d);
const pct = (x) => (x || x === 0 ? `${Math.round(x * 100)}%` : "—");
const C = {
  bull: "#4ade80", bear: "#fb7185", amber: "#e3b341", cyan: "#5fd3c8",
  text: "#e8e6e0", muted: "#9a978f", line: "#2a2a30", panel: "#141417", panel2: "#1b1b1f", bg: "#0b0b0d",
};

function GreekPill({ label, val, unit, dec = 1 }) {
  const pos = val >= 0;
  return (
    <div className="greek-pill">
      <span className="gp-label">{label}</span>
      <span style={{ color: Math.abs(val) < 1e-6 ? C.muted : pos ? C.bull : C.bear }}>{fmtSigned(val, dec)}</span>
      <span className="gp-unit">{unit}</span>
    </div>
  );
}

function PayoffView({ legs, sc, compact }) {
  const a = useMemo(() => analyze(legs, sc), [legs, sc]);
  // gradient split at y=0
  const ys = a.chart.map((d) => d.exp);
  const yMax = Math.max(...ys, 0), yMin = Math.min(...ys, 0);
  const off = yMax === yMin ? 0.5 : yMax / (yMax - yMin);
  const gid = "pl" + Math.round(off * 1000);
  return (
    <div>
      <div style={{ height: compact ? 200 : 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={a.chart} margin={{ top: 8, right: 10, left: -6, bottom: 0 }}>
            <defs>
              <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                <stop offset={Math.max(0, Math.min(1, off))} stopColor={C.bull} stopOpacity={0.32} />
                <stop offset={Math.max(0, Math.min(1, off))} stopColor={C.bear} stopOpacity={0.32} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={C.line} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="S" tick={{ fill: C.muted, fontSize: 10, fontFamily: "IBM Plex Mono" }}
              tickFormatter={(v) => v.toFixed(0)} stroke={C.line} minTickGap={40} />
            <YAxis tick={{ fill: C.muted, fontSize: 10, fontFamily: "IBM Plex Mono" }}
              tickFormatter={(v) => `$${v}`} stroke={C.line} width={48} />
            <Tooltip
              contentStyle={{ background: "#0e0e11", border: `1px solid ${C.line}`, borderRadius: 6, fontFamily: "IBM Plex Mono", fontSize: 12 }}
              labelStyle={{ color: C.amber }}
              formatter={(v, n) => [`$${(+v).toFixed(2)}`, n === "exp" ? "At expiry" : "Today (mark)"]}
              labelFormatter={(l) => `Underlying $${(+l).toFixed(2)}`} />
            <ReferenceLine y={0} stroke={C.muted} strokeWidth={1} />
            <ReferenceLine x={+sc.S} stroke={C.amber} strokeDasharray="4 3" label={{ value: "spot", fill: C.amber, fontSize: 10, position: "top" }} />
            {a.breakevens.map((b, i) => (
              <ReferenceLine key={i} x={b} stroke={C.cyan} strokeDasharray="2 3" />
            ))}
            <Area type="monotone" dataKey="exp" stroke={C.text} strokeWidth={2} fill={`url(#${gid})`} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="today" stroke={C.amber} strokeWidth={1.4} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="stat-grid">
        <div className="stat"><span>Net {a.netCost >= 0 ? "debit" : "credit"}</span><b style={{ color: a.netCost >= 0 ? C.bear : C.bull }}>{fmt(Math.abs(a.netCost))}</b></div>
        <div className="stat"><span>Max profit</span><b style={{ color: C.bull }}>{fmt(a.maxProfit)}</b></div>
        <div className="stat"><span>Max loss</span><b style={{ color: C.bear }}>{a.maxLoss === -Infinity ? "Unlimited" : fmt(Math.abs(a.maxLoss))}</b></div>
        <div className="stat"><span>Breakeven{a.breakevens.length > 1 ? "s" : ""}</span><b style={{ color: C.cyan }}>{a.breakevens.length ? a.breakevens.map((b) => `$${b}`).join(" / ") : "—"}</b></div>
      </div>

      <div className="greek-row">
        <GreekPill label="Δ delta" val={a.greeks.delta} unit="share-equiv" dec={1} />
        <GreekPill label="Γ gamma" val={a.greeks.gamma} unit="Δ/$1" dec={2} />
        <GreekPill label="Θ theta" val={a.greeks.theta} unit="$/day" dec={1} />
        <GreekPill label="ν vega" val={a.greeks.vega} unit="$/1%IV" dec={1} />
      </div>
      <div className="legend">
        <span><i style={{ background: C.text }} /> payoff at expiry</span>
        <span><i style={{ background: C.amber }} /> value today (mark-to-market)</span>
        <span><i style={{ background: C.cyan }} /> breakeven</span>
      </div>
    </div>
  );
}

/* ---------- strategy detail ---------- */
function Detail({ strat, sc, onClose }) {
  const legs = useMemo(() => buildLegs(strat, sc), [strat, sc.S, sc.dte]);
  const e = strat.edu;
  const rows = [
    ["Construction", e.construction], ["Market outlook", e.outlook],
    ["Max profit", e.profit], ["Max loss", e.loss],
    ["Breakeven", e.breakeven], ["Greeks profile", e.greeks],
    ["When to use", e.useWhen], ["Watch out", e.watchOut],
  ];
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-cat">{strat.cat}</div>
            <h2>{strat.name}</h2>
          </div>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <PayoffView legs={legs} sc={sc} />
        <div className="leg-table">
          <div className="lt-head"><span>Leg</span><span>Strike</span><span>DTE</span><span>Entry</span></div>
          {analyze(legs, sc).legs.map((l, i) => (
            <div className="lt-row" key={i}>
              <span style={{ color: l.position === "long" ? C.bull : C.bear }}>
                {l.position === "long" ? "Long" : "Short"} {l.qty} {l.type === "stock" ? "shares" : l.type}
              </span>
              <span>{l.type === "stock" ? "—" : `$${l.strike}`}</span>
              <span>{l.type === "stock" ? "—" : `${l.dte}d`}</span>
              <span>{l.type === "stock" ? `$${sc.S}` : `$${l.entry.toFixed(2)}`}</span>
            </div>
          ))}
        </div>
        <div className="edu">
          {rows.map(([k, v]) => (
            <div className="edu-row" key={k}><div className="edu-k">{k}</div><div className="edu-v">{v}</div></div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- Finder ---------- */
function Finder({ sc, open }) {
  const [o, setO] = useState({ dir: 1, move: 0, ivRank: sc.ivRank ?? 55, definedOnly: false, conviction: 1 });
  // When a live ticker is loaded, sync the IV-rank slider to its proxy.
  useEffect(() => {
    if (sc.ivRank != null) setO((prev) => ({ ...prev, ivRank: sc.ivRank }));
  }, [sc.ivRank]);
  const ranked = useMemo(() => {
    return STRATS.map((s) => ({ s, ...scoreStrategy(s, o) }))
      .filter((r) => r.score > -900)
      .sort((a, b) => b.score - a.score);
  }, [o]);
  const top = ranked[0];
  const maxScore = top ? top.score : 1;

  const Seg = ({ label, val, set, opts }) => (
    <div className="seg-block">
      <div className="seg-label">{label}</div>
      <div className="seg">
        {opts.map(([t, v]) => (
          <button key={t} className={val === v ? "seg-on" : ""} onClick={() => set(v)}>{t}</button>
        ))}
      </div>
    </div>
  );

  return (
    <div>
      <p className="lede">
        Describe the regime you're reading and the generator ranks strategies by fit — direction, the move you expect,
        and where implied volatility sits. This maps a <em>view</em> to a structure; it does not forecast prices.
        {sc.symbol && <> Scenario loaded from <b style={{ color: C.amber }}>{sc.symbol}</b>.</>}
      </p>
      <div className="controls">
        <Seg label="Directional view" val={o.dir} set={(v) => setO({ ...o, dir: v })}
          opts={[["Strong bear", -2], ["Bear", -1], ["Neutral", 0], ["Bull", 1], ["Strong bull", 2]]} />
        <Seg label="Expected move" val={o.move} set={(v) => setO({ ...o, move: v })}
          opts={[["Range-bound", -1], ["Normal", 0], ["Big move", 1]]} />
        <Seg label="Conviction" val={o.conviction} set={(v) => setO({ ...o, conviction: v })}
          opts={[["Low", 0], ["Medium", 1], ["High", 2]]} />
        <div className="seg-block">
          <div className="seg-label">IV Rank — where implied vol sits in its 52-wk range <b style={{ color: C.amber }}>{o.ivRank}</b></div>
          <input className="range" type="range" min="0" max="100" value={o.ivRank}
            onChange={(e) => setO({ ...o, ivRank: +e.target.value })} />
          <div className="range-cap"><span>cheap to buy</span><span>expensive to sell</span></div>
        </div>
        <label className="check">
          <input type="checkbox" checked={o.definedOnly} onChange={(e) => setO({ ...o, definedOnly: e.target.checked })} />
          Defined-risk only (exclude unlimited-loss structures)
        </label>
      </div>

      <div className="rank-list">
        {ranked.slice(0, 6).map((r, i) => (
          <button key={r.s.id} className={`rank ${i === 0 ? "rank-top" : ""}`} onClick={() => open(r.s)}>
            <div className="rank-rowtop">
              <span className="rank-num">{i + 1}</span>
              <span className="rank-name">{r.s.name}</span>
              <span className="rank-tag">{r.s.tag}</span>
            </div>
            <div className="rank-bar"><i style={{ width: `${Math.max(6, (r.score / maxScore) * 100)}%`, background: i === 0 ? C.amber : C.cyan }} /></div>
            <div className="rank-why">{r.why.map((w, k) => <span key={k}>{w}</span>)}</div>
          </button>
        ))}
      </div>

      {top && (
        <div className="top-preview">
          <div className="tp-head">Top match · {top.s.name}<span>tap any card for full breakdown</span></div>
          <PayoffView legs={buildLegs(top.s, sc)} sc={sc} compact />
        </div>
      )}
    </div>
  );
}

/* ---------- Library ---------- */
function Library({ sc, open }) {
  const cats = [...new Set(STRATS.map((s) => s.cat))];
  return (
    <div>
      <p className="lede">Every structure with its full payoff math, Greeks, and the conditions it's built for. Premiums are modeled from Black–Scholes at the scenario in the header.</p>
      {cats.map((cat) => (
        <div key={cat} className="cat-block">
          <h3 className="cat-title">{cat}</h3>
          <div className="card-grid">
            {STRATS.filter((s) => s.cat === cat).map((s) => {
              const a = analyze(buildLegs(s, sc), sc);
              return (
                <button key={s.id} className="card" onClick={() => open(s)}>
                  <div className="card-name">{s.name}</div>
                  <div className="card-tag">{s.tag}</div>
                  <div className="card-stats">
                    <span>Δ {fmtSigned(a.greeks.delta, 0)}</span>
                    <span style={{ color: a.greeks.vega >= 0 ? C.bull : C.bear }}>ν {fmtSigned(a.greeks.vega, 1)}</span>
                    <span style={{ color: a.greeks.theta >= 0 ? C.bull : C.bear }}>Θ {fmtSigned(a.greeks.theta, 1)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------- Lab ---------- */
const LEG_PRESET = { type: "call", position: "long", strike: 100, qty: 1, dte: 45 };
function Lab({ sc }) {
  const [legs, setLegs] = useState([
    { type: "call", position: "long", strike: roundStrike(sc.S, sc.S), qty: 1, dte: sc.dte || 45 },
    { type: "call", position: "short", strike: roundStrike(sc.S * 1.1, sc.S), qty: 1, dte: sc.dte || 45 },
  ]);
  const upd = (i, k, v) => setLegs(legs.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const add = () => setLegs([...legs, { ...LEG_PRESET, strike: roundStrike(sc.S, sc.S), dte: sc.dte || 45 }]);
  const del = (i) => setLegs(legs.filter((_, j) => j !== i));
  return (
    <div>
      <p className="lede">Build any position leg by leg. The engine prices each leg with Black–Scholes at the header scenario, then plots the expiration payoff (shaded) against today's mark-to-market value (amber dashed).</p>
      <div className="lab-legs">
        <div className="lab-head"><span>Side</span><span>Type</span><span>Strike</span><span>Qty</span><span>DTE</span><span></span></div>
        {legs.map((l, i) => (
          <div className="lab-row" key={i}>
            <select value={l.position} onChange={(e) => upd(i, "position", e.target.value)}>
              <option value="long">Long</option><option value="short">Short</option>
            </select>
            <select value={l.type} onChange={(e) => upd(i, "type", e.target.value)}>
              <option value="call">Call</option><option value="put">Put</option><option value="stock">Stock</option>
            </select>
            <input type="number" value={l.strike} disabled={l.type === "stock"} onChange={(e) => upd(i, "strike", +e.target.value)} />
            <input type="number" value={l.qty} onChange={(e) => upd(i, "qty", +e.target.value)} />
            <input type="number" value={l.dte} disabled={l.type === "stock"} onChange={(e) => upd(i, "dte", +e.target.value)} />
            <button className="del" onClick={() => del(i)} disabled={legs.length <= 1}>×</button>
          </div>
        ))}
        <button className="add" onClick={add}>+ add leg</button>
      </div>
      <PayoffView legs={legs} sc={sc} />
    </div>
  );
}

/* ---------- Opportunities (Claude-powered finder) ---------- */
const HORIZONS = [["1wk", 7], ["2wk", 14], ["1mo", 30], ["6wk", 45], ["2mo", 60], ["3mo", 90]];
const OUTLOOKS = [["Bullish", "bullish"], ["Bearish", "bearish"], ["Neutral", "neutral"], ["Big move", "volatile"], ["Any", "any"]];

function Opportunities() {
  const authed = useMessengerStore((s) => s.authed);
  const sendToClaude = useMessengerStore((s) => s.sendToClaude);
  const setGeometry = useMessengerStore((s) => s.setGeometry);

  const [horizon, setHorizon] = useState(30);
  const [outlook, setOutlook] = useState("any");
  const [scan, setScan] = useState(true);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [sent, setSent] = useState(false);

  const find = async () => {
    setLoading(true); setErr(null); setData(null); setSent(false);
    try {
      const res = await fetch("/api/options/opportunity-prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ horizon_days: horizon, outlook, include_market_scan: scan }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      setData(await res.json());
    } catch (e) {
      setErr(e.message || "Failed to build snapshot");
    } finally {
      setLoading(false);
    }
  };

  const askClaude = async () => {
    if (!data) return;
    setGeometry({ open: true });
    if (!authed) {
      setErr("Open the 💬 messenger (bottom-right) and log in, then click again.");
      return;
    }
    setErr(null);
    const cid = await sendToClaude(data.prompt, "scan");
    setSent(!!cid);
    if (!cid) setErr("Could not start a Claude conversation — log into the messenger first.");
  };

  const Seg = ({ val, set, opts }) => (
    <div className="seg">
      {opts.map(([t, v]) => (
        <button key={t} className={val === v ? "seg-on" : ""} onClick={() => set(v)}>{t}</button>
      ))}
    </div>
  );

  const cands = data?.snapshot?.candidates || [];
  const counts = data?.snapshot?.universe_counts || {};

  return (
    <div>
      <p className="lede">
        Build a deterministic options snapshot across <em>your stocks</em> (brokerage + watchlist) plus a curated
        market scan, then hand it to <b style={{ color: C.amber }}>Claude on your WSL2 box</b> to rank the best
        opportunities — the specific expiration to trade and the structure each name's IV regime is paid for.
        Python computes the numbers; Claude does the judgment.
      </p>

      <div className="controls">
        <div className="seg-block">
          <div className="seg-label">Trading horizon — pins the expirations to consider</div>
          <Seg val={horizon} set={setHorizon} opts={HORIZONS} />
        </div>
        <div className="seg-block">
          <div className="seg-label">Outlook</div>
          <Seg val={outlook} set={setOutlook} opts={OUTLOOKS} />
        </div>
        <label className="check">
          <input type="checkbox" checked={scan} onChange={(e) => setScan(e.target.checked)} />
          Include market-scan discoveries (liquid names beyond my book)
        </label>
        <div className="seg-block" style={{ alignSelf: "end" }}>
          <button className="primary" onClick={find} disabled={loading}>
            {loading ? "Scanning chains…" : "Build snapshot"}
          </button>
        </div>
      </div>

      {err && <div className="notice">{err}</div>}

      {data && (
        <div className="opp-result">
          <div className="opp-head">
            <span>
              {cands.length} candidates · holdings {counts.holdings || 0} · watchlist {counts.watchlist || 0} · scan {counts.market_scan || 0}
            </span>
            <button className="primary" onClick={askClaude}>⚡ Ask Claude to rank these →</button>
          </div>
          {sent && (
            <div className="notice notice-ok">
              Sent to Claude — the ranked picks stream into the 💬 messenger (bottom-right).
            </div>
          )}
          <div className="opp-table">
            <div className="opp-row opp-th">
              <span>Symbol</span><span>Src</span><span>Spot</span><span>ATM IV</span>
              <span>IV-rank*</span><span>IV/RV</span><span>Horizon expirations (±1σ move)</span>
            </div>
            {cands.map((c) => (
              <div className="opp-row" key={c.symbol}>
                <span className="opp-sym">{c.symbol}</span>
                <span className="opp-src">{(c.source || "").replace("market_scan", "scan")}</span>
                <span>${c.spot}</span>
                <span>{pct(c.atm_iv)}</span>
                <span style={{ color: (c.iv_rank_proxy ?? 50) >= 55 ? C.bull : (c.iv_rank_proxy ?? 50) <= 35 ? C.cyan : C.muted }}>
                  {c.iv_rank_proxy != null ? c.iv_rank_proxy : "—"}
                </span>
                <span>{c.iv_premium != null ? `${c.iv_premium}x` : "—"}</span>
                <span className="opp-exps">
                  {(c.horizon_expirations || []).length
                    ? c.horizon_expirations.map((e) => (
                        <em key={e.date}>{e.date} · {Math.round(e.dte)}d · ±{e.expected_move_pct ?? "?"}%</em>
                      ))
                    : <em style={{ opacity: 0.5 }}>none in horizon</em>}
                </span>
              </div>
            ))}
          </div>
          <div className="opp-note">
            *IV-rank is a proxy (current ATM IV vs realized vol) — yfinance doesn't expose historical implied vol.
            Educational only, not investment advice.
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- Cycles (education) ---------- */
function Cycles() {
  const phases = [
    { n: "1 · Accumulation", c: C.cyan, d: "After a decline, price stops falling and chops sideways in a base. Volatility is high but starting to compress. Sentiment is fearful; 'smart money' quietly builds positions.", o: "Sell puts / put credit spreads into the fear (IV still rich), or buy cheap longer-dated calls once IV begins to fall." },
    { n: "2 · Markup (Advance)", c: C.bull, d: "Higher highs and higher lows. Trend is up, realized volatility is moderate, IV is usually low-to-moderate as complacency builds.", o: "Bull call spreads, long calls, covered calls on pullbacks. Low IV favors buying premium; define targets with spreads." },
    { n: "3 · Distribution", c: C.amber, d: "The uptrend stalls into a choppy top. Volatility begins to expand; rallies fail. Smart money distributes to late buyers.", o: "Bear call spreads, collars to lock gains, iron condors if range-bound. Begin buying protection while IV is still moderate." },
    { n: "4 · Markdown (Decline)", c: C.bear, d: "Lower highs and lower lows. IV spikes hard; correlations go to one. Fast, emotional moves.", o: "Long puts / bear put spreads bought before the spike; once IV is extreme, shift to selling premium (spreads, not naked) into the panic." },
  ];
  return (
    <div>
      <p className="lede">
        Markets don't repeat on a schedule, but they do <em>rhyme</em> through recognizable phases. The point isn't prediction — it's
        reading which phase the evidence supports, then choosing a structure whose Greeks are paid to be right about <em>that</em> regime.
      </p>

      <h3 className="cat-title">The four-phase cycle (Wyckoff lens)</h3>
      <div className="phase-grid">
        {phases.map((p) => (
          <div className="phase" key={p.n} style={{ borderTop: `2px solid ${p.c}` }}>
            <div className="phase-n" style={{ color: p.c }}>{p.n}</div>
            <p>{p.d}</p>
            <div className="phase-o"><b>Options posture:</b> {p.o}</div>
          </div>
        ))}
      </div>

      <h3 className="cat-title">The two questions that pick a strategy</h3>
      <div className="qa">
        <div className="qa-card">
          <div className="qa-q">1. Which way, and how hard?</div>
          <p>Direction (the delta you want) and the size of the move (the gamma you want). A view of "up, gently" calls for a spread; "huge move, unsure of direction" calls for a straddle.</p>
        </div>
        <div className="qa-card">
          <div className="qa-q">2. Is volatility cheap or expensive?</div>
          <p>This is the question most beginners skip. <b style={{ color: C.amber }}>IV Rank</b> tells you where implied vol sits in its own 52-week range. High rank → <span style={{ color: C.bull }}>sell premium</span> (short vega, collect theta). Low rank → <span style={{ color: C.cyan }}>buy premium</span> (long vega).</p>
        </div>
      </div>

      <h3 className="cat-title">Volatility is the edge</h3>
      <div className="vol-notes">
        <div className="vn"><b>The variance risk premium.</b> Implied volatility tends to trade <em>above</em> the volatility that actually gets realized — option sellers are paid to bear risk. This is the structural reason premium-selling strategies (condors, credit spreads, strangles) have an edge — paid for in occasional large losses when realized vol overshoots.</div>
        <div className="vn"><b>Vol mean-reverts.</b> IV spikes in panics and decays in calm. Selling when IV Rank is high and buying when it's low leans on this. A move can be 'right' and still lose if you paid too much implied vol (the post-earnings 'IV crush').</div>
        <div className="vn"><b>Term structure & skew.</b> Compare near vs far expiries (calendars exploit this) and the fact that puts usually cost more than equidistant calls (skew). These are the second-order edges beyond simple direction.</div>
      </div>

      <div className="disclaimer">
        Educational tool only — not investment advice. Options carry substantial risk, including loss exceeding your initial outlay
        for undefined-risk structures. Modeled premiums use Black–Scholes with constant volatility and ignore commissions,
        dividends, assignment, and bid-ask spreads; real fills will differ.
      </div>
    </div>
  );
}

/* ---------- live data bar ---------- */
function LiveBar({ sc, setSc }) {
  const [sym, setSym] = useState(sc.symbol || "");
  const [exps, setExps] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = async () => {
    const s = sym.trim().toUpperCase();
    if (!s) return;
    setLoading(true); setErr(null);
    try {
      const res = await fetch(`/api/options/snapshot/${encodeURIComponent(s)}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      const d = await res.json();
      const list = d.expirations || [];
      setExps(list);
      setMeta(d);
      const front = list[0];
      setSc((prev) => ({
        ...prev,
        S: d.spot,
        sigma: d.atm_iv || d.hist_vol_30d || prev.sigma,
        r: d.risk_free_rate ?? prev.r,
        dte: front ? front.dte : null,
        symbol: s,
        ivRank: d.iv_rank_proxy ?? null,
        selExp: front ? front.date : null,
      }));
    } catch (e) {
      setErr(e.message || "lookup failed");
      setExps([]); setMeta(null);
    } finally {
      setLoading(false);
    }
  };

  const pickExp = (e) => setSc((prev) => ({ ...prev, dte: e.dte, selExp: e.date }));

  return (
    <div className="livebar">
      <div className="lb-load">
        <input
          value={sym}
          onChange={(e) => setSym(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") load(); }}
          placeholder="ticker (e.g. NVDA)"
          spellCheck={false}
        />
        <button className="primary" onClick={load} disabled={loading}>
          {loading ? "…" : "Load live"}
        </button>
      </div>
      {err && <span className="lb-err">{err}</span>}
      {meta && (
        <div className="lb-meta">
          <span><b>{meta.symbol}</b> ${meta.spot}</span>
          <span>ATM IV {pct(meta.atm_iv)}</span>
          <span>IV-rank* {meta.iv_rank_proxy ?? "—"}</span>
          <span>IV/RV {meta.iv_premium != null ? `${meta.iv_premium}x` : "—"}</span>
          <span>RV30 {pct(meta.hist_vol_30d)}</span>
        </div>
      )}
      {exps.length > 0 && (
        <div className="lb-exps">
          <span className="lb-exps-label">Expiration:</span>
          {exps.map((e) => (
            <button
              key={e.date}
              className={sc.selExp === e.date ? "lb-exp on" : "lb-exp"}
              onClick={() => pickExp(e)}
              title={`±1σ expected move ±$${e.expected_move ?? "?"} (${e.expected_move_pct ?? "?"}%)`}
            >
              {e.date}<i>{Math.round(e.dte)}d{e.expected_move_pct != null ? ` · ±${e.expected_move_pct}%` : ""}</i>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- root ---------- */
export default function OptionStrategist() {
  const [tab, setTab] = useState("finder");
  const [sc, setSc] = useState({ S: 100, sigma: 0.3, r: 0.045, dte: null, symbol: null, ivRank: null, selExp: null });
  const [detail, setDetail] = useState(null);

  const tabs = [
    ["finder", "Strategy Finder"], ["opps", "Opportunities"], ["library", "Strategy Library"],
    ["lab", "Payoff Lab"], ["cycles", "Market Cycles"],
  ];

  return (
    <div className="root">
      <style>{CSS}</style>
      <header className="hdr">
        <div className="brand">
          <div className="brand-mark">◭</div>
          <div>
            <h1>Options Strategist</h1>
            <div className="brand-sub">regime-aware strategy generator · payoff & Greeks lab · live data + Claude finder</div>
          </div>
        </div>
        <div className="scenario">
          <label>Spot<input type="number" value={sc.S} onChange={(e) => setSc({ ...sc, S: Math.max(1, +e.target.value) })} /></label>
          <label>IV %<input type="number" value={Math.round(sc.sigma * 100)} onChange={(e) => setSc({ ...sc, sigma: Math.max(1, +e.target.value) / 100 })} /></label>
          <label>Rate %<input type="number" value={(sc.r * 100).toFixed(1)} step="0.1" onChange={(e) => setSc({ ...sc, r: +e.target.value / 100 })} /></label>
        </div>
      </header>

      <LiveBar sc={sc} setSc={setSc} />

      <nav className="tabs">
        {tabs.map(([k, t]) => (
          <button key={k} className={tab === k ? "tab-on" : ""} onClick={() => setTab(k)}>{t}</button>
        ))}
      </nav>

      <main className="main">
        {tab === "finder" && <Finder sc={sc} open={setDetail} />}
        {tab === "opps" && <Opportunities />}
        {tab === "library" && <Library sc={sc} open={setDetail} />}
        {tab === "lab" && <Lab sc={sc} />}
        {tab === "cycles" && <Cycles />}
      </main>

      {detail && <Detail strat={detail} sc={sc} onClose={() => setDetail(null)} />}

      <footer className="ftr">Black–Scholes engine · constant-vol model · live data via yfinance · educational only, not investment advice</footer>
    </div>
  );
}

/* ---------- styles ---------- */
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
.root * { box-sizing: border-box; }
.root { background:${C.bg}; color:${C.text}; font-family:'IBM Plex Sans',sans-serif; min-height:100vh;
  background-image: radial-gradient(circle at 20% 0%, rgba(227,179,65,0.05), transparent 40%), radial-gradient(circle at 90% 10%, rgba(95,211,200,0.04), transparent 35%);
  background-attachment: fixed; padding-bottom:40px; }
.hdr { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;
  padding:20px 26px 20px 64px; border-bottom:1px solid ${C.line}; }
.brand { display:flex; align-items:center; gap:14px; }
.brand-mark { font-size:30px; color:${C.amber}; line-height:1; }
.hdr h1 { font-family:'Fraunces',serif; font-weight:600; font-size:25px; margin:0; letter-spacing:-0.5px; }
.brand-sub { font-family:'IBM Plex Mono',monospace; font-size:11px; color:${C.muted}; margin-top:3px; letter-spacing:0.3px; }
.scenario { display:flex; gap:8px; }
.scenario label { display:flex; flex-direction:column; font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.muted}; gap:4px; }
.scenario input { width:64px; background:${C.panel}; border:1px solid ${C.line}; color:${C.text};
  font-family:'IBM Plex Mono',monospace; font-size:14px; padding:6px 8px; border-radius:6px; }

/* live data bar */
.livebar { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:12px 26px; border-bottom:1px solid ${C.line};
  background:${C.panel}; }
.lb-load { display:flex; gap:6px; }
.lb-load input { background:${C.panel2}; border:1px solid ${C.line}; color:${C.text}; font-family:'IBM Plex Mono',monospace;
  font-size:13px; padding:7px 10px; border-radius:6px; width:170px; text-transform:uppercase; }
.lb-err { color:${C.bear}; font-family:'IBM Plex Mono',monospace; font-size:12px; }
.lb-meta { display:flex; flex-wrap:wrap; gap:14px; font-family:'IBM Plex Mono',monospace; font-size:12px; color:#bdb9b0; }
.lb-meta b { color:${C.amber}; }
.lb-exps { display:flex; flex-wrap:wrap; align-items:center; gap:6px; width:100%; }
.lb-exps-label { font-family:'IBM Plex Mono',monospace; font-size:11px; color:${C.muted}; }
.lb-exp { background:${C.panel2}; border:1px solid ${C.line}; color:#bdb9b0; font-family:'IBM Plex Mono',monospace;
  font-size:11px; padding:5px 9px; border-radius:6px; cursor:pointer; display:flex; flex-direction:column; line-height:1.3; }
.lb-exp i { font-style:normal; font-size:9px; color:${C.muted}; }
.lb-exp.on { border-color:${C.amber}; background:rgba(227,179,65,0.12); color:${C.amber}; }
.lb-exp.on i { color:${C.amber}; }

.primary { background:${C.amber}; color:#1a1500; border:none; font-family:'IBM Plex Mono',monospace; font-weight:600;
  font-size:13px; padding:8px 14px; border-radius:6px; cursor:pointer; }
.primary:disabled { opacity:0.5; cursor:default; }

.tabs { display:flex; gap:4px; padding:14px 26px 0; flex-wrap:wrap; }
.tabs button { background:transparent; border:none; border-bottom:2px solid transparent; color:${C.muted};
  font-family:'IBM Plex Mono',monospace; font-size:13px; padding:8px 14px; cursor:pointer; letter-spacing:0.3px; }
.tabs button:hover { color:${C.text}; }
.tab-on { color:${C.amber} !important; border-bottom-color:${C.amber} !important; }
.main { max-width:1080px; margin:0 auto; padding:26px; }
.lede { font-size:15px; line-height:1.6; color:#cfccc4; max-width:760px; margin:0 0 22px; }
.lede em { color:${C.amber}; font-style:normal; }

/* finder controls */
.controls { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:18px;
  background:${C.panel}; border:1px solid ${C.line}; border-radius:12px; padding:20px; margin-bottom:24px; }
.seg-label { font-family:'IBM Plex Mono',monospace; font-size:11px; color:${C.muted}; margin-bottom:8px; }
.seg { display:flex; flex-wrap:wrap; gap:5px; }
.seg button { flex:1; min-width:60px; background:${C.panel2}; border:1px solid ${C.line}; color:${C.muted};
  font-family:'IBM Plex Mono',monospace; font-size:12px; padding:7px 6px; border-radius:6px; cursor:pointer; }
.seg button:hover { color:${C.text}; }
.seg-on { background:${C.amber} !important; color:#1a1500 !important; border-color:${C.amber} !important; font-weight:600; }
.range { width:100%; accent-color:${C.amber}; }
.range-cap { display:flex; justify-content:space-between; font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.muted}; margin-top:2px; }
.check { display:flex; align-items:center; gap:9px; font-family:'IBM Plex Mono',monospace; font-size:12px; color:${C.muted}; cursor:pointer; grid-column:1/-1; }
.check input { accent-color:${C.amber}; width:15px; height:15px; }

/* notices */
.notice { background:rgba(227,179,65,0.08); border:1px solid rgba(227,179,65,0.3); border-radius:8px; padding:12px 14px;
  font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:#e3cf9a; margin-bottom:16px; }
.notice-ok { background:rgba(74,222,128,0.08); border-color:rgba(74,222,128,0.3); color:#a7e8c0; }

/* opportunities table */
.opp-result { margin-top:6px; }
.opp-head { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:14px;
  font-family:'IBM Plex Mono',monospace; font-size:12px; color:${C.muted}; }
.opp-table { border:1px solid ${C.line}; border-radius:10px; overflow:hidden; }
.opp-row { display:grid; grid-template-columns:0.8fr 0.6fr 0.7fr 0.7fr 0.7fr 0.6fr 2.4fr; gap:8px; padding:9px 12px;
  font-family:'IBM Plex Mono',monospace; font-size:12px; align-items:center; border-top:1px solid ${C.line}; }
.opp-th { background:${C.panel2}; color:${C.muted}; font-size:10px; border-top:none; }
.opp-sym { color:${C.amber}; font-weight:600; }
.opp-src { color:${C.cyan}; font-size:10px; text-transform:uppercase; }
.opp-exps { display:flex; flex-wrap:wrap; gap:5px; }
.opp-exps em { font-style:normal; background:${C.panel2}; border:1px solid ${C.line}; border-radius:14px; padding:2px 8px;
  font-size:10.5px; color:#bdb9b0; }
.opp-note { font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:${C.muted}; margin-top:10px; line-height:1.5; }

/* payoff stats */
.stat-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:14px 0 12px; }
.stat { background:${C.panel2}; border:1px solid ${C.line}; border-radius:8px; padding:9px 11px; display:flex; flex-direction:column; gap:4px; }
.stat span { font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.muted}; }
.stat b { font-family:'IBM Plex Mono',monospace; font-size:14px; }
.greek-row { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:10px; }
.greek-pill { background:${C.panel2}; border:1px solid ${C.line}; border-radius:8px; padding:8px 10px; display:flex; flex-direction:column; gap:2px; }
.gp-label { font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.muted}; }
.greek-pill > span:nth-child(2) { font-family:'IBM Plex Mono',monospace; font-size:14px; font-weight:600; }
.gp-unit { font-family:'IBM Plex Mono',monospace; font-size:9px; color:${C.muted}; }
.legend { display:flex; flex-wrap:wrap; gap:16px; font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:${C.muted}; }
.legend i { display:inline-block; width:14px; height:3px; border-radius:2px; margin-right:6px; vertical-align:middle; }

/* library */
.cat-block { margin-bottom:30px; }
.cat-title { font-family:'Fraunces',serif; font-size:18px; font-weight:600; color:${C.text}; margin:30px 0 14px; padding-bottom:8px; border-bottom:1px solid ${C.line}; }
.card-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px; }
.card { text-align:left; background:${C.panel}; border:1px solid ${C.line}; border-radius:10px; padding:15px; cursor:pointer; transition:transform .12s, border-color .12s; }
.card:hover { transform:translateY(-2px); border-color:${C.amber}; }
.card-name { font-family:'Fraunces',serif; font-size:16px; font-weight:600; margin-bottom:5px; }
.card-tag { font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:${C.muted}; margin-bottom:12px; min-height:26px; }
.card-stats { display:flex; gap:10px; font-family:'IBM Plex Mono',monospace; font-size:11px; color:#bdb9b0; border-top:1px solid ${C.line}; padding-top:9px; }

/* lab */
.lab-legs { background:${C.panel}; border:1px solid ${C.line}; border-radius:12px; padding:16px; margin-bottom:18px; }
.lab-head, .lab-row { display:grid; grid-template-columns:1fr 1fr 1fr 0.7fr 0.8fr 36px; gap:8px; align-items:center; }
.lab-head { font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.muted}; margin-bottom:8px; padding:0 2px; }
.lab-row { margin-bottom:8px; }
.lab-row select, .lab-row input { background:${C.panel2}; border:1px solid ${C.line}; color:${C.text};
  font-family:'IBM Plex Mono',monospace; font-size:13px; padding:7px 8px; border-radius:6px; width:100%; }
.lab-row input:disabled { opacity:0.4; }
.del { background:${C.panel2}; border:1px solid ${C.line}; color:${C.bear}; border-radius:6px; cursor:pointer; font-size:18px; line-height:1; padding:4px; }
.del:disabled { opacity:0.3; cursor:not-allowed; }
.add { background:transparent; border:1px dashed ${C.line}; color:${C.cyan}; font-family:'IBM Plex Mono',monospace;
  font-size:12px; padding:9px; border-radius:6px; cursor:pointer; width:100%; margin-top:4px; }
.add:hover { border-color:${C.cyan}; }

/* modal */
.modal-bg { position:fixed; inset:0; background:rgba(5,5,7,0.78); display:flex; align-items:flex-start; justify-content:center;
  padding:30px 16px; overflow-y:auto; z-index:50; backdrop-filter:blur(3px); }
.modal { background:${C.bg}; border:1px solid ${C.line}; border-radius:16px; max-width:680px; width:100%; padding:24px; box-shadow:0 30px 80px rgba(0,0,0,0.6); }
.modal-head { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }
.modal-cat { font-family:'IBM Plex Mono',monospace; font-size:10px; color:${C.cyan}; letter-spacing:0.5px; text-transform:uppercase; margin-bottom:4px; }
.modal-head h2 { font-family:'Fraunces',serif; font-size:26px; font-weight:600; margin:0; }
.x { background:${C.panel2}; border:1px solid ${C.line}; color:${C.text}; border-radius:8px; width:34px; height:34px; font-size:22px; line-height:1; cursor:pointer; }
.leg-table { margin:14px 0 8px; border:1px solid ${C.line}; border-radius:8px; overflow:hidden; }
.lt-head, .lt-row { display:grid; grid-template-columns:2fr 1fr 1fr 1fr; gap:8px; padding:9px 12px; font-family:'IBM Plex Mono',monospace; font-size:12px; }
.lt-head { background:${C.panel2}; color:${C.muted}; font-size:10px; }
.lt-row { border-top:1px solid ${C.line}; }
.edu { margin-top:18px; }
.edu-row { display:grid; grid-template-columns:140px 1fr; gap:14px; padding:11px 0; border-top:1px solid ${C.line}; }
.edu-k { font-family:'IBM Plex Mono',monospace; font-size:11px; color:${C.amber}; letter-spacing:0.3px; }
.edu-v { font-size:14px; line-height:1.55; color:#d6d3cb; }

/* cycles */
.phase-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; margin-bottom:14px; }
.phase { background:${C.panel}; border:1px solid ${C.line}; border-radius:10px; padding:16px; }
.phase-n { font-family:'IBM Plex Mono',monospace; font-size:13px; font-weight:600; margin-bottom:8px; }
.phase p { font-size:13.5px; line-height:1.55; color:#cfccc4; margin:0 0 10px; }
.phase-o { font-size:13px; line-height:1.5; color:#bdb9b0; border-top:1px solid ${C.line}; padding-top:10px; }
.phase-o b { color:${C.text}; }
.qa { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin-bottom:14px; }
.qa-card { background:${C.panel}; border:1px solid ${C.line}; border-radius:10px; padding:18px; }
.qa-q { font-family:'Fraunces',serif; font-size:17px; font-weight:600; margin-bottom:8px; color:${C.amber}; }
.qa-card p { font-size:14px; line-height:1.6; color:#cfccc4; margin:0; }
.vol-notes { display:flex; flex-direction:column; gap:10px; margin-bottom:20px; }
.vn { background:${C.panel}; border:1px solid ${C.line}; border-left:2px solid ${C.cyan}; border-radius:8px; padding:14px 16px; font-size:14px; line-height:1.6; color:#cfccc4; }
.vn b { color:${C.text}; }
.disclaimer { background:rgba(251,113,133,0.06); border:1px solid rgba(251,113,133,0.25); border-radius:10px; padding:15px 17px;
  font-family:'IBM Plex Mono',monospace; font-size:11.5px; line-height:1.6; color:#d8b3b6; }
.ftr { text-align:center; font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:${C.muted}; padding:24px; letter-spacing:0.3px; }

@media (max-width:560px){
  .stat-grid, .greek-row { grid-template-columns:repeat(2,1fr); }
  .edu-row { grid-template-columns:1fr; gap:4px; }
  .lab-head { display:none; }
  .lab-row { grid-template-columns:1fr 1fr; gap:6px; }
  .lab-row .del { grid-column:2; justify-self:end; }
  .opp-row { grid-template-columns:1fr 1fr; }
  .opp-th { display:none; }
}
`;
