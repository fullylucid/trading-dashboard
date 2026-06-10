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
export function resolveSide(cfg: ThemeConfig, room: string | undefined, head: string | undefined, side: Side): SideTheme {
  const g = cfg.global[side];
  const proj = (room && cfg.projects?.[room]) || undefined;
  const p = (proj?.[side] as PartialSide) || {};
  const a = ((head && proj?.byAgent?.[head]?.[side]) as PartialSide) || {};
  return {
    font: a.font ?? p.font ?? g.font,
    text: a.text ?? p.text ?? g.text,
    hl: a.hl ?? p.hl ?? g.hl,
  };
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
