export interface ApiError extends Error {
  status: number;
  body?: unknown;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let payload: unknown;
    try { payload = await res.json(); } catch { /* not json */ }
    const err = new Error(`${method} ${path} → ${res.status}`) as ApiError;
    err.status = res.status;
    err.body = payload;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json() as Promise<T>;
  return res.text() as unknown as T;
}

export const api = {
  get:    <T>(p: string)               => request<T>('GET',    p),
  post:   <T>(p: string, body?: any)   => request<T>('POST',   p, body),
  put:    <T>(p: string, body?: any)   => request<T>('PUT',    p, body),
  patch:  <T>(p: string, body?: any)   => request<T>('PATCH',  p, body),
  delete: <T>(p: string)               => request<T>('DELETE', p),
};

// ---------- 类型 ----------
export interface WorldSummary {
  id: string;
  name: string;
  description?: string;
  current_tick?: number;
  active_branch_id?: string | null;
}

export interface WorldDetail {
  id: string;
  name: string;
  description?: string;
  outline?: string;
  current_tick?: number;
  max_tick?: number;
  branch_id?: string;
  rules?: Record<string, unknown>;
  style_profile_id?: string;
}

export interface WorldEntity {
  id: string;
  name: string;
  type?: string;
  summary?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  state?: Record<string, unknown>;
  persona?: Record<string, unknown>;
  memories?: Array<{ tick?: number; text?: string; [k: string]: unknown }>;
  location_id?: string | null;
  map_x?: number | null;
  map_y?: number | null;
  tags?: string[];
  pinned?: number;
}

export interface WorldEvent {
  id: string;
  tick: number;
  title: string;
  description?: string;
  participants?: string[];
  location_id?: string;
}

export interface WorldSnapshot {
  world: WorldDetail;
  entities: WorldEntity[];
  recent_events: WorldEvent[];
  [k: string]: unknown;
}

// ---------- 端点 ----------
export const worldsApi = {
  list: () => api.get<WorldSummary[]>('/api/worlds'),
  get:  (id: string) => api.get<WorldSnapshot>(`/api/worlds/${id}`),
  create: (payload: { name: string; description?: string; outline?: string }) =>
    api.post<{ id: string; active_branch_id: string }>('/api/worlds', {
      name: payload.name,
      description: payload.description ?? '',
      outline: payload.outline ?? '',
      rules: {},
    }),
  update: (id: string, body: {
    name?: string; description?: string; outline?: string;
    rules?: Record<string, unknown>; style_profile_id?: string;
  }) => api.patch<{ ok: boolean; id: string; name: string; description?: string; outline?: string }>(
    `/api/worlds/${id}`, body,
  ),
  setMaxTick: (id: string, max_tick: number) =>
    api.post<{ max_tick: number; current_tick: number }>(`/api/worlds/${id}/max_tick`, { max_tick }),
  remove: (id: string) => api.delete<{ ok: boolean }>(`/api/worlds/${id}`),
  timeline: (id: string, branchId?: string) =>
    api.get<TimelinePayload>(
      `/api/worlds/${id}/timeline${branchId ? `?branch_id=${encodeURIComponent(branchId)}` : ''}`,
    ),
  importJson: (payload: Record<string, unknown>, newName?: string) =>
    api.post<{ ok: boolean; world_id: string }>('/api/worlds/import', {
      payload, new_name: newName,
    }),
  fromManuscript: (body: { name: string; text: string; description?: string }) =>
    api.post<{
      ok: boolean; world_id: string; active_branch_id: string;
      stats: { chunks: number; outline: number; cast: number; locations: number; factions: number };
      warnings: string[];
    }>('/api/worlds/from_manuscript', body),
  manuscriptState: (id: string) =>
    api.get<ManuscriptState>(`/api/worlds/${id}/manuscript/state`),
  extractManuscriptEvents: (id: string, chapterIndices?: number[]) =>
    api.post<{ job_id: string }>(
      `/api/worlds/${id}/manuscript/extract_events_async`,
      chapterIndices && chapterIndices.length ? { chapter_indices: chapterIndices } : {},
    ),
  commitManuscriptEvents: (id: string, events: ManuscriptDraftEvent[], clearDraft = true) =>
    api.post<{ ok: boolean; written: number; causal_links_written?: number; current_tick: number }>(
      `/api/worlds/${id}/manuscript/commit_events`,
      {
        events: events.map(e => ({
          title: e.title,
          description: e.description,
          tick: e.tick,
          chapter_index: e.chapter_index,
          participant_ids: e.participant_ids || [],
          location_id: e.location_id ?? null,
          causes: e.causes || [],
        })),
        clear_draft: clearDraft,
      },
    ),
  discardManuscriptDraft: (id: string) =>
    api.delete<{ ok: boolean }>(`/api/worlds/${id}/manuscript/draft`),
};

export interface ManuscriptDraftEvent {
  chapter_index: number;
  chapter_title: string;
  title: string;
  description: string;
  participant_names: string[];
  participant_ids: string[];
  unresolved_names: string[];
  location_name: string;
  location_id: string | null;
  tick: number;
  causes?: number[];
}

export interface ManuscriptState {
  has_manuscript: boolean;
  chapter_count: number;
  chapters: Array<{ index: number; title: string; char_count: number }>;
  draft_event_count: number;
  draft_events: ManuscriptDraftEvent[];
}

// ---------- 章节 ----------
export interface ChapterMarker {
  id: string;
  tick: number;
  title: string;
  note: string;
  summary: string;
}

export interface TimelineEvent {
  id: string;
  tick: number;
  title: string;
  description?: string;
  participants?: string[];
  location_id?: string;
  consequences?: string;
}

export interface CausalLinkEdge {
  cause: string;
  effect: string;
  description?: string;
  weight?: number;
}

export interface PlotThread {
  id: string;
  title: string;
  summary: string;
  status: 'open' | 'closed' | string;
  opened_tick: number;
  closed_tick: number | null;
  resolution: string;
  related_entity_ids: string[];
}

export interface TimelineNarration {
  id: string;
  tick: number;
  text: string;
  role: string;
  parent_log_id?: string;
  revision_index?: number;
}

export interface TimelinePayload {
  events: TimelineEvent[];
  links: CausalLinkEdge[];
  narration: TimelineNarration[];
  plot_threads: PlotThread[];
  pacing: unknown;
}

export const chaptersApi = {
  list: (worldId: string) =>
    api.get<{ chapters: ChapterMarker[] }>(`/api/worlds/${worldId}/chapters`).then(r => r.chapters),
  create: (worldId: string, payload: { tick: number; title?: string; note?: string }) =>
    api.post<ChapterMarker>(`/api/worlds/${worldId}/chapters`, {
      tick: payload.tick,
      title: payload.title ?? '',
      note: payload.note ?? '',
    }),
  patch: (chapterId: string, payload: { title?: string; note?: string; tick?: number }) =>
    api.patch<ChapterMarker>(`/api/chapters/${chapterId}`, payload),
  remove: (chapterId: string) =>
    api.delete<{ ok: boolean }>(`/api/chapters/${chapterId}`),
  auto: (worldId: string, body: { target_count?: number; provider?: string }) =>
    api.post<{ chapters?: ChapterMarker[]; ok?: boolean }>(`/api/worlds/${worldId}/chapters/auto`, body),
};

// ---------- 异步 Job ----------
export interface JobToolCall {
  name: string;
  arguments?: Record<string, any>;
  status?: string;
  result?: unknown;
  [k: string]: unknown;
}

export interface JobStatus {
  id: string;
  world_id?: string;
  kind?: string;
  status: 'pending' | 'running' | 'completed' | 'error' | 'cancelled';
  progress_message?: string;
  tool_calls?: JobToolCall[];
  narration?: string;
  result?: any;
  error?: string;
  started_at?: number;
  finished_at?: number;
  elapsed_seconds?: number;
  cancellable?: boolean;
}

export const jobsApi = {
  get: (id: string) => api.get<JobStatus>(`/api/jobs/${id}`),
  cancel: (id: string) => api.post<{ ok: boolean }>(`/api/jobs/${id}/cancel`),
};

// ---------- Novelize（生成成稿） ----------
export interface NovelizeChapterSlice {
  index: number;
  title: string;
  tick_lo: number;
  tick_hi: number;
  event_count: number;
}

export interface NovelizeOptions {
  branch_id?: string;
  strategy?: 'manual' | 'by_count' | 'by_tick' | 'single';
  chapter_size?: number;
  tick_lo?: number;
  tick_hi?: number;
  provider?: string;
}

export const novelizeApi = {
  preview: (worldId: string, opts: Pick<NovelizeOptions, 'branch_id' | 'strategy' | 'chapter_size' | 'tick_lo' | 'tick_hi'>) => {
    const qs = new URLSearchParams();
    if (opts.branch_id)   qs.set('branch_id', opts.branch_id);
    if (opts.strategy)    qs.set('strategy', opts.strategy);
    if (opts.chapter_size !== undefined) qs.set('chapter_size', String(opts.chapter_size));
    if (opts.tick_lo !== undefined) qs.set('tick_lo', String(opts.tick_lo));
    if (opts.tick_hi !== undefined) qs.set('tick_hi', String(opts.tick_hi));
    const q = qs.toString();
    return api.get<{ branch_id: string; strategy: string; chapters: NovelizeChapterSlice[] }>(
      `/api/worlds/${worldId}/novelize/chapters${q ? '?' + q : ''}`,
    );
  },
  runAsync: (worldId: string, opts: NovelizeOptions) =>
    api.post<{ job_id: string }>(`/api/worlds/${worldId}/novelize_async`, opts),
};

// ---------- 关系图 ----------
export interface GraphNode {
  id: string;
  name: string;
  type: string;
  alive: number;
  summary?: string;
  location_id?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
  label: string;
  events: { id: string; tick: number; title: string }[];
}

export const relationshipsApi = {
  get: (worldId: string) =>
    api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/api/worlds/${worldId}/relationships`),
  infer: (worldId: string, body: { provider?: string } = {}) =>
    api.post<{ updated?: number; ok?: boolean }>(`/api/worlds/${worldId}/relationships/infer`, body),
};

// ---------- 时间轴 ----------
// 类型定义见上方 TimelineEvent / TimelinePayload。worldsApi.timeline 已暴露 GET。
export const timelineApi = {
  get: (worldId: string, params: { branch_id?: string; include_drafts?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (params.branch_id) qs.set('branch_id', params.branch_id);
    if (params.include_drafts) qs.set('include_drafts', '1');
    const q = qs.toString();
    return api.get<TimelinePayload>(`/api/worlds/${worldId}/timeline${q ? '?' + q : ''}`);
  },
};

// ---------- 推演 ----------
export interface StepResultEvent {
  id?: string;
  tick?: number;
  title?: string;
  description?: string;
  participants?: string[];
  [k: string]: unknown;
}

export interface StepResult {
  ok?: boolean;
  tick?: number;
  max_tick?: number | null;
  results?: unknown[];
  events?: StepResultEvent[];
  narration?: string;
  [k: string]: unknown;
}

export interface DirectiveSuggestion {
  kind: string;
  directive: string;
  rationale: string;
}

export const simApi = {
  step: (
    worldId: string,
    body: { steps?: number; directive?: string; provider?: string } = {},
  ) => api.post<StepResult>(`/api/worlds/${worldId}/step`, body),

  stepMultiAgent: (
    worldId: string,
    body: { character_ids?: string[] | null; directive?: string; provider?: string } = {},
  ) => api.post<StepResult>(`/api/worlds/${worldId}/step_multi_agent`, body),

  stepAsync: (
    worldId: string,
    body: { steps?: number; directive?: string; provider?: string } = {},
  ) => api.post<{ job_id: string }>(`/api/worlds/${worldId}/step_async`, body),

  suggestDirectives: (
    worldId: string,
    body: { n?: number; style?: string; provider?: string } = {},
  ) => api.post<{ suggestions: DirectiveSuggestion[]; raw_ok: boolean }>(
    `/api/worlds/${worldId}/suggest_directives`, body,
  ),
};

// ---------- 分支 ----------
export interface BranchInfo {
  id: string;
  name: string;
  description?: string;
  parent_branch_id: string | null;
  diverged_at_tick: number;
  is_active: boolean;
  event_count: number;
  deleted_count: number;
  max_tick: number;
  entity_count: number;
  created_at?: string;
}

export const branchesApi = {
  list: (worldId: string) =>
    api.get<BranchInfo[]>(`/api/worlds/${worldId}/branches`),
  patch: (branchId: string, body: { name?: string; description?: string }) =>
    api.patch<{ ok: boolean }>(`/api/branches/${branchId}`, body),
  remove: (branchId: string) =>
    api.delete<{ ok: boolean }>(`/api/branches/${branchId}`),
  switch: (worldId: string, branchId: string) =>
    api.post<{ ok: boolean }>(`/api/worlds/${worldId}/switch_branch/${branchId}`),
};

// ---------- 快照 / 历史 ----------
export interface SnapshotInfo {
  id: string;
  tick: number;
  label: string;
  created_at: string | null;
  counts: Record<string, number>;
  is_current: boolean;
}

export const snapshotsApi = {
  history: (worldId: string) =>
    api.get<{ branch_id: string; current_tick: number; snapshots: SnapshotInfo[] }>(
      `/api/worlds/${worldId}/history`,
    ),
  restore: (worldId: string, snapshotId: string) =>
    api.post<{ ok: boolean; restored_tick: number; counts: Record<string, number> }>(
      `/api/worlds/${worldId}/restore/${snapshotId}`,
    ),
  remove: (snapshotId: string) =>
    api.delete<{ ok: boolean }>(`/api/snapshots/${snapshotId}`),
};

// ---------- 实体 / 角色 ----------
export interface EntityFull {
  id: string;
  name: string;
  type: string;
  summary?: string;
  attributes?: Record<string, unknown>;
  state?: Record<string, unknown>;
  persona?: Record<string, unknown>;
  memories?: Array<{ tick?: number; text?: string; [k: string]: unknown }>;
  alive?: number;
  location_id?: string;
  branch_id?: string;
  created_at_tick?: number;
}

export const entitiesApi = {
  create: (
    worldId: string,
    body: {
      name: string; type: string; summary?: string;
      attributes?: Record<string, unknown>;
      persona?: Record<string, unknown>;
      memories?: unknown[];
      location_id?: string | null;
    },
  ) => api.post<{ id: string }>(`/api/worlds/${worldId}/entities`, body),

  patch: (
    entityId: string,
    body: Partial<{
      name: string; summary: string;
      attributes: Record<string, unknown>;
      state: Record<string, unknown>;
      persona: Record<string, unknown>;
      memories: unknown[];
      tags: string[];
      pinned: number;
      alive: number;
    }>,
  ) => api.patch<{ ok: boolean; id: string }>(`/api/entities/${entityId}`, body),

  view: (worldId: string, characterId: string, params: { sight?: number; max_events?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.sight !== undefined) qs.set('sight', String(params.sight));
    if (params.max_events !== undefined) qs.set('max_events', String(params.max_events));
    const q = qs.toString();
    return api.get<any>(
      `/api/worlds/${worldId}/characters/${characterId}/view${q ? '?' + q : ''}`,
    );
  },

  arc: (entityId: string) => api.get<any>(`/api/entities/${entityId}/arc`),

  extractPersona: (entityId: string, body: { provider?: string } = {}) =>
    api.post<{ ok: boolean; persona: Record<string, unknown> }>(
      `/api/entities/${entityId}/extract_persona`, body,
    ),
};

// ---------- 一致性 / 审阅 ----------
export interface ConsistencyIssue {
  id: string;
  world_id: string;
  branch_id?: string;
  category: string;
  category_label: string;
  severity: string;
  title: string;
  description: string;
  suggestion: string;
  entity_ids: string[];
  tick_start: number | null;
  tick_end: number | null;
  status: 'open' | 'ignored' | 'resolved' | string;
  scan_id?: string;
  created_at?: string | null;
  resolved_at?: string | null;
}

export interface ScanRun {
  id: string;
  scope: string;
  tick_from: number | null;
  tick_to: number | null;
  issue_count: number;
  status: string;
  error?: string;
  created_at?: string | null;
}

export interface IssuePatch {
  id: string;
  issue_id: string;
  target_kind: string;
  target_id: string;
  before_excerpt: string;
  after_text: string;
  rationale: string;
  status: string;
  model_used?: string;
  created_at?: string | null;
  applied_at?: string | null;
  can_undo: boolean;
}

export const issuesApi = {
  list: (worldId: string, status?: string) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return api.get<{
      issues: ConsistencyIssue[];
      scans: ScanRun[];
      counts: { open: number; ignored: number; resolved: number };
    }>(`/api/worlds/${worldId}/issues${q}`);
  },
  scan: (worldId: string, body: { scope?: string; tick_from?: number; tick_to?: number; provider?: string } = {}) =>
    api.post<{ scan: ScanRun; issues: ConsistencyIssue[] }>(
      `/api/worlds/${worldId}/scan_consistency`, body,
    ),
  setStatus: (issueId: string, status: 'open' | 'ignored' | 'resolved') =>
    api.patch<ConsistencyIssue>(`/api/issues/${issueId}`, { status }),
  remove: (issueId: string) => api.delete<{ ok: boolean }>(`/api/issues/${issueId}`),

  listPatches: (issueId: string) =>
    api.get<{ issue_id: string; patches: IssuePatch[] }>(`/api/issues/${issueId}/patches`),
  suggestPatches: (issueId: string, body: { provider?: string; max_patches?: number } = {}) =>
    api.post<{ issue_id: string; created: number; patches: IssuePatch[] }>(
      `/api/issues/${issueId}/suggest_patch`, body,
    ),
  applyPatch: (patchId: string) =>
    api.post<{ ok: boolean }>(`/api/issue_patches/${patchId}/apply`),
  rejectPatch: (patchId: string) =>
    api.post<{ ok: boolean }>(`/api/issue_patches/${patchId}/reject`),
  undoPatch: (patchId: string) =>
    api.post<{ ok: boolean }>(`/api/issue_patches/${patchId}/undo`),
  previewPatch: (patchId: string) =>
    api.get<{ before: string; after: string; target_kind: string; target_id: string }>(
      `/api/issue_patches/${patchId}/preview`,
    ),
};

// ---------- 设定库 ----------
export interface LoreEntry {
  id: string;
  world_id: string;
  category: string;
  title: string;
  content: string;
  priority: number;
  pinned: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export const loreApi = {
  list: (worldId: string) =>
    api.get<{ lore: LoreEntry[] }>(`/api/worlds/${worldId}/lore`).then(r => r.lore),
  create: (
    worldId: string,
    body: { title: string; content?: string; category?: string; priority?: number; pinned?: boolean },
  ) => api.post<LoreEntry>(`/api/worlds/${worldId}/lore`, body),
  patch: (
    loreId: string,
    body: Partial<{ title: string; content: string; category: string; priority: number; pinned: boolean }>,
  ) => api.patch<LoreEntry>(`/api/lore/${loreId}`, body),
  remove: (loreId: string) =>
    api.delete<{ ok: boolean }>(`/api/lore/${loreId}`),
  scanGaps: (
    worldId: string,
    body: { branch_id?: string; provider_key?: string; max_gaps?: number } = {},
  ) => api.post<{ gaps: Array<{ category: string; question: string; rationale?: string }> }>(
    `/api/worlds/${worldId}/lore/scan_gaps`, body,
  ),
};

// ---------- 地图 ----------
export interface MapMeta {
  exists: boolean;
  width: number;
  height: number;
  seed: number;
  meta: Record<string, unknown>;
  biomes: Record<string, { label: string; color: [number, number, number] }>;
  terrains: Record<string, string>;
}

export interface MapPin {
  id: string;
  name: string;
  type: string;
  x: number;
  y: number;
}

export const mapApi = {
  meta: (worldId: string) => api.get<MapMeta>(`/api/worlds/${worldId}/map`),
  pinned: (worldId: string) =>
    api.get<{ items: MapPin[] }>(`/api/worlds/${worldId}/map/pinned`).then(r => r.items),
  renderUrl: (worldId: string, layer: 'biome' | 'terrain' | 'height' | 'temp' | 'moist' = 'biome') =>
    `/api/worlds/${worldId}/map/render.png?layer=${layer}&_t=${Date.now()}`,
  generate: (
    worldId: string,
    body: {
      width?: number; height?: number; seed?: number;
      sea_level?: number; octaves?: number; persistence?: number;
      base_freq?: number; warp?: number;
    },
  ) => api.post<{ ok: boolean; width: number; height: number; seed: number }>(
    `/api/worlds/${worldId}/map/generate`, body,
  ),
  drop: (worldId: string) =>
    api.delete<{ ok: boolean; removed: boolean }>(`/api/worlds/${worldId}/map`),
  pin: (worldId: string, body: { entity_id: string; x: number | null; y: number | null }) =>
    api.post<{ ok: boolean }>(`/api/worlds/${worldId}/map/pin`, body),
};

// ---------- 风格档案 ----------
export interface StyleProfileSummary {
  id: string;
  name: string;
  description: string;
  kind: 'builtin' | 'custom' | string;
  category: string;
  frozen: boolean;
}

export interface StyleProfileDetail extends StyleProfileSummary {
  spec_text: string;
  sample_paragraphs: string[];
}

export const stylesApi = {
  list: () => api.get<{ profiles: StyleProfileSummary[] }>('/api/style_profiles')
    .then(r => r.profiles),
  get: (id: string) => api.get<StyleProfileDetail>(`/api/style_profiles/${id}`),
};

// ---------- 故事板 ----------
export interface StoryboardChapter {
  id: string;
  index: number;
  title: string;
  summary: string;
  tick_start: number;
  tick_end: number;
  is_synthetic: boolean;
  event_count: number;
  events: Array<{
    id: string; tick: number; title: string; description: string;
    participants: Array<{ id: string; name: string }>;
  }>;
  characters: Array<{ id: string; name: string; appearances: number; alive: boolean }>;
  issues: Array<{ id: string; title: string; severity: string; category: string; tick: number }>;
  threads: Array<{ id: string; title: string; status: string; phase: 'opened' | 'closed' | 'ongoing' }>;
}

export const storyboardApi = {
  get: (worldId: string, params: { branch_id?: string; top_events?: number; top_characters?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.branch_id) qs.set('branch_id', params.branch_id);
    if (params.top_events !== undefined) qs.set('top_events', String(params.top_events));
    if (params.top_characters !== undefined) qs.set('top_characters', String(params.top_characters));
    const q = qs.toString();
    return api.get<{
      world_id: string; branch_id: string; max_tick: number;
      chapters: StoryboardChapter[];
    }>(`/api/worlds/${worldId}/storyboard${q ? '?' + q : ''}`);
  },
};
