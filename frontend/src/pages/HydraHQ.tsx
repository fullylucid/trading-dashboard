import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import { GREEN, DIM, AMBER, RED, BLUE, card, fmtAge, HeadCard, Pill } from './hq/ui';
import ActivityFeed from './hq/ActivityFeed';
import type { Category, Fleet, Head, Room } from './hq/types';

// Hydra HQ 🛰️ — fleet overview. Polls /api/hq/fleet (a host-collector snapshot served from
// Redis) and renders one card per head, grouped by CATEGORY (the layer above per-repo rooms;
// roadmap A2). The Command category (conductor + hq head) sorts first; project categories are
// their rooms and link to the per-room detail view. See ~/hydra-hq/DESIGN.md.

function CategorySection({ cat, room, heads }: { cat: Category; room?: Room; heads: Head[] }) {
  const working = heads.filter((h) => h.status === 'working').length;
  const titleStyle: React.CSSProperties = { color: GREEN, fontWeight: 700, fontSize: 15, textDecoration: 'none' };
  return (
    <section style={{ marginBottom: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        {cat.kind === 'room' && room ? (
          <Link to={`/hq/room/${room.id}`} style={titleStyle}>
            {cat.label} <span style={{ fontSize: 11, opacity: 0.7 }}>↗</span>
          </Link>
        ) : (
          <span style={titleStyle}>{cat.label}</span>
        )}
        {room?.repo && <span style={{ fontSize: 11, color: DIM }}>{room.repo}</span>}
        <span style={{ fontSize: 11, color: DIM }}>
          {heads.length} head{heads.length === 1 ? '' : 's'}
          {working > 0 ? ` · ${working} working` : ''}
        </span>
        {room && room.open_prs.length > 0 && (
          <Pill color={AMBER}>{room.open_prs.length} open PR{room.open_prs.length === 1 ? '' : 's'}</Pill>
        )}
      </div>
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
        {heads.map((h) => (
          <HeadCard key={h.name} head={h} />
        ))}
      </div>
    </section>
  );
}

// Group heads by category when the collector provides one; otherwise fall back to the rooms
// (older snapshots), so the overview keeps working across a collector/frontend version skew.
function categoriesOf(fleet: Fleet | null): Category[] {
  if (fleet?.categories?.length) return fleet.categories;
  return (fleet?.rooms ?? []).map((r) => ({ id: r.id, label: r.name, kind: 'room', room: r.id, heads: r.heads }));
}

export default function HydraHQ() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const r = await fetch('/api/hq/fleet');
        if (!r.ok) throw new Error('bad response');
        if (active) {
          setFleet(await r.json());
          setErr(false);
        }
      } catch {
        if (active) setErr(true);
      }
    };
    load();
    const id = setInterval(load, 7000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const rooms = fleet?.rooms ?? [];
  const heads = fleet?.heads ?? [];
  const categories = categoriesOf(fleet);
  const roomById = new Map(rooms.map((r) => [r.id, r]));
  const collectorOffline = fleet != null && fleet.available === false;
  const totalWorking = heads.filter((h) => h.status === 'working').length;
  const headsOf = (cat: Category) => heads.filter((h) => (h.category ?? h.room) === cat.id);

  const subtitle =
    fleet == null && !err
      ? 'loading fleet…'
      : collectorOffline
        ? 'collector offline — no snapshot in Redis yet'
        : `${heads.length} heads · ${rooms.length} rooms · ${totalWorking} working` +
          (fleet?.generated_at ? ` · updated ${fmtAge(Math.round(Date.now() / 1000 - fleet.generated_at))}` : '');

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 16px 40px', fontFamily: 'monospace', color: GREEN }}>
      <PageHeader title="🛰️ Hydra HQ" subtitle={subtitle} />

      <div style={{ textAlign: 'center', marginBottom: 16 }}>
        <Link
          to="/hq/memory"
          style={{ color: BLUE, fontSize: 12, textDecoration: 'none', border: `1px solid ${BLUE}`, borderRadius: 4, padding: '4px 10px' }}
        >
          🧠 Memory{fleet?.memory_index?.length ? ` · ${fleet.memory_index.length}` : ''}
        </Link>
      </div>

      {err && fleet == null && (
        <div style={{ ...card, color: RED, borderColor: RED, textAlign: 'center' }}>
          can't reach /api/hq/fleet
        </div>
      )}

      {collectorOffline && (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center' }}>
          The host collector hasn't pushed a snapshot yet. Start it with{' '}
          <code style={{ color: GREEN }}>python3 ~/.local/bin/hq-collector.py</code>.
        </div>
      )}

      {categories.map((cat) => (
        <CategorySection key={cat.id} cat={cat} room={cat.room ? roomById.get(cat.room) : undefined} heads={headsOf(cat)} />
      ))}

      {(fleet?.activity?.length ?? 0) > 0 && (
        <section style={{ marginTop: 28 }}>
          <div style={{ color: GREEN, fontWeight: 700, fontSize: 15, marginBottom: 8 }}>
            Recent activity <span style={{ color: DIM, fontWeight: 400, fontSize: 12 }}>· last 72h</span>
          </div>
          <ActivityFeed items={fleet!.activity!} />
        </section>
      )}
    </div>
  );
}
