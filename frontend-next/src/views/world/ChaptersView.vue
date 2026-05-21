<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  chaptersApi, worldsApi, novelizeApi,
  type ChapterMarker, type TimelineEvent, type WorldDetail,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import { useJob } from '@/composables/useJob';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';
import Markdown from '@/components/Markdown.vue';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const chapters = ref<ChapterMarker[]>([]);
const events = ref<TimelineEvent[]>([]);
const loading = ref(true);
const err = ref('');
const selectedId = ref<string | null>(null);

type Mode = 'events' | 'manuscript';
const mode = ref<Mode>('events');

interface ManuChapter {
  index: number;
  title: string;
  tick_lo: number;
  tick_hi: number;
  markdown: string;
  event_count: number;
}
const manuscript = ref<ManuChapter[]>([]);
const selectedManuIndex = ref<number>(0);

function manuKey() {
  const bid = world.value?.branch_id || '';
  return `manuscript:${worldId.value}:${bid}`;
}
function loadManuscriptCache() {
  try {
    const raw = localStorage.getItem(manuKey());
    if (!raw) { manuscript.value = []; return; }
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed?.chapters)) manuscript.value = parsed.chapters;
  } catch { manuscript.value = []; }
}
function saveManuscriptCache(payload: { chapters: ManuChapter[]; markdown: string }) {
  try { localStorage.setItem(manuKey(), JSON.stringify(payload)); } catch { /* quota */ }
}

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [snap, chs, tl] = await Promise.all([
      worldsApi.get(worldId.value),
      chaptersApi.list(worldId.value),
      worldsApi.timeline(worldId.value),
    ]);
    world.value = snap.world;
    chapters.value = chs;
    events.value = tl.events;
    if (!selectedId.value && chs.length > 0) selectedId.value = chs[0].id;
    loadManuscriptCache();
    if (manuscript.value.length > 0 && mode.value === 'events') {
      // 有缓存就默认进手稿模式（用户上次留下的）
      mode.value = 'manuscript';
    }
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, () => { selectedId.value = null; load(); });

// 用相邻章节的 tick 当边界，把事件切到每章
const chapterRanges = computed(() => {
  const sorted = [...chapters.value].sort((a, b) => a.tick - b.tick);
  return sorted.map((ch, i) => ({
    id: ch.id,
    title: ch.title || `第 ${i + 1} 章`,
    tickLo: ch.tick,
    tickHi: i + 1 < sorted.length ? sorted[i + 1].tick - 1 : Infinity,
    raw: ch,
  }));
});

const selectedRange = computed(() =>
  chapterRanges.value.find(r => r.id === selectedId.value) || null,
);

const selectedEvents = computed(() => {
  const r = selectedRange.value;
  if (!r) return [];
  return events.value.filter(e => e.tick >= r.tickLo && e.tick <= r.tickHi);
});

const maxTick = computed(() =>
  events.value.length ? events.value[events.value.length - 1].tick : 0,
);

// ---------- 来自时间轴的事件聚焦 ----------
const focusEventId = ref<string | null>(null);
let focusAttempts = 0;

async function tryFocus() {
  const id = focusEventId.value;
  if (!id) return;
  if (loading.value || events.value.length === 0) return;
  const ev = events.value.find(e => e.id === id);
  if (!ev) {
    if (++focusAttempts < 3) return;  // 等数据
    focusEventId.value = null;
    return;
  }
  mode.value = 'events';
  const range = chapterRanges.value.find(r => ev.tick >= r.tickLo && ev.tick <= r.tickHi);
  if (range) selectedId.value = range.id;
  await nextTick();
  await new Promise(r => setTimeout(r, 60));
  const el = document.getElementById(`event-${id}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('flash-highlight');
    setTimeout(() => el.classList.remove('flash-highlight'), 2000);
  }
  focusEventId.value = null;
  focusAttempts = 0;
}

watch(
  () => route.query.event,
  (id) => {
    if (typeof id === 'string' && id) {
      focusEventId.value = id;
      focusAttempts = 0;
      tryFocus();
    }
  },
  { immediate: true },
);
watch([events, chapterRanges, loading], () => tryFocus());

// --- 新建章节标记 ---
const createOpen = ref(false);
const draft = ref({ tick: 0, title: '' });
const creating = ref(false);
function openCreate() {
  draft.value = { tick: chapters.value.length === 0 ? 0 : maxTick.value, title: '' };
  createOpen.value = true;
}
async function submitCreate() {
  creating.value = true;
  try {
    const r = await chaptersApi.create(worldId.value, {
      tick: Number(draft.value.tick) || 0,
      title: draft.value.title.trim(),
    });
    toast.success('已添加章节标记');
    createOpen.value = false;
    selectedId.value = r.id;
    await load();
  } catch (e: any) {
    toast.error(`新建失败：${e.message || e}`);
  } finally {
    creating.value = false;
  }
}

// --- 重命名 ---
const renameOpen = ref(false);
const renameDraft = ref({ id: '', title: '' });
const renaming = ref(false);
function openRename() {
  if (!selectedRange.value) return;
  renameDraft.value = {
    id: selectedRange.value.id,
    title: selectedRange.value.raw.title || selectedRange.value.title,
  };
  renameOpen.value = true;
}
async function submitRename() {
  renaming.value = true;
  try {
    await chaptersApi.patch(renameDraft.value.id, { title: renameDraft.value.title.trim() });
    toast.success('已重命名');
    renameOpen.value = false;
    await load();
  } catch (e: any) {
    toast.error(`重命名失败：${e.message || e}`);
  } finally {
    renaming.value = false;
  }
}

// --- 删除 ---
const confirmOpen = ref(false);
const deleting = ref(false);
function askDelete() { if (selectedRange.value) confirmOpen.value = true; }
async function doDelete() {
  if (!selectedRange.value) return;
  deleting.value = true;
  try {
    await chaptersApi.remove(selectedRange.value.id);
    toast.success('已删除章节标记');
    confirmOpen.value = false;
    selectedId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  } finally {
    deleting.value = false;
  }
}

// --- 生成手稿 ---
const genOpen = ref(false);
const genOpts = ref({
  strategy: 'by_count' as 'by_count' | 'manual',
  chapter_size: 6,
});
const { running: genRunning, job: genJob, poll: pollJob, cancel: cancelJob, reset: resetJob } = useJob({ intervalMs: 800 });
const genError = ref<{ summary: string; detail?: string } | null>(null);

const genProgress = computed(() => {
  const msg = genJob.value?.progress_message || '';
  const m = msg.match(/第\s*(\d+)\s*\/\s*(\d+)\s*章/);
  return m ? { done: +m[1], total: +m[2], msg } : { done: 0, total: 0, msg };
});

function openGen() {
  genOpts.value = {
    strategy: chapters.value.length > 0 ? 'manual' : 'by_count',
    chapter_size: 6,
  };
  genError.value = null;
  genOpen.value = true;
}

async function startGen() {
  genOpen.value = false;
  genError.value = null;
  resetJob();
  try {
    const r = await novelizeApi.runAsync(worldId.value, {
      branch_id: world.value?.branch_id,
      strategy: genOpts.value.strategy,
      chapter_size: genOpts.value.chapter_size,
    });
    const j = await pollJob(r.job_id);
    const result = j.result || {};
    const newChapters: ManuChapter[] = result.chapters || [];
    if (newChapters.length === 0) {
      genError.value = {
        summary: '生成完成但没有章节内容',
        detail: '可能是该分支还没有事件，或所选 strategy 下切片为空。',
      };
      return;
    }
    manuscript.value = newChapters;
    saveManuscriptCache({ chapters: newChapters, markdown: result.markdown || '' });
    selectedManuIndex.value = 0;
    mode.value = 'manuscript';
    toast.success(`已生成 ${newChapters.length} 章`);
  } catch (e: any) {
    // 优先用 job.error（后端最详细），其次 ApiError.body.detail，再回落 message
    const jobErr = genJob.value?.error;
    const apiBody: any = e?.body;
    const apiDetail = typeof apiBody === 'object' && apiBody?.detail ? String(apiBody.detail) : '';
    genError.value = {
      summary: jobErr || apiDetail || e?.message || String(e),
      detail: jobErr ? `Job 状态：${genJob.value?.status || '?'}` : (apiDetail ? `HTTP ${e?.status || '?'}` : ''),
    };
    toast.error('生成失败，详情见上方错误条');
  }
}

async function abortGen() {
  await cancelJob();
  toast.info('已取消生成');
}

function clearManuscript() {
  manuscript.value = [];
  selectedManuIndex.value = 0;
  mode.value = 'events';
  try { localStorage.removeItem(manuKey()); } catch { /* ignore */ }
}

const selectedManuChapter = computed(() => manuscript.value[selectedManuIndex.value] || null);
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 顶部条：模式切换 + 生成 -->
    <header class="h-12 px-4 border-b border-border flex items-center gap-3 shrink-0">
      <div class="inline-flex rounded border border-border overflow-hidden text-sm">
        <button class="px-3 h-8 transition-colors"
                :class="mode === 'events' ? 'bg-surface' : 'hover:bg-surface/60 text-muted'"
                @click="mode = 'events'">事件流</button>
        <button class="px-3 h-8 transition-colors"
                :class="mode === 'manuscript' ? 'bg-surface' : 'hover:bg-surface/60 text-muted'"
                :disabled="manuscript.length === 0 && !genRunning"
                @click="manuscript.length > 0 && (mode = 'manuscript')">
          📖 阅读
          <span v-if="manuscript.length > 0" class="ml-1 text-xs text-muted">{{ manuscript.length }}</span>
        </button>
      </div>
      <div class="flex-1" />
      <button v-if="manuscript.length > 0 && !genRunning"
              class="btn btn-ghost text-xs" @click="clearManuscript" title="清空本地缓存的手稿">清空手稿</button>
      <button v-if="!genRunning" class="btn btn-accent" @click="openGen">
        ✨ {{ manuscript.length > 0 ? '重新生成手稿' : '生成手稿' }}
      </button>
      <button v-else class="btn btn-ghost hover:!text-red-500" @click="abortGen">取消生成</button>
    </header>

    <!-- 生成进度条 -->
    <div v-if="genRunning" class="px-4 py-2.5 border-b border-border bg-sunken text-sm flex items-center gap-3 shrink-0">
      <span class="inline-block w-3 h-3 rounded-full bg-accent animate-pulse" />
      <span class="font-mono text-xs text-muted">
        {{ genProgress.total > 0 ? `${genProgress.done}/${genProgress.total}` : '准备中' }}
      </span>
      <span class="flex-1 truncate">{{ genProgress.msg || '与模型对话中…' }}</span>
      <div v-if="genProgress.total > 0" class="w-32 h-1 rounded bg-surface overflow-hidden">
        <div class="h-full bg-accent transition-all"
             :style="{ width: `${(genProgress.done / genProgress.total) * 100}%` }" />
      </div>
    </div>

    <!-- 错误条 -->
    <div v-if="genError && !genRunning"
         class="px-4 py-3 border-b border-red-500/40 bg-red-500/5 text-sm shrink-0 flex items-start gap-3">
      <span class="text-red-500 font-mono shrink-0">!</span>
      <div class="flex-1 min-w-0">
        <div class="font-medium">生成失败</div>
        <div class="text-muted mt-1 break-words whitespace-pre-wrap font-mono text-xs">{{ genError.summary }}</div>
        <div v-if="genError.detail" class="text-muted/70 mt-1 text-xs">{{ genError.detail }}</div>
      </div>
      <button class="btn btn-ghost !h-6 !px-2" @click="genError = null" title="关闭">×</button>
    </div>

    <div class="flex flex-1 min-h-0">
      <!-- 章节列表 -->
      <aside class="w-[280px] shrink-0 surface-sunken border-r border-border flex flex-col">
        <header class="px-4 h-12 flex items-center justify-between border-b border-border">
          <span class="text-xs uppercase tracking-wider text-muted">
            {{ mode === 'manuscript' ? '已生成章节' : '章节标记' }}
          </span>
          <button v-if="mode === 'events'" class="btn btn-ghost !h-7 !px-2 text-xs"
                  @click="openCreate" title="新建章节标记">+</button>
        </header>
        <div class="flex-1 overflow-y-auto py-1">
          <!-- 事件流模式 -->
          <template v-if="mode === 'events'">
            <div v-if="loading" class="px-4 py-3 text-sm text-muted">加载中…</div>
            <div v-else-if="err" class="px-4 py-3 text-sm text-muted">{{ err }}</div>
            <div v-else-if="chapterRanges.length === 0" class="px-4 py-6 text-sm text-muted leading-relaxed">
              还没有章节标记。<br>
              <button class="btn btn-ghost text-xs mt-2 px-0 underline" @click="openCreate">添加第一个</button>
            </div>
            <button v-for="(r, i) in chapterRanges" :key="r.id"
                    class="w-full text-left px-4 py-2.5 flex items-baseline gap-2 hover:bg-surface transition-colors"
                    :class="{ 'bg-surface': r.id === selectedId }"
                    @click="selectedId = r.id">
              <span class="font-mono text-xs text-muted w-7 shrink-0">{{ i + 1 }}</span>
              <div class="flex-1 min-w-0">
                <div class="font-serif text-sm truncate">{{ r.title }}</div>
                <div class="text-xs text-muted mt-0.5">
                  tick {{ r.tickLo }}<span v-if="isFinite(r.tickHi as number)">–{{ r.tickHi }}</span>
                  <span v-else>+</span>
                </div>
              </div>
            </button>
          </template>

          <!-- 手稿模式 -->
          <template v-else>
            <button v-for="(c, i) in manuscript" :key="i"
                    class="w-full text-left px-4 py-2.5 flex items-baseline gap-2 hover:bg-surface transition-colors"
                    :class="{ 'bg-surface': i === selectedManuIndex }"
                    @click="selectedManuIndex = i">
              <span class="font-mono text-xs text-muted w-7 shrink-0">{{ c.index }}</span>
              <div class="flex-1 min-w-0">
                <div class="font-serif text-sm truncate">{{ c.title }}</div>
                <div class="text-xs text-muted mt-0.5">
                  tick {{ c.tick_lo }}–{{ c.tick_hi }} · {{ c.event_count }} 事件
                </div>
              </div>
            </button>
          </template>
        </div>
      </aside>

      <!-- 主区 -->
      <section class="flex-1 min-w-0 overflow-y-auto">
        <!-- 事件流模式 -->
        <template v-if="mode === 'events'">
          <div v-if="!selectedRange && !loading" class="h-full flex items-center justify-center text-muted">
            <div class="text-center">
              <p class="font-serif text-xl mb-2">从左侧选一章</p>
              <p class="text-sm">或者新建一个章节标记开始</p>
            </div>
          </div>

          <article v-else-if="selectedRange" class="max-w-3xl mx-auto px-10 py-12">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">
              第 {{ chapterRanges.findIndex(r => r.id === selectedRange!.id) + 1 }} 章 ·
              tick {{ selectedRange.tickLo }}<span v-if="isFinite(selectedRange.tickHi as number)">–{{ selectedRange.tickHi }}</span>
            </p>
            <h1 class="font-serif text-4xl mb-2">{{ selectedRange.title }}</h1>
            <div class="flex items-center gap-2 mb-8 text-xs">
              <button class="btn btn-ghost" @click="openRename">重命名</button>
              <button class="btn btn-ghost hover:!text-red-500" @click="askDelete">删除标记</button>
            </div>

            <div v-if="selectedRange.raw.note" class="text-muted font-serif text-prose mb-8 italic">
              {{ selectedRange.raw.note }}
            </div>
            <div v-if="selectedRange.raw.summary" class="surface rounded p-5 mb-8">
              <p class="text-muted text-xs uppercase tracking-wider mb-2">章节摘要</p>
              <p class="font-serif leading-relaxed">{{ selectedRange.raw.summary }}</p>
            </div>

            <section>
              <h2 class="text-muted text-xs uppercase tracking-wider mb-3">事件流</h2>
              <div v-if="selectedEvents.length === 0" class="text-muted text-sm">该章范围内还没有事件。</div>
              <ol v-else class="space-y-5">
                <li v-for="ev in selectedEvents" :key="ev.id" :id="`event-${ev.id}`" class="flex gap-5 px-2 -mx-2 py-1 rounded transition-colors">
                  <div class="font-mono text-xs text-muted w-12 shrink-0 pt-1">t{{ ev.tick }}</div>
                  <div class="flex-1 min-w-0">
                    <h3 class="font-serif text-xl leading-snug mb-1">{{ ev.title || '（未命名事件）' }}</h3>
                    <p v-if="ev.description" class="font-serif text-prose text-text leading-relaxed">{{ ev.description }}</p>
                    <p v-if="ev.consequences" class="text-sm text-muted mt-2 italic">→ {{ ev.consequences }}</p>
                  </div>
                </li>
              </ol>
            </section>
          </article>
        </template>

        <!-- 手稿模式 -->
        <template v-else>
          <div v-if="!selectedManuChapter" class="h-full flex items-center justify-center text-muted">
            <p class="font-serif text-xl">还没有选择章节</p>
          </div>
          <article v-else class="max-w-3xl mx-auto px-10 py-12">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">
              第 {{ selectedManuChapter.index }} 章 ·
              tick {{ selectedManuChapter.tick_lo }}–{{ selectedManuChapter.tick_hi }}
            </p>
            <Markdown :source="selectedManuChapter.markdown" />
            <div class="mt-12 pt-6 border-t border-border flex items-center justify-between text-xs text-muted">
              <span>{{ selectedManuChapter.event_count }} 个事件 · {{ selectedManuChapter.markdown.length }} 字</span>
              <div class="flex gap-2">
                <button class="btn btn-ghost"
                        :disabled="selectedManuIndex <= 0"
                        @click="selectedManuIndex--">← 上一章</button>
                <button class="btn btn-ghost"
                        :disabled="selectedManuIndex >= manuscript.length - 1"
                        @click="selectedManuIndex++">下一章 →</button>
              </div>
            </div>
          </article>
        </template>
      </section>
    </div>

    <!-- 新建对话框 -->
    <Dialog :open="createOpen" title="新建章节标记" width="420px"
            @close="!creating && (createOpen = false)">
      <form class="space-y-4" @submit.prevent="submitCreate">
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">起始 tick</span>
          <input v-model.number="draft.tick" type="number" min="0" class="input" />
          <span class="text-xs text-muted mt-1 block">当前世界已演进到 tick {{ maxTick }}</span>
        </label>
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">标题（可选）</span>
          <input v-model="draft.title" class="input" placeholder="第三章 · 港口的夜" />
        </label>
      </form>
      <template #footer>
        <button class="btn btn-ghost" :disabled="creating" @click="createOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="creating" @click="submitCreate">
          <span v-if="creating">创建中…</span><span v-else>创建</span>
        </button>
      </template>
    </Dialog>

    <!-- 重命名 -->
    <Dialog :open="renameOpen" title="重命名章节" width="420px"
            @close="!renaming && (renameOpen = false)">
      <form class="space-y-4" @submit.prevent="submitRename">
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">标题</span>
          <input v-model="renameDraft.title" class="input" autofocus />
        </label>
      </form>
      <template #footer>
        <button class="btn btn-ghost" :disabled="renaming" @click="renameOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="renaming" @click="submitRename">
          <span v-if="renaming">保存中…</span><span v-else>保存</span>
        </button>
      </template>
    </Dialog>

    <!-- 删除确认 -->
    <ConfirmDialog
      :open="confirmOpen"
      :busy="deleting"
      title="删除章节标记"
      :confirm-text="'删除'"
      danger
      @cancel="!deleting && (confirmOpen = false)"
      @confirm="doDelete">
      仅删除该章节标记，事件本身不受影响。
      <strong v-if="selectedRange" class="text-text block mt-2">「{{ selectedRange.title }}」</strong>
    </ConfirmDialog>

    <!-- 生成手稿对话框 -->
    <Dialog :open="genOpen" title="生成手稿" width="480px" @close="genOpen = false">
      <div class="space-y-5">
        <p class="text-sm text-muted leading-relaxed">
          模型会将本世界活跃分支的事件流润色成小说体。生成时长取决于章节数与模型速度，过程中可随时取消。
        </p>
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-2">分章策略</span>
          <div class="grid grid-cols-2 gap-2">
            <button type="button"
                    class="surface rounded p-3 text-left transition-shadow hover:shadow-soft"
                    :class="genOpts.strategy === 'by_count' ? '!border-accent' : ''"
                    @click="genOpts.strategy = 'by_count'">
              <div class="font-medium text-sm mb-0.5">按事件数</div>
              <div class="text-xs text-muted">每 N 个事件一章</div>
            </button>
            <button type="button"
                    class="surface rounded p-3 text-left transition-shadow hover:shadow-soft disabled:opacity-50 disabled:cursor-not-allowed"
                    :class="genOpts.strategy === 'manual' ? '!border-accent' : ''"
                    :disabled="chapters.length === 0"
                    @click="chapters.length > 0 && (genOpts.strategy = 'manual')">
              <div class="font-medium text-sm mb-0.5">按章节标记</div>
              <div class="text-xs text-muted">使用你已设置的 {{ chapters.length }} 个标记</div>
            </button>
          </div>
        </label>
        <label v-if="genOpts.strategy === 'by_count'" class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">每章事件数</span>
          <input v-model.number="genOpts.chapter_size" type="number" min="1" max="50" class="input w-32" />
        </label>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="genOpen = false">取消</button>
        <button class="btn btn-accent" @click="startGen">开始生成</button>
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
@keyframes flash-highlight-anim {
  0%   { background-color: rgb(232 153 104 / 0.28); }
  100% { background-color: transparent; }
}
.flash-highlight {
  animation: flash-highlight-anim 2s ease-out;
}
</style>
