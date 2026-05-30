// Typed client for the reusable AI-explain endpoint.
//
//   POST /api/ai/explain  -> on-demand Claude (free local Opus) explanation of a
//                            dashboard datapoint (alert / regime / sector / generic)
//
// Auth rides the agent session cookie (withCredentials), same as the chart
// AI-read. Every surface calls this with a `kind` + a context blob.

import axios from 'axios';
import type { AxiosInstance } from 'axios';

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

export type ExplainKind = 'alert' | 'regime' | 'sector' | 'generic';

/** Response from POST /api/ai/explain. */
export interface ExplainResponse {
  kind: string;
  symbol?: string | null;
  /** The plain-language explanation. */
  text: string;
  model: string;
}

/** Request a short Claude explanation of a datapoint. Throws on 503 (bus down/busy). */
export async function explainDatapoint(
  kind: ExplainKind,
  context: Record<string, unknown>,
  symbol?: string,
): Promise<ExplainResponse> {
  const res = await client.post<ExplainResponse>('/ai/explain', { kind, context, symbol });
  return res.data;
}

export default { explainDatapoint };
