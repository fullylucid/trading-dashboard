import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import MarkdownView from './MarkdownView';
import { GREEN, DIM, FAINT, AMBER, RED, BLUE, card, HeadCard, Pill } from './ui';
import type { RoomDetailResponse } from './types';

// Hydra HQ 🛰️ — project room detail (Slice 2). One repo's heads + open-PR queue + its
// rendered key docs (README / blueprint / roadmap / architecture), tabbed.

export default function RoomDetail() {
  const { id = '' } = useParams();
  const [data, setData] = useState<RoomDetailResponse | null>(null);
  const [err, setErr] = useState<number | 'net' | null>(null);
  const [activeDoc, setActiveDoc] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const r = await fetch(`/api/hq/room/${encodeURIComponent(id)}`);
        if (!r.ok) {
          if (active) setErr(r.status);
          return;
        }
        if (active) {
          setData(await r.json());
          setErr(null);
        }
      } catch {
        if (active) setErr('net');
      }
    };
    load();
    const t = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [id]);

  const room = data?.room;
  const heads = data?.heads ?? [];
  const docs = room?.docs ?? [];
  const current = docs.find((d) => d.key === activeDoc) ?? docs[0];

  const backLink = (
    <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>
      ← fleet
    </Link>
  );

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 16px 40px', fontFamily: 'monospace', color: GREEN }}>
      <PageHeader title={`🛰️ ${room?.name ?? id}`} subtitle={room?.repo ?? undefined} />

      <div style={{ marginBottom: 14 }}>{backLink}</div>

      {err === 404 && (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center' }}>
          no room <code style={{ color: GREEN }}>{id}</code> in the current snapshot
        </div>
      )}
      {err === 'net' && !data && (
        <div style={{ ...card, color: RED, borderColor: RED, textAlign: 'center' }}>can't reach /api/hq</div>
      )}
      {data && data.available === false && (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center' }}>
          collector offline — no snapshot yet
        </div>
      )}

      {room && (
        <>
          {/* heads */}
          <SectionTitle>
            Heads <span style={{ color: DIM, fontWeight: 400, fontSize: 12 }}>({heads.length})</span>
          </SectionTitle>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', marginBottom: 22 }}>
            {heads.map((h) => <HeadCard key={h.name} head={h} />)}
          </div>

          {/* PR queue */}
          <SectionTitle>
            Open PRs <span style={{ color: DIM, fontWeight: 400, fontSize: 12 }}>({room.open_prs.length})</span>
          </SectionTitle>
          {room.open_prs.length === 0 ? (
            <div style={{ color: DIM, fontSize: 12, marginBottom: 22 }}>none open</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 22 }}>
              {room.open_prs.map((pr) => (
                <a
                  key={pr.number}
                  href={room.repo ? `https://github.com/${room.repo}/pull/${pr.number}` : undefined}
                  target="_blank"
                  rel="noreferrer"
                  style={{ ...card, display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', color: GREEN }}
                >
                  <span style={{ color: DIM, fontSize: 12 }}>#{pr.number}</span>
                  <span style={{ fontSize: 13, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {pr.title}
                  </span>
                  {pr.head && <Pill color={BLUE}>{pr.head}</Pill>}
                  <Pill color={pr.mergeable ? GREEN : AMBER}>{pr.mergeable ? 'mergeable' : 'conflicts'}</Pill>
                </a>
              ))}
            </div>
          )}

          {/* docs */}
          <SectionTitle>Docs</SectionTitle>
          {docs.length === 0 ? (
            <div style={{ color: DIM, fontSize: 12 }}>no key docs found in this repo's main checkout</div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {docs.map((d) => {
                  const on = current?.key === d.key;
                  return (
                    <button
                      key={d.key}
                      type="button"
                      onClick={() => setActiveDoc(d.key)}
                      title={d.path}
                      style={{
                        background: on ? 'rgba(0,255,65,0.15)' : '#000',
                        color: GREEN, border: `1px solid ${on ? GREEN : FAINT}`, borderRadius: 4,
                        padding: '4px 10px', fontFamily: 'monospace', fontSize: 12, cursor: 'pointer',
                      }}
                    >
                      {d.label}
                    </button>
                  );
                })}
              </div>
              {current && (
                <div style={{ ...card, padding: '14px 18px' }}>
                  <div style={{ fontSize: 10, color: DIM, marginBottom: 8 }}>
                    {current.path}{current.truncated ? ' · truncated' : ''}
                  </div>
                  <MarkdownView source={current.markdown} />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ color: GREEN, fontWeight: 700, fontSize: 15, margin: '0 0 8px' }}>{children}</div>;
}
