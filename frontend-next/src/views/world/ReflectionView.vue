<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { reflectionApi, type ReflectionEntry } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

const AGENT_TYPES = [
  { v: 'director', l: '导演' },
  { v: 'author',   l: '作家' },
  { v: 'critic',   l: '审稿' },
];
function agentLabel(v: string): string {
  return AGENT_TYPES.find(a => a.v === v)?.l || v;
}

const items = ref<ReflectionEntry[]>([]);
const loading = ref(true);
const err = ref('');
const search = ref('');
const filterAgent = ref<string>('all');
const selectedId = ref<string | null>(null);

async function load() {
  loading.value = true;
  err.value = '';
  try {
    items.value = await reflectionApi.list(worldId.value);
    if (selectedId.value && !items.value.find(r => r.id === selectedId.value)) {
      selectedId.value = null;
    }
    if (!selectedId.value && items.value.length > 0) {
      selectedId.value = items.value[0].id;
    }
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, () => { selectedId.value = null; load(); });

const visible = computed(() => {
  const q = search.value.trim().toLowerCase();
  return items.value.filter(r => {
    if (filterAgent.value !== 'all' && r.agent_type !== filterAgent.value) return false;
    if (q && !r.title.toLowerCase().includes(q) && !(r.content || '').toLowerCase().includes(q)) return false;
    return true;
  });
});

const enabledItems = computed(() => visible.value.filter(r => r.enabled));
const disabledItems = computed(() => visible.value.filter(r => !r.enabled));
const selected = computed(() => items.value.find(r => r.id === selectedId.value) || null);

// ---------- 编辑 ----------
const draft = ref<{
  title: string; content: string; agent_type: string; enabled: boolean;
} | null>(null);

const dirty = computed(() => {
  if (!selected.value || !draft.value) return false;
  const e = selected.value;
  return (
    draft.value.title !== e.title ||
    draft.value.content !== (e.content || '') ||
    draft.value.agent_type !== e.agent_type ||
    draft.value.enabled !== e.enabled
  );
});

watch(selected, (e) => {
  if (!e) { draft.value = null; return; }
  draft.value = {
    title: e.title,
    content: e.content || '',
    agent_type: e.agent_type,
    enabled: e.enabled,
  };
}, { immediate: true });

const saving = ref(false);
async function saveSelected() {
  if (!selected.value || !draft.value || !dirty.value) return;
  saving.value = true;
  try {
    await reflectionApi.patch(selected.value.id, {
      title: draft.value.title.trim() || selected.value.title,
      content: draft.value.content,
      agent_type: draft.value.agent_type,
      enabled: draft.value.enabled,
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
    agent_type: e.agent_type,
    enabled: e.enabled,
  };
}

// ---------- 创建 ----------
const createOpen = ref(false);
const createDraft = ref({ title: '', agent_type: 'director', content: '' });
const creating = ref(false);
function openCreate() {
  createDraft.value = {
    title: '',
    agent_type: filterAgent.value === 'all' ? 'director' : filterAgent.value,
    content: '',
  };
  createOpen.value = true;
}
async function submitCreate() {
  const title = createDraft.value.title.trim();
  if (!title) { toast.error('请填标题'); return; }
  creating.value = true;
  try {
    const r = await reflectionApi.create(worldId.value, {
      agent_type: createDraft.value.agent_type,
      title,
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
const confirmDelete = ref<ReflectionEntry | null>(null);
async function doDelete() {
  const e = confirmDelete.value;
  if (!e) return;
  try {
    await reflectionApi.remove(e.id);
    toast.success('已删除');
    confirmDelete.value = null;
    selectedId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  }
}

// ---------- 快捷启用/禁用 ----------
async function toggleEnabled(e: ReflectionEntry, ev: Event) {
  ev.stopPropagation();
  try {
    await reflectionApi.patch(e.id, { enabled: !e.enabled });
    await load();
  } catch (err: any) {
    toast.error(`操作失败：${err.message || err}`);
  }
}

// ---------- 加载预设 ----------
const seeding = ref(false);
async function seedDefaults() {
  seeding.value = true;
  try {
    const r = await reflectionApi.seed(worldId.value);
    if (r.seeded > 0) {
      toast.success(`已加载 ${r.seeded} 条预设记忆`);
      await load();
    } else {
      toast.success('已有记忆，跳过预设');
    }
  } catch (e: any) {
    toast.error(`加载预设失败：${e.message || e}`);
  } finally {
    seeding.value = false;
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- 左：列表 -->
    <aside class="w-[320px] shrink-0 border-r border-border bg-sunken/40 flex flex-col">
      <header class="h-12 px-4 border-b border-border flex items-center gap-2 shrink-0">
        <span class="text-muted text-xs uppercase tracking-wider">反思记忆</span>
        <span class="text-xs text-muted font-mono">{{ items.length }}</span>
        <div class="flex-1" />
        <button class="btn btn-ghost text-xs !h-7 !px-2" title="新增" @click="openCreate">＋</button>
      </header>

      <div class="px-3 py-2 border-b border-border space-y-2">
        <input v-model="search" class="input !h-8 text-sm" placeholder="搜索" />
        <select v-model="filterAgent" class="input !h-8 text-sm">
          <option value="all">所有类型</option>
          <option v-for="a in AGENT_TYPES" :key="a.v" :value="a.v">{{ a.l }}</option>
        </select>
      </div>

      <div class="flex-1 overflow-y-auto py-2">
        <div v-if="loading" class="px-4 py-6 text-sm text-muted">加载中…</div>
        <div v-else-if="err" class="px-4 py-6 text-sm text-muted">{{ err }}</div>
        <div v-else-if="visible.length === 0" class="px-4 py-12 text-center text-sm text-muted">
          <p v-if="items.length === 0" class="font-serif text-2xl mb-2">还没有反思记忆</p>
          <p v-if="items.length === 0">记录每个 agent 的经验教训，让它们在后续推演中越来越好。</p>
          <p v-else>没有匹配。</p>
          <div v-if="items.length === 0" class="flex gap-2 justify-center mt-4">
            <button class="btn btn-accent text-xs" :disabled="seeding" @click="seedDefaults">
              {{ seeding ? '加载中…' : '加载预设' }}
            </button>
            <button class="btn btn-ghost text-xs" @click="openCreate">手动添加</button>
          </div>
        </div>

        <div v-else>
          <section v-if="enabledItems.length > 0" class="mb-3">
            <div class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted">● 启用</div>
            <ul>
              <li v-for="e in enabledItems" :key="e.id">
                <button class="w-full text-left px-4 py-2 hover:bg-surface transition-colors flex items-baseline gap-2"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-accent text-xs shrink-0">{{ agentLabel(e.agent_type).slice(0, 1) }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.title }}</span>
                    <span class="block truncate text-xs text-muted">{{ agentLabel(e.agent_type) }}</span>
                  </span>
                  <span class="text-xs text-muted cursor-pointer hover:text-accent" title="禁用" @click="toggleEnabled(e, $event)">●</span>
                </button>
              </li>
            </ul>
          </section>

          <section v-if="disabledItems.length > 0">
            <div class="px-4 py-1 text-[10px] uppercase tracking-wider text-muted">○ 禁用</div>
            <ul>
              <li v-for="e in disabledItems" :key="e.id">
                <button class="w-full text-left px-4 py-2 hover:bg-surface transition-colors flex items-baseline gap-2 opacity-50"
                        :class="selectedId === e.id ? 'bg-surface' : ''"
                        @click="selectedId = e.id">
                  <span class="text-muted text-xs shrink-0">{{ agentLabel(e.agent_type).slice(0, 1) }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="block truncate text-sm">{{ e.title }}</span>
                    <span class="block truncate text-xs text-muted">{{ agentLabel(e.agent_type) }}</span>
                  </span>
                  <span class="text-xs text-muted cursor-pointer hover:text-accent" title="启用" @click="toggleEnabled(e, $event)">○</span>
                </button>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </aside>

    <!-- 右：详情 -->
    <main class="flex-1 overflow-y-auto p-6">
      <div v-if="!selected" class="h-full flex items-center justify-center text-muted text-sm">
        选择一条记忆查看详情
      </div>
      <div v-else-if="draft" class="max-w-2xl space-y-4">
        <div class="flex items-center gap-3">
          <input v-model="draft.title" class="input flex-1 text-lg font-medium" placeholder="标题" />
          <button class="btn btn-ghost text-xs text-red-500" @click="confirmDelete = selected">删除</button>
        </div>

        <div class="flex items-center gap-4">
          <label class="text-sm text-muted">Agent 类型</label>
          <select v-model="draft.agent_type" class="input !w-32 !h-8 text-sm">
            <option v-for="a in AGENT_TYPES" :key="a.v" :value="a.v">{{ a.l }}</option>
          </select>
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" v-model="draft.enabled" class="accent-accent" />
            启用
          </label>
        </div>

        <div v-if="selected.source_tick != null" class="text-xs text-muted">
          来源：tick {{ selected.source_tick }}
          <span v-if="selected.source_event"> · {{ selected.source_event }}</span>
        </div>

        <textarea v-model="draft.content" class="input w-full min-h-[200px] text-sm font-mono resize-y"
                  placeholder="经验内容（会注入到对应 agent 的 prompt 中）" />

        <div class="flex gap-2">
          <button class="btn btn-accent text-sm" :disabled="!dirty || saving" @click="saveSelected">
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button class="btn btn-ghost text-sm" :disabled="!dirty" @click="revertDraft">还原</button>
        </div>
      </div>
    </main>

    <!-- 创建 Dialog -->
    <Dialog :open="createOpen" title="新建反思记忆" @close="createOpen = false">
      <div class="space-y-3 min-w-[360px]">
        <div>
          <label class="text-xs text-muted">Agent 类型</label>
          <select v-model="createDraft.agent_type" class="input !h-8 text-sm w-full mt-1">
            <option v-for="a in AGENT_TYPES" :key="a.v" :value="a.v">{{ a.l }}</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-muted">标题</label>
          <input v-model="createDraft.title" class="input w-full mt-1" placeholder="简短描述这条经验" />
        </div>
        <div>
          <label class="text-xs text-muted">内容</label>
          <textarea v-model="createDraft.content" class="input w-full mt-1 min-h-[100px] text-sm resize-y"
                    placeholder="详细描述经验教训" />
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <button class="btn btn-ghost text-sm" @click="createOpen = false">取消</button>
          <button class="btn btn-accent text-sm" :disabled="creating" @click="submitCreate">
            {{ creating ? '创建中…' : '创建' }}
          </button>
        </div>
      </div>
    </Dialog>

    <!-- 删除确认 -->
    <ConfirmDialog
      :open="!!confirmDelete"
      title="删除反思记忆"
      :message="`确定删除「${confirmDelete?.title || ''}」？`"
      confirm-label="删除"
      @confirm="doDelete"
      @cancel="confirmDelete = null"
    />
  </div>
</template>
