<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { worldsApi, type WorldSnapshot, type ManuscriptState } from '@/services/api';

const route = useRoute();
const router = useRouter();
const snap = ref<WorldSnapshot | null>(null);
const manuscript = ref<ManuscriptState | null>(null);
const loading = ref(true);
const err = ref('');

const worldId = computed(() => route.params.id as string);

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [s, m] = await Promise.all([
      worldsApi.get(worldId.value),
      worldsApi.manuscriptState(worldId.value).catch(() => null),
    ]);
    snap.value = s;
    manuscript.value = m;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, load);

const w        = computed(() => snap.value?.world);
const events   = computed(() => snap.value?.recent_events || []);
const entities = computed(() => snap.value?.entities       || []);

const banner = computed<{ kind: 'review' | 'extract'; title: string; sub: string } | null>(() => {
  const m = manuscript.value;
  if (!m || !m.has_manuscript) return null;
  if (m.draft_event_count > 0) {
    return {
      kind: 'review',
      title: `${m.draft_event_count} 个事件草稿待你审阅`,
      sub: `已从 ${m.chapter_count} 章手稿里抽出，需确认后才会写入时间轴`,
    };
  }
  if ((w.value?.current_tick ?? 0) === 0) {
    return {
      kind: 'extract',
      title: `手稿已导入 · ${m.chapter_count} 章已切分`,
      sub: '从原稿抽事件草稿，审阅后写入时间轴',
    };
  }
  return null;
});

function go(sub: string) { router.push(`/worlds/${worldId.value}/${sub}`); }
function goSettings() { router.push(`/worlds/${worldId.value}/settings`); }
</script>

<template>
  <div class="px-8 py-10 max-w-5xl">
    <div v-if="loading" class="text-muted">加载中…</div>
    <div v-else-if="err" class="text-muted">无法加载：{{ err }}</div>

    <template v-else-if="w">
      <p class="text-muted text-xs uppercase tracking-wider mb-2">概览</p>
      <h1 class="font-serif text-4xl mb-3">{{ w.name }}</h1>
      <p v-if="w.description" class="font-serif text-prose text-muted max-w-2xl mb-8">
        {{ w.description }}
      </p>

      <!-- 手稿提示 -->
      <div v-if="banner"
           class="surface rounded p-4 mb-8 flex items-center gap-4 border-l-2"
           :class="banner.kind === 'review' ? '!border-l-accent' : '!border-l-muted'">
        <div class="flex-1 min-w-0">
          <div class="font-serif text-base mb-0.5">{{ banner.title }}</div>
          <div class="text-xs text-muted">{{ banner.sub }}</div>
        </div>
        <button class="btn shrink-0"
                :class="banner.kind === 'review' ? 'btn-accent' : 'btn-ghost'"
                @click="goSettings">
          {{ banner.kind === 'review' ? '审阅草稿' : '抽取事件' }}
        </button>
      </div>

      <!-- 状态条 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
        <div class="surface rounded p-4">
          <div class="text-muted text-xs uppercase tracking-wider mb-1">当前 Tick</div>
          <div class="font-serif text-2xl">{{ w.current_tick ?? 0 }}</div>
        </div>
        <div class="surface rounded p-4">
          <div class="text-muted text-xs uppercase tracking-wider mb-1">活跃分支</div>
          <div class="font-mono text-sm truncate" :title="w.branch_id || ''">
            {{ w.branch_id ? w.branch_id.slice(0, 14) + '…' : '—' }}
          </div>
        </div>
        <div class="surface rounded p-4">
          <div class="text-muted text-xs uppercase tracking-wider mb-1">实体</div>
          <div class="font-serif text-2xl">{{ entities.length }}</div>
        </div>
        <div class="surface rounded p-4">
          <div class="text-muted text-xs uppercase tracking-wider mb-1">最近事件</div>
          <div class="font-serif text-2xl">{{ events.length }}</div>
        </div>
      </div>

      <!-- 大纲 -->
      <section v-if="w.outline" class="mb-10">
        <h2 class="text-muted text-xs uppercase tracking-wider mb-2">大纲</h2>
        <div class="surface rounded p-5 font-serif text-prose whitespace-pre-wrap">{{ w.outline }}</div>
      </section>

      <!-- 最近事件 -->
      <section class="mb-10">
        <header class="flex items-baseline justify-between mb-3">
          <h2 class="text-muted text-xs uppercase tracking-wider">最近事件</h2>
          <button class="btn btn-ghost text-xs" @click="go('timeline')">查看时间轴 →</button>
        </header>
        <div v-if="events.length === 0" class="text-muted text-sm">还没有事件，去推演一下。</div>
        <ol v-else class="space-y-2">
          <li v-for="ev in events.slice(0, 8)" :key="ev.id"
              class="surface rounded p-4 flex gap-4">
            <div class="font-mono text-xs text-muted w-12 pt-0.5">t{{ ev.tick }}</div>
            <div class="flex-1 min-w-0">
              <div class="font-serif text-lg leading-snug">{{ ev.title || '（未命名事件）' }}</div>
              <div v-if="ev.description" class="text-sm text-muted mt-1 line-clamp-2">{{ ev.description }}</div>
            </div>
          </li>
        </ol>
      </section>

      <!-- 实体 -->
      <section>
        <header class="flex items-baseline justify-between mb-3">
          <h2 class="text-muted text-xs uppercase tracking-wider">主要实体</h2>
          <button class="btn btn-ghost text-xs" @click="go('cast')">查看角色 →</button>
        </header>
        <div v-if="entities.length === 0" class="text-muted text-sm">尚无实体。</div>
        <div v-else class="grid grid-cols-2 md:grid-cols-3 gap-2">
          <div v-for="ent in entities.slice(0, 12)" :key="ent.id"
               class="surface rounded p-3">
            <div class="font-medium text-sm truncate">{{ ent.name }}</div>
            <div v-if="ent.type" class="text-xs text-muted mt-0.5">{{ ent.type }}</div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
