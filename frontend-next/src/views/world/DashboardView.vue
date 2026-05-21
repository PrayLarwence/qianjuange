<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { worldsApi, llmApi, type WorldDetail } from '@/services/api';
import { useToastStore } from '@/stores/toast';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const snapshot = ref<any>(null);
const metrics = ref<any>(null);
const loading = ref(true);
const err = ref('');

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [snap, m] = await Promise.all([
      worldsApi.get(worldId.value),
      llmApi.metrics({ hours: 24 }).catch(() => null),
    ]);
    snapshot.value = snap;
    world.value = snap.world;
    metrics.value = m;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

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

function fmt(n: number | undefined): string {
  if (n === undefined || n === null) return '—';
  return n.toLocaleString();
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
