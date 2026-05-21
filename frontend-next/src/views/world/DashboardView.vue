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

      <!-- 实体分布 -->
      <h2 class="text-sm uppercase tracking-wider text-muted mt-8 mb-3">实体分布</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
        <div class="stat-card">
          <div class="text-xs text-muted mb-3">角色 ({{ entities.chars.length }})</div>
          <div v-if="entities.chars.length" class="space-y-1">
            <div v-for="c in entities.chars.slice(0, 8)" :key="c.id" class="flex justify-between text-sm">
              <span class="truncate mr-2">{{ c.name }}</span>
              <span class="text-muted flex-shrink-0">{{ c.alive ? '' : '已逝' }}</span>
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
