<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  worldsApi, entitiesApi,
  type WorldEntity,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const route = useRoute();
const router = useRouter();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

type EntityType = 'character' | 'location' | 'item' | 'faction' | 'concept';
const TYPE_LABELS: Record<string, string> = {
  character: '角色', location: '地点', item: '物品', faction: '势力', concept: '概念',
};
const TYPE_ICONS: Record<string, string> = {
  character: '☻', location: '◰', item: '◇', faction: '⚑', concept: '✦',
};

type SortMode = 'default' | 'name-asc' | 'name-desc' | 'recent' | 'created-asc';
const SORT_OPTIONS: Array<{ v: SortMode; l: string }> = [
  { v: 'default',    l: '类型分组' },
  { v: 'name-asc',   l: '名字 A → Z' },
  { v: 'name-desc',  l: '名字 Z → A' },
  { v: 'recent',     l: '最近活跃' },
  { v: 'created-asc', l: '创建顺序' },
];

const entities = ref<WorldEntity[]>([]);
const loading = ref(true);
const err = ref('');
const filterType = ref<EntityType | 'all'>('all');
const filterTags = ref<Set<string>>(new Set());
const sortMode = ref<SortMode>('default');
const search = ref('');
const selectedId = ref<string | null>(null);

// tick at which each entity last appeared in an event
const lastSeenByEntity = ref<Record<string, number>>({});

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const snap = await worldsApi.get(worldId.value);
    entities.value = (snap.entities || []) as WorldEntity[];
    const seen: Record<string, number> = {};
    for (const ev of snap.recent_events || []) {
      const t = ev.tick || 0;
      for (const pid of ev.participants || []) {
        if (!(pid in seen) || seen[pid] < t) seen[pid] = t;
      }
    }
    lastSeenByEntity.value = seen;
    if (selectedId.value && !entities.value.find(e => e.id === selectedId.value)) {
      selectedId.value = null;
    }
    if (!selectedId.value && entities.value.length > 0) {
      const characters = entities.value.filter(e => (e.type || 'character') === 'character');
      selectedId.value = (characters[0] || entities.value[0]).id;
    }
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, () => { selectedId.value = null; load(); });

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase();
  const tagSel = filterTags.value;
  return entities.value.filter(e => {
    if (filterType.value !== 'all' && (e.type || 'character') !== filterType.value) return false;
    if (tagSel.size > 0) {
      const ets = e.tags || [];
      let any = false;
      for (const t of ets) {
        if (tagSel.has(t)) { any = true; break; }
      }
      if (!any) return false;
    }
    if (q) {
      const inName = (e.name || '').toLowerCase().includes(q);
      const inSum  = (e.summary || '').toLowerCase().includes(q);
      const inTags = (e.tags || []).some(t => t.toLowerCase().includes(q));
      if (!inName && !inSum && !inTags) return false;
    }
    return true;
  });
});

function compareSort(a: WorldEntity, b: WorldEntity): number {
  switch (sortMode.value) {
    case 'name-asc':   return (a.name || '').localeCompare(b.name || '', 'zh');
    case 'name-desc':  return (b.name || '').localeCompare(a.name || '', 'zh');
    case 'recent': {
      const ta = lastSeenByEntity.value[a.id] ?? -1;
      const tb = lastSeenByEntity.value[b.id] ?? -1;
      return tb - ta;
    }
    case 'created-asc':
    case 'default':
    default:
      return 0;
  }
}

const pinnedItems = computed(() =>
  filtered.value.filter(e => (e.pinned || 0) === 1).sort(compareSort),
);

const visibleSections = computed(() => {
  const rest = filtered.value.filter(e => (e.pinned || 0) !== 1);
  if (sortMode.value === 'default') {
    const order: EntityType[] = ['character', 'location', 'item', 'faction', 'concept'];
    return order
      .filter(t => filterType.value === 'all' || filterType.value === t)
      .map(t => ({
        key: t as string,
        label: TYPE_LABELS[t],
        items: rest.filter(e => (e.type || 'character') === t),
      }))
      .filter(s => s.items.length > 0);
  }
  return [{ key: '_all', label: '全部', items: [...rest].sort(compareSort) }];
});

// 全局已用 tag —— 给 filter chip 列表
const allTags = computed(() => {
  const counts = new Map<string, number>();
  for (const e of entities.value) {
    for (const t of (e.tags || [])) {
      counts.set(t, (counts.get(t) || 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh'))
    .map(([tag, count]) => ({ tag, count }));
});

function toggleTagFilter(t: string) {
  const s = new Set(filterTags.value);
  if (s.has(t)) s.delete(t); else s.add(t);
  filterTags.value = s;
}
function clearTagFilter() { filterTags.value = new Set(); }

const selected = computed(() => entities.value.find(e => e.id === selectedId.value) || null);

// ---------- 详情面板 ----------
const editingDraft = ref<{
  name: string; summary: string;
  attributes: string; persona: string;
  tags: string[];
} | null>(null);
const tagInput = ref('');
const detailDirty = computed(() => {
  if (!selected.value || !editingDraft.value) return false;
  const e = selected.value;
  const d = editingDraft.value;
  const curTags = (e.tags || []).join('||');
  const newTags = d.tags.join('||');
  return (
    d.name !== (e.name || '') ||
    d.summary !== (e.summary || '') ||
    d.attributes !== JSON.stringify(e.attributes || {}, null, 2) ||
    d.persona !== JSON.stringify(e.persona || {}, null, 2) ||
    curTags !== newTags
  );
});

watch(selected, (e) => {
  if (!e) { editingDraft.value = null; return; }
  editingDraft.value = {
    name: e.name || '',
    summary: e.summary || '',
    attributes: JSON.stringify(e.attributes || {}, null, 2),
    persona: JSON.stringify(e.persona || {}, null, 2),
    tags: [...(e.tags || [])],
  };
  tagInput.value = '';
}, { immediate: true });

function addTag() {
  const v = tagInput.value.trim();
  if (!v || !editingDraft.value) return;
  if (v.length > 32) {
    toast.error('标签太长（最多 32 字）');
    return;
  }
  if (editingDraft.value.tags.includes(v)) {
    tagInput.value = '';
    return;
  }
  if (editingDraft.value.tags.length >= 16) {
    toast.error('一个实体最多 16 个标签');
    return;
  }
  editingDraft.value.tags.push(v);
  tagInput.value = '';
}
function removeTag(t: string) {
  if (!editingDraft.value) return;
  editingDraft.value.tags = editingDraft.value.tags.filter(x => x !== t);
}
function reuseTag(t: string) {
  if (!editingDraft.value) return;
  if (editingDraft.value.tags.includes(t)) return;
  if (editingDraft.value.tags.length >= 16) return;
  editingDraft.value.tags.push(t);
}

const savingDetail = ref(false);
async function saveDetail() {
  if (!selected.value || !editingDraft.value || !detailDirty.value) return;
  let attrs: Record<string, unknown>;
  let pers: Record<string, unknown>;
  try {
    attrs = JSON.parse(editingDraft.value.attributes || '{}');
    pers = JSON.parse(editingDraft.value.persona || '{}');
  } catch (e: any) {
    toast.error(`JSON 不合法：${e.message || e}`);
    return;
  }
  savingDetail.value = true;
  try {
    await entitiesApi.patch(selected.value.id, {
      name: editingDraft.value.name.trim() || selected.value.name,
      summary: editingDraft.value.summary,
      attributes: attrs,
      persona: pers,
      tags: editingDraft.value.tags,
    });
    toast.success('已保存');
    await load();
  } catch (e: any) {
    toast.error(`保存失败：${e.message || e}`);
  } finally {
    savingDetail.value = false;
  }
}
function revertDetail() {
  if (!selected.value) return;
  const e = selected.value;
  editingDraft.value = {
    name: e.name || '',
    summary: e.summary || '',
    attributes: JSON.stringify(e.attributes || {}, null, 2),
    persona: JSON.stringify(e.persona || {}, null, 2),
    tags: [...(e.tags || [])],
  };
  tagInput.value = '';
}

async function togglePin(e: WorldEntity, ev?: Event) {
  ev?.stopPropagation();
  try {
    await entitiesApi.patch(e.id, { pinned: (e.pinned || 0) === 1 ? 0 : 1 });
    await load();
  } catch (err: any) {
    toast.error(`置顶失败：${err.message || err}`);
  }
}

const extracting = ref(false);
async function extractPersona() {
  if (!selected.value) return;
  extracting.value = true;
  try {
    const r = await entitiesApi.extractPersona(selected.value.id, {});
    toast.success('已抽取人物画像');
    if (editingDraft.value) {
      editingDraft.value.persona = JSON.stringify(r.persona || {}, null, 2);
    }
    await load();
  } catch (e: any) {
    toast.error(`抽取失败：${e.message || e}`);
  } finally {
    extracting.value = false;
  }
}

// ---------- 创建 ----------
const createOpen = ref(false);
const createDraft = ref<{ name: string; type: EntityType; summary: string }>({
  name: '', type: 'character', summary: '',
});
const creating = ref(false);
function openCreate(type: EntityType = 'character') {
  createDraft.value = { name: '', type, summary: '' };
  createOpen.value = true;
}
async function submitCreate() {
  const name = createDraft.value.name.trim();
  if (!name) { toast.error('请填名字'); return; }
  creating.value = true;
  try {
    const r = await entitiesApi.create(worldId.value, {
      name, type: createDraft.value.type,
      summary: createDraft.value.summary,
    });
    toast.success('已添加');
    createOpen.value = false;
    await load();
    selectedId.value = r.id;
  } catch (e: any) {
    toast.error(`添加失败：${e.message || e}`);
  } finally {
    creating.value = false;
  }
}

// ---------- 删除（标记为不在世） ----------
const confirmKill = ref(false);
async function killSelected() {
  if (!selected.value) return;
  try {
    await entitiesApi.patch(selected.value.id, { alive: 0 });
    toast.success('已标记为离场');
    confirmKill.value = false;
    selectedId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`操作失败：${e.message || e}`);
  }
}

function gotoTimelineForEntity() {
  if (!selected.value) return;
  router.push(`/worlds/${worldId.value}/timeline?character=${selected.value.id}`);
}

const memoriesPreview = computed(() => {
  const ms = selected.value?.memories || [];
  return [...ms].sort((a, b) => (b.tick ?? 0) - (a.tick ?? 0)).slice(0, 8);
});
</script>

<template>
  <div class="flex h-full">
    <!-- 左：列表 -->
    <aside class="w-[300px] shrink-0 border-r border-border bg-sunken/40 flex flex-col">
      <header class="h-12 px-4 border-b border-border flex items-center gap-2 shrink-0">
        <span class="text-muted text-xs uppercase tracking-wider">名册</span>
        <div class="flex-1" />
        <button class="btn btn-ghost text-xs !h-7 !px-2" title="新增" @click="openCreate('character')">＋</button>
      </header>

      <div class="px-3 py-2 space-y-2 border-b border-border">
        <input v-model="search" class="input !h-8 text-sm" placeholder="搜索名字 / 描述 / 标签" />
        <div class="flex flex-wrap gap-1">
          <button class="px-2 h-6 rounded text-xs border"
                  :class="filterType === 'all' ? 'bg-accent border-accent text-white' : 'border-border text-muted hover:bg-surface'"
                  @click="filterType = 'all'">全部</button>
          <button v-for="(label, t) in TYPE_LABELS" :key="t"
                  class="px-2 h-6 rounded text-xs border"
                  :class="filterType === t ? 'bg-accent border-accent text-white' : 'border-border text-muted hover:bg-surface'"
                  @click="filterType = t as EntityType">
            <span class="mr-0.5">{{ TYPE_ICONS[t] }}</span>{{ label }}
          </button>
        </div>
        <select v-model="sortMode" class="input !h-7 text-xs">
          <option v-for="opt in SORT_OPTIONS" :key="opt.v" :value="opt.v">{{ opt.l }}</option>
        </select>
      </div>

      <div v-if="allTags.length > 0" class="px-3 py-2 border-b border-border">
        <div class="flex items-baseline justify-between mb-1">
          <span class="text-[10px] uppercase tracking-wider text-muted">标签</span>
          <button v-if="filterTags.size > 0"
                  class="text-[10px] text-accent" @click="clearTagFilter">清空</button>
        </div>
        <div class="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
          <button v-for="t in allTags" :key="t.tag"
                  class="px-1.5 h-5 rounded-full text-[11px] border inline-flex items-center gap-1"
                  :class="filterTags.has(t.tag)
                    ? 'bg-accent border-accent text-white'
                    : 'border-border text-muted hover:bg-surface'"
                  @click="toggleTagFilter(t.tag)">
            <span>{{ t.tag }}</span>
            <span class="font-mono opacity-70">{{ t.count }}</span>
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto py-2">
        <div v-if="loading" class="px-4 py-6 text-sm text-muted">加载中…</div>
        <div v-else-if="err" class="px-4 py-6 text-sm text-muted">{{ err }}</div>
        <div v-else-if="visibleSections.length === 0 && pinnedItems.length === 0"
             class="px-4 py-10 text-sm text-muted text-center">
          没有匹配的实体。
        </div>
        <div v-else>
          <section v-if="pinnedItems.length > 0" class="mb-3">
            <div class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted flex items-baseline gap-2">
              <span class="text-accent">★ 置顶</span>
              <span class="font-mono">{{ pinnedItems.length }}</span>
            </div>
            <ul>
              <li v-for="e in pinnedItems" :key="e.id">
                <button class="w-full text-left px-4 py-2 flex items-baseline gap-2 hover:bg-surface transition-colors"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-accent text-xs w-3 text-center shrink-0">★</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.name }}</span>
                    <span v-if="e.summary || (e.tags && e.tags.length > 0)" class="block truncate text-xs text-muted">
                      <span v-if="e.tags && e.tags.length > 0">
                        <span v-for="t in e.tags.slice(0, 3)" :key="t" class="mr-1.5">#{{ t }}</span>
                      </span>
                      <span v-else>{{ e.summary }}</span>
                    </span>
                  </span>
                  <button class="text-xs text-accent hover:opacity-70 px-1 -mr-2 shrink-0"
                          title="取消置顶"
                          @click="togglePin(e, $event)">★</button>
                </button>
              </li>
            </ul>
          </section>

          <section v-for="sec in visibleSections" :key="sec.key" class="mb-3">
            <div class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted flex items-baseline gap-2">
              <span>{{ sec.label }}</span>
              <span class="font-mono">{{ sec.items.length }}</span>
            </div>
            <ul>
              <li v-for="e in sec.items" :key="e.id">
                <button class="w-full text-left px-4 py-2 flex items-baseline gap-2 hover:bg-surface transition-colors group/row"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-muted text-sm w-3 text-center shrink-0">{{ TYPE_ICONS[e.type || 'character'] }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.name }}</span>
                    <span v-if="e.summary || (e.tags && e.tags.length > 0)"
                          class="block truncate text-xs text-muted">
                      <span v-if="e.tags && e.tags.length > 0">
                        <span v-for="t in e.tags.slice(0, 3)" :key="t" class="mr-1.5">#{{ t }}</span>
                      </span>
                      <span v-else>{{ e.summary }}</span>
                    </span>
                  </span>
                  <button class="text-xs text-muted hover:text-accent px-1 -mr-2 shrink-0 opacity-0 group-hover/row:opacity-100 transition-opacity"
                          title="置顶"
                          @click="togglePin(e, $event)">☆</button>
                </button>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </aside>

    <!-- 右：详情 -->
    <main class="flex-1 min-w-0 overflow-y-auto">
      <div v-if="!selected" class="h-full flex items-center justify-center text-muted">
        <p class="text-sm">从左边选一个，或者<button class="text-accent ml-1" @click="openCreate('character')">添加新角色</button></p>
      </div>

      <div v-else class="px-8 py-8 max-w-3xl">
        <header class="flex items-baseline justify-between mb-2">
          <p class="text-muted text-xs uppercase tracking-wider">
            {{ TYPE_LABELS[selected.type || 'character'] }} · <span class="font-mono">{{ selected.id }}</span>
          </p>
          <div class="flex items-center gap-2">
            <button class="btn btn-ghost text-xs"
                    :class="(selected.pinned || 0) === 1 ? '!text-accent' : ''"
                    @click="togglePin(selected)">
              {{ (selected.pinned || 0) === 1 ? '★ 已置顶' : '☆ 置顶' }}
            </button>
            <button class="btn btn-ghost text-xs" @click="gotoTimelineForEntity">在时间轴查看 →</button>
            <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                    @click="confirmKill = true">标记离场</button>
          </div>
        </header>

        <input v-if="editingDraft" v-model="editingDraft.name"
               class="font-serif text-4xl mb-4 w-full bg-transparent border-0 outline-none focus:bg-sunken/50 px-1 -ml-1 rounded" />

        <textarea v-if="editingDraft" v-model="editingDraft.summary"
                  rows="2"
                  class="input !h-auto py-2 mb-6 font-serif text-prose leading-relaxed"
                  placeholder="一两句话的角色简述" />

        <!-- tags -->
        <section v-if="editingDraft" class="mb-6">
          <header class="flex items-baseline justify-between mb-2">
            <h2 class="text-muted text-xs uppercase tracking-wider">标签</h2>
            <span class="text-xs text-muted">用 Enter 添加 · 最多 16 个</span>
          </header>
          <div class="flex flex-wrap gap-1.5 items-center">
            <span v-for="t in editingDraft.tags" :key="t"
                  class="inline-flex items-center gap-1 px-2 h-6 rounded-full text-xs bg-sunken border border-border">
              <span>#{{ t }}</span>
              <button class="text-muted hover:text-[#b04f33]" @click="removeTag(t)">×</button>
            </span>
            <input v-model="tagInput"
                   class="input !h-6 !w-32 text-xs px-2"
                   placeholder="敌人 / 我方 / 主角…"
                   @keydown.enter.prevent="addTag"
                   @keydown.,.prevent="addTag" />
          </div>
          <div v-if="allTags.length > 0" class="mt-2 flex flex-wrap gap-1">
            <span class="text-[10px] text-muted mr-1 self-center">已用：</span>
            <button v-for="t in allTags.slice(0, 14)" :key="t.tag"
                    class="px-1.5 h-5 rounded-full text-[11px] border border-border text-muted hover:bg-surface"
                    :disabled="editingDraft.tags.includes(t.tag)"
                    :class="editingDraft.tags.includes(t.tag) ? 'opacity-40 cursor-not-allowed' : ''"
                    @click="reuseTag(t.tag)">
              {{ t.tag }}
            </button>
          </div>
        </section>

        <!-- attributes -->
        <section class="mb-6">
          <h2 class="text-muted text-xs uppercase tracking-wider mb-2">属性 (JSON)</h2>
          <textarea v-if="editingDraft" v-model="editingDraft.attributes"
                    rows="4"
                    class="input !h-auto py-2 font-mono text-xs leading-relaxed" />
        </section>

        <!-- persona -->
        <section class="mb-6">
          <header class="flex items-baseline justify-between mb-2">
            <h2 class="text-muted text-xs uppercase tracking-wider">人物画像 (Persona)</h2>
            <button class="btn btn-ghost text-xs"
                    :disabled="extracting"
                    @click="extractPersona">
              {{ extracting ? '抽取中…' : '✨ 从已发生事件中抽取' }}
            </button>
          </header>
          <textarea v-if="editingDraft" v-model="editingDraft.persona"
                    rows="6"
                    class="input !h-auto py-2 font-mono text-xs leading-relaxed" />
        </section>

        <!-- memories preview -->
        <section v-if="memoriesPreview.length > 0" class="mb-6">
          <h2 class="text-muted text-xs uppercase tracking-wider mb-2">最近记忆</h2>
          <ul class="space-y-1.5">
            <li v-for="(m, i) in memoriesPreview" :key="i"
                class="surface rounded px-3 py-2 flex gap-3 text-sm">
              <span class="font-mono text-xs text-muted w-10 shrink-0 pt-0.5">t{{ m.tick ?? '?' }}</span>
              <span class="flex-1 min-w-0">{{ m.text || JSON.stringify(m) }}</span>
            </li>
          </ul>
        </section>

        <!-- save bar -->
        <div v-if="detailDirty"
             class="sticky bottom-0 -mx-8 px-8 py-3 bg-bg/95 backdrop-blur border-t border-border flex items-center justify-end gap-2">
          <span class="text-xs text-muted mr-auto">有未保存的修改</span>
          <button class="btn btn-ghost text-xs" @click="revertDetail">撤回</button>
          <button class="btn btn-accent text-xs" :disabled="savingDetail" @click="saveDetail">
            {{ savingDetail ? '保存…' : '保存' }}
          </button>
        </div>
      </div>
    </main>

    <!-- create dialog -->
    <Dialog :open="createOpen" title="新增实体" @close="createOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-muted mb-1 block">类型</span>
          <select v-model="createDraft.type" class="input">
            <option v-for="(label, t) in TYPE_LABELS" :key="t" :value="t">{{ label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-muted mb-1 block">名字</span>
          <input v-model="createDraft.name" class="input" placeholder="林雪 / 苍澜学院 / 玄铁剑…" />
        </label>
        <label class="block">
          <span class="text-xs text-muted mb-1 block">简述（可空）</span>
          <textarea v-model="createDraft.summary" rows="3" class="input !h-auto py-2" />
        </label>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="createOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="creating" @click="submitCreate">
          {{ creating ? '创建中…' : '添加' }}
        </button>
      </template>
    </Dialog>

    <ConfirmDialog
      :open="confirmKill"
      title="标记离场？"
      :message="selected ? `「${selected.name}」之后不会再出现在新事件里，但已发生的历史会保留。` : ''"
      confirm-text="标记"
      danger
      @cancel="confirmKill = false"
      @confirm="killSelected" />
  </div>
</template>
