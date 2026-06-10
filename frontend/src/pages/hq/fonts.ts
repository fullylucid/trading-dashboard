// Curated font roster for the console theming system. T1 ships the three faces already present
// in the app (so defaults render with no new assets); T2 self-hosts the rest as woff2 (Inter,
// EB Garamond, VT323 — same @font-face/preload pattern as MedievalSharp) and adds them here.
// Every entry must render cross-device incl. iOS — that's why the characterful faces are
// self-hosted, not CDN- or system-name-dependent.
import { C } from './render/tokens';

export type FontDef = { id: string; label: string; stack: string; kind: 'sans' | 'mono' | 'serif' | 'display' | 'system' };

export const FONTS: FontDef[] = [
  { id: 'system', label: 'System', stack: C.sans, kind: 'system' },
  { id: 'inter', label: 'Inter', stack: "'Inter', -apple-system, sans-serif", kind: 'sans' },
  { id: 'mono', label: 'JetBrains Mono', stack: C.mono, kind: 'mono' },
  { id: 'vt323', label: 'VT323', stack: "'VT323', 'JetBrains Mono', monospace", kind: 'mono' },
  { id: 'ebgaramond', label: 'EB Garamond', stack: "'EB Garamond', Georgia, serif", kind: 'serif' },
  { id: 'medievalsharp', label: 'MedievalSharp', stack: "'MedievalSharp', fantasy", kind: 'display' },
];

const _byId = new Map(FONTS.map((f) => [f.id, f]));

// Resolve a font id -> a CSS font-family stack; unknown/legacy ids fall back to the clean sans.
export function fontStack(id: string | undefined): string {
  return (id && _byId.get(id)?.stack) || C.sans;
}
