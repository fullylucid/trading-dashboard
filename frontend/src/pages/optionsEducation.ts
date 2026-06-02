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
};

export const METRICS: Record<string, string> = {
  POP: 'Probability of Profit — the model’s chance you keep the premium / finish past breakeven. Higher POP usually means smaller premium.',
  'annual yield': 'Premium as a % of the capital you tie up, annualized. Great for comparing trades — but note short-dated, high-IV options annualize to wild numbers that aren’t repeatable.',
  cushion: 'How far the stock can move against you before you start losing (CSP: discount below spot to your breakeven; CC: the premium’s downside cover).',
  breakeven: 'The stock price where the trade breaks even at expiration.',
  'R:R': 'Reward-to-risk — max profit divided by max loss.',
};
