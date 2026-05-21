<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { timelineApi, worldsApi,
  type TimelineEvent, type PlotThread, type CausalLinkEdge } from '@/services/api';

const route = useRoute();
const router = useRouter();
const worldId = computed(() => route.params.id as string);

const events = ref<TimelineEvent[]>([]);
const links = ref<CausalLinkEdge[]>([]);
const threads = ref<PlotThread[]>([]);
const entities = ref<{ id: string; name: string; type?: string }[]>([]);

const loading = ref(true);
const err = ref('');
const includeDrafts = ref(false);
const zoom = ref(1);

const selectedEventId = ref<string | null>(null);
const selectedThreadId = ref<string | null>(null);

// 主区滚动（用于 minimap 联动）
const mainScrollEl = ref<HTMLDivElement | null>(null);
const mainScrollLeft = ref(0);
const mainViewportWidth = ref(800);
function onMainScroll(e: Event) {
  mainScrollLeft.value = (e.target as HTMLElement).scrollLeft;
}

// ----- 角色色板 -----
const CHAR_PALETTE = [
  '#b04f33', '#6a8e6f', '#bb9856', '#4a6e8c', '#7e6090',
  '#7d6e57', '#a35d4f', '#5e8a72', '#9a7a3a', '#3d5e8a',
];
function colorForChar(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return CHAR_PALETTE[h % CHAR_PALETTE.length];
}

const entityTypeById = computed(() => {
  const m: Record<string, string> = {};
  for (const e of entities.value) m[e.id] = e.type || 'other';
  return m;
});

// 事件视觉编码
function eventMainCharId(e: TimelineEvent): string | null {
  const ps = (e.participants || []).filter(p => entityTypeById.value[p] === 'character');
  return ps[0] || null;
}
function eventColor(e: TimelineEvent): string {
  const id = eventMainCharId(e);
  return id ? colorForChar(id) : 'rgb(var(--muted))';
}
const linkCountByEvent = computed(() => {
  const m: Record<string, number> = {};
  for (const l of links.value) {
    m[l.cause] = (m[l.cause] || 0) + 1;
    m[l.effect] = (m[l.effect] || 0) + 1;
  }
  return m;
});
function eventRadius(e: TimelineEvent): number {
  const partN = (e.participants || []).length;
  const linkN = linkCountByEvent.value[e.id] || 0;
  const score = Math.max(partN, linkN);
  if (score >= 4) return 8;
  if (score >= 2) return 6.5;
  return 5;
}

const maxTick = computed(() => {
  let m = 0;
  for (const e of events.value) m = Math.max(m, e.tick);
  for (const t of threads.value) m = Math.max(m, t.closed_tick ?? t.opened_tick);
  return m;
});

const TICK_PX_BASE = 48;
const tickPx = computed(() => TICK_PX_BASE * zoom.value);
const totalWidth = computed(() => Math.max(900, (maxTick.value + 2) * tickPx.value + 80));
function tickToX(t: number) { return 40 + t * tickPx.value; }

const eventsById = computed(() => {
  const m: Record<string, TimelineEvent> = {};
  for (const e of events.value) m[e.id] = e;
  return m;
});
const entityById = computed(() => {
  const m: Record<string, string> = {};
  for (const e of entities.value) m[e.id] = e.name;
  return m;
});

const selectedEvent = computed(() => selectedEventId.value ? eventsById.value[selectedEventId.value] || null : null);
const selectedThread = computed(() => threads.value.find(t => t.id === selectedThreadId.value) || null);

const upstreamIds = computed<Set<string>>(() => {
  const id = selectedEventId.value;
  if (!id) return new Set();
  return new Set(links.value.filter(l => l.effect === id).map(l => l.cause));
});
const downstreamIds = computed<Set<string>>(() => {
  const id = selectedEventId.value;
  if (!id) return new Set();
  return new Set(links.value.filter(l => l.cause === id).map(l => l.effect));
});

const threadEventIds = computed<Set<string>>(() => {
  const t = selectedThread.value;
  if (!t || !t.related_entity_ids?.length) return new Set();
  const set = new Set(t.related_entity_ids);
  return new Set(events.value
    .filter(e => e.participants?.some(p => set.has(p)) || (e.location_id && set.has(e.location_id)))
    .map(e => e.id));
});

const threadRows = computed(() => {
  const sorted = [...threads.value].sort((a, b) => a.opened_tick - b.opened_tick);
  const ends: number[] = [];
  const result: { thread: PlotThread; row: number }[] = [];
  for (const t of sorted) {
    const closed = t.closed_tick ?? maxTick.value + 1;
    let row = ends.findIndex(e => e < t.opened_tick);
    if (row === -1) { ends.push(closed); row = ends.length - 1; }
    else ends[row] = closed;
    result.push({ thread: t, row });
  }
  return result;
});
const threadRowCount = computed(() => threadRows.value.length === 0 ? 0 : Math.max(...threadRows.value.map(r => r.row + 1)));

const HEADER_H = 30;
const THREAD_ROW_H = 26;
const THREADS_PADDING = 12;
const EVENTS_Y = computed(() => HEADER_H + (threadRowCount.value * THREAD_ROW_H) + THREADS_PADDING + 30);
const svgHeight = computed(() => EVENTS_Y.value + 80);

function isHighlighted(e: TimelineEvent): boolean {
  if (!selectedEventId.value && !selectedThreadId.value) return true;
  if (selectedEventId.value === e.id) return true;
  if (upstreamIds.value.has(e.id) || downstreamIds.value.has(e.id)) return true;
  if (threadEventIds.value.has(e.id)) return true;
  return false;
}

// ---------- Minimap ----------
const MINIMAP_H = 56;
const MINIMAP_BUCKETS = 140;
const minimapEl = ref<HTMLDivElement | null>(null);
const minimapWidth = ref(800);

const minimapBuckets = computed(() => {
  const N = MINIMAP_BUCKETS;
  const span = Math.max(1, maxTick.value + 1);
  const buckets = new Array(N).fill(0);
  for (const e of events.value) {
    const i = Math.min(N - 1, Math.floor((e.tick / span) * N));
    buckets[i]++;
  }
  return buckets;
});
const minimapMaxBucket = computed(() => Math.max(1, ...minimapBuckets.value));
const minimapBucketW = computed(() => minimapWidth.value / MINIMAP_BUCKETS);

const visibleTickStart = computed(() => mainScrollLeft.value / tickPx.value);
const visibleTickEnd = computed(() => visibleTickStart.value + mainViewportWidth.value / tickPx.value);
const minimapBoxX = computed(() => {
  const span = Math.max(1, maxTick.value + 1);
  return Math.max(0, (visibleTickStart.value / span) * minimapWidth.value);
});
const minimapBoxW = computed(() => {
  const span = Math.max(1, maxTick.value + 1);
  const w = ((visibleTickEnd.value - visibleTickStart.value) / span) * minimapWidth.value;
  return Math.max(20, Math.min(minimapWidth.value, w));
});

function jumpToTick(tick: number) {
  if (!mainScrollEl.value) return;
  const target = tick * tickPx.value - mainViewportWidth.value / 2 + 40;
  mainScrollEl.value.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
}
function onMinimapClick(e: MouseEvent) {
  if (!minimapEl.value) return;
  const rect = minimapEl.value.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const span = maxTick.value + 1;
  const tick = (x / minimapWidth.value) * span;
  jumpToTick(Math.round(tick));
}
let dragging = false;
function onMinimapBoxMouseDown(e: MouseEvent) {
  e.stopPropagation();
  dragging = true;
  const startX = e.clientX;
  const startScroll = mainScrollLeft.value;
  const span = maxTick.value + 1;
  const tickPerPx = span / minimapWidth.value;
  function move(ev: MouseEvent) {
    if (!dragging || !mainScrollEl.value) return;
    const dx = ev.clientX - startX;
    const dTick = dx * tickPerPx;
    mainScrollEl.value.scrollLeft = Math.max(0, startScroll + dTick * tickPx.value);
  }
  function up() { dragging = false; window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); }
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
}

// ResizeObserver: 跟踪主视图视口宽度 + minimap 宽度
let ro: ResizeObserver | null = null;
function setupResize() {
  ro = new ResizeObserver(entries => {
    for (const ent of entries) {
      if (ent.target === mainScrollEl.value) mainViewportWidth.value = ent.contentRect.width;
      if (ent.target === minimapEl.value) minimapWidth.value = ent.contentRect.width;
    }
  });
  if (mainScrollEl.value) ro.observe(mainScrollEl.value);
  if (minimapEl.value) ro.observe(minimapEl.value);
}

async function load() {
  loading.value = true; err.value = '';
  try {
    const [tl, snap] = await Promise.all([
      timelineApi.get(worldId.value, { include_drafts: includeDrafts.value }),
      worldsApi.get(worldId.value),
    ]);
    events.value = tl.events || [];
    links.value = tl.links || [];
    threads.value = tl.plot_threads || [];
    entities.value = (snap.entities as any) || [];
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally { loading.value = false; }
}
onMounted(async () => {
  await load();
  setupResize();
});
onBeforeUnmount(() => { ro?.disconnect(); });
watch(includeDrafts, load);

function selectEvent(id: string) { selectedEventId.value = id; selectedThreadId.value = null; }
function selectThread(id: string) { selectedThreadId.value = id; selectedEventId.value = null; }
function clearSelect() { selectedEventId.value = null; selectedThreadId.value = null; }
function gotoChapters() {
  if (!selectedEventId.value) return;
  router.push({ name: 'world.chapters', params: { id: worldId.value }, query: { event: selectedEventId.value } });
}

const tickLabelStep = computed(() => zoom.value < 0.55 ? 10 : zoom.value < 0.85 ? 5 : 1);
</script>

<template>
  <div class="flex flex-col h-full">
    <header class="h-12 px-4 border-b border-border flex items-center gap-3 shrink-0">
      <span class="text-muted text-xs">tick 0 — {{ maxTick }}</span>
      <span v-if="loading" class="text-xs text-muted">加载中…</span>
      <div class="flex-1" />
      <label class="text-xs text-muted inline-flex items-center gap-1.5">
        <input type="checkbox" v-model="includeDrafts" />
        含草稿
      </label>
      <div class="inline-flex rounded border border-border overflow-hidden text-xs">
        <button class="px-2.5 h-7 hover:bg-surface" @click="zoom = Math.max(0.4, +(zoom - 0.2).toFixed(2))">−</button>
        <span class="px-2.5 h-7 inline-flex items-center text-muted border-l border-border w-14 justify-center">{{ Math.round(zoom * 100) }}%</span>
        <button class="px-2.5 h-7 hover:bg-surface border-l border-border" @click="zoom = Math.min(3, +(zoom + 0.2).toFixed(2))">+</button>
      </div>
    </header>

    <div class="flex flex-1 min-h-0">
      <div class="flex-1 min-w-0 flex flex-col">
        <div ref="mainScrollEl" class="flex-1 overflow-auto p-4" @scroll="onMainScroll" @click="clearSelect">
          <div v-if="err" class="text-muted text-sm">{{ err }}</div>
          <div v-else-if="!loading && events.length === 0 && threads.length === 0"
               class="h-full flex items-center justify-center text-muted text-sm">
            这个分支还没有事件或情节线。先去推演里推几步看看。
          </div>
          <svg v-else
               :width="totalWidth"
               :height="svgHeight"
               class="block"
               @click.stop>
          <!-- tick grid -->
          <g>
            <template v-for="t in maxTick + 2" :key="`g${t-1}`">
              <line :x1="tickToX(t-1)" y1="20" :x2="tickToX(t-1)" :y2="svgHeight - 10"
                    stroke="rgb(var(--border))"
                    :stroke-opacity="(t-1) % 5 === 0 ? 0.6 : 0.2"
                    stroke-dasharray="2 4" />
              <text v-if="(t-1) % tickLabelStep === 0"
                    :x="tickToX(t-1)" y="14"
                    font-size="10" fill="rgb(var(--muted))" text-anchor="middle"
                    font-family="ui-monospace, SFMono-Regular, Menlo, monospace">
                {{ t-1 }}
              </text>
            </template>
          </g>

          <!-- plot threads -->
          <g :transform="`translate(0, ${HEADER_H})`">
            <g v-for="rt in threadRows" :key="rt.thread.id"
               class="cursor-pointer"
               :opacity="selectedThreadId && selectedThreadId !== rt.thread.id ? 0.3 : 1"
               @click.stop="selectThread(rt.thread.id)">
              <rect :x="tickToX(rt.thread.opened_tick)"
                    :y="rt.row * THREAD_ROW_H + 2"
                    :width="Math.max(10, tickToX(rt.thread.closed_tick ?? maxTick) - tickToX(rt.thread.opened_tick))"
                    :height="THREAD_ROW_H - 6"
                    rx="3"
                    :fill="rt.thread.status === 'open' ? 'rgb(176 79 51 / 0.85)' : 'rgb(var(--muted) / 0.55)'"
                    :stroke="selectedThreadId === rt.thread.id ? 'rgb(var(--text))' : 'transparent'"
                    stroke-width="2" />
              <text :x="tickToX(rt.thread.opened_tick) + 6"
                    :y="rt.row * THREAD_ROW_H + 2 + (THREAD_ROW_H - 6) / 2 + 4"
                    font-size="11"
                    fill="rgb(var(--bg))"
                    font-weight="500"
                    pointer-events="none"
                    font-family='"Noto Serif SC", Georgia, serif'>
                {{ rt.thread.title }}
              </text>
            </g>
          </g>

          <!-- causal arcs (selected event) -->
          <g v-if="selectedEventId" :transform="`translate(0, ${EVENTS_Y})`" pointer-events="none">
            <template v-for="l in links" :key="`${l.cause}-${l.effect}`">
              <path v-if="l.cause === selectedEventId || l.effect === selectedEventId"
                    :d="`M ${tickToX(eventsById[l.cause]?.tick ?? 0)} 14 Q ${(tickToX(eventsById[l.cause]?.tick ?? 0) + tickToX(eventsById[l.effect]?.tick ?? 0)) / 2} ${l.cause === selectedEventId ? -22 : 50} ${tickToX(eventsById[l.effect]?.tick ?? 0)} 14`"
                    fill="none"
                    stroke="rgb(232 153 104 / 0.9)"
                    stroke-width="1.4"
                    :stroke-dasharray="l.cause === selectedEventId ? '0' : '4 3'" />
            </template>
          </g>

          <!-- events -->
          <g :transform="`translate(0, ${EVENTS_Y})`">
            <g v-for="e in events" :key="e.id"
               class="cursor-pointer"
               @click.stop="selectEvent(e.id)">
              <circle :cx="tickToX(e.tick)" cy="14"
                      :r="selectedEventId === e.id ? eventRadius(e) + 2 : eventRadius(e)"
                      :fill="eventColor(e)"
                      :stroke="selectedEventId === e.id ? 'rgb(var(--text))' : 'rgb(var(--bg))'"
                      :stroke-width="selectedEventId === e.id ? 2 : 1"
                      :opacity="isHighlighted(e) ? 1 : 0.22"
                      class="transition-all" />
              <title>{{ e.title }} (t{{ e.tick }})</title>
            </g>
          </g>
        </svg>
        </div>

        <!-- minimap -->
        <div v-if="!loading && events.length > 0"
             class="border-t border-border surface-sunken px-4 py-2 shrink-0 select-none">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-muted text-[10px] uppercase tracking-wider">概览</span>
            <span class="text-muted text-xs">{{ events.length }} 事件 / 0 - {{ maxTick }}</span>
            <div class="flex-1" />
            <span class="text-muted text-xs">视口 t{{ Math.round(visibleTickStart) }} – t{{ Math.round(visibleTickEnd) }}</span>
          </div>
          <div ref="minimapEl"
               class="relative cursor-pointer"
               :style="{ height: MINIMAP_H + 'px' }"
               @click="onMinimapClick">
            <!-- 桶柱状图 -->
            <svg :width="minimapWidth" :height="MINIMAP_H" class="absolute inset-0">
              <line :x1="0" :y1="MINIMAP_H - 1" :x2="minimapWidth" :y2="MINIMAP_H - 1"
                    stroke="rgb(var(--border))" stroke-width="1" />
              <rect v-for="(c, i) in minimapBuckets" :key="i"
                    :x="i * minimapBucketW"
                    :y="MINIMAP_H - 4 - (c / minimapMaxBucket) * (MINIMAP_H - 8)"
                    :width="Math.max(1, minimapBucketW - 0.5)"
                    :height="(c / minimapMaxBucket) * (MINIMAP_H - 8)"
                    :fill="c > 0 ? 'rgb(var(--muted))' : 'transparent'"
                    :opacity="c > 0 ? 0.7 : 0" />
            </svg>
            <!-- 视口框 -->
            <div class="absolute top-0 bottom-0 border border-accent rounded-sm cursor-grab active:cursor-grabbing"
                 :style="{
                   left: minimapBoxX + 'px',
                   width: minimapBoxW + 'px',
                   background: 'rgb(232 153 104 / 0.18)',
                 }"
                 @mousedown="onMinimapBoxMouseDown"
                 @click.stop />
          </div>
        </div>
      </div>

      <aside class="w-[320px] shrink-0 border-l border-border surface-sunken overflow-y-auto">
        <div v-if="!selectedEvent && !selectedThread" class="p-5 text-sm">
          <p class="text-muted text-xs uppercase tracking-wider mb-3">综览</p>
          <dl class="space-y-2 mb-6">
            <div class="flex justify-between"><dt class="text-muted">事件总数</dt><dd>{{ events.length }}</dd></div>
            <div class="flex justify-between"><dt class="text-muted">情节线</dt><dd>{{ threads.length }}</dd></div>
            <div class="flex justify-between"><dt class="text-muted">未结线</dt><dd>{{ threads.filter(t => t.status === 'open').length }}</dd></div>
            <div class="flex justify-between"><dt class="text-muted">最大 tick</dt><dd>{{ maxTick }}</dd></div>
            <div class="flex justify-between"><dt class="text-muted">因果链</dt><dd>{{ links.length }}</dd></div>
          </dl>
          <p class="text-muted text-xs uppercase tracking-wider mb-2">图例</p>
          <div class="space-y-1.5 mb-4">
            <div class="flex items-center gap-2 text-xs">
              <span class="w-6 h-2 rounded-sm" style="background:rgb(176 79 51 / 0.85)" />
              <span>未结情节线</span>
            </div>
            <div class="flex items-center gap-2 text-xs">
              <span class="w-6 h-2 rounded-sm" style="background:rgb(var(--muted) / 0.55)" />
              <span>已结情节线</span>
            </div>
            <div class="flex items-center gap-2 text-xs pt-1.5">
              <span class="inline-flex items-center gap-0.5">
                <span class="w-2 h-2 rounded-full" style="background:#b04f33" />
                <span class="w-2.5 h-2.5 rounded-full" style="background:#6a8e6f" />
                <span class="w-3.5 h-3.5 rounded-full" style="background:#4a6e8c" />
              </span>
              <span>颜色 = 主参与者，大小 = 重要度</span>
            </div>
          </div>
          <p class="text-muted text-xs leading-relaxed">点击事件查看因果链，点击情节线条查看其涉及事件。</p>
        </div>

        <div v-else-if="selectedEvent" class="p-5">
          <p class="font-mono text-xs text-muted mb-1">tick {{ selectedEvent.tick }}</p>
          <h2 class="font-serif text-xl mb-3">{{ selectedEvent.title }}</h2>
          <p class="text-sm leading-relaxed whitespace-pre-wrap mb-4">{{ selectedEvent.description }}</p>

          <div v-if="selectedEvent.participants?.length" class="mb-4">
            <p class="text-muted text-xs uppercase tracking-wider mb-1.5">参与者</p>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="pid in selectedEvent.participants" :key="pid"
                    class="px-2 h-6 inline-flex items-center rounded text-xs surface border border-border">
                {{ entityById[pid] || pid }}
              </span>
            </div>
          </div>

          <div v-if="upstreamIds.size > 0" class="mb-3">
            <p class="text-muted text-xs uppercase tracking-wider mb-1.5">起因</p>
            <ul class="space-y-1">
              <li v-for="id in [...upstreamIds]" :key="id" class="text-sm">
                <button class="hover:underline text-left" @click.stop="selectEvent(id)">
                  <span class="font-mono text-xs text-muted mr-1">t{{ eventsById[id]?.tick }}</span>
                  {{ eventsById[id]?.title || id }}
                </button>
              </li>
            </ul>
          </div>
          <div v-if="downstreamIds.size > 0" class="mb-3">
            <p class="text-muted text-xs uppercase tracking-wider mb-1.5">影响</p>
            <ul class="space-y-1">
              <li v-for="id in [...downstreamIds]" :key="id" class="text-sm">
                <button class="hover:underline text-left" @click.stop="selectEvent(id)">
                  <span class="font-mono text-xs text-muted mr-1">t{{ eventsById[id]?.tick }}</span>
                  {{ eventsById[id]?.title || id }}
                </button>
              </li>
            </ul>
          </div>

          <button class="btn btn-ghost text-xs mt-3 px-2" @click.stop="gotoChapters">
            在章节里查看 →
          </button>
        </div>

        <div v-else-if="selectedThread" class="p-5">
          <p class="text-muted text-xs uppercase tracking-wider mb-1">{{ selectedThread.status === 'open' ? '未结情节线' : '已完结' }}</p>
          <h2 class="font-serif text-xl mb-3">{{ selectedThread.title }}</h2>
          <p class="text-sm leading-relaxed mb-3">{{ selectedThread.summary }}</p>
          <p class="font-mono text-xs text-muted mb-2">
            t{{ selectedThread.opened_tick }} —
            {{ selectedThread.closed_tick !== null ? 't' + selectedThread.closed_tick : '进行中' }}
          </p>
          <p v-if="selectedThread.resolution" class="text-sm italic text-muted mb-3">「{{ selectedThread.resolution }}」</p>

          <div v-if="selectedThread.related_entity_ids?.length" class="mb-3">
            <p class="text-muted text-xs uppercase tracking-wider mb-1.5">相关</p>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="id in selectedThread.related_entity_ids" :key="id"
                    class="px-2 h-6 inline-flex items-center rounded text-xs surface border border-border">
                {{ entityById[id] || id }}
              </span>
            </div>
          </div>

          <p class="text-muted text-xs mt-4">{{ threadEventIds.size }} 个相关事件已在轴上高亮</p>
        </div>
      </aside>
    </div>
  </div>
</template>
