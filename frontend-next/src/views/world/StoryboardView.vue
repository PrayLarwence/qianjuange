<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { storyboardApi, type StoryboardChapter } from '@/services/api';

const route = useRoute();
const router = useRouter();
const worldId = computed(() => route.params.id as string);

const chapters = ref<StoryboardChapter[]>([]);
const maxTick = ref(0);
const loading = ref(true);
const err = ref('');

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const r = await storyboardApi.get(worldId.value, { top_events: 8, top_characters: 6 });
    chapters.value = r.chapters || [];
    maxTick.value = r.max_tick || 0;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, load);

const SEV_CLS: Record<string, string> = {
  high:   'bg-[#b04f33]/15 text-[#b04f33] border-[#b04f33]/30',
  medium: 'bg-[#bb9856]/15 text-[#bb9856] border-[#bb9856]/30',
  low:    'bg-[#6a8e6f]/15 text-[#6a8e6f] border-[#6a8e6f]/30',
};
const SEV_LABEL: Record<string, string> = { high: '严重', medium: '中等', low: '轻微' };

const PHASE_META: Record<string, { label: string; cls: string }> = {
  opened:  { label: '开启', cls: 'text-accent' },
  closed:  { label: '收束', cls: 'text-[#6a8e6f]' },
  ongoing: { label: '推进', cls: 'text-muted' },
};

const totalCount = computed(() => ({
  events: chapters.value.reduce((s, c) => s + c.event_count, 0),
  issues: chapters.value.reduce((s, c) => s + c.issues.length, 0),
}));

function gotoTimeline(tick: number) {
  router.push(`/worlds/${worldId.value}/timeline?tick=${tick}`);
}
function gotoEntity(id: string) {
  router.push(`/worlds/${worldId.value}/cast?id=${id}`);
}
function gotoIssue(_id: string) {
  router.push(`/worlds/${worldId.value}/review`);
}
function gotoChapters() {
  router.push(`/worlds/${worldId.value}/chapters`);
}
</script>

<template>
  <div class="px-8 py-8 max-w-5xl mx-auto">
    <header class="flex items-baseline justify-between mb-2">
      <p class="text-muted text-xs uppercase tracking-wider">故事板</p>
      <button class="btn btn-ghost text-xs" @click="gotoChapters">在章节中编辑 →</button>
    </header>
    <h1 class="font-serif text-4xl mb-2">章节速览</h1>
    <p class="text-muted text-sm mb-8">
      <template v-if="loading">加载中…</template>
      <template v-else-if="chapters.length === 0">还没有章节标记。</template>
      <template v-else>
        共 {{ chapters.length }} 章 ·
        {{ totalCount.events }} 事件 ·
        <span :class="totalCount.issues > 0 ? 'text-[#b04f33]' : ''">{{ totalCount.issues }} 待审</span> ·
        覆盖 t0 → t{{ maxTick }}
      </template>
    </p>

    <div v-if="err" class="text-muted text-sm mb-8">{{ err }}</div>

    <div v-if="loading" class="text-muted text-sm">加载中…</div>

    <div v-else-if="chapters.length === 0" class="surface rounded p-12 text-center">
      <p class="font-serif text-2xl mb-2">这个世界还没分章</p>
      <p class="text-muted text-sm mb-4">推演产生事件后，可以在「章节」里手动或自动添加分章标记。</p>
      <button class="btn btn-accent text-xs" @click="gotoChapters">去章节面板</button>
    </div>

    <ol v-else class="space-y-6">
      <li v-for="ch in chapters" :key="ch.id"
          class="surface rounded p-6 shadow-soft">
        <header class="flex items-baseline gap-3 mb-3 pb-3 border-b border-border">
          <span class="font-mono text-xs text-muted shrink-0">
            t{{ ch.tick_start }}<span v-if="ch.tick_end !== ch.tick_start"> – t{{ ch.tick_end }}</span>
          </span>
          <h2 class="font-serif text-2xl flex-1 min-w-0 truncate">{{ ch.title }}</h2>
          <span class="text-xs text-muted shrink-0 font-mono">{{ ch.event_count }} 事件</span>
          <button class="btn btn-ghost text-xs shrink-0"
                  @click="gotoTimeline(ch.tick_start)">时间轴 →</button>
        </header>

        <p v-if="ch.summary"
           class="font-serif text-prose leading-relaxed mb-4 whitespace-pre-wrap">{{ ch.summary }}</p>
        <p v-else-if="ch.is_synthetic" class="text-xs text-muted italic mb-4">
          这是基于 tick 范围生成的虚拟分组，没有手写概要。
        </p>

        <div class="grid md:grid-cols-2 gap-5">
          <!-- 角色 -->
          <section v-if="ch.characters.length > 0">
            <h3 class="text-muted text-xs uppercase tracking-wider mb-2">出场角色</h3>
            <ul class="flex flex-wrap gap-1.5">
              <li v-for="c in ch.characters" :key="c.id">
                <button class="px-2 h-6 rounded-full text-xs border border-border bg-sunken/60 hover:bg-surface inline-flex items-center gap-1.5"
                        :class="!c.alive ? 'opacity-60 line-through' : ''"
                        @click="gotoEntity(c.id)">
                  {{ c.name }}
                  <span class="text-muted font-mono">×{{ c.appearances }}</span>
                </button>
              </li>
            </ul>
          </section>

          <!-- 推进的 thread -->
          <section v-if="ch.threads.length > 0">
            <h3 class="text-muted text-xs uppercase tracking-wider mb-2">情节线</h3>
            <ul class="space-y-1">
              <li v-for="t in ch.threads" :key="t.id"
                  class="flex items-baseline gap-2 text-sm">
                <span class="text-xs shrink-0 w-10"
                      :class="PHASE_META[t.phase]?.cls">
                  {{ PHASE_META[t.phase]?.label || t.phase }}
                </span>
                <span class="flex-1 min-w-0 truncate">{{ t.title }}</span>
              </li>
            </ul>
          </section>
        </div>

        <!-- 关键事件 -->
        <section v-if="ch.events.length > 0" class="mt-5">
          <h3 class="text-muted text-xs uppercase tracking-wider mb-2">关键事件</h3>
          <ul class="space-y-1.5">
            <li v-for="ev in ch.events" :key="ev.id"
                class="flex items-baseline gap-3 text-sm">
              <span class="font-mono text-xs text-muted w-10 shrink-0">t{{ ev.tick }}</span>
              <button class="flex-1 min-w-0 text-left hover:text-accent transition-colors"
                      @click="gotoTimeline(ev.tick)">
                <span class="truncate block">{{ ev.title || '（无标题）' }}</span>
              </button>
              <span v-if="ev.participants.length > 0" class="text-xs text-muted shrink-0 hidden md:block">
                {{ ev.participants.slice(0, 3).map(p => p.name).join('、') }}<span v-if="ev.participants.length > 3">…</span>
              </span>
            </li>
          </ul>
        </section>

        <!-- issue 警示 -->
        <section v-if="ch.issues.length > 0" class="mt-5 pt-4 border-t border-border">
          <h3 class="text-muted text-xs uppercase tracking-wider mb-2">章内待审 {{ ch.issues.length }} 条</h3>
          <ul class="space-y-1">
            <li v-for="iss in ch.issues" :key="iss.id"
                class="flex items-baseline gap-2 text-sm">
              <span class="text-[10px] px-1.5 py-0.5 rounded border shrink-0"
                    :class="SEV_CLS[iss.severity] || 'bg-sunken text-muted'">
                {{ SEV_LABEL[iss.severity] || iss.severity }}
              </span>
              <button class="flex-1 min-w-0 text-left hover:text-accent transition-colors truncate"
                      @click="gotoIssue(iss.id)">{{ iss.title }}</button>
              <span class="font-mono text-xs text-muted shrink-0">t{{ iss.tick }}</span>
            </li>
          </ul>
        </section>
      </li>
    </ol>
  </div>
</template>
