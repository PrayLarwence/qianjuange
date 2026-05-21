<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { worldsApi, llmApi, type WorldDetail } from '@/services/api';
import { agentPipelineApi, type PipelineMetrics } from '@/services/agentApi';
import { useToastStore } from '@/stores/toast';

const route = useRoute();
const router = useRouter();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const snapshot = ref<any>(null);
const metrics = ref<any>(null);
const pipelineMetrics = ref<PipelineMetrics | null>(null);
const manuscript = ref<any>(null);
const loading = ref(true);
const err = ref('');

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [snap, m, met, pm] = await Promise.all([
      worldsApi.get(worldId.value),
      worldsApi.manuscriptState(worldId.value).catch(() => null),
      llmApi.metrics({ hours: 24 }).catch(() => null),
      agentPipelineApi.metrics(worldId.value, 168).catch(() => null),
    ]);
    snapshot.value = snap;
    world.value = snap.world;
    manuscript.value = m;
    metrics.value = met;
    pipelineMetrics.value = pm;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const banner = computed(() => {
  const m = manuscript.value;
  if (!m || !m.has_manuscript) return null;
  if (m.draft_event_count > 0) {
    return { kind: 'review', title: `${m.draft_event_count} 个事件草稿待审阅`, sub: '点击前往设置 → 手稿抽取审阅' };
  }
  return { kind: 'extract', title: `${m.chapter_count} 章已切分`, sub: '点击前往设置 → 抽取事件' };
});

const entities = computed(() => {
  const all = snapshot.value?.entities || [];
  const chars = all.filter((e: any) => e.type === 'character');
  const locs = all.filter((e: any) => e.type === 'location');
  const facs = all.filter((e: any) => e.type === 'faction');
  return { chars, locs, facs, total: all.length };
});

const eventCount = computed(() => {
  return (snapshot.value?.events || []).length;
});

const draftCount = computed(() => {
  const w = world.value as any;
  return (w?.manuscript_draft_events || []).length;
});

const chunkCount = computed(() => {
  const w = world.value as any;
  return (w?.manuscript_chunks || []).length;
});

const hasEvents = computed(() => eventCount.value > 0);
const hasManuscript = computed(() => manuscript.value?.has_manuscript);
const hasDrafts = computed(() => (manuscript.value?.draft_event_count || 0) > 0);
const workflowStep = computed(() => {
  if (!hasManuscript.value) return 1;
  if (!hasDrafts.value) return 2;
  if (!hasEvents.value) return 3;
  return 4;
});

function fmt(n: number | undefined): string {
  if (n === undefined || n === null) return '—';
  return n.toLocaleString();
}

function goSettings(section: string) {
  router.push(`/worlds/${worldId.value}/settings`);
  // 延迟滚动到 manuscript section
  setTimeout(() => {
    const el = document.querySelector('#section-manuscript');
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  }, 300);
}
</script>

<template>
  <div class="px-8 py-10 max-w-5xl">
    <p v-if="err" class="text-red-500 text-sm mb-4">{{ err }}</p>
    <div v-if="loading" class="text-muted text-sm">加载中…</div>

    <template v-if="world">
      <div class="mb-8">
        <h1 class="font-serif text-3xl mb-1">{{ world.name }}</h1>
        <p class="text-muted text-sm">{{ world.description || '无描述' }}</p>
      </div>

      <!-- 引导流程 -->
      <div v-if="workflowStep < 4" class="mb-6 p-4 rounded-lg bg-accent/5 border border-accent/20">
        <div class="text-sm font-medium mb-2">从这里开始</div>
        <div class="grid grid-cols-3 gap-2 text-xs">
          <div class="text-center" :class="workflowStep <= 1 ? 'text-accent font-medium' : 'text-muted'">
            <div class="text-lg mb-0.5">📖</div>
            <div>导入手稿</div>
            <div v-if="workflowStep === 1" class="mt-1">
              <router-link to="/worlds" class="text-accent underline">去导入</router-link>
            </div>
            <div v-else class="text-green-600">✓</div>
          </div>
          <div class="text-center" :class="workflowStep === 2 ? 'text-accent font-medium' : (workflowStep > 2 ? 'text-muted' : 'text-muted/50')">
            <div class="text-lg mb-0.5">🔍</div>
            <div>抽取事件</div>
            <div v-if="hasManuscript && !hasDrafts" class="mt-1">
              <span class="text-accent underline cursor-pointer" @click="goSettings('manuscript')">去抽取</span>
            </div>
            <div v-else-if="workflowStep > 2" class="text-green-600">✓</div>
          </div>
          <div class="text-center" :class="workflowStep === 3 ? 'text-accent font-medium' : (workflowStep > 3 ? 'text-muted' : 'text-muted/30')">
            <div class="text-lg mb-0.5">✍️</div>
            <div>审阅并推演</div>
            <div v-if="hasDrafts && !hasEvents" class="mt-1">
              <router-link :to="`/worlds/${worldId}/sim`" class="text-accent underline">去推演</router-link>
            </div>
            <div v-else-if="workflowStep > 3" class="text-green-600">✓</div>
          </div>
        </div>
      </div>

      <!-- 手稿横幅 -->
      <div v-if="banner" class="mb-6 p-4 rounded-lg border cursor-pointer"
           :class="banner.kind === 'review' ? 'bg-accent/10 border-accent/30' : 'bg-sunken border-border'"
           @click="goSettings('manuscript')">
        <div class="text-sm font-medium">{{ banner.title }}</div>
        <div class="text-xs text-muted mt-0.5">{{ banner.sub }}</div>
      </div>

      <!-- 风格提醒 -->
      <div v-if="!world?.style_profile_id" class="mb-6 p-3 rounded-lg bg-sunken border border-border text-xs">
        ⚡ 尚未绑定风格档案 —
        <router-link :to="`/worlds/${worldId}/settings`" class="text-accent underline">去设置</router-link>
        选择文风模板，让 AI 生成的文字更统一
      </div>

      <!-- 世界统计 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <div class="stat-card">
          <div class="text-muted text-xs uppercase tracking-wider">实体</div>
          <div class="text-2xl font-medium mt-1">{{ entities.total }}</div>
          <div class="text-xs text-muted mt-0.5">
            {{ entities.chars.length }}角色 · {{ entities.locs.length }}地点 · {{ entities.facs.length }}派系
          </div>
        </div>
        <div class="stat-card">
          <div class="text-muted text-xs uppercase tracking-wider">事件</div>
          <div class="text-2xl font-medium mt-1">{{ eventCount }}</div>
          <div class="text-xs text-muted mt-0.5">当前 tick: {{ world.current_tick || 0 }}</div>
        </div>
        <div class="stat-card">
          <div class="text-muted text-xs uppercase tracking-wider">手稿</div>
          <div class="text-2xl font-medium mt-1">{{ chunkCount || '—' }}</div>
          <div class="text-xs mt-0.5" :class="draftCount ? 'text-accent' : 'text-muted'">
            <span v-if="draftCount">{{ draftCount }} 草稿待审</span>
            <span v-else>无待审</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="text-muted text-xs uppercase tracking-wider">分支</div>
          <div class="text-2xl font-medium mt-1">{{ (world as any).branch_count || 1 }}</div>
          <div class="text-xs text-muted mt-0.5">ID: {{ (world as any).branch_id?.slice(0,8) || '—' }}</div>
        </div>
      </div>

      <!-- LLM 调用统计 -->
      <div v-if="metrics?.summary" class="mb-8">
        <h2 class="text-sm uppercase tracking-wider text-muted mb-3">LLM 调用（24h）</h2>
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div class="stat-card">
            <div class="text-muted text-xs">调用次数</div>
            <div class="text-xl font-medium mt-1">{{ fmt(metrics.summary.total_calls) }}</div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">输入 Token</div>
            <div class="text-xl font-medium mt-1">{{ fmt(metrics.summary.total_tokens_in) }}</div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">输出 Token</div>
            <div class="text-xl font-medium mt-1">{{ fmt(metrics.summary.total_tokens_out) }}</div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">平均延迟</div>
            <div class="text-xl font-medium mt-1">{{ metrics.summary.avg_latency_ms }}ms</div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">错误</div>
            <div class="text-xl font-medium mt-1" :class="metrics.summary.errors ? 'text-red-500' : ''">
              {{ metrics.summary.errors }}
            </div>
          </div>
        </div>
      </div>

      <!-- Pipeline 指标（编排推演 7 天） -->
      <div v-if="pipelineMetrics && pipelineMetrics.summary.total_jobs > 0" class="mb-8">
        <h2 class="text-sm uppercase tracking-wider text-muted mb-3">
          Pipeline 表现（7 天 · {{ pipelineMetrics.summary.total_jobs }} 次编排推演）
        </h2>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <div class="stat-card">
            <div class="text-muted text-xs">一次过 critic</div>
            <div class="text-xl font-medium mt-1">
              {{ pipelineMetrics.summary.first_pass }}
              <span class="text-sm text-muted">
                / {{ Math.round(pipelineMetrics.summary.first_pass_rate * 100) }}%
              </span>
            </div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">平均 critic 轮数</div>
            <div class="text-xl font-medium mt-1">{{ pipelineMetrics.summary.avg_critic_rounds }}</div>
            <div v-if="pipelineMetrics.summary.avg_critic_rounds_when_retried" class="text-xs text-muted mt-0.5">
              重写时均值 {{ pipelineMetrics.summary.avg_critic_rounds_when_retried }}
            </div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">强制接受</div>
            <div class="text-xl font-medium mt-1"
                 :class="pipelineMetrics.summary.forced_accept ? 'text-amber-600 dark:text-amber-400' : ''">
              {{ pipelineMetrics.summary.forced_accept }}
              <span class="text-sm text-muted">
                / {{ Math.round(pipelineMetrics.summary.forced_accept_rate * 100) }}%
              </span>
            </div>
          </div>
          <div class="stat-card">
            <div class="text-muted text-xs">活跃 critic</div>
            <div class="text-xl font-medium mt-1">{{ Object.keys(pipelineMetrics.by_critic).length }}</div>
          </div>
        </div>
        <div v-if="Object.keys(pipelineMetrics.by_critic).length" class="stat-card">
          <div class="text-xs text-muted mb-2">各 critic 表现</div>
          <table class="w-full text-sm">
            <thead class="text-xs text-muted">
              <tr>
                <th class="text-left py-1 font-normal">名称</th>
                <th class="text-right py-1 font-normal">运行</th>
                <th class="text-right py-1 font-normal">pass</th>
                <th class="text-right py-1 font-normal">fail</th>
                <th class="text-right py-1 font-normal">fail 率</th>
                <th class="text-right py-1 font-normal">均分</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(d, name) in pipelineMetrics.by_critic" :key="name"
                  class="border-t border-border/30">
                <td class="py-1.5 truncate">{{ name }}</td>
                <td class="py-1.5 text-right font-mono text-xs">{{ d.runs }}</td>
                <td class="py-1.5 text-right font-mono text-xs text-green-600">{{ d.pass }}</td>
                <td class="py-1.5 text-right font-mono text-xs"
                    :class="d.fail ? 'text-amber-600' : 'text-muted'">{{ d.fail }}</td>
                <td class="py-1.5 text-right font-mono text-xs"
                    :class="d.fail_rate > 0.5 ? 'text-amber-600' : 'text-muted'">
                  {{ Math.round(d.fail_rate * 100) }}%
                </td>
                <td class="py-1.5 text-right font-mono text-xs text-muted">{{ d.avg_score ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 快捷入口 -->
      <h2 class="text-sm uppercase tracking-wider text-muted mb-3">快捷入口</h2>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
        <router-link :to="`/worlds/${worldId}/cast`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">角色名册</div>
          <div class="text-xs text-muted mt-1">查看、编辑角色档案与关系</div>
        </router-link>
        <router-link :to="`/worlds/${worldId}/sim`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">推演</div>
          <div class="text-xs text-muted mt-1">AI 推演下一步故事</div>
        </router-link>
        <router-link :to="`/worlds/${worldId}/agent-run`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">编排推演</div>
          <div class="text-xs text-muted mt-1">多 Agent 流水线：导演→作者→审稿</div>
        </router-link>
        <router-link :to="`/worlds/${worldId}/chapters`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">章节</div>
          <div class="text-xs text-muted mt-1">标记、渲染、导出小说</div>
        </router-link>
        <router-link :to="`/worlds/${worldId}/review`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">一致性审查</div>
          <div class="text-xs text-muted mt-1">扫描 OOC / 时间线矛盾</div>
        </router-link>
        <router-link :to="`/worlds/${worldId}/settings`" class="stat-card hover:bg-sunken transition-colors no-underline text-text">
          <div class="text-sm font-medium">世界设置</div>
          <div class="text-xs text-muted mt-1">手稿、风格、Agent 配置</div>
        </router-link>
      </div>

      <!-- 实体分布 -->
      <h2 class="text-sm uppercase tracking-wider text-muted mt-8 mb-3">实体分布</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
        <div class="stat-card">
          <div class="text-xs text-muted mb-3">角色 ({{ entities.chars.length }})</div>
          <div v-if="entities.chars.length" class="space-y-1">
            <div v-for="c in entities.chars.slice(0, 8)" :key="c.id" class="flex justify-between text-sm">
              <span class="truncate mr-2">{{ c.name }}</span>
              <span v-if="!c.alive" class="text-[#b04f33] flex-shrink-0">已逝</span>
            </div>
            <div v-if="entities.chars.length > 8" class="text-xs text-muted">
              …及其他 {{ entities.chars.length - 8 }} 个角色
            </div>
          </div>
          <div v-else class="text-xs text-muted">暂无角色</div>
        </div>
        <div class="stat-card">
          <div class="text-xs text-muted mb-3">地点 ({{ entities.locs.length }})</div>
          <div v-if="entities.locs.length" class="space-y-1">
            <div v-for="l in entities.locs.slice(0, 8)" :key="l.id" class="text-sm truncate">{{ l.name }}</div>
            <div v-if="entities.locs.length > 8" class="text-xs text-muted">
              …及其他 {{ entities.locs.length - 8 }} 个地点
            </div>
          </div>
          <div v-else class="text-xs text-muted">暂无地点</div>
        </div>
      </div>

      <!-- 最近事件 -->
      <h2 class="text-sm uppercase tracking-wider text-muted mb-3">最近事件</h2>
      <div class="stat-card mb-8">
        <div v-if="(snapshot?.events || []).length" class="space-y-2">
          <div v-for="ev in (snapshot.events || []).slice(-8).reverse()" :key="ev.id"
               class="flex items-start gap-3 text-sm py-1 border-b border-border/30 last:border-0">
            <span class="text-muted font-mono text-xs flex-shrink-0 w-20">tick {{ ev.tick }}</span>
            <span class="font-medium truncate">{{ ev.title }}</span>
            <span v-if="ev.participants?.length" class="text-xs text-muted ml-auto flex-shrink-0">
              {{ ev.participants.length }}人
            </span>
          </div>
        </div>
        <div v-else class="text-xs text-muted">暂无事件 — 开始推演吧</div>
      </div>

      <!-- 最近 LLM 调用 -->
      <h2 class="text-sm uppercase tracking-wider text-muted mb-3">最近 LLM 调用</h2>
      <div class="stat-card">
        <div v-if="metrics?.recent?.length" class="space-y-1">
          <div v-for="r in metrics.recent.slice(0, 10)" :key="r.id"
               class="flex items-center gap-3 text-xs py-1 border-b border-border/20 last:border-0">
            <span class="w-16 text-muted flex-shrink-0">{{ r.provider }}</span>
            <span class="w-20 text-muted flex-shrink-0 truncate">{{ r.kind || '—' }}</span>
            <span class="flex-shrink-0">{{ (r.tokens_in || 0) + (r.tokens_out || 0) }} tok</span>
            <span class="flex-shrink-0">{{ r.latency_ms }}ms</span>
            <span :class="r.status === 'error' ? 'text-red-500' : 'text-green-600'" class="flex-shrink-0 ml-auto">
              {{ r.status === 'error' ? '✕' : '✓' }}
            </span>
            <span class="text-muted hidden md:inline">{{ new Date(r.created_at).toLocaleTimeString() }}</span>
          </div>
        </div>
        <div v-else class="text-xs text-muted">暂无调用记录</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 14px 16px;
}
</style>
