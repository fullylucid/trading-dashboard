import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import MarkdownView from './MarkdownView';
import { useIsMobile } from '../../hooks/useMediaQuery';
import { GREEN, DIM, FAINT, AMBER, RED, BLUE, card } from './ui';
import type { MemoryDoc, MemoryDocResponse, MemoryIndexEntry, MemoryIndexResponse } from './types';

// Hydra HQ 🛰️ — memory browser (Slice 3). A clean doc browser over the git-tracked memory
// knowledge base, with [[wikilinks]] rendered as in-app navigation between memory files
// (+ a backlinks panel). The visual [[link]] graph (Cytoscape) stays a later fast-follow.

const TYPE_ORDER = ['project', 'feedback', 'user', 'reference', 'note'];
const TYPE_LABEL: Record<string, string> = {
  project: 'Project', feedback: 'Feedback', user: 'User', reference: 'Reference', note: 'Notes',
};

export default function MemoryBrowser() {
  const { name } = useParams();
  const isMobile = useIsMobile();
  const [index, setIndex] = useState<MemoryIndexEntry[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    fetch('/api/hq/memory')
      .then((r) => r.json() as Promise<MemoryIndexResponse>)
      .then((d) => {
        if (!active) return;
        if (d.available && d.index) setIndex(d.index);
        else setUnavailable(true);
      })
      .catch(() => active && setUnavailable(true));
    return () => {
      active = false;
    };
  }, []);

  // group index by type
  const groups: Record<string, MemoryIndexEntry[]> = {};
  for (const e of index ?? []) (groups[e.type] ||= []).push(e);
  const orderedTypes = Object.keys(groups).sort(
    (a, b) => (TYPE_ORDER.indexOf(a) + 1 || 99) - (TYPE_ORDER.indexOf(b) + 1 || 99),
  );

  const sidebar = (
    <nav style={{ minWidth: isMobile ? undefined : 240, maxWidth: isMobile ? undefined : 280 }}>
      {unavailable && (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, fontSize: 12 }}>
          collector offline — no memory snapshot
        </div>
      )}
      {orderedTypes.map((t) => (
        <div key={t} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
            {TYPE_LABEL[t] ?? t} <span style={{ opacity: 0.6 }}>({groups[t].length})</span>
          </div>
          {groups[t].map((e) => {
            const active = e.name === name;
            return (
              <Link
                key={e.name}
                to={`/hq/memory/${e.name}`}
                title={e.description}
                style={{
                  display: 'block', padding: '4px 8px', borderRadius: 3, fontSize: 12.5,
                  textDecoration: 'none', color: GREEN, marginBottom: 1,
                  background: active ? 'rgba(0,255,65,0.15)' : 'transparent',
                  fontWeight: active ? 700 : 400,
                }}
              >
                {e.title}
                {e.n_links > 0 && <span style={{ color: DIM, fontSize: 10 }}> · {e.n_links}🔗</span>}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 16px 40px', fontFamily: 'monospace', color: GREEN }}>
      <PageHeader title="🛰️ HQ Memory" subtitle={index ? `${index.length} docs · git-tracked knowledge base` : 'loading…'} />
      <div style={{ marginBottom: 14 }}>
        <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>← fleet</Link>
      </div>

      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 20, alignItems: 'flex-start' }}>
        {sidebar}
        <main style={{ flex: 1, minWidth: 0, width: isMobile ? '100%' : undefined }}>
          {name ? <DocView name={name} /> : (
            <div style={{ color: DIM, fontSize: 13, paddingTop: 20 }}>
              Select a memory doc on the left. <span style={{ opacity: 0.7 }}>[[wikilinks]] inside a doc navigate here.</span>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function DocView({ name }: { name: string }) {
  const [doc, setDoc] = useState<MemoryDoc | null>(null);
  const [err, setErr] = useState<number | 'net' | null>(null);

  useEffect(() => {
    let active = true;
    setDoc(null);
    setErr(null);
    fetch(`/api/hq/memory/${encodeURIComponent(name)}`)
      .then((r) => {
        if (!r.ok) {
          if (active) setErr(r.status);
          return null;
        }
        return r.json() as Promise<MemoryDocResponse>;
      })
      .then((d) => {
        if (active && d?.available && d.doc) setDoc(d.doc);
      })
      .catch(() => active && setErr('net'));
    return () => {
      active = false;
    };
  }, [name]);

  if (err === 404) {
    return <div style={{ ...card, color: AMBER, borderColor: AMBER }}>no memory <code>{name}</code></div>;
  }
  if (err === 'net') {
    return <div style={{ ...card, color: RED, borderColor: RED }}>can't reach /api/hq/memory</div>;
  }
  if (!doc) return <div style={{ color: DIM, fontSize: 12 }}>loading {name}…</div>;

  const meta = [
    doc.type,
    doc.scope && `scope: ${doc.scope}`,
    doc.updated && `updated ${doc.updated}`,
    doc.confidence && `confidence: ${doc.confidence}`,
  ].filter(Boolean);

  return (
    <article>
      <h2 style={{ color: GREEN, fontSize: 20, margin: '0 0 4px', textShadow: `0 0 8px ${GREEN}` }}>{doc.title}</h2>
      <div style={{ fontSize: 11, color: DIM, marginBottom: 2 }}>{meta.join(' · ')}</div>
      {doc.description && <div style={{ fontSize: 12, color: 'rgba(0,255,65,0.7)', marginBottom: 12 }}>{doc.description}</div>}

      <div style={{ ...card, padding: '14px 18px' }}>
        <MarkdownView
          source={doc.body}
          renderWikiLink={(target, label, key) => {
            const broken = !doc.links_out.find((l) => l.name === target)?.exists;
            return broken ? (
              <span key={key} title="no such memory doc" style={{ color: DIM, textDecoration: 'line-through' }}>
                {label}
              </span>
            ) : (
              <Link key={key} to={`/hq/memory/${target}`} style={{ color: BLUE }}>{label}</Link>
            );
          }}
        />
      </div>

      {doc.links_in.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
            Linked from ({doc.links_in.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {doc.links_in.map((b) => (
              <Link
                key={b}
                to={`/hq/memory/${b}`}
                style={{
                  fontSize: 11, color: GREEN, border: `1px solid ${FAINT}`, borderRadius: 3,
                  padding: '2px 8px', textDecoration: 'none',
                }}
              >
                ← {b}
              </Link>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
