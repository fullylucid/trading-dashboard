// scoutApi — client for the charting-ideas scout (backend /api/charting/*).
// The scout mines charting techniques from sources, has the AI express each as a
// constrained indicator spec, and stages them as idea cards for review → demo →
// accept-into-arsenal. See backend/charting_scout.py.

import axios from 'axios';

import type { ArsenalItem, IndicatorSpec } from './indicatorApi';

export interface ScoutIdea {
  id: string;
  title: string;
  technique: string;
  description: string;
  why_useful: string;
  confidence: number;
  source_type: string;
  source_url: string;
  spec: IndicatorSpec | null;
  spec_valid: boolean;
  spec_errors: string[];
  created_at: string;
  accepted: boolean;
  arsenal_id: string | null;
}

export interface ScoutSource {
  name: string;
  implemented: boolean;
}

export async function listIdeas(limit = 80): Promise<ScoutIdea[]> {
  const { data } = await axios.get<{ ideas: ScoutIdea[] }>('/api/charting/ideas', {
    params: { limit },
  });
  return data.ideas ?? [];
}

export async function listSources(): Promise<ScoutSource[]> {
  const { data } = await axios.get<{ sources: ScoutSource[] }>('/api/charting/sources');
  return data.sources ?? [];
}

export async function runScout(sources?: string[], max = 12): Promise<{ status: string }> {
  const { data } = await axios.post<{ status: string }>('/api/charting/scout', { sources, max });
  return data;
}

/** Promote an idea's validated spec into the arsenal. */
export async function acceptIdea(id: string, tags: string[] = []): Promise<ArsenalItem> {
  const { data } = await axios.post<ArsenalItem>(`/api/charting/ideas/${id}/accept`, { tags });
  return data;
}

export async function deleteIdea(id: string): Promise<boolean> {
  const { data } = await axios.delete<{ deleted: boolean }>(`/api/charting/ideas/${id}`);
  return data.deleted;
}
