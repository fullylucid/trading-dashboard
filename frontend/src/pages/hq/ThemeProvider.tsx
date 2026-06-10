import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { DEFAULT_THEME, normalizeTheme, resolveSide } from './theme';
import type { Side, SideTheme, ThemeConfig } from './theme';

// ThemeProvider — loads the console theme config once (localStorage cache for instant paint,
// then the server blob from /api/hq/theme), exposes a per-(project,head,side) resolver, and an
// `update` that writes through to both localStorage and the server so a change on the phone
// shows up on the desktop. T1 wires the data; the palette UI that calls `update` lands in T3.

const CACHE_KEY = 'hq.theme';

type ThemeCtx = {
  cfg: ThemeConfig;
  resolve: (room: string | undefined, head: string | undefined, side: Side) => SideTheme;
  update: (next: ThemeConfig) => void;
};

const Ctx = createContext<ThemeCtx | null>(null);

function readCache(): ThemeConfig {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (raw) return normalizeTheme(JSON.parse(raw));
  } catch { /* private mode / bad json */ }
  return DEFAULT_THEME;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<ThemeConfig>(readCache);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // reconcile with the server on mount (cross-device source of truth)
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch('/api/hq/theme');
        if (!r.ok || !alive) return;
        const d = await r.json();
        if (d && d.theme) {
          const norm = normalizeTheme(d.theme);
          setCfg(norm);
          try { localStorage.setItem(CACHE_KEY, JSON.stringify(norm)); } catch { /* ignore */ }
        }
      } catch { /* keep cache */ }
    })();
    return () => { alive = false; };
  }, []);

  const update = useCallback((next: ThemeConfig) => {
    setCfg(next);                                            // optimistic
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
    if (saveTimer.current) clearTimeout(saveTimer.current);  // debounce rapid swatch drags
    saveTimer.current = setTimeout(() => {
      fetch('/api/hq/theme', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next),
      }).catch(() => { /* localStorage already holds it; next load reconciles */ });
    }, 350);
  }, []);

  const value = useMemo<ThemeCtx>(() => ({
    cfg,
    resolve: (room, head, side) => resolveSide(cfg, room, head, side),
    update,
  }), [cfg, update]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// Resolve one side's theme for a console. Safe outside a provider too (returns the default),
// so a stray HeadConsole render never crashes.
export function useSideTheme(room: string | undefined, head: string | undefined, side: Side): SideTheme {
  const ctx = useContext(Ctx);
  if (!ctx) return resolveSide(DEFAULT_THEME, room, head, side);
  return ctx.resolve(room, head, side);
}

// Full context for the palette UI (T3).
export function useThemeConfig(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useThemeConfig must be used within <ThemeProvider>');
  return ctx;
}
