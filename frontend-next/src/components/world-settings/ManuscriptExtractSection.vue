<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import {
  worldsApi, jobsApi,
  type WorldEntity, type ManuscriptState, type ManuscriptDraftEvent,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const props = defineProps<{
  worldId: string;
  entities: WorldEntity[];
}>();
const emit = defineEmits<{ (e: 'tick-changed', tick: number): void }>();

const toast = useToastStore();

const manuscript = ref<ManuscriptState | null>(null);
const loading = ref(false);
const error = ref<string>('');
const extractJobId = ref<string | null>(null);
const extractStatus = ref<string>('');
const extractRunning = ref(false);
const extractError = ref<string>('');
const extractRangeText = ref<string>('');
const extractFactCheck = ref<boolean>(false);
let pollTimer: number | null = null;

const reviewOpen = ref(false);
type DraftRow = ManuscriptDraftEvent & { _accept: boolean; _expand?: boolean; _showSource?: boolean };
const reviewDraft = ref<DraftRow[]>([]);
const committing = ref(false);
const discarding = ref(false);
const confirmDiscard = ref(false);

const castOptions = computed(() =>
  props.entities
    .filter(e => (e.type || 'character') !== 'location' && (e.type || 'character') !== 'faction')
    .map(e => ({ id: e.id, name: e.name }))
);
const locationOptions = computed(() =>
  props.entities.filter(e => e.type === 'location').map(e => ({ id: e.id, name: e.name }))
);
const castNameById = computed(() => {
  const m: Record<string, string> = {};
  for (const c of castOptions.value) m[c.id] = c.name;
  return m;
});
const acceptedCount = computed(() => reviewDraft.value.filter(e => e._accept).length);
const needsReviewCount = computed(() => reviewDraft.value.filter(e => e.needs_review).length);
const onlyNeedsReview = ref(false);
const eventsByChapter = computed(() => {
  const groups = new Map<number, DraftRow[]>();
  const filtered = onlyNeedsReview.value
    ? reviewDraft.value.filter(e => e.needs_review)
    : reviewDraft.value;
  for (const ev of filtered) {
    const arr = groups.get(ev.chapter_index) || [];
    arr.push(ev);
    groups.set(ev.chapter_index, arr);
  }
  return [...groups.entries()].sort((a, b) => a[0] - b[0]);
});

async function loadManuscript() {
  if (!props.worldId) return;
  loading.value = true;
  error.value = '';
  try {
    manuscript.value = await worldsApi.manuscriptState(props.worldId);
  } catch (e: any) {
    error.value = e.message || String(e);
    manuscript.value = { has_manuscript: false, chapter_count: 0, chapters: [], draft_event_count: 0, draft_events: [] };
  } finally {
    loading.value = false;
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollExtractJob() {
  if (!extractJobId.value) return;
  try {
    const job = await jobsApi.get(extractJobId.value);
    extractStatus.value = job.progress_message || (job.status === 'running' ? '运行中…' : job.status);
    if (job.status === 'completed') {
      stopPolling();
      extractRunning.value = false;
      extractJobId.value = null;
      extractStatus.value = '';
      const warns: string[] = job.result?.warnings || [];
      if (warns.length) toast.error(warns[0]);
      await loadManuscript();
      openReview();
    } else if (job.status === 'error' || job.status === 'cancelled') {
      stopPolling();
      extractRunning.value = false;
      extractJobId.value = null;
      extractError.value = job.error || (job.status === 'cancelled' ? '已取消' : '抽取失败');
      toast.error(extractError.value);
    }
  } catch (e: any) {
    stopPolling();
    extractRunning.value = false;
    extractJobId.value = null;
    extractError.value = e.message || String(e);
  }
}

async function startExtract() {
  if (!props.worldId || extractRunning.value) return;
  let chapterIndices: number[] | undefined;
  if (extractRangeText.value.trim()) {
    const total = manuscript.value?.chapter_count ?? 0;
    const parsed = parseChapterRange(extractRangeText.value, total);
    if (parsed === null) {
      toast.error('章节范围格式错误，请用 5-7、5,8,12 或 5-7,10');
      return;
    }
    if (parsed.length === 0) {
      toast.error('章节范围未选中任何章节');
      return;
    }
    chapterIndices = parsed;
  }
  extractError.value = '';
  extractStatus.value = '排队中…';
  extractRunning.value = true;
  try {
    const r = await worldsApi.extractManuscriptEvents(
      props.worldId, chapterIndices, extractFactCheck.value,
    );
    extractJobId.value = r.job_id;
    pollTimer = window.setInterval(pollExtractJob, 1500);
  } catch (e: any) {
    extractRunning.value = false;
    extractError.value = e.message || String(e);
    toast.error(`启动失败：${extractError.value}`);
  }
}

function parseChapterRange(text: string, max: number): number[] | null {
  const set = new Set<number>();
  for (const part of text.split(',').map(s => s.trim()).filter(Boolean)) {
    const m = part.match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) {
      const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
      if (!Number.isFinite(a) || !Number.isFinite(b) || a < 1 || b < a) return null;
      for (let i = a; i <= Math.min(b, max); i++) set.add(i);
    } else if (/^\d+$/.test(part)) {
      const n = parseInt(part, 10);
      if (n < 1 || n > max) return null;
      set.add(n);
    } else {
      return null;
    }
  }
  return [...set].sort((a, b) => a - b);
}

async function cancelExtract() {
  if (!extractJobId.value) return;
  try { await jobsApi.cancel(extractJobId.value); } catch { /* noop */ }
}

function openReview() {
  if (!manuscript.value || manuscript.value.draft_event_count === 0) {
    toast.error('暂无可审阅的草稿');
    return;
  }
  reviewDraft.value = manuscript.value.draft_events.map(e => ({ ...e, _accept: true, _expand: false }));
  reviewOpen.value = true;
}

function toggleParticipant(ev: ManuscriptDraftEvent, entityId: string) {
  const ids = ev.participant_ids;
  const i = ids.indexOf(entityId);
  if (i >= 0) ids.splice(i, 1);
  else ids.push(entityId);
}

function setEventLocation(ev: ManuscriptDraftEvent, entityId: string) {
  if (!entityId) {
    ev.location_id = null;
    ev.location_name = '';
  } else {
    ev.location_id = entityId;
    const found = locationOptions.value.find(l => l.id === entityId);
    ev.location_name = found?.name || '';
  }
}

async function commitDraft() {
  if (!props.worldId) return;
  const accepted = reviewDraft.value.filter(e => e._accept);
  if (accepted.length === 0) {
    toast.error('至少接受一个事件再提交');
    return;
  }
  committing.value = true;
  try {
    const r = await worldsApi.commitManuscriptEvents(
      props.worldId,
      accepted.map(({ _accept, _expand, ...rest }) => rest),
      true,
    );
    toast.success(`已落库 ${r.written} 个事件`);
    reviewOpen.value = false;
    await loadManuscript();
    emit('tick-changed', r.current_tick);
  } catch (e: any) {
    toast.error(`提交失败：${e.message || e}`);
  } finally {
    committing.value = false;
  }
}

async function discardDraft() {
  if (!props.worldId) return;
  discarding.value = true;
  try {
    await worldsApi.discardManuscriptDraft(props.worldId);
    toast.success('草稿已丢弃');
    confirmDiscard.value = false;
    await loadManuscript();
  } catch (e: any) {
    toast.error(`丢弃失败：${e.message || e}`);
  } finally {
    discarding.value = false;
  }
}

onMounted(loadManuscript);
watch(() => props.worldId, loadManuscript);
onUnmounted(stopPolling);
</script>

<template>
  <section id="section-manuscript" class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">手稿事件抽取</h2>
      <span class="text-xs text-muted">从导入的小说原稿里抽事件，审阅后写入时间轴</span>
    </header>

    <div v-if="loading" class="surface rounded p-5 text-sm text-muted">加载手稿状态…</div>

    <div v-else-if="error" class="surface rounded p-5 border-l-2 !border-l-[#b04f33]">
      <p class="text-[#b04f33] text-sm mb-2">加载手稿状态失败</p>
      <p class="text-xs text-muted font-mono">{{ error }}</p>
      <button class="btn btn-ghost text-xs mt-3" @click="loadManuscript">重试</button>
    </div>

    <div v-else-if="!manuscript?.has_manuscript" class="surface rounded p-5 text-sm">
      <p class="mb-1.5">此世界未关联手稿。</p>
      <p class="text-muted text-xs leading-relaxed">
        想用「先抽骨架 → 再抽事件 → 审阅落库」的导入流程，请到
        <router-link to="/worlds" class="text-accent hover:underline">世界库</router-link>
        点 <span class="font-mono">📖 从手稿建</span> 创建一个新世界。
        手动新建的世界目前不能后置粘入手稿。
      </p>
    </div>

    <div v-else class="surface rounded p-5 space-y-4">
      <div class="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-sm">
        <span><span class="text-muted">章节</span> <strong>{{ manuscript.chapter_count }}</strong></span>
        <span><span class="text-muted">待审草稿</span> <strong>{{ manuscript.draft_event_count }}</strong></span>
        <span class="text-xs text-muted">事件不会自动落库，必须经过你手动确认</span>
      </div>

      <div v-if="extractRunning" class="text-sm">
        <p class="font-mono text-xs text-muted mb-1">{{ extractStatus || '抽取中…' }}</p>
        <div class="h-1 bg-muted/20 rounded overflow-hidden">
          <div class="h-1 bg-accent animate-pulse w-1/3"></div>
        </div>
        <button class="btn btn-ghost text-xs mt-2" @click="cancelExtract">取消</button>
      </div>

      <div v-else class="flex flex-wrap items-center gap-2">
        <input v-model="extractRangeText"
               type="text"
               class="input !h-8 text-xs font-mono w-44"
               :placeholder="`章节范围（默认全部 1-${manuscript.chapter_count}）`" />
        <label class="flex items-center gap-1 text-xs cursor-pointer select-none"
               title="抽完后再让 LLM 对照原文复核每个事件，可疑的标 needs_review 给你审阅时一眼看到。耗时翻倍">
          <input type="checkbox" v-model="extractFactCheck" />
          <span>fact-check</span>
        </label>
        <button class="btn btn-accent" @click="startExtract">
          {{ extractRangeText.trim() ? '抽这些章' : (manuscript.draft_event_count > 0 ? '重抽全部' : '抽取事件') }}
        </button>
        <button v-if="manuscript.draft_event_count > 0"
                class="btn btn-ghost" @click="openReview">
          审阅草稿（{{ manuscript.draft_event_count }}）
        </button>
        <button v-if="manuscript.draft_event_count > 0"
                class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                @click="confirmDiscard = true">丢弃草稿</button>
        <span v-if="extractError" class="text-xs text-[#b04f33]">{{ extractError }}</span>
      </div>
      <p class="text-xs text-muted -mt-1">
        范围语法：<span class="font-mono">5-7</span>、<span class="font-mono">5,8,12</span>、<span class="font-mono">5-7,10</span>。指定范围会替换该范围已有草稿，其它章节草稿保留。
      </p>

      <details class="text-xs text-muted">
        <summary class="cursor-pointer hover:text-text">查看章节列表（{{ manuscript.chapter_count }}）</summary>
        <ul class="mt-2 space-y-0.5 max-h-48 overflow-y-auto pr-2">
          <li v-for="c in manuscript.chapters" :key="c.index" class="font-mono">
            {{ String(c.index).padStart(3, '0') }}. {{ c.title || '（无标题）' }}
            <span class="text-muted/60">· {{ c.char_count }} 字</span>
          </li>
        </ul>
      </details>
    </div>

    <Dialog :open="reviewOpen" title="审阅事件草稿" width="900px"
            @close="!committing && (reviewOpen = false)">
      <div class="space-y-4">
        <div class="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
          <span class="text-muted">共 <strong class="text-text">{{ reviewDraft.length }}</strong> 个事件</span>
          <span class="text-muted">已勾选 <strong class="text-text">{{ acceptedCount }}</strong> 个</span>
          <span v-if="needsReviewCount > 0" class="text-amber-600">
            ⚠ <strong>{{ needsReviewCount }}</strong> 个事件 fact-check 失败
          </span>
          <button class="btn btn-ghost text-xs"
                  @click="reviewDraft.forEach(e => e._accept = true)">全选</button>
          <button class="btn btn-ghost text-xs"
                  @click="reviewDraft.forEach(e => e._accept = false)">全不选</button>
          <label v-if="needsReviewCount > 0" class="flex items-center gap-1 text-xs cursor-pointer select-none">
            <input type="checkbox" v-model="onlyNeedsReview" />
            <span>仅看 fact-check 失败的</span>
          </label>
          <span class="text-xs text-muted">名字解析失败的角色会用红字标出，落库时会被忽略，可以先去角色页补全再来抽。</span>
        </div>

        <div class="max-h-[60vh] overflow-y-auto pr-2 space-y-5">
          <div v-for="[chIdx, evs] in eventsByChapter" :key="chIdx">
            <h3 class="font-serif text-sm text-muted mb-2 sticky top-0 bg-bg/95 backdrop-blur py-1">
              第 {{ chIdx }} 章 · {{ evs[0]?.chapter_title || '' }}
            </h3>
            <ul class="space-y-2">
              <li v-for="ev in evs" :key="`${ev.chapter_index}-${ev.tick}`"
                  class="surface rounded p-3 flex gap-3"
                  :class="{
                    'opacity-50': !ev._accept,
                    'border-l-4 border-amber-500': ev.needs_review,
                  }">
                <input type="checkbox" v-model="ev._accept"
                       class="mt-1.5 w-4 h-4 cursor-pointer shrink-0" />
                <div class="flex-1 min-w-0 space-y-1.5">
                  <div v-if="ev.needs_review" class="text-xs text-amber-600 flex items-start gap-1">
                    <span class="font-bold">⚠ fact-check：</span>
                    <span>{{ ev.review_reason || '与原文对不上，请人工复核' }}</span>
                  </div>
                  <input v-model="ev.title" :disabled="!ev._accept"
                         class="input !h-8 text-sm font-serif" placeholder="事件标题" />
                  <textarea v-model="ev.description" :disabled="!ev._accept" rows="2"
                            class="input !h-auto py-1.5 text-sm leading-relaxed"
                            placeholder="描述" />

                  <div class="text-xs flex flex-wrap gap-1.5 items-center">
                    <span class="text-muted">角色</span>
                    <span v-for="pid in ev.participant_ids" :key="pid"
                          class="px-1.5 py-0.5 rounded bg-accent/10 text-accent text-xs">
                      {{ castNameById[pid] || pid }}
                    </span>
                    <button type="button"
                            class="text-xs px-1 text-muted hover:text-accent"
                            :disabled="!ev._accept"
                            @click="ev._expand = !ev._expand">
                      {{ ev._expand ? '收起' : '+ 改' }}
                    </button>
                    <span v-if="ev.unresolved_names.length"
                          class="text-[#b04f33]"
                          :title="ev.unresolved_names.join('、')">
                      未匹配 {{ ev.unresolved_names.length }} 个名字（点 + 选择已有角色，或先去角色页补全）
                    </span>
                  </div>

                  <div v-if="ev._expand && ev._accept"
                       class="surface-subtle rounded p-2 flex flex-wrap gap-1.5">
                    <span v-if="castOptions.length === 0" class="text-xs text-muted italic">
                      该世界还没有角色实体
                    </span>
                    <button v-for="opt in castOptions" :key="opt.id"
                            type="button"
                            class="text-xs px-1.5 py-0.5 rounded transition-colors"
                            :class="ev.participant_ids.includes(opt.id)
                              ? 'bg-accent text-white'
                              : 'bg-bg hover:bg-surface text-muted hover:text-text'"
                            @click="toggleParticipant(ev, opt.id)">
                      {{ opt.name }}
                    </button>
                  </div>

                  <div class="text-xs flex flex-wrap gap-2 items-center">
                    <span class="text-muted">tick {{ ev.tick }}</span>
                    <span class="text-muted">·</span>
                    <span class="text-muted">地点</span>
                    <select :value="ev.location_id || ''"
                            :disabled="!ev._accept"
                            class="input !h-7 text-xs !py-0 max-w-[180px]"
                            @change="setEventLocation(ev, ($event.target as HTMLSelectElement).value)">
                      <option value="">（无）</option>
                      <option v-for="opt in locationOptions" :key="opt.id" :value="opt.id">
                        {{ opt.name }}
                      </option>
                    </select>
                    <span v-if="ev.location_name && !ev.location_id" class="text-[#b04f33] text-xs"
                          :title="`原稿地点 ${ev.location_name} 没有对应实体`">
                      原稿: {{ ev.location_name }}（未匹配）
                    </span>
                    <button v-if="ev.source_context"
                            type="button"
                            class="text-xs text-muted hover:text-accent ml-auto"
                            @click="ev._showSource = !ev._showSource">
                      {{ ev._showSource ? '收起原文' : '🔍 原文' }}
                    </button>
                  </div>
                  <div v-if="ev._showSource && ev.source_context"
                       class="text-xs text-muted italic mt-1 p-2 bg-sunken/50 rounded leading-relaxed">
                    {{ ev.source_context }}
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" :disabled="committing" @click="reviewOpen = false">关闭</button>
        <button class="btn btn-accent" :disabled="committing || acceptedCount === 0" @click="commitDraft">
          <span v-if="committing">写入中…</span>
          <span v-else>落库 {{ acceptedCount }} 个事件</span>
        </button>
      </template>
    </Dialog>

    <ConfirmDialog
      :open="confirmDiscard"
      :busy="discarding"
      title="丢弃事件草稿？"
      :message="`将丢弃 ${manuscript?.draft_event_count || 0} 个未审阅的事件草稿，原稿和章节切分会保留。`"
      confirm-text="丢弃"
      danger
      @cancel="!discarding && (confirmDiscard = false)"
      @confirm="discardDraft" />
  </section>
</template>
