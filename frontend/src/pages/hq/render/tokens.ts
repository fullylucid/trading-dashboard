// Refined "premium terminal-green" design tokens for the HQ Console (E1; the aesthetic Schyler
// locked: sans-for-prose + mono-for-code/status, #22ff6a as a restrained accent not a flood,
// subtle glow, Linear/Vercel/Stripe-tier craft). E2 systematizes these across HQ; for now they
// live with the console renderer.
export const C = {
  bg: '#070a07',
  panel: '#0c110c',
  panel2: '#0f150f',
  raised: '#121a12',
  line: 'rgba(0,255,65,.14)',
  line2: 'rgba(0,255,65,.28)',
  green: '#22ff6a',
  greenDim: 'rgba(120,230,160,.62)',
  faint: 'rgba(120,200,150,.34)',
  ink: '#d7f7e2',
  muted: '#7fae90',
  blue: '#5cc8ff',
  amber: '#ffcf5c',
  red: '#ff6b6b',
  violet: '#b79bff',
  // user bubble (blue-tinted)
  userBg: 'linear-gradient(180deg,rgba(92,200,255,.12),rgba(92,200,255,.06))',
  userLine: 'rgba(92,200,255,.32)',
  userInk: '#dcf0ff',
  // Schyler's OWN outgoing-message text: cerulean MedievalSharp (self-hosted woff2, OFL — see
  // index.css @font-face). Renders cross-device incl. iOS; `fantasy` as a last-resort fallback.
  cerulean: '#007BA7',           // tune-able
  userFont: "'MedievalSharp', fantasy",
  // syntax-highlight palette
  synKey: '#ff8fd0',
  synStr: '#9be39b',
  synCom: '#5f7d68',
  synFn: '#7cc7ff',
  synNum: '#ffcf5c',
  diffAddBg: 'rgba(34,255,106,.10)',
  diffAddInk: '#9bf0bb',
  diffDelBg: 'rgba(255,107,107,.10)',
  diffDelInk: '#ffadad',
  mono: "'SFMono-Regular',ui-monospace,'JetBrains Mono',Consolas,monospace",
  sans: "-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif",
} as const;
