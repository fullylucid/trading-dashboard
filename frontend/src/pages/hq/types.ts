// Shared types for the Hydra HQ 🛰️ views (overview + room detail).

export type Status = 'working' | 'idle' | 'waiting-input' | 'offline';

export type Head = {
  name: string;
  room: string;
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

export type Fleet = {
  available: boolean;
  generated_at?: number;
  rooms?: Room[];
  heads?: Head[];
};

export type RoomDetailResponse = {
  available: boolean;
  generated_at?: number;
  room?: Room;
  heads?: Head[];
};
