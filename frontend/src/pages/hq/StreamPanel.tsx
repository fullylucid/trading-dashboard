import { useEffect, useRef, useState } from 'react';
import { GREEN, DIM, FAINT, AMBER, RED, card } from './ui';

// Hydra HQ 🛰️ — cyborganic live-view + run/stop control (B2 stream + B3 app control).
// The <img> is the MJPEG view (per STREAM.md): while mounted, the backend counts a viewer and
// tells the app to render, so the GPU/fan idle when nobody's watching; the backend serves an
// offline placeholder until frames arrive. The control row (per CONTROL.md) shows the app's
// actual state and exposes Run/Stop, which POST a state-enum to the command-locked launcher.

type AppState = 'starting' | 'running' | 'stopping' | 'stopped' | 'error' | 'offline' | 'unknown';
type AppStatus = {
  controller_offline: boolean;
  state: AppState;
  pid: number | null;
  since: number | null;
  detail?: string;
  fps?: number;
  live?: { tick?: number; ts?: number; w?: number; h?: number };
};

const STATE_GLYPH: Record<AppState, string> = {
  running: '●', starting: '◌', stopping: '◌', stopped: '○', error: '⚠', offline: '⚠', unknown: '·',
};

function fmtUptime(s: number): string {
  s = Math.max(0, Math.floor(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${s % 60}s`;
  return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m`;
}

// the one compact dim status line under the control (B3 addendum)
function infoLine(state: AppState, st: AppStatus | null): string {
  if (state === 'offline') return '⚠ controller offline';
  if (state === 'stopped') return '○ stopped';
  if (state === 'starting') return '◌ starting…';
  if (state === 'stopping') return '◌ stopping…';
  const parts = [`${STATE_GLYPH[state]} ${state}`];
  if (st?.since) parts.push(`up ${fmtUptime(Date.now() / 1000 - st.since)}`);
  if (st?.pid) parts.push(`pid ${st.pid}`);
  if (st?.fps) parts.push(`${st.fps}fps`);
  if (st?.live?.w && st?.live?.h) parts.push(`${st.live.w}×${st.live.h}`);
  return parts.join(' · ');
}

const STATE_META: Record<AppState, { color: string; label: string; pulse: boolean }> = {
  running: { color: GREEN, label: 'LIVE', pulse: true },
  starting: { color: AMBER, label: 'starting…', pulse: true },
  stopping: { color: AMBER, label: 'stopping…', pulse: true },
  stopped: { color: DIM, label: 'stopped', pulse: false },
  error: { color: RED, label: 'error', pulse: false },
  offline: { color: FAINT, label: 'controller offline', pulse: false },
  unknown: { color: FAINT, label: '…', pulse: false },
};

export default function StreamPanel({ roomId }: { roomId: string }) {
  const base = `/api/hq/room/${encodeURIComponent(roomId)}`;
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [errored, setErrored] = useState(false);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<() => void>(() => {});

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const r = await fetch(`${base}/app`);
        if (r.ok && active) setStatus(await r.json());
      } catch {
        /* keep last status */
      }
    };
    pollRef.current = poll;
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [base]);

  const offline = status?.controller_offline ?? true;
  const state: AppState = offline ? 'offline' : (status?.state ?? 'unknown');
  const meta = STATE_META[state] ?? STATE_META.unknown;
  const canRun = !offline && (state === 'stopped' || state === 'error');
  const canStop = !offline && (state === 'running' || state === 'starting');

  const command = async (action: 'run' | 'stop') => {
    setBusy(true);
    try {
      await fetch(`${base}/app`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      setTimeout(() => pollRef.current(), 400); // reflect the new state quickly
    } catch {
      /* ignore; next poll recovers */
    } finally {
      setBusy(false);
    }
  };

  const btn = (enabled: boolean, color: string): React.CSSProperties => ({
    background: '#000',
    color: enabled ? color : FAINT,
    border: `1px solid ${enabled ? color : FAINT}`,
    borderRadius: 4,
    fontFamily: 'monospace',
    fontSize: 11,
    padding: '3px 12px',
    cursor: enabled && !busy ? 'pointer' : 'not-allowed',
    opacity: busy ? 0.6 : 1,
  });

  return (
    <section style={{ marginBottom: 22 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 15 }}>Live view</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: meta.color }}>
          <span
            style={{
              width: 8, height: 8, borderRadius: '50%', background: meta.color,
              boxShadow: meta.pulse ? `0 0 6px ${meta.color}` : 'none',
            }}
          />
          {meta.label}
        </span>
        {status?.detail ? <span style={{ fontSize: 10, color: RED }}>{status.detail}</span> : null}
        <span style={{ fontSize: 10, color: DIM }}>renders on demand — idles when unwatched</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button type="button" disabled={!canRun || busy} onClick={() => command('run')} style={btn(canRun, GREEN)}>
            ▶ Run
          </button>
          <button type="button" disabled={!canStop || busy} onClick={() => command('stop')} style={btn(canStop, RED)}>
            ❚❚ Stop
          </button>
        </div>
      </div>

      <div style={{ fontSize: 10, color: DIM, marginBottom: 8, fontFamily: 'monospace' }}>{infoLine(state, status)}</div>

      <div style={{ ...card, padding: 0, overflow: 'hidden', position: 'relative', aspectRatio: '16 / 9', background: '#050805' }}>
        {!errored ? (
          <img
            src={`${base}/stream`}
            alt="cyborganic live render"
            onError={() => setErrored(true)}
            style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
          />
        ) : (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: DIM, fontSize: 12 }}>
            stream unavailable — backend offline
          </div>
        )}
      </div>
    </section>
  );
}
