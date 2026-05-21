<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { loreApi, type LoreEntry } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const CATEGORY_OPTIONS = [
  { v: 'setting',  l: '设定' },
  { v: 'rule',     l: '规则' },
  { v: 'glossary', l: '术语' },
  { v: 'history',  l: '历史' },
  { v: 'culture',  l: '文化' },
  { v: 'magic',    l: '体系' },
  { v: 'misc',     l: '其它' },
];
function catLabel(v: string): string {
  return CATEGORY_OPTIONS.find(c => c.v === v)?.l || v;
}

const lore = ref<LoreEntry[]>([]);
const loading = ref(true);
const err = ref('');
const search = ref('');
const filterCat = ref<string>('all');
const selectedId = ref<string | null>(null);

async function load() {
  loading.value = true;
  err.value = '';
  try {
    lore.value = await loreApi.list(worldId.value);
    if (selectedId.value && !lore.value.find(l => l.id === selectedId.value)) {
      selectedId.value = null;
    }
    if (!selectedId.value && lore.value.length > 0) {
      selectedId.value = lore.value[0].id;
    }
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, () => { selectedId.value = null; load(); });

const visibleLore = computed(() => {
  const q = search.value.trim().toLowerCase();
  return lore.value.filter(l => {
    if (filterCat.value !== 'all' && l.category !== filterCat.value) return false;
    if (q && !l.title.toLowerCase().includes(q) && !(l.content || '').toLowerCase().includes(q)) return false;
    return true;
  });
});

const pinnedLore = computed(() => visibleLore.value.filter(l => l.pinned));
const unpinnedLore = computed(() => visibleLore.value.filter(l => !l.pinned));
const selected = computed(() => lore.value.find(l => l.id === selectedId.value) || null);

// ---------- 编辑 ----------
const draft = ref<{
  title: string; content: string; category: string;
  priority: number; pinned: boolean;
} | null>(null);

const dirty = computed(() => {
  if (!selected.value || !draft.value) return false;
  const e = selected.value;
  return (
    draft.value.title !== e.title ||
    draft.value.content !== (e.content || '') ||
    draft.value.category !== e.category ||
    draft.value.priority !== (e.priority || 0) ||
    draft.value.pinned !== e.pinned
  );
});

watch(selected, (e) => {
  if (!e) { draft.value = null; return; }
  draft.value = {
    title: e.title,
    content: e.content || '',
    category: e.category || 'setting',
    priority: e.priority || 0,
    pinned: e.pinned,
  };
}, { immediate: true });

const saving = ref(false);
async function saveSelected() {
  if (!selected.value || !draft.value || !dirty.value) return;
  saving.value = true;
  try {
    await loreApi.patch(selected.value.id, {
      title: draft.value.title.trim() || selected.value.title,
      content: draft.value.content,
      category: draft.value.category,
      priority: Math.floor(Number(draft.value.priority) || 0),
      pinned: draft.value.pinned,
    });
    toast.success('已保存');
    await load();
  } catch (e: any) {
    toast.error(`保存失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}
function revertDraft() {
  if (!selected.value) return;
  const e = selected.value;
  draft.value = {
    title: e.title,
    content: e.content || '',
    category: e.category || 'setting',
    priority: e.priority || 0,
    pinned: e.pinned,
  };
}

// ---------- 创建 ----------
const createOpen = ref(false);
const createDraft = ref({ title: '', category: 'setting', content: '' });
const creating = ref(false);
function openCreate() {
  createDraft.value = { title: '', category: filterCat.value === 'all' ? 'setting' : filterCat.value, content: '' };
  createOpen.value = true;
}
async function submitCreate() {
  const title = createDraft.value.title.trim();
  if (!title) { toast.error('请填标题'); return; }
  creating.value = true;
  try {
    const r = await loreApi.create(worldId.value, {
      title,
      category: createDraft.value.category,
      content: createDraft.value.content,
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

// ---------- 删除 ----------
const confirmDelete = ref<LoreEntry | null>(null);
async function doDelete() {
  const e = confirmDelete.value;
  if (!e) return;
  try {
    await loreApi.remove(e.id);
    toast.success('已删除');
    confirmDelete.value = null;
    selectedId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  }
}

// ---------- 缺口扫描 ----------
const scanning = ref(false);
const gaps = ref<Array<{ category: string; question: string; rationale?: string }>>([]);
const gapsOpen = ref(false);
async function scanGaps() {
  scanning.value = true;
  try {
    const r = await loreApi.scanGaps(worldId.value, { max_gaps: 8 });
    gaps.value = r.gaps || [];
    gapsOpen.value = true;
    if (gaps.value.length === 0) toast.success('当前世界设定看起来挺完整');
  } catch (e: any) {
    toast.error(`扫描失败：${e.message || e}`);
  } finally {
    scanning.value = false;
  }
}
function applyGap(g: { category: string; question: string; rationale?: string }) {
  createDraft.value = {
    title: g.question.length > 80 ? g.question.slice(0, 77) + '…' : g.question,
    category: g.category || 'setting',
    content: g.rationale ? `（待补充）\n\n${g.rationale}` : '',
  };
  gapsOpen.value = false;
  createOpen.value = true;
}

// ---------- 快捷置顶 ----------
async function togglePin(e: LoreEntry, ev: Event) {
  ev.stopPropagation();
  try {
    await loreApi.patch(e.id, { pinned: !e.pinned });
    await load();
  } catch (err: any) {
    toast.error(`操作失败：${err.message || err}`);
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- 左：列表 -->
    <aside class="w-[320px] shrink-0 border-r border-border bg-sunken/40 flex flex-col">
      <header class="h-12 px-4 border-b border-border flex items-center gap-2 shrink-0">
        <span class="text-muted text-xs uppercase tracking-wider">设定库</span>
        <span class="text-xs text-muted font-mono">{{ lore.length }}</span>
        <div class="flex-1" />
        <button class="btn btn-ghost text-xs !h-7 !px-2" title="新增" @click="openCreate">＋</button>
      </header>

      <div class="px-3 py-2 border-b border-border space-y-2">
        <input v-model="search" class="input !h-8 text-sm" placeholder="搜索" />
        <select v-model="filterCat" class="input !h-8 text-sm">
          <option value="all">所有分类</option>
          <option v-for="c in CATEGORY_OPTIONS" :key="c.v" :value="c.v">{{ c.l }}</option>
        </select>
      </div>

      <div class="px-3 py-2 border-b border-border">
        <button class="btn btn-ghost text-xs w-full !justify-start"
                :disabled="scanning"
                @click="scanGaps">
          {{ scanning ? '扫描中…' : '✨ 检查 lore 缺口' }}
        </button>
      </div>

      <div class="flex-1 overflow-y-auto py-2">
        <div v-if="loading" class="px-4 py-6 text-sm text-muted">加载中…</div>
        <div v-else-if="err" class="px-4 py-6 text-sm text-muted">{{ err }}</div>
        <div v-else-if="visibleLore.length === 0" class="px-4 py-12 text-center text-sm text-muted">
          <p v-if="lore.length === 0" class="font-serif text-2xl mb-2">还没有设定</p>
          <p v-if="lore.length === 0">把世界规则、术语、文化背景写下来，会成为推演的稳定背景。</p>
          <p v-else>没有匹配。</p>
          <button v-if="lore.length === 0" class="btn btn-accent text-xs mt-4" @click="openCreate">添加第一条</button>
        </div>

        <div v-else>
          <section v-if="pinnedLore.length > 0" class="mb-3">
            <div class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted">★ 置顶</div>
            <ul>
              <li v-for="e in pinnedLore" :key="e.id">
                <button class="w-full text-left px-4 py-2 hover:bg-surface transition-colors flex items-baseline gap-2"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-accent text-xs shrink-0">★</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.title }}</span>
                    <span class="block truncate text-xs text-muted">{{ catLabel(e.category) }}</span>
                  </span>
                </button>
              </li>
            </ul>
          </section>

          <section v-if="unpinnedLore.length > 0">
            <div v-if="pinnedLore.length > 0" class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted">其它</div>
            <ul>
              <li v-for="e in unpinnedLore" :key="e.id">
                <button class="w-full text-left px-4 py-2 hover:bg-surface transition-colors flex items-baseline gap-2"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-muted text-xs shrink-0">{{ catLabel(e.category).slice(0, 1) }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.title }}</span>
                    <span class="block truncate text-xs text-muted">{{ catLabel(e.category) }}</span>
                  </span>
                </button>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </aside>

    <!-- 右：编辑 -->
    <main class="flex-1 min-w-0 overflow-y-auto">
      <div v-if="!selected" class="h-full flex items-center justify-center text-muted text-sm">
        <p>从左侧选一条 lore，或者<button class="text-accent ml-1" @click="openCreate">添加新条目</button></p>
      </div>

      <div v-else-if="draft" class="px-8 py-8 max-w-3xl">
        <header class="flex items-center gap-2 mb-2">
          <p class="text-muted text-xs uppercase tracking-wider">{{ catLabel(draft.category) }}</p>
          <span class="text-xs text-muted">·</span>
          <span class="text-xs text-muted font-mono">{{ selected.id }}</span>
          <div class="flex-1" />
          <button class="btn btn-ghost text-xs"
                  :class="draft.pinned ? '!text-accent' : ''"
                  @click="draft.pinned = !draft.pinned">
            {{ draft.pinned ? '★ 已置顶' : '☆ 置顶' }}
          </button>
          <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                  @click="confirmDelete = selected">删除</button>
        </header>

        <input v-model="draft.title"
               class="font-serif text-3xl mb-4 w-full bg-transparent border-0 outline-none focus:bg-sunken/50 px-1 -ml-1 rounded" />

        <div class="flex items-center gap-3 mb-5">
          <label class="text-xs text-muted flex items-center gap-2">
            <span>分类</span>
            <select v-model="draft.category" class="input !h-7 !w-32 text-xs">
              <option v-for="c in CATEGORY_OPTIONS" :key="c.v" :value="c.v">{{ c.l }}</option>
            </select>
          </label>
          <label class="text-xs text-muted flex items-center gap-2">
            <span>优先级</span>
            <input v-model.number="draft.priority" type="number" class="input !h-7 !w-20 text-xs" />
          </label>
        </div>

        <textarea v-model="draft.content"
                  rows="20"
                  class="input !h-auto py-3 font-serif text-prose leading-relaxed"
                  placeholder="把这条设定写清楚，作为推演时的稳定背景知识。" />

        <div v-if="dirty"
             class="sticky bottom-0 -mx-8 px-8 py-3 mt-4 bg-bg/95 backdrop-blur border-t border-border flex items-center justify-end gap-2">
          <span class="text-xs text-muted mr-auto">有未保存的修改</span>
          <button class="btn btn-ghost text-xs" @click="revertDraft">撤回</button>
          <button class="btn btn-accent text-xs" :disabled="saving" @click="saveSelected">
            {{ saving ? '保存…' : '保存' }}
          </button>
        </div>
      </div>
    </main>

    <!-- create -->
    <Dialog :open="createOpen" title="新增 lore" @close="createOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-muted mb-1 block">分类</span>
          <select v-model="createDraft.category" class="input">
            <option v-for="c in CATEGORY_OPTIONS" :key="c.v" :value="c.v">{{ c.l }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-muted mb-1 block">标题</span>
          <input v-model="createDraft.title" class="input" placeholder="例如：苍澜大陆的魔法等级体系" />
        </label>
        <label class="block">
          <span class="text-xs text-muted mb-1 block">内容（可空，回头再补）</span>
          <textarea v-model="createDraft.content" rows="6" class="input !h-auto py-2 font-serif" />
        </label>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="createOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="creating" @click="submitCreate">
          {{ creating ? '创建中…' : '添加' }}
        </button>
      </template>
    </Dialog>

    <!-- gaps -->
    <Dialog :open="gapsOpen" title="lore 缺口检查" @close="gapsOpen = false">
      <div v-if="gaps.length === 0" class="text-sm text-muted">当前没有发现明显缺口。</div>
      <ul v-else class="space-y-2 max-h-[60vh] overflow-y-auto">
        <li v-for="(g, i) in gaps" :key="i" class="surface rounded p-3">
          <div class="flex items-baseline gap-2 mb-1">
            <span class="text-xs text-muted">{{ catLabel(g.category) }}</span>
          </div>
          <p class="text-sm font-serif leading-relaxed mb-2">{{ g.question }}</p>
          <p v-if="g.rationale" class="text-xs text-muted leading-relaxed mb-2">{{ g.rationale }}</p>
          <button class="btn btn-ghost text-xs" @click="applyGap(g)">基于此创建 →</button>
        </li>
      </ul>
      <template #footer>
        <button class="btn btn-ghost" @click="gapsOpen = false">关闭</button>
      </template>
    </Dialog>

    <ConfirmDialog
      :open="confirmDelete !== null"
      title="删除 lore？"
      :message="confirmDelete ? `「${confirmDelete.title}」` : ''"
      confirm-text="删除"
      danger
      @cancel="confirmDelete = null"
      @confirm="doDelete" />
  </div>
</template>

