<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import { useRoute } from 'vue-router';
import { agentPipelineApi, type AgentTrace } from '@/services/agentApi';
import { jobsApi, type JobStatus } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const directive = ref('');
const jobId = ref<string | null>(null);
const job = ref<JobStatus | null>(null);
const traces = ref<AgentTrace[]>([]);
const lastSeq = ref(0);
const polling = ref(false);
const expanded = ref<Record<string, boolean>>({});
const fullCache = ref<Record<string, { full_prompt: string; full_response: string }>>({});
const fullDialog = ref<{ traceId: string; prompt: string; response: string } | null>(null);

let jobTimer: number | null = null;
let traceTimer: number | null = null;

function clearTimers() {
  if (jobTimer !== null) { window.clearInterval(jobTimer); jobTimer = null; }
  if (traceTimer !== null) { window.clearInterval(traceTimer); traceTimer = null; }
}

onBeforeUnmount(clearTimers);

async function start() {
  if (polling.value) return;
  traces.value = [];
  lastSeq.value = 0;
  job.value = null;
  expanded.value = {};
  fullCache.value = {};
  try {
    const resp = await agentPipelineApi.startStep(worldId.value, {
      directive: directive.value.trim() || undefined,
    });
    jobId.value = resp.job_id;
    polling.value = true;
    toast.success(`已启动编排推演 ${resp.job_id.slice(0, 12)}`);
    startPolling();
  } catch (e: any) {
    toast.error(`启动失败：${e.message || e}`);
  }
}

function startPolling() {
  if (!jobId.value) return;
  // 拉 job 状态（1.2s）
  jobTimer = window.setInterval(async () => {
    if (!jobId.value) return;
    try {
      const j = await jobsApi.get(jobId.value);
      job.value = j;
      if (j.status === 'completed' || j.status === 'error' || j.status === 'cancelled') {
        // 终态：再拉一次 trace 后停轮询
        await pullTraces();
        clearTimers();
        polling.value = false;
      }
    } catch { /* ignore */ }
  }, 1200);

  // 拉 trace 增量（1.5s）
  traceTimer = window.setInterval(pullTraces, 1500);
  // 立即拉一次
  pullTraces();
}

async function pullTraces() {
  if (!jobId.value) return;
  try {
    const resp = await agentPipelineApi.traces(jobId.value, lastSeq.value);
    if (resp.traces.length > 0) {
      traces.value.push(...resp.traces);
      lastSeq.value = resp.traces[resp.traces.length - 1].seq;
    }
  } catch { /* ignore */ }
}

async function cancel() {
  if (!jobId.value) return;
  try {
    await jobsApi.cancel(jobId.value);
    toast.success('已请求取消（等待当前 LLM 调用结束）');
  } catch (e: any) {
    toast.error(`取消失败：${e.message || e}`);
  }
}

async function toggleExpand(t: AgentTrace) {
  expanded.value[t.id] = !expanded.value[t.id];
  if (expanded.value[t.id] && !fullCache.value[t.id] && jobId.value) {
    try {
      const full = await agentPipelineApi.traceFull(jobId.value, t.id);
      fullCache.value[t.id] = full;
    } catch (e: any) {
      toast.error(`加载完整内容失败：${e.message || e}`);
    }
  }
}

function openFull(t: AgentTrace) {
  if (!jobId.value) return;
  const cached = fullCache.value[t.id];
  if (cached) {
    fullDialog.value = { traceId: t.id, prompt: cached.full_prompt, response: cached.full_response };
    return;
  }
  agentPipelineApi.traceFull(jobId.value, t.id).then(full => {
    fullCache.value[t.id] = full;
    fullDialog.value = { traceId: t.id, prompt: full.full_prompt, response: full.full_response };
  }).catch(e => toast.error(`加载失败：${e.message || e}`));
}

function roleColor(role: string) {
  return {
    director: 'bg-blue-500/10 text-blue-700 dark:text-blue-300',
    author:   'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    critic:   'bg-amber-500/10 text-amber-700 dark:text-amber-300',
    orchestrator: 'bg-purple-500/10 text-purple-700 dark:text-purple-300',
  }[role] || 'bg-sunken text-muted';
}

function verdictBadge(v: string) {
  if (v === 'pass') return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300';
  if (v === 'fail') return 'bg-rose-500/15 text-rose-700 dark:text-rose-300';
  if (v === 'forced_accept') return 'bg-amber-500/15 text-amber-700 dark:text-amber-300';
  if (v === 'skipped') return 'bg-sunken text-muted';
  return 'bg-sunken text-muted';
}

const finalVerdictLabel: Record<string, string> = {
  pass: '通过',
  forced_accept: '强制接受（达到重试上限）',
  no_critics: '无审稿（直接通过）',
  budget_exhausted: '预算耗尽',
  cancelled: '已取消',
};

const verdictTone = computed(() => {
  const v = job.value?.result?.final_verdict as string | undefined;
  if (!v) return '';
  if (v === 'pass' || v === 'no_critics') return 'text-emerald-600 dark:text-emerald-400';
  if (v === 'forced_accept') return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
});
</script>

<template>
  <div class="px-8 py-10 max-w-5xl">
    <p class="text-muted text-xs uppercase tracking-wider mb-2">推演 · multi-agent</p>
    <h1 class="font-serif text-3xl mb-6">Agent 编排推演</h1>

    <!-- 触发条 -->
    <section class="surface rounded p-4 mb-6 space-y-3">
      <label class="text-xs text-muted">指示语（可选）</label>
      <textarea v-model="directive" rows="3"
                placeholder="比如：让林冲去找柴进借宿，路上遇见一个信使。"
                class="input w-full text-sm" :disabled="polling"></textarea>
      <div class="flex items-center gap-2">
        <button class="btn btn-accent" :disabled="polling" @click="start">
          {{ polling ? '推演中…' : '启动编排推演' }}
        </button>
        <button v-if="polling" class="btn btn-ghost hover:!text-[#b04f33]" @click="cancel">
          停止
        </button>
        <a class="btn btn-ghost ml-auto text-xs"
           :href="`/worlds/${worldId}/settings`">
          调整 agent 配置 →
        </a>
      </div>
    </section>

    <!-- Job 状态 -->
    <section v-if="job || polling" class="surface rounded p-4 mb-6 text-sm">
      <div class="flex items-center gap-3 flex-wrap">
        <span class="text-xs text-muted">Job</span>
        <span class="font-mono text-xs">{{ jobId }}</span>
        <span class="px-2 py-0.5 rounded text-xs"
              :class="{
                'bg-blue-500/10 text-blue-600 dark:text-blue-300': job?.status === 'running' || job?.status === 'pending',
                'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300': job?.status === 'completed',
                'bg-rose-500/15 text-rose-700 dark:text-rose-300': job?.status === 'error',
                'bg-amber-500/15 text-amber-700 dark:text-amber-300': job?.status === 'cancelled',
              }">
          {{ job?.status || 'pending' }}
        </span>
        <span v-if="job?.progress_message" class="text-muted text-xs">{{ job.progress_message }}</span>
      </div>

      <div v-if="job?.error" class="mt-2 text-rose-600 dark:text-rose-400 text-xs">{{ job.error }}</div>

      <div v-if="job?.result" class="mt-3 space-y-2">
        <div class="flex items-center gap-2 text-xs">
          <span class="text-muted">最终结果：</span>
          <span :class="verdictTone">
            {{ finalVerdictLabel[job.result.final_verdict] || job.result.final_verdict }}
          </span>
          <span class="text-muted">·</span>
          <span class="text-muted">{{ job.result.critic_rounds }} 轮 critic</span>
          <span class="text-muted">·</span>
          <span class="text-muted">
            预算 {{ job.result.budget_used?.llm_calls }} 次 LLM / {{ job.result.budget_used?.wall_seconds }}s
          </span>
        </div>
        <div v-if="job.result.narration" class="surface rounded p-3 text-sm font-serif leading-relaxed whitespace-pre-wrap">
          {{ job.result.narration }}
        </div>
      </div>
    </section>

    <!-- Trace 流 -->
    <section v-if="traces.length > 0" class="space-y-2">
      <h2 class="text-muted text-xs uppercase tracking-wider mb-2">Agent traces（{{ traces.length }}）</h2>
      <div v-for="t in traces" :key="t.id"
           class="surface rounded p-3 text-sm">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="px-2 py-0.5 rounded text-xs uppercase tracking-wider" :class="roleColor(t.role)">
            {{ t.role }}
          </span>
          <span class="font-medium">{{ t.agent_name }}</span>
          <span v-if="t.iteration > 0" class="text-xs text-muted">· iter {{ t.iteration }}</span>
          <span v-if="t.verdict" class="text-xs px-2 py-0.5 rounded" :class="verdictBadge(t.verdict)">
            {{ t.verdict }}
          </span>
          <span class="text-xs text-muted ml-auto">#{{ t.seq }}</span>
          <button class="btn btn-ghost text-xs" @click="toggleExpand(t)">
            {{ expanded[t.id] ? '收起' : '展开' }}
          </button>
          <button class="btn btn-ghost text-xs" @click="openFull(t)">完整</button>
        </div>

        <div v-if="t.input_summary" class="mt-2 text-xs text-muted">
          <span class="text-[10px] uppercase tracking-wider mr-1">in:</span>
          <span class="whitespace-pre-wrap">{{ t.input_summary }}</span>
        </div>
        <div v-if="t.output_summary" class="mt-1 text-sm leading-relaxed">
          <span class="text-[10px] uppercase tracking-wider mr-1 text-muted">out:</span>
          <span class="whitespace-pre-wrap">{{ t.output_summary }}</span>
        </div>

        <div v-if="expanded[t.id]" class="mt-3 border-t border-border pt-3 space-y-2">
          <div v-if="fullCache[t.id]" class="space-y-3">
            <div>
              <p class="text-[10px] uppercase tracking-wider text-muted mb-1">prompt</p>
              <pre class="surface rounded p-2 text-xs leading-relaxed whitespace-pre-wrap font-mono max-h-64 overflow-auto">{{ fullCache[t.id].full_prompt || '(空)' }}</pre>
            </div>
            <div>
              <p class="text-[10px] uppercase tracking-wider text-muted mb-1">response</p>
              <pre class="surface rounded p-2 text-xs leading-relaxed whitespace-pre-wrap font-mono max-h-64 overflow-auto">{{ fullCache[t.id].full_response || '(空)' }}</pre>
            </div>
          </div>
          <div v-else class="text-xs text-muted">加载中…</div>
        </div>
      </div>
    </section>

    <Dialog v-if="fullDialog" :open="!!fullDialog" :title="`Trace ${fullDialog.traceId.slice(0,12)}`"
            width="800px" @close="fullDialog = null">
      <div class="space-y-4 max-h-[70vh] overflow-y-auto">
        <div>
          <p class="text-xs uppercase tracking-wider text-muted mb-2">prompt</p>
          <pre class="surface rounded p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono">{{ fullDialog.prompt || '(空)' }}</pre>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wider text-muted mb-2">response</p>
          <pre class="surface rounded p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono">{{ fullDialog.response || '(空)' }}</pre>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="fullDialog = null">关闭</button>
      </template>
    </Dialog>
  </div>
</template>
  ...[truncated 4123 chars]