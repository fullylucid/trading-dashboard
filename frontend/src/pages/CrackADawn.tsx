import { useState, useEffect, ReactNode } from 'react';

const GREEN = '#00ff41';

type Brief = { date: string; brief_markdown: string; movers: any[] };

// --- tiny renderer for the Telegram-flavored markdown the agent writes ---
// handles *bold*, _italic_, [text](url), • bullets, emojis, line breaks. JSX (no innerHTML).
function inline(text: string, key: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /\[([^\]]+)\]\(([^)]+)\)|\*([^*]+)\*|_([^_]+)_/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1]) {
      nodes.push(
        <a key={`${key}-${i}`} href={m[2]} target="_blank" rel="noopener noreferrer"
           style={{ color: '#7fdfff' }}>{m[1]}</a>,
      );
    } else if (m[3]) {
      nodes.push(<strong key={`${key}-${i}`} style={{ color: GREEN }}>{m[3]}</strong>);
    } else if (m[4]) {
      nodes.push(<em key={`${key}-${i}`} style={{ opacity: 0.85 }}>{m[4]}</em>);
    }
    last = re.lastIndex;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function Markdown({ md }: { md: string }) {
  return (
    <div style={{ lineHeight: 1.55, fontSize: 14 }}>
      {md.split('\n').map((line, idx) => {
        if (!line.trim()) return <div key={idx} style={{ height: 8 }} />;
        const bullet = line.trimStart().startsWith('•');
        const body = bullet ? line.trimStart().slice(1).trim() : line;
        return (
          <div key={idx} style={{ paddingLeft: bullet ? 16 : 0, marginBottom: 2, display: 'flex' }}>
            {bullet && <span style={{ color: GREEN, marginRight: 8 }}>•</span>}
            <span>{inline(body, String(idx))}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function CrackADawn() {
  const [dates, setDates] = useState<string[]>([]);
  const [sel, setSel] = useState<string>('');
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const d = await (await fetch('/api/brief/dates')).json();
        setDates(d.dates || []);
        const latest = await fetch('/api/brief/latest');
        if (latest.ok) {
          const b = await latest.json();
          setBrief(b);
          setSel(b.date);
        } else {
          setErr('No briefs yet — Crack-a-Dawn runs at 6 AM PT on trading days.');
        }
      } catch {
        setErr('Could not reach the brief service.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const pick = async (date: string) => {
    setSel(date);
    setLoading(true);
    setErr('');
    try {
      const r = await fetch(`/api/brief/${date}`);
      if (r.ok) setBrief(await r.json());
      else setErr('No brief for that date.');
    } catch {
      setErr('Could not load that brief.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#000', color: GREEN,
                  fontFamily: 'monospace', padding: '16px 16px 24px', maxWidth: 760, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h1 style={{ fontSize: 20, margin: 0, textShadow: `0 0 8px ${GREEN}` }}>🌅 Crack-a-Dawn</h1>
        {dates.length > 0 && (
          <label style={{ fontSize: 12, opacity: 0.8 }}>
            archive&nbsp;
            <select value={sel} onChange={(e) => pick(e.target.value)}
                    style={{ background: '#000', color: GREEN, border: `1px solid ${GREEN}`,
                             borderRadius: 4, fontFamily: 'monospace', padding: '4px 6px' }}>
              {dates.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
        )}
      </div>

      <div style={{ border: `1px solid rgba(0,255,65,0.35)`, borderRadius: 6,
                    padding: 16, background: 'rgba(0,255,65,0.03)',
                    boxShadow: '0 0 14px rgba(0,255,65,0.15)' }}>
        {loading && <div style={{ opacity: 0.7 }}>loading…</div>}
        {!loading && err && <div style={{ opacity: 0.7 }}>{err}</div>}
        {!loading && !err && brief && <Markdown md={brief.brief_markdown} />}
      </div>
    </div>
  );
}
