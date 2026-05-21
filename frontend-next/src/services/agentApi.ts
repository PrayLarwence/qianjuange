/**
 * Multi-agent pipeline 配置 + 编排执行 + trace 增量拉取。
 * 后端定义见 backend/app/engine/agent_pipeline.py + orchestrator.py。
 */
import { api } from './api';

export type CriticSeverity = 'lenient' | 'normal' | 'strict';
export type CriticMode = 'serial' | 'parallel';

export interface DirectorAgent {
  name: string;
  model: string;
  temperature: number;
  max_hops: number;
}

export interface AuthorAgent {
  name: string;
  model: string;
  temperature: number;
}

export interface CriticAgent {
  name: string;
  model: string;
  temperature: number;
  focus: string;
  severity: CriticSeverity;
  kind?: 'general' | 'arc';
}

export interface BudgetConfig {
  max_llm_calls: number;
  max_wall_seconds: number;
}

export interface PipelineConfig {
  directors: DirectorAgent[];
  authors: AuthorAgent[];
  critics: CriticAgent[];
  critic_mode: CriticMode;
  max_critic_retries: number;
  author_best_of?: number;
  budget: BudgetConfig;
}

export interface PipelineLimits {
  max_directors: number;
  max_critics: number;
  max_critic_retries: number;
  max_llm_calls: number;
  max_wall_seconds: number;
  max_author_best_of?: number;
}

export interface AgentTrace {
  id: string;
  seq: number;
  role: 'director' | 'author' | 'critic' | 'orchestrator';
  agent_name: string;
  iteration: number;
  model: string;
  status: string;
  verdict: string;
  input_summary: string;
  output_summary: string;
  extra: Record<string, unknown>;
  started_at: string | null;
  ended_at: string | null;
}

export interface AgentTraceFull {
  id: string;
  full_prompt: string;
  full_response: string;
}

export interface OrchestratedJobStartResp {
  job_id: string;
}

export interface OrchestratedStepResult {
  ok: boolean;
  tick: number;
  tick_start: number;
  hops: number;
  tool_calls: unknown[];
  narration: string;
  critic_rounds: number;
  final_verdict: 'pass' | 'forced_accept' | 'no_critics' | 'budget_exhausted' | 'cancelled';
  unresolved_critics?: { name: string; reason: string; suggestions: string }[];
  budget_used: { llm_calls: number; wall_seconds: number };
}

export interface PipelineMetrics {
  summary: {
    total_jobs: number;
    forced_accept: number;
    forced_accept_rate: number;
    first_pass: number;
    first_pass_rate: number;
    avg_critic_rounds: number;
    avg_critic_rounds_when_retried: number | null;
    hours: number;
  };
  by_critic: Record<string, {
    runs: number;
    pass: number;
    fail: number;
    error: number;
    avg_score: number | null;
    fail_rate: number;
  }>;
  recent_forced: {
    job_id: string;
    ts: string | null;
    unresolved_count: number;
    unresolved: { name: string; reason: string; suggestions: string }[];
  }[];
}

export const agentPipelineApi = {
  // 世界级配置
  getForWorld: (worldId: string) =>
    api.get<{ inherited: boolean; config: PipelineConfig }>(
      `/api/worlds/${worldId}/agent_pipeline`,
    ),
  setForWorld: (worldId: string, body: { config: PipelineConfig | null; save_as_default?: boolean }) =>
    api.put<{ ok: boolean; inherited: boolean; config: PipelineConfig; default_save_error?: string }>(
      `/api/worlds/${worldId}/agent_pipeline`, body,
    ),

  // 全局 default
  getDefault: () => api.get<{ config: PipelineConfig }>(`/api/agent_pipeline/default`),
  setDefault: (config: PipelineConfig) =>
    api.put<{ ok: boolean; config: PipelineConfig }>(`/api/agent_pipeline/default`, { config }),

  // 上限常量
  limits: () => api.get<PipelineLimits>(`/api/agent_pipeline/limits`),

  // 启动编排推演（异步 job）
  startStep: (worldId: string, body: { directive?: string; config_override?: PipelineConfig | null } = {}) =>
    api.post<OrchestratedJobStartResp>(`/api/worlds/${worldId}/step_orchestrated`, body),

  // 增量拉 trace
  traces: (jobId: string, afterSeq = 0) =>
    api.get<{ traces: AgentTrace[] }>(`/api/jobs/${jobId}/agent_traces?after_seq=${afterSeq}`),

  // 单条 trace 完整 prompt + response
  traceFull: (jobId: string, traceId: string) =>
    api.get<AgentTraceFull>(`/api/jobs/${jobId}/agent_traces/${traceId}/full`),

  // Pipeline 指标聚合
  metrics: (worldId: string, hours = 168) =>
    api.get<PipelineMetrics>(`/api/worlds/${worldId}/pipeline_metrics?hours=${hours}`),
};

// 工具：构造一个最小可用的空白配置（前端 UI 新增 critic 时用）
export function emptyDirector(): DirectorAgent {
  return { name: 'director', model: '', temperature: 0.7, max_hops: 8 };
}
export function emptyAuthor(): AuthorAgent {
  return { name: 'author', model: '', temperature: 0.7 };
}
export function emptyCritic(): CriticAgent {
  return { name: '审稿人', model: '', temperature: 0.3, focus: '', severity: 'normal', kind: 'general' };
}
export function emptyArcCritic(): CriticAgent {
  return {
    name: 'Arc 审稿',
    model: '',
    temperature: 0.3,
    focus: '是否与前文章节冲突；是否推进主线（不要管文笔/节奏）',
    severity: 'normal',
    kind: 'arc',
  };
}
