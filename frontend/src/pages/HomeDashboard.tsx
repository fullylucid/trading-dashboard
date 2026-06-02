import { useEffect, useState, useCallback } from 'react';

const GREEN = '#00ff41';
const RED = '#ff5555';
const AMBER = '#ffcc00';
const DIM = 'rgba(0,255,65,0.55)';
const card: React.CSSProperties = { border: `1px solid ${DIM}`, borderRadius: 8, padding: '12px 14px', background: 'rgba(0,255,65,0.03)' };

// ---------------------------------------------------------------- stale-while-revalidate
function useCached<T>(key: string, url: string, initial: T) {
  const [data, setData] = useState<T>(() => {
    try { const c = localStorage.getItem('home:' + key); return c ? (JSON.parse(c) as T) : initial; } catch { return initial; }
  });
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await fetch(url);
      if (r.ok) { const j = await r.json(); setData(j); try { localStorage.setItem('home:' + key, JSON.stringify(j)); } catch { /* quota */ } }
    } catch { /* keep cached */ } finally { setRefreshing(false); }
  }, [key, url]);
  useEffect(() => { load(); const id = setInterval(load, 60000); return () => clearInterval(id); }, [load]);
  return { data, refreshing, reload: load };
}

// ---------------------------------------------------------------- tiny markdown (brief)
function mdToHtml(md: string): string {
  return md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*([^*]+)\*/g, '<b style="color:#00ff41">$1</b>')
    .replace(/_([^_]+)_/g, '<i style="opacity:.85">$1</i>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#7fdfff">$1</a>')
    .replace(/\n/g, '<br/>');
}

// ---------------------------------------------------------------- types (loose)
type FeedItem = { id: string; type: 'brief' | 'news' | 'signal'; ts: number; tag: string; title: string; source: string; summary?: string; body?: string; url?: string };
type Account = { name: string; number?: string; total_value?: number };

const fmtUsd = (n?: number) => n == null ? '—' : '$' + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const sinceTs = (ms: number) => { const s = (Date.now() - ms) / 1000; if (s < 3600) return `${Math.round(s / 60)}m`; if (s < 86400) return `${Math.round(s / 3600)}h`; return `${Math.round(s / 86400)}d`; };

export default function HomeDashboard() {
  const port = useCached<any>('portfolio', '/api/portfolio/', { data: {} });
  const brief = useCached<any>('brief', '/api/brief/latest', {});
  const news = useCached<any>('news', '/api/news/market?limit=25', { articles: [] });
  const signals = useCached<any>('signals', '/api/signals', { signals: [] });
  const [open, setOpen] = useState<FeedItem | null>(null);

  const refreshing = port.refreshing || brief.refreshing || news.refreshing || signals.refreshing;

  // ---- build the unified feed ----
  const feed: FeedItem[] = [];
  const b = brief.data;
  if (b?.brief_markdown) {
    feed.push({ id: 'brief-' + (b.date || ''), type: 'brief', ts: Date.parse(b.date + 'T06:00:00') || Date.now(), tag: '🌅 Crack-a-Dawn', title: `Pre-market brief — ${b.date || 'today'}`, source: 'Charlotte', summary: (b.brief_markdown.split('\n').slice(0, 2).join(' ').replace(/[*_]/g, '').slice(0, 160)), body: b.brief_markdown });
  }
  for (const a of (news.data?.articles || []) as any[]) {
    feed.push({ id: 'news-' + (a.id || a.url || a.title), type: 'news', ts: Date.parse(a.datetime || a.published || a.published_at || '') || Date.now(), tag: '📰 ' + (a.source || 'News'), title: a.title || a.headline || 'Untitled', source: a.source || 'News', summary: a.summary || a.description, url: a.url || a.link, body: a.summary || a.description });
  }
  for (const s of (signals.data?.signals || []) as any[]) {
    feed.push({ id: 'sig-' + (s.symbol || '') + (s.created_at || ''), type: 'signal', ts: Date.parse(s.created_at || '') || Date.now(), tag: '📡 Signal', title: `${s.symbol} — ${s.action || s.type || 'signal'}`, source: 'Scanner', summary: s.thesis || s.reason, body: s.thesis || s.reason });
  }
  feed.sort((x, y) => (x.type === 'brief' ? 1e15 : x.ts) < (y.type === 'brief' ? 1e15 : y.ts) ? 1 : -1);

  // ---- portfolio (accounts sorted high -> low) ----
  const pdata = port.data?.data || {};
  const accounts: Account[] = [...(pdata.accounts || [])].sort((a, b2) => (b2.total_value || 0) - (a.total_value || 0));
  const totalVal = pdata.account_value ?? accounts.reduce((s, a) => s + (a.total_value || 0), 0);
  const maxAcct = Math.max(1, ...accounts.map((a) => a.total_value || 0));

  const wrap: React.CSSProperties = { minHeight: '100vh', background: '#000', color: GREEN, fontFamily: 'monospace', padding: '52px 14px 60px', maxWidth: 1280, margin: '0 auto' };

  return (
    <div style={wrap}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>📈 Home</h2>
        {refreshing && <span style={{ fontSize: 10, color: DIM, border: `1px solid ${DIM}`, borderRadius: 10, padding: '1px 8px' }}>↻ refreshing…</span>}
      </div>

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {/* ---------- LEFT 3/4: feed ---------- */}
        <div style={{ flex: '3 1 520px', minWidth: 300, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {feed.length === 0 && <div style={{ ...card, color: DIM, fontSize: 12 }}>Feed is warming up — Crack-a-Dawn, news and signals will populate here.</div>}
          {feed.map((it) => (
            <div key={it.id} onClick={() => setOpen(it)} style={{ ...card, cursor: 'pointer',
              borderColor: it.type === 'brief' ? GREEN : DIM, background: it.type === 'brief' ? 'rgba(0,255,65,0.07)' : 'rgba(0,255,65,0.03)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10, color: DIM }}>{it.tag}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10, color: DIM }}>{sinceTs(it.ts)} ago</span>
              </div>
              <div style={{ fontSize: it.type === 'brief' ? 15 : 13, fontWeight: 700, marginTop: 3, color: GREEN }}>{it.title}</div>
              {it.summary && <div style={{ fontSize: 12, color: 'rgba(0,255,65,0.8)', marginTop: 4, lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{it.summary}</div>}
              <div style={{ fontSize: 10, color: DIM, marginTop: 5 }}>click to open →</div>
            </div>
          ))}
        </div>

        {/* ---------- RIGHT 1/4: portfolio ---------- */}
        <div style={{ flex: '1 1 240px', minWidth: 230, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={card}>
            <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1 }}>Portfolio value</div>
            <div style={{ fontSize: 26, fontWeight: 700, color: GREEN }}>{fmtUsd(totalVal)}</div>
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: DIM, marginTop: 2 }}>
              <span>cash {fmtUsd(pdata.cash)}</span><span>BP {fmtUsd(pdata.buying_power)}</span>
            </div>
          </div>
          <div style={card}>
            <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Accounts (high → low)</div>
            {accounts.map((a) => (
              <div key={a.number || a.name} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', fontSize: 11, alignItems: 'baseline' }}>
                  <span style={{ fontWeight: 700 }}>{a.name}</span>
                  <span style={{ color: DIM, marginLeft: 6 }}>···{a.number}</span>
                  <span style={{ marginLeft: 'auto', color: GREEN }}>{fmtUsd(a.total_value)}</span>
                </div>
                <div style={{ height: 4, background: 'rgba(0,255,65,0.12)', borderRadius: 2, marginTop: 3 }}>
                  <div style={{ height: '100%', width: `${Math.max(2, ((a.total_value || 0) / maxAcct) * 100)}%`, background: GREEN, borderRadius: 2 }} />
                </div>
              </div>
            ))}
            {accounts.length === 0 && <div style={{ fontSize: 11, color: DIM }}>No accounts loaded.</div>}
          </div>
          {Array.isArray(pdata.positions) && pdata.positions.length > 0 && (
            <div style={card}>
              <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Top holdings</div>
              {[...pdata.positions].sort((p: any, q: any) => (q.market_value || q.current_value || 0) - (p.market_value || p.current_value || 0)).slice(0, 8).map((p: any) => (
                <div key={p.symbol} style={{ display: 'flex', fontSize: 11, padding: '2px 0' }}>
                  <span style={{ fontWeight: 700 }}>{p.symbol}</span>
                  <span style={{ marginLeft: 'auto' }}>{fmtUsd(p.market_value || p.current_value)}</span>
                  <span style={{ width: 56, textAlign: 'right', color: (p.unrealized_pl_pct ?? p.gain_loss_pct ?? 0) >= 0 ? GREEN : RED }}>
                    {(p.unrealized_pl_pct ?? p.gain_loss_pct ?? 0) >= 0 ? '+' : ''}{(p.unrealized_pl_pct ?? p.gain_loss_pct ?? 0).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---------- reader overlay ---------- */}
      {open && (
        <div onClick={() => setOpen(null)} style={{ position: 'fixed', inset: 0, zIndex: 1600, background: 'rgba(0,0,0,0.7)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '40px 14px', overflowY: 'auto' }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: '#000', border: `1px solid ${GREEN}`, borderRadius: 10, maxWidth: 760, width: '100%', padding: '18px 20px', boxShadow: '0 10px 40px rgba(0,0,0,0.7)' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 10, color: DIM }}>{open.tag} · {open.source}</span>
              <button onClick={() => setOpen(null)} style={{ marginLeft: 'auto', background: '#000', color: GREEN, border: `1px solid ${DIM}`, borderRadius: 4, cursor: 'pointer', fontFamily: 'monospace', padding: '3px 10px' }}>✕</button>
            </div>
            <h3 style={{ margin: '0 0 10px', fontSize: 16, color: GREEN }}>{open.title}</h3>
            {open.type === 'brief'
              ? <div style={{ fontSize: 13, lineHeight: 1.6 }} dangerouslySetInnerHTML={{ __html: mdToHtml(open.body || '') }} />
              : <div style={{ fontSize: 13, lineHeight: 1.6, color: 'rgba(0,255,65,0.85)', whiteSpace: 'pre-wrap' }}>{open.body || open.summary || 'No content.'}</div>}
            {open.url && <div style={{ marginTop: 14 }}><a href={open.url} target="_blank" rel="noreferrer" style={{ color: '#7fdfff', fontSize: 12 }}>Open original ↗</a></div>}
          </div>
        </div>
      )}
    </div>
  );
}
