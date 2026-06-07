import { useState } from 'react';
import { GREEN, DIM, FAINT, RED, card } from './ui';

// Hydra HQ 🛰️ — cyborganic live-view panel (B2, per STREAM.md). The <img> points at the
// backend MJPEG endpoint; while it's mounted the backend counts a viewer and tells the app
// (via control.json on the shared bus) to render — so the GPU/fan idle when nobody's watching.
// Unmounting (leaving the room, or Stop here) drops the connection and releases the stream.
// The backend always emits an "offline" placeholder frame, so there's a graceful idle state.

export default function StreamPanel({ roomId }: { roomId: string }) {
  const [playing, setPlaying] = useState(true);
  const [errored, setErrored] = useState(false);
  const src = `/api/hq/room/${encodeURIComponent(roomId)}/stream`;

  return (
    <section style={{ marginBottom: 22 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 15 }}>Live view</span>
        {playing && !errored && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: RED }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: RED, boxShadow: `0 0 6px ${RED}` }} />
            LIVE
          </span>
        )}
        <span style={{ fontSize: 10, color: DIM }}>renders on demand — idles when unwatched</span>
        <button
          type="button"
          onClick={() => { setErrored(false); setPlaying((p) => !p); }}
          style={{
            marginLeft: 'auto', background: '#000', color: GREEN, border: `1px solid ${FAINT}`,
            borderRadius: 4, fontFamily: 'monospace', fontSize: 11, padding: '3px 10px', cursor: 'pointer',
          }}
        >
          {playing ? '❚❚ Stop' : '▶ Start'}
        </button>
      </div>

      <div style={{ ...card, padding: 0, overflow: 'hidden', position: 'relative', aspectRatio: '16 / 9', background: '#050805' }}>
        {playing && !errored ? (
          <img
            src={src}
            alt="cyborganic live render"
            onError={() => setErrored(true)}
            style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
          />
        ) : (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: DIM, fontSize: 12 }}>
            {errored ? 'stream unavailable — backend or app offline' : 'stopped — press ▶ Start to watch'}
          </div>
        )}
      </div>
    </section>
  );
}
