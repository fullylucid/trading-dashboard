import { useEffect, useState, useCallback, useRef } from 'react';

const GREEN = '#00ff41';
const RED = '#ff5555';
const AMBER = '#ffcc00';
const DIM = 'rgba(0,255,65,0.55)';

const td: React.CSSProperties = { padding: '2px 6px', fontSize: 11, textAlign: 'right', whiteSpace: 'nowrap' };
const th: React.CSSProperties = { ...td, color: DIM, fontWeight: 400, borderBottom: `1px solid ${DIM}` };
const card: React.CSSProperties = { border: `1px solid ${DIM}`, borderRadius: 6, padding: '10px 12px', background: 'rgba(0,255,65,0.03)' };

type Proc = { name: string; pid: number; cpu?: number; gpu?: number; net_kbps?: number; signed?: boolean; path?: string };
type Snapshot = {
  ts: string;
  cpu: { temp?: number; load?: number; power_w?: number; tjmax_distance?: number; warn?: number; crit?: number };
  gpu: { temp?: number; load?: number; fan_rpm?: number; hotspot?: number };
  mem: { used_pct?: number };
  disk: { busy_pct?: number };
  fans: { name: string; rpm: number }[];
  top: Proc[];
  security: {
    defender?: { rtp?: boolean; engine_ok?: boolean; last_threat?: string | null };
    flags?: { proc: string; pid: number; why: string }[];
    new_autoruns?: { name: string; path: string }[];
  };
};
type Current = { online: boolean; age_s?: number; snapshot?: Snapshot; series?: Record<string, number[]> };
type Ev = {
  ts: string; metric: string; value: number; z: number; severity: string;
  culprit?: { name: string; pid: number; value: number; signed?: boolean; path?: string } | null;
  explained: boolean; explanation?: string | null;
};

const sevColor = (s: string) => (s === 'CRITICAL' ? RED : s === 'WARN' ? AMBER : DIM);

// thermal-margin coloring: green far from warn, amber near/over warn, red past crit
function tempColor(v?: number, warn = 75, crit = 86): string {
  if (v == null) return DIM;
  if (v >= crit) return RED;
  if (v >= warn - 10) return AMBER;
  return GREEN;
}
function loadColor(v?: number): string {
  if (v == null) return DIM;
  if (v >= 90) return RED;
  if (v >= 70) return AMBER;
  return GREEN;
}

function Spark({ data, color = GREEN, w = 120, h = 28 }: { data: number[]; color?: string; w?: number; h?: number }) {
  if (!data || data.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * (w - 2) + 1;
    const y = h - 1 - ((v - min) / span) * (h - 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}

function Gauge({ label, value, unit, color, sub }: { label: string; value: string; unit: string; color: string; sub?: string }) {
  return (
    <div style={{ ...card, minWidth: 120, flex: '1 1 120px' }}>
      <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, lineHeight: 1.1 }}>{value}<span style={{ fontSize: 12, opacity: 0.6 }}> {unit}</span></div>
      {sub && <div style={{ fontSize: 10, color: DIM, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ============================================================ full detail view
export function SystemFull({ cur, events }: { cur: Current | null; events: Ev[] }) {
  const snap = cur?.snapshot;
  const series = cur?.series || {};
  const def = snap?.security?.defender;
  const flags = snap?.security?.flags || [];
  const autoruns = snap?.security?.new_autoruns || [];

  if (!snap) {
    return (
      <div style={{ ...card }}>
        <div style={{ fontSize: 13, marginBottom: 6 }}>No host data yet.</div>
        <div style={{ fontSize: 11, color: DIM }}>
          Start the host collector (<code>syswatch.ps1</code>) on the Windows side — it pushes temps, fans,
          CPU/GPU load and process info here every few seconds. LibreHardwareMonitor must be running for the
          temp/fan rows to populate.
        </div>
      </div>
    );
  }

  return (
    <>
      {/* gauges */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <Gauge label="CPU Temp" value={snap.cpu.temp != null ? String(Math.round(snap.cpu.temp)) : '—'} unit="°C"
               color={tempColor(snap.cpu.temp, snap.cpu.warn, snap.cpu.crit)}
               sub={snap.cpu.tjmax_distance != null ? `${Math.round(snap.cpu.tjmax_distance)}°C to TjMax` : undefined} />
        <Gauge label="CPU Load" value={snap.cpu.load != null ? snap.cpu.load.toFixed(1) : '—'} unit="%" color={loadColor(snap.cpu.load)} />
        <Gauge label="CPU Power" value={snap.cpu.power_w != null ? String(Math.round(snap.cpu.power_w)) : '—'} unit="W" color={GREEN} />
        <Gauge label="GPU Temp" value={snap.gpu.temp != null ? String(Math.round(snap.gpu.temp)) : '—'} unit="°C" color={tempColor(snap.gpu.temp, 83, 90)}
               sub={snap.gpu.hotspot != null ? `hot spot ${Math.round(snap.gpu.hotspot)}°C` : undefined} />
        <Gauge label="GPU Load" value={snap.gpu.load != null ? snap.gpu.load.toFixed(1) : '—'} unit="%" color={loadColor(snap.gpu.load)} />
        <Gauge label="GPU Fan" value={snap.gpu.fan_rpm != null ? String(snap.gpu.fan_rpm) : '—'} unit="RPM"
               color={snap.gpu.fan_rpm ? GREEN : DIM} sub={snap.gpu.fan_rpm ? undefined : 'idle / fans-off'} />
      </div>

      {/* sparklines */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        {([
          ['cpu_load', 'CPU load %', loadColor(snap.cpu.load)],
          ['gpu_load', 'GPU load %', loadColor(snap.gpu.load)],
          ['cpu_temp', 'CPU temp °C', tempColor(snap.cpu.temp, snap.cpu.warn, snap.cpu.crit)],
          ['cpu_power', 'CPU power W', GREEN],
        ] as const).map(([k, lbl, col]) => (
          <div key={k} style={{ ...card, flex: '1 1 150px' }}>
            <div style={{ fontSize: 10, color: DIM, marginBottom: 2 }}>{lbl} <span style={{ float: 'right' }}>{series[k]?.length ? series[k][series[k].length - 1] : ''}</span></div>
            <Spark data={series[k] || []} color={col as string} w={150} />
          </div>
        ))}
      </div>

      {/* security strip */}
      <div style={{ ...card, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', fontSize: 12 }}>
          <span style={{ color: DIM }}>SECURITY</span>
          <span style={{ color: def?.rtp ? GREEN : RED }}>Defender RTP: {def?.rtp ? 'on' : 'OFF'}</span>
          <span style={{ color: def?.last_threat ? RED : DIM }}>Threats: {def?.last_threat || 'none'}</span>
          <span style={{ color: flags.length ? AMBER : DIM }}>Flagged procs: {flags.length}</span>
          <span style={{ color: autoruns.length ? AMBER : DIM }}>New autoruns: {autoruns.length}</span>
        </div>
        {flags.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {flags.map((f) => (
              <div key={`${f.pid}-${f.proc}`} style={{ fontSize: 11, color: AMBER }}>⚠ {f.proc} (pid {f.pid}) — {f.why}</div>
            ))}
          </div>
        )}
        {autoruns.length > 0 && (
          <div style={{ marginTop: 6 }}>
            {autoruns.map((a) => (
              <div key={a.path} style={{ fontSize: 11, color: AMBER }}>⚠ new autorun: {a.name} → {a.path}</div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {/* top processes */}
        <div style={{ ...card, flex: '1 1 430px' }}>
          <div style={{ fontSize: 12, color: DIM, marginBottom: 6 }}>TOP PROCESSES</div>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead><tr>
              <th style={{ ...th, textAlign: 'left' }}>process</th><th style={th}>CPU%</th><th style={th}>GPU%</th>
              <th style={th}>net kB/s</th><th style={th}>signed</th>
            </tr></thead>
            <tbody>
              {snap.top.slice(0, 10).map((p) => (
                <tr key={p.pid}>
                  <td style={{ ...td, textAlign: 'left' }} title={p.path}>{p.name}</td>
                  <td style={{ ...td, color: loadColor(p.cpu) }}>{p.cpu != null ? p.cpu.toFixed(1) : '—'}</td>
                  <td style={td}>{p.gpu != null ? p.gpu.toFixed(1) : '—'}</td>
                  <td style={td}>{p.net_kbps != null ? Math.round(p.net_kbps) : '—'}</td>
                  <td style={{ ...td, color: p.signed === false ? AMBER : DIM }}>{p.signed === false ? 'no' : p.signed ? 'yes' : '?'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* event log */}
        <div style={{ ...card, flex: '1 1 430px' }}>
          <div style={{ fontSize: 12, color: DIM, marginBottom: 6 }}>SPIKE EVENTS</div>
          {events.length === 0 && <div style={{ fontSize: 11, color: DIM }}>No abnormal events logged. (Spikes are flagged by z-score vs the box's own baseline — nothing weird yet.)</div>}
          {events.map((e, i) => (
            <div key={i} style={{ borderBottom: `1px solid rgba(0,255,65,0.12)`, padding: '4px 0' }}>
              <div style={{ fontSize: 11 }}>
                <span style={{ color: sevColor(e.severity), fontWeight: 700 }}>{e.severity}</span>{' '}
                <span>{e.metric}</span> = <b>{e.value}</b> <span style={{ color: DIM }}>(z {e.z})</span>
                <span style={{ float: 'right', color: DIM, fontSize: 10 }}>{e.ts?.replace('T', ' ').slice(5, 19)}</span>
              </div>
              {e.culprit && (
                <div style={{ fontSize: 10, color: DIM }}>
                  → {e.culprit.name} (pid {e.culprit.pid}, {typeof e.culprit.value === 'number' ? e.culprit.value.toFixed(1) : e.culprit.value})
                  {e.culprit.signed === false && <span style={{ color: AMBER }}> · unsigned</span>}
                </div>
              )}
              {e.explanation && <div style={{ fontSize: 10, color: GREEN, marginTop: 2 }}>{e.explanation}</div>}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ============================================================ thin top banner
const BANNER_H = 28;

function Pill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span style={{ color: DIM, fontSize: 10 }}>{label} </span>
      <span style={{ color, fontWeight: 700 }}>{value}</span>
    </span>
  );
}

export default function SystemBanner() {
  const [cur, setCur] = useState<Current | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const poll = useCallback(async () => {
    try { const r = await fetch('/api/system/current'); if (r.ok) setCur(await r.json()); } catch { /* ignore */ }
  }, []);
  const pollEvents = useCallback(async () => {
    try { const r = await fetch('/api/system/events?limit=40'); if (r.ok) setEvents((await r.json()).events || []); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    poll(); pollEvents();
    const a = setInterval(poll, 3000);
    const b = setInterval(pollEvents, 10000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [poll, pollEvents]);

  // close on Esc / click-outside the panel
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    // defer so the opening click doesn't immediately close it
    const t = setTimeout(() => document.addEventListener('mousedown', onClick), 0);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onClick); clearTimeout(t); };
  }, [open]);

  const online = cur?.online;
  const snap = cur?.snapshot;
  const recentAlerts = events.filter((e) => e.severity === 'WARN' || e.severity === 'CRITICAL').length;
  const crit = events.some((e) => e.severity === 'CRITICAL');
  const dot = online ? (crit ? RED : recentAlerts ? AMBER : GREEN) : RED;

  const bannerStyle: React.CSSProperties = {
    position: 'fixed', top: 0, left: 0, right: 0, height: BANNER_H, zIndex: 1500,
    display: 'flex', alignItems: 'center', gap: 16,
    padding: `0 14px 0 60px`,  // left pad clears the floating ☰ nav button
    background: 'rgba(0,0,0,0.92)', borderBottom: `1px solid ${DIM}`,
    fontFamily: 'monospace', cursor: 'pointer', backdropFilter: 'blur(4px)',
    boxShadow: open ? 'none' : '0 1px 8px rgba(0,255,65,0.15)',
  };

  return (
    <>
      <div style={bannerStyle} onClick={() => setOpen((v) => !v)} title="Click for full system view (Esc to close)">
        <span style={{ color: dot, fontSize: 12 }}>{online ? '●' : '○'}</span>
        <span style={{ color: DIM, fontSize: 11, fontWeight: 700 }}>🖥 SYSTEM</span>
        {snap ? (
          <>
            <Pill label="CPU" value={`${snap.cpu.temp != null ? Math.round(snap.cpu.temp) : '—'}°C`} color={tempColor(snap.cpu.temp, snap.cpu.warn, snap.cpu.crit)} />
            <Pill label="load" value={`${snap.cpu.load != null ? snap.cpu.load.toFixed(0) : '—'}%`} color={loadColor(snap.cpu.load)} />
            <Pill label="GPU" value={`${snap.gpu.temp != null ? Math.round(snap.gpu.temp) : '—'}°C`} color={tempColor(snap.gpu.temp, 83, 90)} />
            <Pill label="fan" value={`${snap.gpu.fan_rpm ?? '—'}`} color={snap.gpu.fan_rpm ? GREEN : DIM} />
            <Pill label="mem" value={`${snap.mem?.used_pct != null ? Math.round(snap.mem.used_pct) : '—'}%`} color={GREEN} />
            {recentAlerts > 0 && <Pill label="⚠" value={`${recentAlerts}`} color={crit ? RED : AMBER} />}
          </>
        ) : (
          <span style={{ color: DIM, fontSize: 11 }}>{online ? 'loading…' : 'collector offline'}</span>
        )}
        <span style={{ marginLeft: 'auto', color: DIM, fontSize: 11 }}>{open ? '▲ close' : '▼ expand'}</span>
      </div>

      {open && (
        <div
          ref={panelRef}
          style={{
            position: 'fixed', top: BANNER_H, left: 0, right: 0, zIndex: 1499,
            maxHeight: `calc(100vh - ${BANNER_H}px)`, overflowY: 'auto',
            background: '#000', color: GREEN, fontFamily: 'monospace',
            borderBottom: `1px solid ${DIM}`, boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
            padding: '14px 16px 28px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16 }}>🖥️ System Monitor</h2>
            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, border: `1px solid ${online ? GREEN : RED}`, color: online ? GREEN : RED }}>
              {online ? `● live (${cur?.age_s}s)` : '○ offline — collector not reporting'}
            </span>
            <button onClick={() => setOpen(false)} style={{ marginLeft: 'auto', background: '#000', color: GREEN, border: `1px solid ${DIM}`, borderRadius: 4, cursor: 'pointer', fontFamily: 'monospace', padding: '4px 10px' }}>✕ close</button>
          </div>
          <SystemFull cur={cur} events={events} />
        </div>
      )}
    </>
  );
}
