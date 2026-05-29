import { create } from 'zustand';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type JobKind = 'code' | 'data' | 'brainstorm' | 'scan';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  jobId?: string;
  type?: 'chunk' | 'final' | 'error';
  approvalKind?: string | null;
  prUrl?: string | null;
  ts?: string;
}

export interface Conversation {
  conversationId: string;
  title: string;
  lastActivity?: number;
}

export interface Geometry {
  x: number;
  y: number;
  w: number;
  h: number;
  open: boolean;
  collapsed: boolean;
}

const GEOMETRY_KEY = 'messenger.geometry.v1';

const DEFAULT_GEOMETRY: Geometry = {
  x: Math.max(20, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 460),
  y: 80,
  w: 440,
  h: 560,
  open: false,
  collapsed: false,
};

function loadGeometry(): Geometry {
  try {
    const raw = localStorage.getItem(GEOMETRY_KEY);
    if (raw) return { ...DEFAULT_GEOMETRY, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_GEOMETRY;
}

function saveGeometry(g: Geometry) {
  try {
    localStorage.setItem(GEOMETRY_KEY, JSON.stringify(g));
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// API helpers (relative /api, Vite proxies in dev; same-origin in prod)
// ---------------------------------------------------------------------------

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`/api/agent${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  return res;
}

function wsUrl(ticket: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/agent?ticket=${encodeURIComponent(ticket)}`;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface MessengerState {
  authed: boolean;
  agentWsConnected: boolean;
  conversations: Conversation[];
  activeConversationId: string | null;
  messages: Record<string, ChatMessage[]>;
  geometry: Geometry;
  ws: WebSocket | null;

  // geometry / widget
  setGeometry: (patch: Partial<Geometry>) => void;
  toggleOpen: () => void;
  toggleCollapsed: () => void;

  // auth
  login: (password: string) => Promise<boolean>;

  // conversations
  loadConversations: () => Promise<void>;
  newConversation: () => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  selectConversation: (id: string) => Promise<void>;

  // messaging
  send: (content: string, kind: JobKind) => Promise<void>;
  approve: (jobId: string, action: 'merge' | 'reject') => Promise<void>;

  // websocket
  connectWs: () => Promise<void>;
  disconnectWs: () => void;
}

const useMessengerStore = create<MessengerState>((set, get) => ({
  authed: false,
  agentWsConnected: false,
  conversations: [],
  activeConversationId: null,
  messages: {},
  geometry: loadGeometry(),
  ws: null,

  setGeometry: (patch) =>
    set((s) => {
      const geometry = { ...s.geometry, ...patch };
      saveGeometry(geometry);
      return { geometry };
    }),

  toggleOpen: () =>
    set((s) => {
      const geometry = { ...s.geometry, open: !s.geometry.open };
      saveGeometry(geometry);
      return { geometry };
    }),

  toggleCollapsed: () =>
    set((s) => {
      const geometry = { ...s.geometry, collapsed: !s.geometry.collapsed };
      saveGeometry(geometry);
      return { geometry };
    }),

  login: async (password) => {
    const res = await api('/login', { method: 'POST', body: JSON.stringify({ password }) });
    if (!res.ok) return false;
    set({ authed: true });
    await get().loadConversations();
    await get().connectWs();
    return true;
  },

  loadConversations: async () => {
    const res = await api('/conversations');
    if (!res.ok) return;
    const data = await res.json();
    const conversations: Conversation[] = (data.conversations || []).map((c: any) => ({
      conversationId: c.conversation_id,
      title: c.title,
      lastActivity: c.last_activity,
    }));
    set({ conversations });
    if (!get().activeConversationId && conversations.length) {
      await get().selectConversation(conversations[0].conversationId);
    }
  },

  newConversation: async () => {
    const res = await api('/conversations', { method: 'POST', body: JSON.stringify({}) });
    if (!res.ok) return;
    const data = await res.json();
    const conv: Conversation = { conversationId: data.conversation_id, title: data.title };
    set((s) => ({
      conversations: [conv, ...s.conversations],
      activeConversationId: conv.conversationId,
      messages: { ...s.messages, [conv.conversationId]: [] },
    }));
  },

  deleteConversation: async (id) => {
    await api(`/conversations/${id}`, { method: 'DELETE' });
    set((s) => {
      const conversations = s.conversations.filter((c) => c.conversationId !== id);
      const messages = { ...s.messages };
      delete messages[id];
      const activeConversationId =
        s.activeConversationId === id ? conversations[0]?.conversationId ?? null : s.activeConversationId;
      return { conversations, messages, activeConversationId };
    });
  },

  selectConversation: async (id) => {
    set({ activeConversationId: id });
    const res = await api(`/history?conversation_id=${encodeURIComponent(id)}`);
    if (!res.ok) return;
    const data = await res.json();
    const msgs: ChatMessage[] = (data.turns || []).map((t: any) => ({
      role: t.role,
      content: t.content,
      jobId: t.job_id,
      type: t.type,
      approvalKind: t.approval_kind,
      prUrl: t.pr_url,
      ts: t.ts,
    }));
    set((s) => ({ messages: { ...s.messages, [id]: msgs } }));
  },

  send: async (content, kind) => {
    const cid = get().activeConversationId;
    if (!cid) return;
    set((s) => ({
      messages: {
        ...s.messages,
        [cid]: [...(s.messages[cid] || []), { role: 'user', content }],
      },
    }));
    await api('/enqueue', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: cid, kind, content }),
    });
  },

  approve: async (jobId, action) => {
    await api('/approve', { method: 'POST', body: JSON.stringify({ job_id: jobId, action }) });
  },

  connectWs: async () => {
    if (get().ws) return;
    const res = await api('/ws-ticket');
    if (!res.ok) return;
    const { ticket } = await res.json();
    const ws = new WebSocket(wsUrl(ticket));

    ws.onopen = () => {
      set({ agentWsConnected: true });
      // Subscribe to every known conversation channel.
      const channels = get().conversations.map((c) => `chat:${c.conversationId}`);
      const active = get().activeConversationId;
      if (active) channels.push(`chat:${active}`);
      ws.send(JSON.stringify({ action: 'subscribe', symbols: Array.from(new Set(channels)) }));
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type !== 'chat') return;
        const payload = msg.data;
        const cid = payload.conversation_id;
        if (!cid) return;

        if (payload.type === 'title_update') {
          set((s) => ({
            conversations: s.conversations.map((c) =>
              c.conversationId === cid ? { ...c, title: payload.title } : c
            ),
          }));
          return;
        }

        const incoming: ChatMessage = {
          role: 'assistant',
          content: payload.content,
          jobId: payload.job_id,
          type: payload.type,
          approvalKind: payload.approval_kind,
          prUrl: payload.pr_url,
          ts: payload.ts,
        };
        set((s) => ({
          messages: { ...s.messages, [cid]: [...(s.messages[cid] || []), incoming] },
        }));
      } catch {
        /* ignore malformed */
      }
    };

    const reconnect = () => {
      set({ agentWsConnected: false, ws: null });
      if (get().authed) setTimeout(() => get().connectWs(), 3000);
    };
    ws.onclose = reconnect;
    ws.onerror = () => ws.close();

    set({ ws });
  },

  disconnectWs: () => {
    const ws = get().ws;
    if (ws) ws.close();
    set({ ws: null, agentWsConnected: false });
  },
}));

export default useMessengerStore;
