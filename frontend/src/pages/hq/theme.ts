// HQ console theming — the data model + resolver (slice T1). Two SIDES per console: `you`
// (Schyler's own messages) and `agents` (the head's messages); each side has a font, a text
// colour, and a highlight colour. Values resolve per-field, each falling back independently:
//
//     agent-override  >  project-config  >  global-default
//
// Persisted server-side (Redis `hq:theme`, see backend /api/hq/theme) so it follows Schyler
// across phone + desktop; localStorage caches the last-known blob for instant first paint.
import { C } from './render/tokens';

export type Side = 'you' | 'agents';
export type SideTheme = { font: string; text: string; hl: string };   // font = a FONTS id; colours = hex
export type PartialSide = Partial<SideTheme>;
export type ProjectTheme = {
  you?: PartialSide;
  agents?: PartialSide;
  byAgent?: Record<string, { you?: PartialSide; agents?: PartialSide }>;
};
export type ThemeConfig = {
  global: { you: SideTheme; agents: SideTheme };
  projects: Record<string, ProjectTheme>;
};

// Defaults reproduce TODAY's look exactly, so T1 ships the plumbing with zero visual change:
// your messages stay cerulean MedievalSharp, the agents' stay refined-sans ink. The green
// accent (used by the T4 highlighter) is the shared default highlight for both sides.
export const DEFAULT_THEME: ThemeConfig = {
  global: {
    you: { font: 'medievalsharp', text: C.cerulean, hl: C.green },
    agents: { font: 'system', text: C.ink, hl: C.green },
  },
  projects: {},
};

// Resolve one side's full theme for a given (project, head). Every field independently walks
// agent → project → global, so e.g. a per-head font can sit on top of a project-wide colour.
// SECURITY: colours are validated here (the chokepoint where a value becomes a `style`), so a
// config value — even one hand-poked into Redis, though it's owner-only behind Access — can never
// inject CSS. Fonts are likewise allow-listed at apply time via fonts.ts `fontStack` (an unknown
// id falls back to the system stack), so only curated faces ever reach the DOM.
export function resolveSide(cfg: ThemeConfig, room: string | undefined, head: string | undefined, side: Side): SideTheme {
  const g = cfg.global[side];
  const proj = (room && cfg.projects?.[room]) || undefined;
  const p = (proj?.[side] as PartialSide) || {};
  const a = ((head && proj?.byAgent?.[head]?.[side]) as PartialSide) || {};
  return {
    font: a.font ?? p.font ?? g.font,                 // fontStack() allow-lists this at apply time
    text: safeColor(a.text ?? p.text ?? g.text, g.text),
    hl: safeColor(a.hl ?? p.hl ?? g.hl, g.hl),
  };
}

// A colour is only accepted if it's a hex (#rgb/#rgba/#rrggbb/#rrggbbaa) or rgb()/rgba() literal —
// nothing else can be written into a style. Anything off-pattern falls back to a known-good token.
const _HEX_RE = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const _RGB_RE = /^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/;
export function isColor(v: unknown): v is string {
  return typeof v === 'string' && (_HEX_RE.test(v) || _RGB_RE.test(v));
}
export function safeColor(v: unknown, fallback: string): string {
  return isColor(v) ? v : fallback;
}

// Curated colour swatches for the palette's text + highlight pickers (a custom hex input rides
// alongside). Drawn from the design tokens so the menu stays on-brand.
export const SWATCHES = [
  C.green, C.cerulean, C.blue, C.amber, C.violet, C.red,
  '#ff8fd0', '#9bf0bb', C.ink, '#ffffff', C.muted, '#5f7d68',
];

// Immutable edit of one (scope, side, field): scope is the whole project (head=null) or a single
// head override (head=name). Returns a new config; the provider persists it cross-device.
export function setSideField(
  cfg: ThemeConfig, room: string, head: string | null, side: Side, field: keyof SideTheme, value: string,
): ThemeConfig {
  const projects = { ...cfg.projects };
  const proj: ProjectTheme = { ...(projects[room] || {}) };
  if (head) {
    const byAgent = { ...(proj.byAgent || {}) };
    const agent = { ...(byAgent[head] || {}) };
    agent[side] = { ...(agent[side] || {}), [field]: value };
    byAgent[head] = agent;
    proj.byAgent = byAgent;
  } else {
    proj[side] = { ...((proj[side] as PartialSide) || {}), [field]: value };
  }
  projects[room] = proj;
  return { ...cfg, projects };
}

// Drop the override object for one (scope, side) so it falls back to the next level up.
export function clearSide(cfg: ThemeConfig, room: string, head: string | null, side: Side): ThemeConfig {
  const projects = { ...cfg.projects };
  const proj: ProjectTheme = { ...(projects[room] || {}) };
  if (head) {
    const byAgent = { ...(proj.byAgent || {}) };
    const agent = { ...(byAgent[head] || {}) };
    delete agent[side];
    if (Object.keys(agent).length) byAgent[head] = agent; else delete byAgent[head];
    proj.byAgent = byAgent;
  } else {
    delete proj[side];
  }
  projects[room] = proj;
  return { ...cfg, projects };
}

// A defensive merge of a possibly-partial/old server blob onto the defaults, so a missing key
// (or a brand-new field added in a later slice) never crashes the resolver.
export function normalizeTheme(raw: unknown): ThemeConfig {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Partial<ThemeConfig>;
  const side = (s: Partial<SideTheme> | undefined, d: SideTheme): SideTheme => ({
    font: s?.font ?? d.font, text: s?.text ?? d.text, hl: s?.hl ?? d.hl,
  });
  return {
    global: {
      you: side(r.global?.you, DEFAULT_THEME.global.you),
      agents: side(r.global?.agents, DEFAULT_THEME.global.agents),
    },
    projects: (r.projects && typeof r.projects === 'object' ? r.projects : {}) as Record<string, ProjectTheme>,
  };
}
