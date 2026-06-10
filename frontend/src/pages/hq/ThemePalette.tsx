import { useState } from 'react';
import { C } from './render/tokens';
import { FONTS, fontStack } from './fonts';
import { useThemeConfig } from './ThemeProvider';
import { SWATCHES, clearSide, isColor, setSideField } from './theme';
import type { Side } from './theme';

// ThemePalette (T3) — the 🎨 menu in the console's project header. Pick, per SIDE (You = your
// messages, Agents = the head's), a font + text colour + highlight colour, scoped to the whole
// project or to a single head. Writes go through the ThemeProvider (optimistic localStorage +
// debounced server PUT), so a tweak on the phone shows on the desktop. Refined-premium, thumb-driven.
//
// Safe by construction: fonts come only from the curated FONTS allow-list; colours only from the
// swatch palette or a native <input type=color> (always #rrggbb), and the resolver re-validates
// every colour before it becomes a style. A value here can never inject CSS.

export default function ThemePalette({ room, heads }: { room: string; heads: string[] }) {
  const { cfg, resolve, update } = useThemeConfig();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState('');        // '' = whole project; otherwise a head name
  const [side, setSide] = useState<Side>('agents');

  const head = scope || null;
  const cur = resolve(room, head || undefined, side);   // resolved font/text/hl for the active target
  const setField = (field: 'font' | 'text' | 'hl', value: string) =>
    update(setSideField(cfg, room, head, side, field, value));

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} title="Theme" aria-label="Theme"
        style={{ ...iconBtn, color: C.green, borderColor: C.line2 }}>🎨</button>
    );
  }

  return (
    <>
      {/* tap-away backdrop */}
      <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 1400 }} />
      <div style={{ position: 'relative', zIndex: 1401 }}>
        <button type="button" onClick={() => setOpen(false)} title="Theme" aria-label="Close theme"
          style={{ ...iconBtn, color: C.bg, background: C.green, borderColor: C.green }}>🎨</button>

        <div style={panel}>
          {/* header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ fontFamily: C.sans, fontSize: 13, fontWeight: 700, color: C.ink }}>🎨 Theme</span>
            <span style={{ fontFamily: C.mono, fontSize: 10, color: C.faint, marginLeft: 'auto' }}>tap away to close</span>
          </div>

          {/* scope: whole project or one head */}
          <Label>Applies to</Label>
          <select value={scope} onChange={(e) => setScope(e.target.value)}
            style={{ width: '100%', background: C.raised, color: C.ink, border: `1px solid ${C.line2}`, borderRadius: 8, fontFamily: C.mono, fontSize: 12, padding: '7px 9px', marginBottom: 10 }}>
            <option value="">Whole project</option>
            {heads.map((h) => <option key={h} value={h}>↳ {h} only</option>)}
          </select>

          {/* side: You vs Agents */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            {(['you', 'agents'] as Side[]).map((s) => (
              <button key={s} type="button" onClick={() => setSide(s)}
                style={{
                  flex: 1, fontFamily: C.mono, fontSize: 12, textTransform: 'none', letterSpacing: 0,
                  padding: '7px 0', borderRadius: 8, cursor: 'pointer',
                  border: `1px solid ${side === s ? C.green : C.line2}`,
                  background: side === s ? 'rgba(34,255,106,.10)' : C.raised,
                  color: side === s ? C.green : C.muted,
                }}>{s === 'you' ? 'You' : 'Agents'}</button>
            ))}
          </div>

          {/* font */}
          <Label>Font</Label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 168, overflowY: 'auto', marginBottom: 12 }}>
            {FONTS.map((f) => {
              const active = cur.font === f.id;
              return (
                <button key={f.id} type="button" onClick={() => setField('font', f.id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                    padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textTransform: 'none', letterSpacing: 0,
                    border: `1px solid ${active ? C.green : C.line}`,
                    background: active ? 'rgba(34,255,106,.08)' : C.raised,
                  }}>
                  <span style={{ fontFamily: fontStack(f.id), fontSize: 16, color: active ? C.green : C.ink, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.label}</span>
                  <span style={{ fontFamily: fontStack(f.id), fontSize: 13, color: C.faint, marginLeft: 'auto', whiteSpace: 'nowrap' }}>Ag 0$</span>
                  {active && <span style={{ color: C.green, flex: '0 0 auto' }}>✓</span>}
                </button>
              );
            })}
          </div>

          {/* text colour */}
          <Label>Text colour</Label>
          <ColorRow value={cur.text} onPick={(v) => setField('text', v)} />

          {/* highlight colour */}
          <Label>Highlight</Label>
          <ColorRow value={cur.hl} onPick={(v) => setField('hl', v)} />

          {/* live preview */}
          <div style={{ marginTop: 12, padding: '9px 11px', borderRadius: 9, border: `1px solid ${C.line}`, background: C.panel2 }}>
            <span style={{ fontFamily: fontStack(cur.font), fontSize: 14, color: cur.text }}>
              Ship <b style={{ color: cur.hl }}>F6</b> — <b style={{ color: cur.hl }}>AAPL</b> $187 looks sharp
            </span>
          </div>

          {/* reset this (scope, side) */}
          <button type="button" onClick={() => update(clearSide(cfg, room, head, side))}
            style={{ marginTop: 10, width: '100%', fontFamily: C.mono, fontSize: 11, textTransform: 'none', letterSpacing: 0, padding: '7px 0', borderRadius: 8, cursor: 'pointer', border: `1px solid ${C.line2}`, background: 'transparent', color: C.muted }}>
            ↺ Reset {side === 'you' ? 'You' : 'Agents'}{head ? ` · ${head}` : ''} to default
          </button>
        </div>
      </div>
    </>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: C.mono, fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: C.faint, marginBottom: 6 }}>{children}</div>;
}

function ColorRow({ value, onPick }: { value: string; onPick: (v: string) => void }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 12 }}>
      {SWATCHES.map((sw) => {
        const active = value.toLowerCase() === sw.toLowerCase();
        return (
          <button key={sw} type="button" onClick={() => onPick(sw)} title={sw} aria-label={sw}
            style={{ width: 22, height: 22, padding: 0, borderRadius: 6, cursor: 'pointer', background: sw, border: `2px solid ${active ? C.ink : 'transparent'}`, boxShadow: active ? `0 0 0 1px ${C.bg}` : 'none' }} />
        );
      })}
      {/* custom hex via the native picker (works on iOS); only ever yields #rrggbb */}
      <label title="Custom colour" style={{ width: 24, height: 24, borderRadius: 6, border: `1px dashed ${C.line2}`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', position: 'relative', overflow: 'hidden' }}>
        <span style={{ fontSize: 12, color: C.muted }}>＋</span>
        <input type="color" value={isColor(value) && /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#22ff6a'}
          onChange={(e) => onPick(e.target.value)}
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
      </label>
    </div>
  );
}

const iconBtn: React.CSSProperties = {
  fontSize: 15, lineHeight: 1, padding: '5px 8px', borderRadius: 8, border: '1px solid',
  background: 'transparent', cursor: 'pointer',
};

const panel: React.CSSProperties = {
  position: 'absolute', top: 'calc(100% + 8px)', right: 0, zIndex: 1401,
  width: 'min(320px, 92vw)', maxHeight: '78vh', overflowY: 'auto',
  background: C.panel, border: `1px solid ${C.line2}`, borderRadius: 14,
  padding: 14, boxShadow: '0 12px 44px rgba(0,0,0,.55)',
};
