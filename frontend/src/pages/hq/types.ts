// Shared types for the Hydra HQ 🛰️ views (overview + room detail).

export type Status = 'working' | 'idle' | 'waiting-input' | 'offline';
export type Role = 'conductor' | 'hq' | 'head';

export type Head = {
  name: string;
  room: string;
  role?: Role;
  category?: string;
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

export type PR = {
  number: number;
  title: string;
  branch: string | null;
  head: string | null;
  mergeable: boolean;
};

export type Doc = { key: string; label: string; path: string; markdown: string; truncated?: boolean };

export type Room = {
  id: string;
  name: string;
  repo: string | null;
  heads: string[];
  open_prs: PR[];
  docs?: Doc[];
};

export type ActivityKind = 'commit' | 'pr_opened' | 'pr_merged';

export type ActivityItem = {
  ts: number;
  kind: ActivityKind;
  head: string | null;
  room: string;
  number?: number;
  sha?: string;
  text: string;
  url?: string | null;
};

export type Category = {
  id: string;
  label: string;
  kind: 'room' | 'custom';
  room?: string;
  heads: string[];
};

export type Fleet = {
  available: boolean;
  generated_at?: number;
  rooms?: Room[];
  categories?: Category[];
  heads?: Head[];
  activity?: ActivityItem[];
  memory_index?: MemoryIndexEntry[];
};

export type RoomDetailResponse = {
  available: boolean;
  generated_at?: number;
  room?: Room;
  heads?: Head[];
};

export type Commit = { sha: string; ts: number | null; text: string };
export type Fossil = { name: string; ts: number; size: number; kind: 'session' | 'subagent' };

export type HeadDetail = Head & {
  recent_commits: Commit[];
  fossils: { count: number; files: Fossil[] };
  memory_scope: { name: string; title: string }[];
  open_prs: PR[];
};

export type HeadDetailResponse = {
  available: boolean;
  generated_at?: number;
  head?: HeadDetail;
};

export type MemoryIndexEntry = {
  name: string;
  title: string;
  description: string;
  type: string;
  scope: string | null;
  updated: string | null;
  n_links: number;
};

export type MemoryIndexResponse = {
  available: boolean;
  generated_at?: number;
  index?: MemoryIndexEntry[];
};

export type MemoryDoc = {
  name: string;
  title: string;
  description: string;
  type: string;
  scope?: string | null;
  updated?: string | null;
  confidence?: string | null;
  body: string;
  links_out: { name: string; exists: boolean }[];
  links_in: string[];
};

export type MemoryDocResponse = {
  available: boolean;
  generated_at?: number;
  doc?: MemoryDoc;
};
