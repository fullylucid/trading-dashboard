import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import HeadConsole from './HeadConsole';
import RoadmapCard from './RoadmapCard';
import ThemePalette from './ThemePalette';
import { GREEN, DIM, FAINT, BLUE, AMBER, card, StatusDot } from './ui';
import { CHROME_TOP } from '../../layout';
import type { Category, Fleet, Head } from './types';

// HQ Console — fleet navigation (CONSOLE.md Slice 3). A project dropdown (the A2 categories:
// Command / trading-dashboard / cyborganic / …) selects a set of heads; you swipe between
// those heads, each screen a FULL console (HeadConsole = Slice-1 chat + Slice-2 composer).
// Evolves the A1 deck: same scroll-snap swipe, but each screen is a live console — and only the
// on-screen one polls. Bus/external heads (no local transcript/pane) are excluded.

const PROJECT_KEY = 'hq.console.project';
const DECK_CHROME = 118; // top bar (dropdown) + dots row below the swipe area

export default function ConsoleDeck() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [project, setProject] = useState<string>(() =>
    (typeof localStorage !== 'undefined' && localStorage.getItem(PROJECT_KEY)) || '',
  );
  const [active, setActive] = useState(0);
  const trackRef = useRef<HTMLDivElement | null>(null);

  // fleet (categories + heads) — refreshed slowly; the per-head consoles do their own live-tail
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch('/api/hq/fleet');
        if (r.ok && alive) setFleet(await r.json());
      } catch { /* keep last */ }
    };
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const categories: Category[] = fleet?.categories ?? [];
  const heads: Head[] = fleet?.heads ?? [];
  // default the project once categories arrive
  const selected = project || categories[0]?.id || '';
  // Director/lead first (the project's owner loads first when you open the deck), then alphabetical.
  // The collector already ranks the room this way; honour it here instead of flat alpha.
  const roleRank = (h: Head) => (h.role === 'director' ? 0 : h.role === 'lead' ? 1 : 2);
  const projectHeads = heads
    .filter((h) => (h.category ?? h.room) === selected && h.source !== 'bus')
    .sort((a, b) => roleRank(a) - roleRank(b) || a.name.localeCompare(b.name));

  const changeProject = (id: string) => {
    setProject(id);
    setActive(0);
    try { localStorage.setItem(PROJECT_KEY, id); } catch { /* private mode */ }
    if (trackRef.current) trackRef.current.scrollLeft = 0;
  };

  const scrollToIndex = (i: number) => {
    const el = trackRef.current;
    if (!el) return;
    const clamped = Math.max(0, Math.min(projectHeads.length - 1, i));
    el.scrollTo({ left: clamped * el.clientWidth, behavior: 'smooth' });
  };
  const onScroll = () => {
    const el = trackRef.current;
    if (!el) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== active) setActive(i);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT')) return; // don't hijack the composer
      if (e.key === 'ArrowRight') scrollToIndex(active + 1);
      else if (e.key === 'ArrowLeft') scrollToIndex(active - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, projectHeads.length]);

  // no CHROME_BOTTOM here — the market ticker is hidden on /hq, so its clearance would be dead space
  const screenH = `calc(100vh - ${CHROME_TOP + DECK_CHROME}px)`;

  return (
    <div style={{ maxWidth: 980, margin: '0 auto', padding: '0 10px', fontFamily: 'monospace', color: GREEN }}>
      <style>{`.hq-console-track{scrollbar-width:none;-ms-overflow-style:none}.hq-console-track::-webkit-scrollbar{display:none}`}</style>
      {selected && <RoadmapCard roomId={selected} label={categories.find((c) => c.id === selected)?.label} />}

      {/* top bar: project dropdown + back */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 2px', flexWrap: 'wrap' }}>
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 14 }}>🛰️ Console</span>
        <select
          value={selected}
          onChange={(e) => changeProject(e.target.value)}
          style={{ background: '#000', color: GREEN, border: `1px solid ${FAINT}`, borderRadius: 4, fontFamily: 'monospace', fontSize: 13, padding: '4px 8px' }}
        >
          {categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          {selected && <ThemePalette room={selected} heads={projectHeads.map((h) => h.name)} />}
          <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>← fleet</Link>
        </div>
      </div>

      {projectHeads.length === 0 ? (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center', marginTop: 10 }}>
          {fleet ? 'no drivable heads in this project' : 'loading…'}
        </div>
      ) : (
        <>
          <div ref={trackRef} className="hq-console-track" onScroll={onScroll}
               style={{ display: 'flex', overflowX: 'auto', scrollSnapType: 'x mandatory' }}>
            {projectHeads.map((h, i) => (
              <section key={h.name} style={{ flex: '0 0 100%', minWidth: '100%', scrollSnapAlign: 'start', padding: '0 4px', height: screenH, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flex: '0 0 auto' }}>
                  <StatusDot status={h.status} />
                  <Link to={`/hq/console/${h.name}`} style={{ color: GREEN, fontWeight: 700, fontSize: 15, textDecoration: 'none' }}>{h.name}</Link>
                  {h.branch && <span style={{ fontSize: 10, color: DIM }}>⎇ {h.branch}</span>}
                </div>
                <div style={{ flex: 1, minHeight: 0 }}>
                  {/* only the visible screen live-tails */}
                  <HeadConsole name={h.name} room={selected} active={i === active} />
                </div>
              </section>
            ))}
          </div>

          {/* dots + arrows */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, marginTop: 8 }}>
            <button type="button" aria-label="previous" onClick={() => scrollToIndex(active - 1)}
                    style={navBtn(active > 0)}>‹</button>
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', justifyContent: 'center', maxWidth: '70%' }}>
              {projectHeads.map((h, i) => (
                <button key={h.name} type="button" title={h.name} aria-label={h.name} onClick={() => scrollToIndex(i)}
                        style={{ width: i === active ? 9 : 7, height: i === active ? 9 : 7, borderRadius: '50%', border: 'none', padding: 0, cursor: 'pointer', background: i === active ? GREEN : FAINT, boxShadow: i === active ? `0 0 6px ${GREEN}` : 'none' }} />
              ))}
            </div>
            <button type="button" aria-label="next" onClick={() => scrollToIndex(active + 1)}
                    style={navBtn(active < projectHeads.length - 1)}>›</button>
          </div>
          <div style={{ textAlign: 'center', fontSize: 10, color: DIM, marginTop: 4 }}>
            {projectHeads[active]?.name} · {active + 1}/{projectHeads.length} · swipe or ← →
          </div>
        </>
      )}
    </div>
  );
}

function navBtn(enabled: boolean): React.CSSProperties {
  return { background: 'transparent', color: enabled ? BLUE : FAINT, border: 'none', fontSize: 22, lineHeight: 1, cursor: enabled ? 'pointer' : 'default', padding: '0 4px' };
}
