<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  worldsApi, issuesApi,
  type WorldDetail, type WorldEntity,
  type ConsistencyIssue, type ScanRun, type IssuePatch,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const route = useRoute();
const router = useRouter();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const entityById = ref<Record<string, WorldEntity>>({});
const issues = ref<ConsistencyIssue[]>([]);
const scans = ref<ScanRun[]>([]);
const counts = ref({ open: 0, ignored: 0, resolved: 0 });
const loading = ref(true);
const err = ref('');

const statusFilter = ref<'open' | 'all' | 'resolved' | 'ignored'>('open');
const severityFilter = ref<'all' | 'high' | 'medium' | 'low'>('all');
const selectedId = ref<string | null>(null);

const SEV_META: Record<string, { label: string; cls: string; rank: number }> = {
  high:   { label: '严重', cls: 'bg-[#b04f33]/15 text-[#b04f33] border-[#b04f33]/30', rank: 0 },
  medium: { label: '中等', cls: 'bg-[#bb9856]/15 text-[#bb9856] border-[#bb9856]/30', rank: 1 },
  low:    { label: '轻微', cls: 'bg-[#6a8e6f]/15 text-[#6a8e6f] border-[#6a8e6f]/30', rank: 2 },
};
function sevMeta(s: string) { return SEV_META[s] || { label: s, cls: 'bg-sunken text-muted', rank: 9 }; }

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [snap, listResp] = await Promise.all([
      worldsApi.get(worldId.value),
      issuesApi.list(worldId.value, statusFilter.value === 'all' ? undefined : statusFilter.value),
    ]);
    world.value = snap.world;
    entityById.value = Object.fromEntries((snap.entities || []).map(e => [e.id, e as WorldEntity]));
    issues.value = listResp.issues || [];
    scans.value = listResp.scans || [];
    counts.value = listResp.counts || { open: 0, ignored: 0, resolved: 0 };
    if (selectedId.value && !issues.value.find(i => i.id === selectedId.value)) {
      selectedId.value = issues.value[0]?.id || null;
    } else if (!selectedId.value && issues.value.length > 0) {
      selectedId.value = issues.value[0].id;
    }
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, () => { selectedId.value = null; load(); });
watch(statusFilter, load);

const visibleIssues = computed(() => {
  let arr = issues.value;
  if (severityFilter.value !== 'all') {
    arr = arr.filter(i => i.severity === severityFilter.value);
  }
  return [...arr].sort((a, b) => {
    const r = sevMeta(a.severity).rank - sevMeta(b.severity).rank;
    if (r !== 0) return r;
    return (b.created_at || '').localeCompare(a.created_at || '');
  });
});

const selected = computed(() => issues.value.find(i => i.id === selectedId.value) || null);

// ---------- 扫描 ----------
const scanning = ref(false);
const scanScope = ref<'recent' | 'all'>('recent');
async function runScan() {
  scanning.value = true;
  try {
    const r = await issuesApi.scan(worldId.value, { scope: scanScope.value });
    toast.success(`扫描完成，发现 ${r.scan.issue_count} 条 issue`);
    statusFilter.value = 'open';
    await load();
    if (r.issues?.[0]) selectedId.value = r.issues[0].id;
  } catch (e: any) {
    toast.error(`扫描失败：${e.message || e}`);
  } finally {
    scanning.value = false;
  }
}

// ---------- patches ----------
const patches = ref<IssuePatch[]>([]);
const loadingPatches = ref(false);
const suggesting = ref(false);

async function loadPatches() {
  if (!selected.value) { patches.value = []; return; }
  loadingPatches.value = true;
  try {
    const r = await issuesApi.listPatches(selected.value.id);
    patches.value = r.patches || [];
  } catch (e: any) {
    patches.value = [];
  } finally {
    loadingPatches.value = false;
  }
}
watch(selected, loadPatches, { immediate: true });

async function suggestPatches() {
  if (!selected.value) return;
  suggesting.value = true;
  try {
    const r = await issuesApi.suggestPatches(selected.value.id, { max_patches: 3 });
    toast.success(`新增 ${r.created} 条补丁`);
    await loadPatches();
  } catch (e: any) {
    toast.error(`生成补丁失败：${e.message || e}`);
  } finally {
    suggesting.value = false;
  }
}

const applyingId = ref<string | null>(null);
async function applyPatch(p: IssuePatch) {
  applyingId.value = p.id;
  try {
    await issuesApi.applyPatch(p.id);
    toast.success('已应用');
    await Promise.all([loadPatches(), load()]);
  } catch (e: any) {
    toast.error(`应用失败：${e.message || e}`);
  } finally {
    applyingId.value = null;
  }
}
async function rejectPatch(p: IssuePatch) {
  try {
    await issuesApi.rejectPatch(p.id);
    toast.success('已忽略');
    await loadPatches();
  } catch (e: any) {
    toast.error(`操作失败：${e.message || e}`);
  }
}
async function undoPatch(p: IssuePatch) {
  try {
    await issuesApi.undoPatch(p.id);
    toast.success('已撤销');
    await Promise.all([loadPatches(), load()]);
  } catch (e: any) {
    toast.error(`撤销失败：${e.message || e}`);
  }
}

// ---------- issue 状态 ----------
async function setIssueStatus(i: ConsistencyIssue, s: 'open' | 'ignored' | 'resolved') {
  try {
    await issuesApi.setStatus(i.id, s);
    toast.success({ open: '已重新打开', ignored: '已忽略', resolved: '已标记解决' }[s]);
    await load();
  } catch (e: any) {
    toast.error(`操作失败：${e.message || e}`);
  }
}
const confirmDelete = ref<ConsistencyIssue | null>(null);
async function doDelete() {
  const i = confirmDelete.value;
  if (!i) return;
  try {
    await issuesApi.remove(i.id);
    toast.success('已删除');
    confirmDelete.value = null;
    selectedId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  }
}

function entityName(id: string): string {
  return entityById.value[id]?.name || id.slice(0, 10);
}
function gotoTimeline(tick: number | null) {
  if (tick == null) return;
  router.push(`/worlds/${worldId.value}/timeline?tick=${tick}`);
}
function fmtTime(s?: string | null): string {
  if (!s) return '';
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }); }
  catch { return s; }
}
</script>

<template>
  <div class="flex h-full">
    <!-- 左：issue 列表 -->
    <aside class="w-[360px] shrink-0 border-r border-border bg-sunken/40 flex flex-col">
      <header class="h-12 px-4 border-b border-border flex items-center gap-2 shrink-0">
        <span class="text-muted text-xs uppercase tracking-wider">审阅</span>
        <span class="text-xs text-muted">·</span>
        <span class="text-xs text-muted font-mono">{{ counts.open }} 待处理</span>
      </header>

      <!-- 扫描栏 -->
      <div class="px-3 py-3 border-b border-border space-y-2">
        <div class="flex items-center gap-2">
          <select v-model="scanScope" class="input !h-8 !w-auto text-sm flex-1" :disabled="scanning">
            <option value="recent">仅最近 30 步</option>
            <option value="all">全量扫描</option>
          </select>
          <button class="btn btn-accent text-xs !h-8 !px-3 shrink-0"
                  :disabled="scanning"
                  @click="runScan">
            {{ scanning ? '扫描中…' : '✨ 扫描' }}
          </button>
        </div>
        <p v-if="scans[0]" class="text-xs text-muted">
          上次扫描：{{ fmtTime(scans[0].created_at) }} · 发现 {{ scans[0].issue_count }} 条
        </p>
      </div>

      <!-- 过滤 -->
      <div class="px-3 py-2 border-b border-border space-y-1.5">
        <div class="flex gap-1">
          <button v-for="opt in [
              { v: 'open',     l: `待处理 (${counts.open})` },
              { v: 'resolved', l: `已解决 (${counts.resolved})` },
              { v: 'ignored',  l: `已忽略 (${counts.ignored})` },
              { v: 'all',      l: '全部' },
            ]" :key="opt.v"
            class="flex-1 px-2 h-7 rounded text-xs border transition-colors"
            :class="statusFilter === opt.v
              ? 'bg-accent border-accent text-white'
              : 'border-border text-muted hover:bg-surface'"
            @click="statusFilter = opt.v as any">
            {{ opt.l }}
          </button>
        </div>
        <div class="flex gap-1">
          <button v-for="opt in ['all','high','medium','low']" :key="opt"
                  class="flex-1 px-2 h-6 rounded text-xs border"
                  :class="severityFilter === opt
                    ? 'bg-surface border-border text-text'
                    : 'border-border/50 text-muted hover:bg-surface'"
                  @click="severityFilter = opt as any">
            {{ opt === 'all' ? '所有等级' : sevMeta(opt).label }}
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto">
        <div v-if="loading" class="px-4 py-6 text-sm text-muted">加载中…</div>
        <div v-else-if="err" class="px-4 py-6 text-sm text-muted">{{ err }}</div>
        <div v-else-if="visibleIssues.length === 0" class="px-4 py-12 text-center text-sm text-muted">
          <div v-if="counts.open === 0 && statusFilter === 'open'">
            <p class="font-serif text-2xl mb-2">一切看起来很整洁</p>
            <p>没有发现一致性问题。</p>
          </div>
          <div v-else>这个筛选下没有 issue。</div>
        </div>
        <ul v-else>
          <li v-for="i in visibleIssues" :key="i.id">
            <button class="w-full text-left px-4 py-3 border-b border-border/50 hover:bg-surface transition-colors"
                    :class="selectedId === i.id ? 'bg-surface' : ''"
                    @click="selectedId = i.id">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-[10px] px-1.5 py-0.5 rounded border"
                      :class="sevMeta(i.severity).cls">
                  {{ sevMeta(i.severity).label }}
                </span>
                <span class="text-[10px] text-muted">{{ i.category_label }}</span>
                <span v-if="i.status === 'resolved'" class="text-[10px] text-[#6a8e6f] ml-auto">✓ 已解决</span>
                <span v-else-if="i.status === 'ignored'" class="text-[10px] text-muted ml-auto">已忽略</span>
              </div>
              <p class="text-sm leading-snug line-clamp-2">{{ i.title }}</p>
              <p v-if="i.tick_start != null" class="text-xs text-muted mt-1 font-mono">
                t{{ i.tick_start }}<span v-if="i.tick_end && i.tick_end !== i.tick_start"> – t{{ i.tick_end }}</span>
              </p>
            </button>
          </li>
        </ul>
      </div>
    </aside>

    <!-- 右：详情 -->
    <main class="flex-1 min-w-0 overflow-y-auto">
      <div v-if="!selected" class="h-full flex items-center justify-center text-muted text-sm">
        <p>选择左侧 issue 查看详情</p>
      </div>

      <div v-else class="px-8 py-8 max-w-3xl">
        <header class="mb-6">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs px-1.5 py-0.5 rounded border"
                  :class="sevMeta(selected.severity).cls">
              {{ sevMeta(selected.severity).label }}
            </span>
            <span class="text-xs text-muted">{{ selected.category_label }}</span>
            <span v-if="selected.tick_start != null"
                  class="text-xs text-muted font-mono ml-auto">
              tick {{ selected.tick_start }}<span v-if="selected.tick_end && selected.tick_end !== selected.tick_start"> – {{ selected.tick_end }}</span>
            </span>
          </div>
          <h1 class="font-serif text-3xl leading-tight">{{ selected.title }}</h1>
        </header>

        <section class="mb-6">
          <h2 class="text-muted text-xs uppercase tracking-wider mb-2">问题描述</h2>
          <p class="text-prose leading-relaxed whitespace-pre-wrap">{{ selected.description }}</p>
        </section>

        <section v-if="selected.suggestion" class="mb-6">
          <h2 class="text-muted text-xs uppercase tracking-wider mb-2">建议</h2>
          <div class="surface rounded p-4 text-prose leading-relaxed whitespace-pre-wrap">{{ selected.suggestion }}</div>
        </section>

        <section v-if="selected.entity_ids.length > 0" class="mb-6">
          <h2 class="text-muted text-xs uppercase tracking-wider mb-2">相关角色 / 实体</h2>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="id in selected.entity_ids" :key="id"
                  class="px-2 h-6 rounded-full text-xs border border-border bg-surface inline-flex items-center">
              {{ entityName(id) }}
            </span>
          </div>
        </section>

        <!-- 补丁建议 -->
        <section class="mb-6">
          <header class="flex items-baseline justify-between mb-2">
            <h2 class="text-muted text-xs uppercase tracking-wider">AI 补丁建议</h2>
            <button class="btn btn-ghost text-xs"
                    :disabled="suggesting"
                    @click="suggestPatches">
              {{ suggesting ? '生成中…' : (patches.length ? '✨ 再来几个' : '✨ 生成补丁') }}
            </button>
          </header>

          <div v-if="loadingPatches" class="text-xs text-muted">加载补丁…</div>
          <div v-else-if="patches.length === 0" class="text-sm text-muted">
            还没有补丁。点「生成补丁」让 AI 给出几个修改建议。
          </div>
          <ul v-else class="space-y-3">
            <li v-for="p in patches" :key="p.id"
                class="surface rounded p-4">
              <div class="flex items-baseline gap-2 mb-2">
                <span class="text-xs text-muted">{{ p.target_kind }}</span>
                <span v-if="p.status === 'pending'" class="text-[10px] text-muted">待处理</span>
                <span v-else-if="p.status === 'applied'" class="text-[10px] text-accent">已应用</span>
                <span v-else-if="p.status === 'rejected'" class="text-[10px] text-muted">已忽略</span>
                <span v-if="p.model_used" class="text-[10px] text-muted ml-auto font-mono">{{ p.model_used }}</span>
              </div>
              <div v-if="p.before_excerpt" class="mb-2">
                <p class="text-[10px] uppercase tracking-wider text-muted mb-1">改前</p>
                <p class="text-sm text-muted whitespace-pre-wrap line-clamp-3 font-serif italic">{{ p.before_excerpt }}</p>
              </div>
              <div class="mb-2">
                <p class="text-[10px] uppercase tracking-wider text-muted mb-1">改后</p>
                <p class="text-sm whitespace-pre-wrap font-serif">{{ p.after_text }}</p>
              </div>
              <p v-if="p.rationale" class="text-xs text-muted leading-relaxed mb-3">
                <span class="text-[10px] uppercase tracking-wider mr-1.5">理由</span>{{ p.rationale }}
              </p>
              <div class="flex items-center gap-2">
                <template v-if="p.status === 'pending'">
                  <button class="btn btn-accent text-xs"
                          :disabled="applyingId === p.id"
                          @click="applyPatch(p)">
                    {{ applyingId === p.id ? '应用中…' : '应用' }}
                  </button>
                  <button class="btn btn-ghost text-xs" @click="rejectPatch(p)">忽略</button>
                </template>
                <button v-else-if="p.can_undo" class="btn btn-ghost text-xs" @click="undoPatch(p)">撤销应用</button>
                <span v-if="p.applied_at" class="text-xs text-muted ml-auto">{{ fmtTime(p.applied_at) }}</span>
              </div>
            </li>
          </ul>
        </section>

        <!-- 状态操作 -->
        <section class="mt-10 pt-6 border-t border-border flex items-center gap-2">
          <span class="text-xs text-muted mr-auto">状态：{{ selected.status }}</span>
          <button v-if="selected.tick_start != null"
                  class="btn btn-ghost text-xs"
                  @click="gotoTimeline(selected.tick_start)">在时间轴查看 →</button>
          <button v-if="selected.status !== 'resolved'"
                  class="btn btn-ghost text-xs"
                  @click="setIssueStatus(selected, 'resolved')">标记为已解决</button>
          <button v-if="selected.status !== 'ignored'"
                  class="btn btn-ghost text-xs"
                  @click="setIssueStatus(selected, 'ignored')">忽略</button>
          <button v-if="selected.status !== 'open'"
                  class="btn btn-ghost text-xs"
                  @click="setIssueStatus(selected, 'open')">重新打开</button>
          <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                  @click="confirmDelete = selected">删除</button>
        </section>
      </div>
    </main>

    <ConfirmDialog
      :open="confirmDelete !== null"
      title="删除 issue？"
      :message="confirmDelete ? confirmDelete.title : ''"
      confirm-text="删除"
      danger
      @cancel="confirmDelete = null"
      @confirm="doDelete" />
  </div>
</template>

