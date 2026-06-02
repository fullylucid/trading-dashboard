// Plain-English teaching content for the Options Engine — Greeks + strategies + metrics,
// written for someone learning to SELL options (theta/vega/assignment framing).

export type GreekDoc = { sym: string; name: string; plain: string; seller: string };

export const GREEKS: GreekDoc[] = [
  {
    sym: 'Δ', name: 'Delta',
    plain: 'How much the option price moves per $1 move in the stock — and roughly its probability of finishing in-the-money. A 0.30 call ≈ 30% chance ITM.',
    seller: 'As a seller, delta is your directional risk AND your assignment odds. Sell a 0.30-delta put → ~30% chance you get assigned the shares. Lower delta = safer, less premium.',
  },
  {
    sym: 'Θ', name: 'Theta',
    plain: 'Time decay — how much value the option bleeds each day, just from time passing.',
    seller: 'This is the seller’s engine. When you SELL, theta is positive for you: every day you keep more of the premium. It’s fastest in the final weeks before expiration.',
  },
  {
    sym: 'V', name: 'Vega',
    plain: 'Sensitivity to implied volatility (IV). Higher vega = the price swings more when IV changes.',
    seller: 'Sellers are SHORT vega — you profit when IV falls. The play: sell when IV is rich and let it deflate (e.g. the “IV crush” after earnings). Rising IV hurts a short option.',
  },
  {
    sym: 'Γ', name: 'Gamma',
    plain: 'How fast delta itself changes as the stock moves. High near the strike, near expiration.',
    seller: 'Sellers are SHORT gamma — your risk accelerates as the stock nears your strike close to expiry. It’s why short options near-the-money in the last days are dangerous.',
  },
  {
    sym: 'IV', name: 'Implied Volatility',
    plain: 'The market’s expected volatility baked into the price — the fuel behind premium size.',
    seller: 'High IV = fat premiums (great to sell — but it’s high for a reason). The seller’s mantra: sell rich, buy cheap. Compare a name’s IV to its own history before selling.',
  },
];

export const STRATEGIES: Record<string, { title: string; what: string }> = {
  spreads: {
    title: 'Vertical spreads (defined-risk directional)',
    what: 'Buy one option and sell another further out, same expiration. A debit spread (bull call / bear put) is a capped-risk directional BET — cheaper than a long option, but max gain is capped too. A credit spread (bull put / bear call) SELLS the spread for income: max profit = the credit, max loss = the width minus credit, and POP is usually high.',
  },
  cash_secured_put: {
    title: 'Cash-Secured Put (get paid to buy lower)',
    what: 'You SELL a put and set aside the cash to buy 100 shares if assigned. You’re paid a premium to agree to buy the stock cheaper. Keep the full premium if it stays above the strike; if it drops below, you buy at the strike — your real cost = strike − premium. Best on names you’d happily own. Theta and falling IV both work for you.',
  },
  covered_call: {
    title: 'Covered Call (get paid to cap upside)',
    what: 'You OWN 100 shares and sell a call against them. You’re paid to cap your upside: keep the premium (plus any gain up to the strike) if it stays below; if it rises past the strike, your shares get called away there. Income on stock you already hold, with a small downside cushion from the premium.',
  },
  iron_condor: {
    title: 'Iron Condor (range-bound income, defined risk)',
    what: 'Sell an OTM put spread AND an OTM call spread at once. You collect two credits and profit if the stock stays in the range between your short strikes through expiration. Max profit = the total credit; max loss = the wider wing minus credit — fully defined. The premier neutral, “I think it goes nowhere” trade. Loves high IV and theta; you want a calm, range-bound stock.',
  },
  strangle: {
    title: 'Strangle (volatility play)',
    what: 'A call and a put at different OTM strikes. SHORT (sell both) = collect premium betting the stock stays in a range — high POP but UNDEFINED risk if it runs (only for stocks you can babysit). LONG (buy both) = cheap bet on a BIG move either direction (earnings, catalysts); you lose the premium if it sits still. Long strangle is long vega — it wants IV to rise.',
  },
  wheel: {
    title: 'The Wheel (a repeating income loop)',
    what: 'Sell a cash-secured put on a stock you’d happily own. If it expires worthless, keep the premium and repeat. If you get assigned, you now own 100 shares at the strike — so you sell covered calls against them. If those get called away, you’re back to selling puts. Around and around, collecting premium at every step. The engine below checks whether you hold the shares and tells you exactly which leg you’re on.',
  },
  straddle: {
    title: 'Straddle (pure move bet, at-the-money)',
    what: 'A call and a put at the SAME at-the-money strike. LONG (buy both) = a pure bet on a big move in either direction — max risk is the premium, profit if it moves past either breakeven. Expensive (two ATM options), so the move has to be real. SHORT (sell both) = maximum premium for a stock you’re sure won’t move — undefined risk, advanced only.',
  },
};

export const METRICS: Record<string, string> = {
  POP: 'Probability of Profit — the model’s chance you keep the premium / finish past breakeven. Higher POP usually means smaller premium.',
  'annual yield': 'Premium as a % of the capital you tie up, annualized. Great for comparing trades — but note short-dated, high-IV options annualize to wild numbers that aren’t repeatable.',
  cushion: 'How far the stock can move against you before you start losing (CSP: discount below spot to your breakeven; CC: the premium’s downside cover).',
  breakeven: 'The stock price where the trade breaks even at expiration.',
  'R:R': 'Reward-to-risk — max profit divided by max loss.',
};
