import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { GREEN, DIM, FAINT, AMBER, BLUE, HeadCard } from './ui';
import { CHROME_TOP, CHROME_BOTTOM } from '../../layout';
import type { Category, Head, Room } from './types';

// Hydra HQ 🛰️ — swipe-deck view (roadmap A1). Each category (Command first, then each project
// room) is a full-bleed screen; swipe horizontally between them. Touch-first via native CSS
// scroll-snap (no deps, momentum on mobile), plus keyboard arrows + clickable dots. The deck
// screens ARE the A2 categories in configured order.

// room/header chrome above the deck (page header + toggle + dots) — keeps a screen within the viewport
const DECK_CHROME = 188;

export default function DeckView({
  categories,
  roomById,
  heads,
}: {
  categories: Category[];
  roomById: Map<string, Room>;
  heads: Head[];
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState(0);

  const scrollToIndex = (i: number) => {
    const el = trackRef.current;
    if (!el) return;
    const clamped = Math.max(0, Math.min(categories.length - 1, i));
    el.scrollTo({ left: clamped * el.clientWidth, behavior: 'smooth' });
  };

  // keep `active` in sync with whatever screen is snapped into view
  const onScroll = () => {
    const el = trackRef.current;
    if (!el) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== active) setActive(i);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') scrollToIndex(active + 1);
      else if (e.key === 'ArrowLeft') scrollToIndex(active - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, categories.length]);

  const screenH = `calc(100vh - ${CHROME_TOP + CHROME_BOTTOM + DECK_CHROME}px)`;

  return (
    <div>
      {/* hide the horizontal scrollbar while keeping native swipe/snap */}
      <style>{`.hq-deck-track{scrollbar-width:none;-ms-overflow-style:none}.hq-deck-track::-webkit-scrollbar{display:none}`}</style>

      <div
        ref={trackRef}
        className="hq-deck-track"
        onScroll={onScroll}
        style={{
          display: 'flex',
          overflowX: 'auto',
          scrollSnapType: 'x mandatory',
          gap: 0,
        }}
      >
        {categories.map((cat) => {
          const room = cat.room ? roomById.get(cat.room) : undefined;
          const screenHeads = heads.filter((h) => (h.category ?? h.room) === cat.id);
          const working = screenHeads.filter((h) => h.status === 'working').length;
          return (
            <section
              key={cat.id}
              style={{ flex: '0 0 100%', minWidth: '100%', scrollSnapAlign: 'start', padding: '0 4px' }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                {cat.kind === 'room' && room ? (
                  <Link to={`/hq/room/${room.id}`} style={{ color: GREEN, fontWeight: 700, fontSize: 17, textDecoration: 'none' }}>
                    {cat.label} <span style={{ fontSize: 12, opacity: 0.7 }}>↗</span>
                  </Link>
                ) : (
                  <span style={{ color: GREEN, fontWeight: 700, fontSize: 17 }}>{cat.label}</span>
                )}
                <span style={{ fontSize: 11, color: DIM }}>
                  {screenHeads.length} head{screenHeads.length === 1 ? '' : 's'}
                  {working > 0 ? ` · ${working} working` : ''}
                </span>
                {room && room.open_prs.length > 0 && (
                  <span style={{ fontSize: 10, color: AMBER, border: `1px solid ${AMBER}`, borderRadius: 3, padding: '1px 5px' }}>
                    {room.open_prs.length} open PR{room.open_prs.length === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              <div style={{ height: screenH, overflowY: 'auto', paddingRight: 4 }}>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', alignContent: 'start' }}>
                  {screenHeads.map((h) => (
                    <HeadCard key={h.name} head={h} />
                  ))}
                </div>
              </div>
            </section>
          );
        })}
      </div>

      {/* dots + arrows */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14, marginTop: 12 }}>
        <button type="button" aria-label="previous" onClick={() => scrollToIndex(active - 1)} style={navBtn(active > 0)}>‹</button>
        <div style={{ display: 'flex', gap: 8 }}>
          {categories.map((cat, i) => (
            <button
              key={cat.id}
              type="button"
              aria-label={cat.label}
              title={cat.label}
              onClick={() => scrollToIndex(i)}
              style={{
                width: i === active ? 10 : 8,
                height: i === active ? 10 : 8,
                borderRadius: '50%',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                background: i === active ? GREEN : FAINT,
                boxShadow: i === active ? `0 0 6px ${GREEN}` : 'none',
              }}
            />
          ))}
        </div>
        <button type="button" aria-label="next" onClick={() => scrollToIndex(active + 1)} style={navBtn(active < categories.length - 1)}>›</button>
      </div>
      <div style={{ textAlign: 'center', fontSize: 10, color: DIM, marginTop: 6 }}>
        {categories[active]?.label} · {active + 1}/{categories.length} · swipe or ← →
      </div>
    </div>
  );
}

function navBtn(enabled: boolean): React.CSSProperties {
  return {
    background: 'transparent',
    color: enabled ? BLUE : FAINT,
    border: 'none',
    fontSize: 22,
    lineHeight: 1,
    cursor: enabled ? 'pointer' : 'default',
    padding: '0 4px',
  };
}
