import { useEffect, useState } from 'react';
import PageHeader from '../components/PageHeader';

// Hydra HQ 🛰️ — fleet command center (Slice 1: read-first overview).
// Polls /api/hq/fleet (a host-collector snapshot served from Redis) and renders one card
// per head, grouped by project room. See ~/hydra-hq/DESIGN.md.

const GREEN = '#00ff41';
const DIM = 'rgba(0,255,65,0.55)';
const FAINT = 'rgba(0,255,65,0.32)';
const AMBER = '#ffcc00';
const RED = '#ff5555';
const BLUE = '#4db8ff';

type Status = 'working' | 'idle' | 'waiting-input' | 'offline';

type Head = {
  name: string;
  room: string;
  workdir: string;
  branch: string | null;
  status: Status;
  current: string | null;
  last_active: string | null;
  last_active_age_s: number | null;
  rc: { paired: boolean; name: string };
  git: { ahead: number; uncommitted: number; last_commit: string | null };
  tmux: { window: number; pane: string } | null;
  fossil_dir: string;
};

type PR = { number: number; title: string; branch: string | null; head: string | null; mergeable: boolean };
type Room = { id: string; name: string; repo: string | null; heads: string[]; open_prs: PR[] };
type Fleet = {
  available: boolean;
  generated_at?: number;
  rooms?: Room[];
  heads?: Head[];
};

const STATUS_META: Record<Status, { color: string; label: string; pulse: boolean }> = {
  working: { color: GREEN, label: 'working', pulse: true },
  'waiting-input': { color: AMBER, label: 'waiting', pulse: true },
  idle: { color: DIM, label: 'idle', pulse: false },
  offline: { color: FAINT, label: 'offline', pulse: false },
};

function fmtAge(s: number | null): string {
  if (s == null) return '—';
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const card: React.CSSProperties = {
  border: `1px solid ${FAINT}`,
  borderRadius: 6,
  padding: '10px 12px',
  background: 'rgba(0,255,65,0.03)',
  fontFamily: 'monospace',
};

function StatusDot({ status }: { status: Status }) {
  const m = STATUS_META[status] ?? STATUS_META.offline;
  return (
    <span
      title={m.label}
      style={{
        display: 'inline-block',
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: m.color,
        boxShadow: m.pulse ? `0 0 7px ${m.color}` : 'none',
        flex: '0 0 auto',
      }}
    />
  );
}

function Pill({ children, color = DIM }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      style={{
        fontSize: 10,
        color,
        border: `1px solid ${color}`,
        borderRadius: 3,
        padding: '1px 5px',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  );
}

function HeadCard({ head }: { head: Head }) {
  const m = STATUS_META[head.status] ?? STATUS_META.offline;
  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <StatusDot status={head.status} />
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 14 }}>{head.name}</span>
        <span style={{ color: m.color, fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>
          {m.label}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: DIM }}>{fmtAge(head.last_active_age_s)}</span>
      </div>

      <div
        style={{
          fontSize: 11,
          color: head.current ? 'rgba(0,255,65,0.8)' : FAINT,
          minHeight: 28,
          lineHeight: 1.3,
          fontStyle: head.current ? 'normal' : 'italic',
        }}
      >
        {head.current || 'no recent activity'}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
        {head.branch && <Pill color={BLUE}>⎇ {head.branch}</Pill>}
        {head.git.ahead > 0 && <Pill color={GREEN}>↑{head.git.ahead}</Pill>}
        {head.git.uncommitted > 0 && <Pill color={AMBER}>±{head.git.uncommitted}</Pill>}
        {head.rc.paired && <Pill color={BLUE}>🎮 RC</Pill>}
      </div>

      {head.git.last_commit && (
        <div style={{ fontSize: 10, color: FAINT, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {head.git.last_commit}
        </div>
      )}
    </div>
  );
}

function RoomSection({ room, heads }: { room: Room; heads: Head[] }) {
  const working = heads.filter((h) => h.status === 'working').length;
  return (
    <section style={{ marginBottom: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 15 }}>{room.name}</span>
        {room.repo && <span style={{ fontSize: 11, color: DIM }}>{room.repo}</span>}
        <span style={{ fontSize: 11, color: DIM }}>
          {heads.length} head{heads.length === 1 ? '' : 's'}
          {working > 0 ? ` · ${working} working` : ''}
        </span>
        {room.open_prs.length > 0 && <Pill color={AMBER}>{room.open_prs.length} open PR{room.open_prs.length === 1 ? '' : 's'}</Pill>}
      </div>
      <div
        style={{
          display: 'grid',
          gap: 10,
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
        }}
      >
        {heads.map((h) => (
          <HeadCard key={h.name} head={h} />
        ))}
      </div>
    </section>
  );
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
  const collectorOffline = fleet != null && fleet.available === false;
  const totalWorking = heads.filter((h) => h.status === 'working').length;

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

      {rooms.map((room) => (
        <RoomSection
          key={room.id}
          room={room}
          heads={heads.filter((h) => h.room === room.id)}
        />
      ))}
    </div>
  );
}
