import React, { useEffect, useState, useCallback } from 'react';
import PageHeader from '../components/PageHeader';

const GREEN = '#00ff41';
const RED = '#ff5555';
const AMBER = '#ffcc00';
const DIM = 'rgba(0,255,65,0.55)';

const box: React.CSSProperties = { background: '#000', color: GREEN, border: `1px solid ${DIM}`, borderRadius: 4, fontFamily: 'monospace', padding: '5px 9px' };
const card: React.CSSProperties = { border: `1px solid ${DIM}`, borderRadius: 6, padding: '12px 14px', background: 'rgba(0,255,65,0.03)', marginBottom: 12 };
const td: React.CSSProperties = { padding: '3px 7px', fontSize: 11, textAlign: 'left', verticalAlign: 'top' };
const th: React.CSSProperties = { ...td, color: DIM, fontWeight: 400, borderBottom: `1px solid ${DIM}` };

type Channel = { id: string; handle: string; name: string; category: string };
type Call = { ticker?: string | null; action?: string; conviction?: string; price_target?: number | null; horizon?: string; thesis?: string };
type Distill = {
  category?: string; summary?: string; creator_view?: string; philosophy?: string; macro_thesis?: string;
  calls?: Call[]; key_insights?: string[]; tools_mentioned?: string[]; recommendations?: string[];
  claims?: { claim: string; stance: string }[];
};
type VideoDoc = {
  video_id: string; title: string; channel: string; channel_id: string; published: string;
  url: string; category: string; distill?: Distill | null; error?: string; distilled_at?: string;
};
type Pick = { ticker: string; dir: number; ret: number; alpha: number; pub: string; title: string; in_flight?: boolean; horizon_days?: number; window_end?: string };
type LbRow = { channel: string; calls: number; scored: number; settled?: number; in_flight?: number; watch_calls?: number; avg_alpha: number | null; hit_rate: number | null; picks: Pick[] };
type TkCreator = { channel: string; action?: string; conviction?: string; pub?: string; avg_alpha?: number | null; scored?: number };
type TkCall = { channel: string; action?: string; conviction?: string; horizon?: string; price_target?: number | null; thesis?: string; pub?: string; title?: string; url?: string; creator_alpha?: number | null; creator_scored?: number };
type TickerRow = {
  ticker: string; mentions: number; buy: number; sell: number; watch: number; hold: number;
  crowd_lean: number; net: string; first_pub?: string | null; last_pub?: string | null;
  price?: number | null; ret_since_first?: number | null; avg_price_target?: number | null;
  upside?: number | null; smart_agrees?: boolean | null; top_creator?: string | null;
  signal: string; creators: TkCreator[]; calls: TkCall[];
};

const actionColor = (a?: string) => (a === 'buy' ? GREEN : a === 'sell' ? RED : a === 'watch' ? AMBER : DIM);
const viewColor = (v?: string) => (v === 'bullish' ? GREEN : v === 'bearish' ? RED : v === 'mixed' ? AMBER : DIM);
const signalColor = (s: string) => (s.startsWith('contrarian') ? '#ff9d3c' : s.includes('long') ? GREEN : s.includes('short') ? RED : DIM);
const pct = (x?: number | null, d = 1) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(d)}%`);
const retColor = (x?: number | null) => (x == null ? DIM : x >= 0 ? GREEN : RED);
const CATS = ['finance', 'ai-coding', 'science', 'engineering', 'general'];

function CallsTable({ calls }: { calls: Call[] }) {
  return (
    <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: 6 }}>
      <thead><tr><th style={th}>ticker</th><th style={th}>action</th><th style={th}>conv</th><th style={th}>target</th><th style={th}>horizon</th><th style={th}>thesis</th></tr></thead>
      <tbody>
        {calls.map((c, i) => (
          <tr key={i}>
            <td style={{ ...td, fontWeight: 700 }}>{c.ticker || '—'}</td>
            <td style={{ ...td, color: actionColor(c.action), fontWeight: 700 }}>{c.action}</td>
            <td style={td}>{c.conviction}</td>
            <td style={td}>{c.price_target != null ? `$${c.price_target}` : '—'}</td>
            <td style={td}>{c.horizon}</td>
            <td style={{ ...td, color: DIM, maxWidth: 360 }}>{c.thesis}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Chips({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
    {items.map((t, i) => <span key={i} style={{ fontSize: 10, border: `1px solid ${DIM}`, borderRadius: 10, padding: '1px 8px' }}>{t}</span>)}
  </div>;
}

function VideoCard({ v }: { v: VideoDoc }) {
  const d = v.distill;
  return (
    <div style={card}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <a href={v.url} target="_blank" rel="noreferrer" style={{ color: GREEN, fontWeight: 700, fontSize: 13, textDecoration: 'none' }}>{v.title || v.video_id}</a>
        <span style={{ fontSize: 11, color: DIM }}>{v.channel} · {v.published}</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, border: `1px solid ${DIM}`, borderRadius: 10, padding: '1px 8px', color: DIM }}>{v.category}</span>
        {d?.creator_view && <span style={{ fontSize: 11, color: viewColor(d.creator_view), fontWeight: 700 }}>{d.creator_view}</span>}
      </div>
      {v.error && <div style={{ fontSize: 11, color: AMBER, marginTop: 6 }}>⚠ {v.error}</div>}
      {d && (
        <>
          {d.summary && <div style={{ fontSize: 12, marginTop: 6, lineHeight: 1.45 }}>{d.summary}</div>}
          {d.philosophy && <div style={{ fontSize: 11, color: DIM, marginTop: 4 }}><b>Philosophy:</b> {d.philosophy}</div>}
          {d.macro_thesis && <div style={{ fontSize: 11, color: DIM, marginTop: 2 }}><b>Macro:</b> {d.macro_thesis}</div>}
          {!!d.calls?.length && <CallsTable calls={d.calls} />}
          {!!d.key_insights?.length && <div style={{ marginTop: 6 }}>
            <div style={{ fontSize: 11, color: DIM }}>Key insights</div>
            <ul style={{ margin: '2px 0 0 16px', padding: 0 }}>{d.key_insights.map((k, i) => <li key={i} style={{ fontSize: 12, lineHeight: 1.4 }}>{k}</li>)}</ul>
          </div>}
          {!!d.tools_mentioned?.length && <div style={{ marginTop: 6 }}><div style={{ fontSize: 11, color: DIM }}>Tools / refs</div><Chips items={d.tools_mentioned} /></div>}
          {!!d.recommendations?.length && <div style={{ marginTop: 6 }}>
            <div style={{ fontSize: 11, color: DIM }}>Recommendations</div>
            <ul style={{ margin: '2px 0 0 16px', padding: 0 }}>{d.recommendations.map((k, i) => <li key={i} style={{ fontSize: 12, lineHeight: 1.4 }}>{k}</li>)}</ul>
          </div>}
        </>
      )}
    </div>
  );
}

export default function FinTube() {
  const [view, setView] = useState<'feed' | 'channels' | 'tickers' | 'leaderboard'>('feed');
  const [videos, setVideos] = useState<VideoDoc[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [lb, setLb] = useState<LbRow[]>([]);
  const [tks, setTks] = useState<TickerRow[]>([]);
  const [tkOpen, setTkOpen] = useState<string | null>(null);
  const [catFilter, setCatFilter] = useState<string>('all');

  // add-box state
  const [url, setUrl] = useState('');
  const [cat, setCat] = useState('finance');
  const [track, setTrack] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // find-by-photo (vision) state
  const [visionOn, setVisionOn] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [finding, setFinding] = useState(false);
  const [findMsg, setFindMsg] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<{ video_id: string; title: string; channel?: string; url: string; published?: string; match?: number }[]>([]);

  const loadFeed = useCallback(async () => {
    const q = catFilter === 'all' ? '' : `?category=${catFilter}`;
    try { const r = await fetch(`/api/fintube/feed${q}`); if (r.ok) setVideos((await r.json()).videos || []); } catch { /* */ }
  }, [catFilter]);
  const loadChannels = useCallback(async () => {
    try { const r = await fetch('/api/fintube/channels'); if (r.ok) setChannels((await r.json()).channels || []); } catch { /* */ }
  }, []);
  const loadLb = useCallback(async () => {
    try { const r = await fetch('/api/fintube/leaderboard'); if (r.ok) setLb((await r.json()).leaderboard || []); } catch { /* */ }
  }, []);
  const loadTks = useCallback(async () => {
    try { const r = await fetch('/api/fintube/tickers'); if (r.ok) setTks((await r.json()).tickers || []); } catch { /* */ }
  }, []);

  useEffect(() => { loadFeed(); loadChannels(); }, [loadFeed, loadChannels]);
  useEffect(() => { if (view === 'leaderboard') loadLb(); }, [view, loadLb]);
  useEffect(() => { if (view === 'tickers') loadTks(); }, [view, loadTks]);
  useEffect(() => { fetch('/api/fintube/vision-status').then(r => r.ok ? r.json() : null).then(d => setVisionOn(!!d?.configured)).catch(() => {}); }, []);

  const submit = async (overrideUrl?: string) => {
    const target = (overrideUrl ?? url).trim();
    if (!target) return;
    setBusy(true); setMsg('distilling… (transcript → Opus pool, ~30-60s)');
    try {
      const r = await fetch('/api/fintube/ingest', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ url: target, category: cat, track }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`error: ${d.detail || r.status}`); }
      else {
        setMsg(d.type === 'channel' ? `resolved ${d.channel?.name}${d.tracked ? ' (now tracked)' : ''}` : (d.cached ? 'already in feed' : 'distilled ✓'));
        setUrl('');
        await loadFeed(); await loadChannels();
      }
    } catch (e: any) { setMsg(`error: ${e?.message || e}`); }
    finally { setBusy(false); }
  };

  const findByPhoto = async (file: File) => {
    setFinding(true); setCandidates([]); setFindMsg('reading the screen with the local VLM…');
    try {
      const b64 = await new Promise<string>((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result).split(',')[1] || '');
        fr.onerror = () => rej(fr.error);
        fr.readAsDataURL(file);
      });
      const r = await fetch('/api/fintube/find', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ image_b64: b64, mime: file.type || 'image/jpeg' }),
      });
      const d = await r.json();
      if (!r.ok) { setFindMsg(`error: ${d.detail || r.status}`); }
      else if (d.status === 'vision-unconfigured') { setFindMsg('vision service not configured on the backend'); }
      else if (d.status === 'no-text-read') { setFindMsg('couldn’t read a title from that image — try a clearer shot'); }
      else if (!d.candidates?.length) { setFindMsg(`read “${d.read}” but found no matches`); }
      else { setFindMsg(`read “${d.read}” → ${d.candidates.length} match(es):`); setCandidates(d.candidates); }
    } catch (e: any) { setFindMsg(`error: ${e?.message || e}`); }
    finally { setFinding(false); }
  };

  const refresh = async () => {
    setBusy(true); setMsg('refreshing tracked channels in background…');
    try { await fetch('/api/fintube/refresh', { method: 'POST' }); } catch { /* */ }
    setTimeout(() => { loadFeed(); setBusy(false); setMsg('new videos will appear as they finish'); }, 1500);
  };

  const removeChannel = async (id: string) => {
    await fetch(`/api/fintube/channels/${id}`, { method: 'DELETE' });
    loadChannels();
  };

  const byCat: Record<string, Channel[]> = {};
  channels.forEach((c) => { (byCat[c.category] ||= []).push(c); });

  const wrap: React.CSSProperties = { minHeight: '100vh', background: '#000', color: GREEN, fontFamily: 'monospace', padding: '16px 16px 24px', maxWidth: 1040, margin: '0 auto' };

  return (
    <div style={wrap}>
      <PageHeader title="📺 FinTube" subtitle="content distillation hub" />

      {/* add box */}
      <div style={{ ...card }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="paste a video or channel URL / @handle"
                 onKeyDown={(e) => { if (e.key === 'Enter' && !busy) submit(); }}
                 style={{ ...box, flex: '1 1 320px', minWidth: 220 }} />
          <select value={cat} onChange={(e) => setCat(e.target.value)} style={{ ...box, cursor: 'pointer' }}>
            {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <label style={{ fontSize: 11, color: DIM, display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
            <input type="checkbox" checked={track} onChange={(e) => setTrack(e.target.checked)} /> track channel
          </label>
          <button onClick={() => submit()} disabled={busy} style={{ ...box, cursor: busy ? 'default' : 'pointer', color: busy ? DIM : GREEN }}>{busy ? '…' : '⚙ distill'}</button>
          <button onClick={refresh} disabled={busy} style={{ ...box, cursor: busy ? 'default' : 'pointer' }} title="check all tracked channels for new videos">↻ refresh tracked</button>
          {visionOn && <button onClick={() => setFindOpen(o => !o)} style={{ ...box, cursor: 'pointer', background: findOpen ? 'rgba(0,255,65,0.18)' : '#000' }} title="snap/upload a screen showing a video — the local VLM reads the title and finds it">📷 find by photo</button>}
        </div>
        {msg && <div style={{ fontSize: 11, color: DIM, marginTop: 6 }}>{msg}</div>}

        {visionOn && findOpen && (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${DIM}` }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ ...box, cursor: 'pointer' }}>
                📷 snap / upload
                <input type="file" accept="image/*" capture="environment" style={{ display: 'none' }}
                       onChange={(e) => { const f = e.target.files?.[0]; if (f) findByPhoto(f); e.currentTarget.value = ''; }} />
              </label>
              <span style={{ fontSize: 11, color: DIM }}>{finding ? '…reading' : 'point at a screen showing a YouTube video; the local VLM reads the title and resolves it'}</span>
            </div>
            {findMsg && <div style={{ fontSize: 11, color: DIM, marginTop: 6 }}>{findMsg}</div>}
            {candidates.map((c) => (
              <div key={c.video_id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '4px 0', borderTop: `1px solid rgba(0,255,65,0.12)` }}>
                {c.match != null && <span style={{ fontSize: 10, color: c.match >= 0.6 ? GREEN : AMBER, minWidth: 34 }}>{Math.round(c.match * 100)}%</span>}
                <a href={c.url} target="_blank" rel="noreferrer" style={{ color: GREEN, fontSize: 12, textDecoration: 'none', fontWeight: 700 }}>{c.title}</a>
                <span style={{ fontSize: 10, color: DIM }}>{c.channel}{c.published ? ` · ${c.published}` : ''}</span>
                <button onClick={() => submit(c.url)} disabled={busy} style={{ marginLeft: 'auto', ...box, padding: '1px 8px', fontSize: 10, cursor: busy ? 'default' : 'pointer' }}>⚙ distill</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* view switch */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['feed', 'channels', 'tickers', 'leaderboard'] as const).map((v) => (
          <button key={v} onClick={() => setView(v)} style={{ ...box, cursor: 'pointer', background: view === v ? 'rgba(0,255,65,0.18)' : '#000' }}>
            {v === 'feed' ? '📰 feed' : v === 'channels' ? '📡 channels' : v === 'tickers' ? '🎯 tickers' : '🏆 alpha leaderboard'}
          </button>
        ))}
        {view === 'feed' && (
          <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)} style={{ ...box, cursor: 'pointer', marginLeft: 'auto' }}>
            <option value="all">all categories</option>
            {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
      </div>

      {view === 'feed' && (
        <>
          {videos.length === 0 && <div style={{ ...card, fontSize: 12, color: DIM }}>No distilled videos yet. Paste a video/channel above, or hit “refresh tracked” to pull the latest from your channels.</div>}
          {videos.map((v) => <VideoCard key={v.video_id} v={v} />)}
        </>
      )}

      {view === 'channels' && (
        <>
          {Object.keys(byCat).sort().map((c) => (
            <div key={c} style={card}>
              <div style={{ fontSize: 12, color: DIM, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1 }}>{c}</div>
              {byCat[c].map((ch) => (
                <div key={ch.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '2px 0' }}>
                  <span style={{ fontWeight: 700 }}>{ch.name}</span>
                  <span style={{ color: DIM, fontSize: 10 }}>@{ch.handle || ch.id}</span>
                  <button onClick={() => removeChannel(ch.id)} style={{ marginLeft: 'auto', ...box, padding: '1px 7px', fontSize: 10, cursor: 'pointer', color: RED, borderColor: RED }}>remove</button>
                </div>
              ))}
            </div>
          ))}
          <div style={{ fontSize: 11, color: DIM }}>Add channels with the box up top (paste @handle or URL, pick a category, tick “track channel”).</div>
        </>
      )}

      {view === 'tickers' && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: DIM }}>Every ticker called across the finance feed, pivoted by symbol: crowd stance, who called it (ranked by track-record α), live price &amp; return since the first call, avg target, and a <b>consensus / contrarian</b> read — does the sharpest creator on this name agree with the crowd, or fade it? <span style={{ color: '#ff9d3c' }}>contrarian</span> = top-α creator disagrees with the crowd. Tap a row for the calls.</span>
            <button onClick={() => fetch('/api/fintube/tickers?force=true').then(r => r.json()).then(d => setTks(d.tickers || []))} style={{ marginLeft: 'auto', ...box, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>recompute</button>
          </div>
          {tks.length === 0 && <div style={{ fontSize: 12, color: DIM }}>No ticker calls yet — distill some finance videos with buy/sell/watch calls first.</div>}
          {tks.length > 0 && (
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead><tr>
                <th style={th}>ticker</th><th style={th}>calls (B/S/W)</th><th style={th}>signal</th>
                <th style={th}>price</th><th style={th}>since 1st</th><th style={th}>avg tgt</th><th style={th}>top creator</th>
              </tr></thead>
              <tbody>
                {tks.map((t) => {
                  const open = tkOpen === t.ticker;
                  return (
                    <React.Fragment key={t.ticker}>
                      <tr onClick={() => setTkOpen(open ? null : t.ticker)} style={{ cursor: 'pointer', background: open ? 'rgba(0,255,65,0.06)' : undefined }}>
                        <td style={{ ...td, fontWeight: 700 }}>{open ? '▾ ' : '▸ '}{t.ticker}</td>
                        <td style={td}>
                          <span style={{ color: GREEN }}>{t.buy}</span>/<span style={{ color: RED }}>{t.sell}</span>/<span style={{ color: AMBER }}>{t.watch}</span>
                        </td>
                        <td style={{ ...td, color: signalColor(t.signal), fontWeight: 700 }}>{t.signal}</td>
                        <td style={td}>{t.price != null ? `$${t.price}` : '—'}</td>
                        <td style={{ ...td, color: retColor(t.ret_since_first), fontWeight: 700 }}>{pct(t.ret_since_first)}</td>
                        <td style={td}>{t.avg_price_target != null ? <>${t.avg_price_target}{t.upside != null && <span style={{ color: retColor(t.upside) }}> ({pct(t.upside, 0)})</span>}</> : '—'}</td>
                        <td style={td}>{t.top_creator || '—'}{t.smart_agrees === false && <span style={{ color: '#ff9d3c' }} title="top creator fades the crowd"> ⚑</span>}</td>
                      </tr>
                      {open && (
                        <tr><td colSpan={7} style={{ ...td, paddingTop: 0, paddingBottom: 10 }}>
                          <div style={{ fontSize: 10, color: DIM, margin: '4px 0 2px' }}>
                            first call {t.first_pub || '—'} · latest {t.last_pub || '—'} · crowd lean {pct(t.crowd_lean, 0)}
                          </div>
                          {t.calls.map((c, i) => (
                            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', padding: '3px 0', borderTop: i ? `1px solid rgba(0,255,65,0.12)` : undefined }}>
                              <span style={{ color: actionColor(c.action), fontWeight: 700, fontSize: 11, minWidth: 38 }}>{c.action || '—'}</span>
                              <span style={{ fontWeight: 700, fontSize: 11 }}>{c.channel}</span>
                              {c.creator_alpha != null && <span style={{ fontSize: 10, color: c.creator_alpha >= 0 ? GREEN : RED }} title="creator track-record α">α {pct(c.creator_alpha, 0)}</span>}
                              {c.conviction && <span style={{ fontSize: 10, color: DIM }}>{c.conviction}</span>}
                              {c.horizon && <span style={{ fontSize: 10, color: DIM }}>{c.horizon}</span>}
                              {c.price_target != null && <span style={{ fontSize: 10, color: DIM }}>tgt ${c.price_target}</span>}
                              <span style={{ fontSize: 10, color: DIM }}>{c.pub}</span>
                              {c.thesis && <span style={{ fontSize: 11, color: DIM, flexBasis: '100%' }}>{c.thesis}</span>}
                              {c.url && <a href={c.url} target="_blank" rel="noreferrer" style={{ fontSize: 10, color: DIM }}>↗ {c.title?.slice(0, 60)}</a>}
                            </div>
                          ))}
                        </td></tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {view === 'leaderboard' && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: DIM }}>Each buy/sell scored over its own <b>horizon</b> (e.g. a “weeks” call judged on weeks, not months) vs SPY, signed by direction. <i>Hit rate = % that beat SPY (α&gt;0)</i>. <span style={{ color: AMBER }}>·live</span> = horizon still open, scored to date. Higher avg α = sharper picks; negative = fade candidates.</span>
            <button onClick={() => fetch('/api/fintube/leaderboard?force=true').then(r => r.json()).then(d => setLb(d.leaderboard || []))} style={{ marginLeft: 'auto', ...box, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>recompute</button>
          </div>
          {lb.length === 0 && <div style={{ fontSize: 12, color: DIM }}>No scored calls yet — distill some finance videos with ticker calls first.</div>}
          {lb.length > 0 && (
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead><tr><th style={th}>creator</th><th style={th}>calls</th><th style={th}>scored</th><th style={th}>hit rate</th><th style={th}>avg α</th><th style={th}>best picks</th></tr></thead>
              <tbody>
                {lb.map((row) => (
                  <tr key={row.channel}>
                    <td style={{ ...td, fontWeight: 700 }}>{row.channel}</td>
                    <td style={td}>{row.calls}{row.watch_calls ? <span style={{ color: DIM }}> +{row.watch_calls}👁</span> : null}</td>
                    <td style={td}>{row.scored}{row.in_flight ? <span style={{ color: AMBER }}> ·{row.in_flight} live</span> : null}</td>
                    <td style={td}>{row.hit_rate != null ? `${(row.hit_rate * 100).toFixed(0)}%` : '—'}</td>
                    <td style={{ ...td, color: row.avg_alpha == null ? DIM : row.avg_alpha >= 0 ? GREEN : RED, fontWeight: 700 }}>{row.avg_alpha != null ? `${(row.avg_alpha * 100).toFixed(1)}%` : '—'}</td>
                    <td style={{ ...td, color: DIM }}>{row.picks.slice(0, 4).map((p, i) => (
                      <span key={i}>{i ? ', ' : ''}<span style={{ color: p.alpha >= 0 ? GREEN : RED }} title={p.in_flight ? `open · ${p.horizon_days}d horizon` : `settled ${p.window_end || ''}`}>{p.ticker} {(p.alpha * 100).toFixed(0)}%{p.in_flight ? '·' : ''}</span></span>
                    ))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
