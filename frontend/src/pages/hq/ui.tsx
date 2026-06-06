// Shared visual vocabulary for the Hydra HQ 🛰️ views — colors, status meta, and the
// HeadCard reused by both the fleet overview and the room-detail page.
import { Link } from 'react-router-dom';
import type { Head, Status } from './types';

export const GREEN = '#00ff41';
export const DIM = 'rgba(0,255,65,0.55)';
export const FAINT = 'rgba(0,255,65,0.32)';
export const AMBER = '#ffcc00';
export const RED = '#ff5555';
export const BLUE = '#4db8ff';

export const card: React.CSSProperties = {
  border: `1px solid ${FAINT}`,
  borderRadius: 6,
  padding: '10px 12px',
  background: 'rgba(0,255,65,0.03)',
  fontFamily: 'monospace',
};

export const STATUS_META: Record<Status, { color: string; label: string; pulse: boolean }> = {
  working: { color: GREEN, label: 'working', pulse: true },
  'waiting-input': { color: AMBER, label: 'waiting', pulse: true },
  idle: { color: DIM, label: 'idle', pulse: false },
  offline: { color: FAINT, label: 'offline', pulse: false },
};

export function fmtAge(s: number | null): string {
  if (s == null) return '—';
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function StatusDot({ status }: { status: Status }) {
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

export function Pill({ children, color = DIM }: { children: React.ReactNode; color?: string }) {
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

export function HeadCard({ head }: { head: Head }) {
  const m = STATUS_META[head.status] ?? STATUS_META.offline;
  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <StatusDot status={head.status} />
        <Link to={`/hq/head/${head.name}`} style={{ color: GREEN, fontWeight: 700, fontSize: 14, textDecoration: 'none' }}>
          {head.name}
        </Link>
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
