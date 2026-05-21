<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  worldsApi, simApi, issuesApi,
  type WorldDetail, type WorldEntity, type WorldEvent,
  type DirectiveSuggestion, type StepResult, type JobToolCall,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import { useJob } from '@/composables/useJob';

const route = useRoute();
const router = useRouter();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const entities = ref<WorldEntity[]>([]);
const recentEvents = ref<WorldEvent[]>([]);
const loading = ref(true);
const loadErr = ref('');

const characters = computed(() => entities.value.filter(e => (e.type || 'character') === 'character'));
const reachedMax = computed(() => {
  const w = world.value;
  if (!w?.max_tick) return false;
  return (w.current_tick ?? 0) >= w.max_tick;
});

async function loadWorld() {
  loading.value = true;
  loadErr.value = '';
  try {
    const snap = await worldsApi.get(worldId.value);
    world.value = snap.world;
    entities.value = snap.entities || [];
    recentEvents.value = snap.recent_events || [];
  } catch (e: any) {
    loadErr.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(loadWorld);
watch(worldId, () => { resetRunState(); loadWorld(); });

// ---------- 用户输入 ----------
const directive = ref('');
const stepCount = ref(1);
const selectedCharIds = ref<Set<string>>(new Set());

function toggleChar(id: string) {
  const next = new Set(selectedCharIds.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedCharIds.value = next;
}
function clearChars() { selectedCharIds.value = new Set(); }

// ---------- 推断方向 ----------
const suggestions = ref<DirectiveSuggestion[]>([]);
const suggesting = ref(false);
async function fetchSuggestions() {
  suggesting.value = true;
  try {
    const r = await simApi.suggestDirectives(worldId.value, { n: 4 });
    suggestions.value = r.suggestions || [];
    if (suggestions.value.length === 0) toast.info('AI 这次没给出建议');
  } catch (e: any) {
    toast.error(`建议失败：${e.message || e}`);
  } finally {
    suggesting.value = false;
  }
}
function applySuggestion(s: DirectiveSuggestion) {
  directive.value = s.directive;
  textareaEl.value?.focus();
}
const textareaEl = ref<HTMLTextAreaElement | null>(null);

const KIND_LABEL: Record<string, { text: string; cls: string }> = {
  continue: { text: '顺势', cls: 'bg-[#8b7565]/15 text-[#8b7565]' },
  twist:    { text: '反转', cls: 'bg-[#bb9856]/15 text-[#bb9856]' },
  tragic:   { text: '悲剧', cls: 'bg-[#b04f33]/15 text-[#b04f33]' },
  tender:   { text: '温情', cls: 'bg-[#6a8e6f]/15 text-[#6a8e6f]' },
  reveal:   { text: '揭秘', cls: 'bg-[#4a6e8c]/15 text-[#4a6e8c]' },
  conflict: { text: '冲突', cls: 'bg-[#7e6090]/15 text-[#7e6090]' },
};
function kindMeta(k: string) {
  return KIND_LABEL[k] || { text: k, cls: 'bg-sunken text-muted' };
}

// ---------- 运行 ----------
type RunMode = 'single' | 'auto' | 'multi';
const running = ref(false);
const currentMode = ref<RunMode | null>(null);
const phaseMessage = ref('');
const liveToolCalls = ref<JobToolCall[]>([]);
const liveNarration = ref('');
const lastResult = ref<StepResult | null>(null);
const newEvents = ref<WorldEvent[]>([]);
const runStartedTick = ref(0);
const runError = ref('');
const openIssues = ref(0);

async function checkConsistency() {
  try {
    const r = await issuesApi.list(worldId.value, 'open');
    openIssues.value = r.counts?.open || 0;
    if (openIssues.value > 0) {
      toast.info(`${openIssues.value} 个一致性问题待处理`);
    }
  } catch { /* noop */ }
}

function resetRunState() {
  liveToolCalls.value = [];
  liveNarration.value = '';
  lastResult.value = null;
  newEvents.value = [];
  phaseMessage.value = '';
  runError.value = '';
  currentMode.value = null;
}

const stream = useJob({
  intervalMs: 700,
  onProgress: j => {
    phaseMessage.value = j.progress_message || '';
    if (j.tool_calls) liveToolCalls.value = j.tool_calls;
    if (j.narration) liveNarration.value = j.narration;
    autoScrollStream();
  },
});
const streamEl = ref<HTMLDivElement | null>(null);
function autoScrollStream() {
  nextTick(() => {
    const el = streamEl.value;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  });
}

async function refreshAfterRun(captured?: StepResult) {
  await loadWorld();
  // 用本次开始时的 tick 作为门槛找出新生事件
  newEvents.value = recentEvents.value
    .filter(e => e.tick >= runStartedTick.value)
    .sort((a, b) => a.tick - b.tick);
  // 若后端的 step 返回里直接带 events，优先用它
  if (captured?.events?.length) {
    const merged: WorldEvent[] = [];
    const seen = new Set<string>();
    for (const ev of captured.events as WorldEvent[]) {
      if (ev.id && !seen.has(ev.id)) { merged.push(ev); seen.add(ev.id); }
    }
    for (const ev of newEvents.value) {
      if (ev.id && !seen.has(ev.id)) { merged.push(ev); seen.add(ev.id); }
    }
    newEvents.value = merged.sort((a, b) => a.tick - b.tick);
  }
}

async function runSingle() {
  if (running.value) return;
  resetRunState();
  running.value = true;
  currentMode.value = 'single';
  runStartedTick.value = world.value?.current_tick ?? 0;
  phaseMessage.value = '推演中…';
  try {
    const r = await simApi.step(worldId.value, {
      steps: 1,
      directive: directive.value.trim() || undefined,
    });
    lastResult.value = r;
    if (r.narration) liveNarration.value = r.narration;
    await refreshAfterRun(r);
    autoScrollStream();
    checkConsistency();
    toast.success(`完成 1 步，当前 tick = ${world.value?.current_tick ?? '?'}`);
  } catch (e: any) {
    runError.value = e.message || String(e);
    toast.error(`推演失败：${runError.value}`);
  } finally {
    running.value = false;
  }
}

async function runAuto() {
  if (running.value) return;
  const steps = Math.max(1, Math.min(20, stepCount.value | 0));
  resetRunState();
  running.value = true;
  currentMode.value = 'auto';
  runStartedTick.value = world.value?.current_tick ?? 0;
  phaseMessage.value = '排队中…';
  try {
    const { job_id } = await simApi.stepAsync(worldId.value, {
      steps,
      directive: directive.value.trim() || undefined,
    });
    const finalJob = await stream.poll(job_id);
    lastResult.value = (finalJob.result as StepResult) || null;
    if (finalJob.narration) liveNarration.value = finalJob.narration;
    await refreshAfterRun(lastResult.value || undefined);
    checkConsistency();
    toast.success(`已完成 ${steps} 步`);
  } catch (e: any) {
    runError.value = e.message || String(e);
    if (String(runError.value).includes('cancelled')) {
      toast.info('已取消');
      await refreshAfterRun();
    } else {
      toast.error(`推演失败：${runError.value}`);
    }
  } finally {
    running.value = false;
    stream.reset();
  }
}

async function runMultiAgent() {
  if (running.value) return;
  resetRunState();
  running.value = true;
  currentMode.value = 'multi';
  runStartedTick.value = world.value?.current_tick ?? 0;
  phaseMessage.value = '多角色推演中…';
  try {
    const r = await simApi.stepMultiAgent(worldId.value, {
      character_ids: selectedCharIds.value.size ? [...selectedCharIds.value] : null,
      directive: directive.value.trim() || undefined,
    });
    lastResult.value = r;
    if (r.narration) liveNarration.value = r.narration;
    await refreshAfterRun(r);
    toast.success('多角色推演完成');
  } catch (e: any) {
    runError.value = e.message || String(e);
    toast.error(`多角色推演失败：${runError.value}`);
  } finally {
    running.value = false;
  }
}

async function cancelRun() {
  if (currentMode.value === 'auto') {
    await stream.cancel();
    phaseMessage.value = '取消中…';
  }
}

onBeforeUnmount(() => { stream.reset(); });

const canRun = computed(() => !loading.value && !running.value && !reachedMax.value);

function gotoEventInTimeline(id: string) {
  router.push(`/worlds/${worldId.value}/timeline?event=${id}`);
}
function gotoEventInChapters(id: string) {
  router.push(`/worlds/${worldId.value}/chapters?event=${id}`);
}

// 简单的 JSON 概要：参数 → 一行字
function toolArgPreview(c: JobToolCall): string {
  const a = c.arguments || {};
  const keys = Object.keys(a).slice(0, 3);
  if (keys.length === 0) return '';
  const parts: string[] = [];
  for (const k of keys) {
    const v = (a as any)[k];
    let s = '';
    if (v == null) s = 'null';
    else if (typeof v === 'string') s = v.length > 24 ? v.slice(0, 24) + '…' : v;
    else if (typeof v === 'object') s = Array.isArray(v) ? `[${v.length}]` : '{…}';
    else s = String(v);
    parts.push(`${k}=${s}`);
  }
  return parts.join('  ·  ');
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 顶栏：当前 tick / 上限 / 分支 / 取消 -->
    <header class="h-12 px-4 border-b border-border flex items-center gap-3 shrink-0">
      <span class="text-muted text-xs uppercase tracking-wider">推演</span>
      <span class="text-sm font-mono">
        tick <span class="text-text">{{ world?.current_tick ?? 0 }}</span>
        <span v-if="world?.max_tick" class="text-muted"> / {{ world.max_tick }}</span>
      </span>
      <span v-if="reachedMax" class="text-xs px-1.5 py-0.5 rounded bg-[#b04f33]/15 text-[#b04f33]">
        已达上限
      </span>
      <span v-if="world?.branch_id" class="text-xs text-muted font-mono truncate max-w-[180px]"
            :title="world.branch_id">
        @{{ world.branch_id.slice(0, 10) }}…
      </span>

      <div class="flex-1" />

      <router-link v-if="openIssues > 0" :to="`/worlds/${worldId}/review`"
                   class="text-xs px-2 py-0.5 rounded bg-[#bb9856]/15 text-[#bb9856] hover:underline">
        ⚠ {{ openIssues }} 个问题待处理
      </router-link>

      <span v-if="running" class="text-xs text-muted inline-flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
        {{ phaseMessage || '推演中…' }}
      </span>
      <button v-if="running && currentMode === 'auto'"
              class="btn btn-ghost text-xs"
              @click="cancelRun">取消</button>
    </header>

    <div v-if="loadErr" class="p-6 text-muted text-sm">{{ loadErr }}</div>

    <div v-else class="flex flex-1 min-h-0">
      <!-- 左：操作面板 -->
      <aside class="w-[380px] shrink-0 border-r border-border bg-sunken/40 overflow-y-auto">
        <div class="p-5 space-y-5">
          <!-- 指令输入 -->
          <section>
            <div class="flex items-center justify-between mb-2">
              <p class="text-muted text-xs uppercase tracking-wider">下一步指令</p>
              <button class="btn btn-ghost text-xs !h-6 !px-2"
                      :disabled="suggesting || running"
                      @click="fetchSuggestions">
                {{ suggesting ? '想…' : '✨ 想几个' }}
              </button>
            </div>
            <textarea ref="textareaEl" v-model="directive"
                      class="input !h-auto py-2"
                      rows="3"
                      placeholder="可选：让张三在酒馆撞见李四的妻子…&#10;留空则让 AI 自由发挥" />
            <p class="text-xs text-muted mt-1.5 leading-relaxed">
              指令越具体，结果越可控。每步会先存一个快照，可在「世界设置 / 分支」回滚。
            </p>
          </section>

          <!-- AI 建议卡片 -->
          <section v-if="suggestions.length > 0">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">AI 建议</p>
            <ul class="space-y-2">
              <li v-for="(s, i) in suggestions" :key="i">
                <button class="w-full text-left surface rounded p-3 hover:shadow-soft transition-shadow"
                        @click="applySuggestion(s)">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-[10px] px-1.5 py-0.5 rounded font-medium" :class="kindMeta(s.kind).cls">
                      {{ kindMeta(s.kind).text }}
                    </span>
                    <span v-if="s.rationale" class="text-xs text-muted truncate flex-1">{{ s.rationale }}</span>
                  </div>
                  <p class="text-sm leading-snug line-clamp-3">{{ s.directive }}</p>
                </button>
              </li>
            </ul>
          </section>

          <!-- 角色选择（多角色模式用） -->
          <section v-if="characters.length > 0">
            <div class="flex items-center justify-between mb-2">
              <p class="text-muted text-xs uppercase tracking-wider">焦点角色（多角色模式）</p>
              <button v-if="selectedCharIds.size > 0"
                      class="btn btn-ghost text-xs !h-6 !px-2"
                      @click="clearChars">清空</button>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button v-for="c in characters" :key="c.id"
                      class="px-2.5 h-7 rounded-full text-xs border transition-colors"
                      :class="selectedCharIds.has(c.id)
                        ? 'bg-accent text-white border-accent'
                        : 'border-border text-muted hover:bg-surface'"
                      @click="toggleChar(c.id)">
                {{ c.name }}
              </button>
            </div>
            <p class="text-xs text-muted mt-1.5">未选则由 AI 挑选最相关的几个出场。</p>
          </section>

          <!-- 操作按钮 -->
          <section class="space-y-2 pt-2 border-t border-border">
            <button class="btn btn-accent w-full justify-center"
                    :disabled="!canRun"
                    @click="runSingle">
              <span v-if="running && currentMode === 'single'">推演中…</span>
              <span v-else>↻ 推演 1 步</span>
            </button>

            <div class="flex gap-2">
              <input v-model.number="stepCount" type="number" min="1" max="20"
                     class="input !w-20 text-center"
                     :disabled="!canRun" />
              <button class="btn flex-1 justify-center border border-border"
                      :disabled="!canRun"
                      @click="runAuto">
                <span v-if="running && currentMode === 'auto'">推演 {{ stepCount }} 步…</span>
                <span v-else>⏵ 自动 {{ stepCount }} 步</span>
              </button>
            </div>

            <button class="btn w-full justify-center border border-border"
                    :disabled="!canRun || characters.length === 0"
                    @click="runMultiAgent">
              <span v-if="running && currentMode === 'multi'">多角色推演中…</span>
              <span v-else>
                ☻ 多角色推演
                <span v-if="selectedCharIds.size > 0" class="text-muted">（{{ selectedCharIds.size }}）</span>
              </span>
            </button>
          </section>

          <p v-if="reachedMax" class="text-xs text-muted text-center">
            已达推演上限。可在「世界设置」里调整 max_tick。
          </p>
        </div>
      </aside>

      <!-- 中：实时流 + 结果 -->
      <main ref="streamEl" class="flex-1 min-w-0 overflow-y-auto px-8 py-8">
        <!-- 空态 / 引导 -->
        <div v-if="!running && !lastResult && !runError && newEvents.length === 0"
             class="max-w-2xl mx-auto pt-20 text-center">
          <template v-if="(world?.current_tick ?? 0) === 0">
            <p class="font-serif text-2xl mb-3">这个世界还没有事件</p>
            <p class="text-muted leading-relaxed mb-4">
              如果你从手稿导入，先去
              <router-link :to="`/worlds/${worldId}/settings`" class="text-accent underline">世界设置</router-link>
              抽取事件草稿并审阅落库，然后再来推演。
            </p>
          </template>
          <template v-else>
            <p class="font-serif text-2xl mb-3">让故事往前走一点</p>
            <p class="text-muted leading-relaxed mb-6">
              输入一个具体指令，或者直接点「推演 1 步」让 AI 自由接龙。<br />
              想要更多角色视角时用「多角色推演」。
            </p>
            <div class="text-xs text-muted space-y-1.5">
              <div><span class="font-mono text-text">↻ 1 步</span> — 同步执行，秒回</div>
              <div><span class="font-mono text-text">⏵ 自动 N 步</span> — 后台跑，可取消</div>
              <div><span class="font-mono text-text">☻ 多角色</span> — 每个焦点角色出意图，再合并</div>
            </div>
          </template>
        </div>
        <div v-else-if="!running && !lastResult && !runError"
             class="max-w-2xl mx-auto pt-20 text-center">
          <p class="font-serif text-2xl mb-3">让故事往前走一点</p>
          <p class="text-muted leading-relaxed mb-6">
            输入一个具体指令，或者直接点「推演 1 步」让 AI 自由接龙。<br />
            想要更多角色视角时用「多角色推演」。
          </p>
          <div class="text-xs text-muted space-y-1.5">
            <div><span class="font-mono text-text">↻ 1 步</span> — 同步执行，秒回</div>
            <div><span class="font-mono text-text">⏵ 自动 N 步</span> — 后台跑，可取消</div>
            <div><span class="font-mono text-text">☻ 多角色</span> — 每个焦点角色出意图，再合并</div>
          </div>
        </div>

        <!-- 实时阶段 + 工具调用流 -->
        <section v-if="running || liveToolCalls.length > 0 || liveNarration" class="mb-10">
          <div v-if="running" class="surface rounded p-4 mb-4 flex items-center gap-3">
            <span class="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span class="text-sm">{{ phaseMessage || '推演中…' }}</span>
            <span v-if="currentMode === 'auto'" class="text-xs text-muted ml-auto">
              已用 {{ liveToolCalls.length }} 个工具
            </span>
          </div>

          <div v-if="liveToolCalls.length > 0" class="mb-6">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">AI 工具调用</p>
            <ol class="space-y-1.5">
              <li v-for="(c, i) in liveToolCalls" :key="i"
                  class="surface rounded px-3 py-2 flex items-baseline gap-3 text-sm">
                <span class="font-mono text-xs text-muted w-6 shrink-0">#{{ i + 1 }}</span>
                <span class="font-mono text-accent shrink-0">{{ c.name }}</span>
                <span class="text-xs text-muted truncate flex-1">{{ toolArgPreview(c) }}</span>
              </li>
            </ol>
          </div>

          <div v-if="liveNarration" class="mb-6">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">叙述</p>
            <div class="surface rounded p-5 font-serif leading-relaxed whitespace-pre-wrap">{{ liveNarration }}</div>
          </div>
        </section>

        <!-- 错误 -->
        <section v-if="runError && !running" class="mb-10">
          <div class="surface rounded p-4 border-l-2 border-[#b04f33]">
            <p class="text-xs uppercase tracking-wider text-[#b04f33] mb-1">推演失败</p>
            <p class="text-sm text-muted">{{ runError }}</p>
          </div>
        </section>

        <!-- 新事件 -->
        <section v-if="newEvents.length > 0 && !running">
          <header class="flex items-baseline justify-between mb-3">
            <h2 class="text-muted text-xs uppercase tracking-wider">本次新增（{{ newEvents.length }}）</h2>
            <span class="text-xs text-muted">tick {{ runStartedTick }} → {{ world?.current_tick }}</span>
          </header>
          <ol class="space-y-2">
            <li v-for="ev in newEvents" :key="ev.id"
                class="surface rounded p-4 flex gap-4 group">
              <div class="font-mono text-xs text-muted w-12 pt-0.5 shrink-0">t{{ ev.tick }}</div>
              <div class="flex-1 min-w-0">
                <div class="font-serif text-lg leading-snug">{{ ev.title || '（未命名事件）' }}</div>
                <div v-if="ev.description"
                     class="text-sm text-muted mt-1 leading-relaxed line-clamp-3">{{ ev.description }}</div>
                <div class="mt-2 flex items-center gap-3 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button class="text-xs text-muted hover:text-accent" @click="gotoEventInTimeline(ev.id)">
                    在时间轴查看 →
                  </button>
                  <button class="text-xs text-muted hover:text-accent" @click="gotoEventInChapters(ev.id)">
                    在章节里查看 →
                  </button>
                </div>
              </div>
            </li>
          </ol>
        </section>
      </main>
    </div>
  </div>
</template>
