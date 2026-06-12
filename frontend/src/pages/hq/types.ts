// Shared types for the Hydra HQ 🛰️ views (overview + room detail).

export type Status = 'working' | 'idle' | 'waiting-input' | 'offline' | 'dormant';
export type Role = 'conductor' | 'hq' | 'head' | 'lead' | 'director';

export type Head = {
  name: string;
  room: string;
  role?: Role;
  category?: string;
  source?: 'bus';        // external/heartbeat head (no tmux/git)
  kind?: string;         // e.g. 'windows' — badge hint for external heads
  tick?: number | null;  // bus heartbeat tick
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

// HQ Console (CONSOLE.md Slice 1) — a head's live conversation
export type ConsoleBlock =
  | { kind: 'text'; text: string }
  | { kind: 'thinking'; text: string }
  | { kind: 'tool_use'; name: string; input: string }
  | { kind: 'tool_result'; text: string; is_error: boolean };

export type ConsoleTurn = {
  uuid: string | null;
  type: 'user' | 'assistant' | 'system';
  timestamp: string | null;
  blocks: ConsoleBlock[];
};

// F6: a menu a waiting head is blocked on — surfaced as tappable buttons in the console.
export type MenuPrompt = {
  kind: 'permission' | 'question';
  nav: 'number' | 'arrow';
  question: string;
  options: { index: number; label: string }[];
};

export type TranscriptResponse = {
  available: boolean;
  reason?: string;
  status?: Status | null;   // head busy-state — the console derives the "queued" message state
  prompt?: MenuPrompt | null;   // F6: the menu this head is waiting on (or null)
  file?: string | null;
  rotated?: boolean;
  cursor?: number;
  turns?: ConsoleTurn[];
};

export type SlashCommand = { name: string; desc: string; source: 'builtin' | 'skill' | 'custom' };
export type CommandsResponse = { available: boolean; commands: SlashCommand[]; counts?: Record<string, number> };

export type RoadmapNode = {
  text: string;
  checked: boolean | null;            // null = group/heading (no checkbox)
  owner: string | null;
  milestone: string | null;
  status?: 'done' | 'in_progress' | 'planned' | 'group';
  pr?: { number: number; state: string; title: string } | null;
  children: RoadmapNode[];
};
export type Roadmap = {
  source: string;
  repo: string | null;
  nodes: RoadmapNode[];
  progress: { done: number; total: number };
  milestones: string[];
  active_milestone?: string | null;
};
export type RoadmapResponse = { available: boolean; generated_at?: number; roadmap: Roadmap | null };

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
