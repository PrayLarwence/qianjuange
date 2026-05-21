<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import cytoscape, { type Core, type ElementDefinition, type Stylesheet } from 'cytoscape';
import { relationshipsApi, type GraphNode, type GraphEdge } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import { useThemeStore } from '@/stores/theme';

const route = useRoute();
const toast = useToastStore();
const themeStore = useThemeStore();
const worldId = computed(() => route.params.id as string);

const nodes = ref<GraphNode[]>([]);
const edges = ref<GraphEdge[]>([]);
const loading = ref(true);
const err = ref('');

// 选中
type Selection =
  | { kind: 'node'; data: GraphNode }
  | { kind: 'edge'; data: GraphEdge }
  | null;
const selection = ref<Selection>(null);

// 过滤
const search = ref('');
const enabledTypes = ref<Record<string, boolean>>({});
const allTypes = computed(() => {
  const set = new Set(nodes.value.map(n => n.type || 'other'));
  return [...set].sort();
});
watch(allTypes, types => {
  for (const t of types) if (!(t in enabledTypes.value)) enabledTypes.value[t] = true;
});

// 视图模式：全图 / 聚焦某个中心节点（1-hop 邻居）
type ViewMode = 'all' | 'ego';
const viewMode = ref<ViewMode>('all');
const egoCenterId = ref<string | null>(null);

// 计算每个节点的 degree（共同事件次数加权）
const nodeDegree = computed(() => {
  const m: Record<string, number> = {};
  for (const n of nodes.value) m[n.id] = 0;
  for (const e of edges.value) {
    m[e.source] = (m[e.source] || 0) + e.weight;
    m[e.target] = (m[e.target] || 0) + e.weight;
  }
  return m;
});

// 自动选择"核心人物"：度数最高的 character
const autoCenterId = computed<string | null>(() => {
  const chars = nodes.value.filter(n => n.type === 'character');
  if (chars.length === 0) return null;
  return chars.reduce((best, n) =>
    (nodeDegree.value[n.id] || 0) > (nodeDegree.value[best.id] || 0) ? n : best,
  chars[0]).id;
});

const effectiveCenterId = computed<string | null>(() =>
  egoCenterId.value || autoCenterId.value,
);

const centerNode = computed<GraphNode | null>(() => {
  const id = effectiveCenterId.value;
  return id ? nodes.value.find(n => n.id === id) || null : null;
});

const visibleNodeIds = computed(() => {
  const q = search.value.trim().toLowerCase();
  if (viewMode.value === 'ego' && effectiveCenterId.value) {
    const c = effectiveCenterId.value;
    const ids = new Set<string>([c]);
    for (const e of edges.value) {
      if (e.source === c) ids.add(e.target);
      if (e.target === c) ids.add(e.source);
    }
    return new Set(
      [...ids].filter(id => {
        const n = nodes.value.find(x => x.id === id);
        if (!n) return false;
        if (enabledTypes.value[n.type || 'other'] === false && id !== c) return false;
        if (q && id !== c && !n.name.toLowerCase().includes(q)) return false;
        return true;
      }),
    );
  }
  return new Set(
    nodes.value
      .filter(n => enabledTypes.value[n.type || 'other'] !== false)
      .filter(n => !q || n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
      .map(n => n.id),
  );
});

function focusOn(id: string) {
  egoCenterId.value = id;
  viewMode.value = 'ego';
  selection.value = null;
}
function exitEgo() {
  viewMode.value = 'all';
  egoCenterId.value = null;
}
function useAutoCenter() {
  egoCenterId.value = null;
  viewMode.value = 'ego';
}

// 推断
const inferring = ref(false);
async function runInfer() {
  inferring.value = true;
  try {
    const r = await relationshipsApi.infer(worldId.value, {});
    toast.success(`推断完成：更新 ${r.updated ?? 0} 对关系`);
    await load();
  } catch (e: any) {
    toast.error(`推断失败：${e.message || e}`);
  } finally {
    inferring.value = false;
  }
}

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const r = await relationshipsApi.get(worldId.value);
    nodes.value = r.nodes || [];
    edges.value = r.edges || [];
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}

// ---------- Cytoscape ----------
const container = ref<HTMLDivElement | null>(null);
let cy: Core | null = null;

function readTheme() {
  const cs = getComputedStyle(document.documentElement);
  const rgb = (name: string) => `rgb(${cs.getPropertyValue(name).trim() || '0 0 0'})`;
  return {
    bg:      rgb('--bg'),
    text:    rgb('--text'),
    muted:   rgb('--muted'),
    border:  rgb('--border'),
    surface: rgb('--surface'),
    sunken:  rgb('--sunken'),
    accent:  rgb('--accent'),
  };
}

function buildElements(): ElementDefinition[] {
  const visible = visibleNodeIds.value;
  const center = effectiveCenterId.value;
  const ns: ElementDefinition[] = nodes.value
    .filter(n => visible.has(n.id))
    .map(n => ({
      group: 'nodes' as const,
      data: {
        id: n.id, label: n.name, type: n.type || 'other',
        alive: n.alive ? 1 : 0,
        center: viewMode.value === 'ego' && n.id === center ? 1 : 0,
      },
    }));
  const es: ElementDefinition[] = edges.value
    .filter(e => visible.has(e.source) && visible.has(e.target))
    .map(e => ({
      group: 'edges' as const,
      data: {
        id: e.id, source: e.source, target: e.target,
        weight: e.weight, label: e.label || '',
      },
    }));
  return [...ns, ...es];
}

// zoom 阈值控制：缩得很小时隐藏节点 label
const HIDE_LABEL_BELOW = 0.55;
let labelHidden = false;

function buildStyle(): Stylesheet[] {
  const t = readTheme();
  // 手稿水彩风色板，两种主题下都成立
  const PALETTE = {
    character: '#b04f33',  // 铁锈红
    location:  '#6a8e6f',  // 苔藓绿
    item:      '#bb9856',  // 古金
    faction:   '#4a6e8c',  // 靛蓝
    other:     '#8b7565',  // 暖褐
  };
  // 标签色：明亮暖橙，白天/黑夜都成立
  const LABEL = '#e89968';
  return [
    {
      selector: 'node',
      style: {
        'background-color': PALETTE.other,
        'border-color': t.text,
        'border-width': 1.5,
        'border-opacity': 0.55,
        'label': 'data(label)',
        'color': LABEL,
        'font-family': '"Noto Serif SC", Georgia, serif',
        'font-size': 11,
        'font-weight': 500,
        'text-valign': 'bottom',
        'text-margin-y': 5,
        'text-wrap': 'ellipsis',
        'text-max-width': '110px',
        'width': 22, 'height': 22,
      } as any,
    },
    { selector: 'node[type = "character"]', style: {
        'background-color': PALETTE.character,
        'width': 32, 'height': 32, 'font-size': 12,
    } },
    { selector: 'node[type = "location"]', style: {
        'shape': 'round-rectangle', 'width': 44, 'height': 22,
        'background-color': PALETTE.location,
    } },
    { selector: 'node[type = "item"]', style: { 'background-color': PALETTE.item } },
    { selector: 'node[type = "faction"]', style: { 'background-color': PALETTE.faction } },
    { selector: 'node[alive = 0]', style: { 'opacity': 0.45, 'border-style': 'dashed' } },
    { selector: 'node[center = 1]', style: {
        'border-color': t.text, 'border-width': 3.5, 'border-opacity': 1,
        'width': 44, 'height': 44, 'font-size': 13,
    } },
    { selector: 'node:selected', style: {
        'border-color': t.text, 'border-width': 3, 'border-opacity': 1,
        'overlay-opacity': 0.1, 'overlay-color': t.accent,
    } },
    { selector: 'node.label-hidden', style: { 'label': '' } as any },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'line-color': t.muted,
        'width': 'mapData(weight, 1, 12, 1, 6)' as any,
        'opacity': 0.5,
        'label': '',
        'color': LABEL,
        'font-size': 10,
        'text-rotation': 'autorotate' as any,
      } as any,
    },
    { selector: 'edge:selected, edge.show-label', style: {
        'line-color': t.accent, 'opacity': 1, 'width': 3,
        'color': LABEL, 'label': 'data(label)',
    } as any },
  ];
}

function applyZoomLabelPolicy() {
  if (!cy) return;
  const z = cy.zoom();
  const shouldHide = z < HIDE_LABEL_BELOW;
  if (shouldHide === labelHidden) return;
  labelHidden = shouldHide;
  if (shouldHide) cy.nodes().addClass('label-hidden');
  else cy.nodes().removeClass('label-hidden');
}

function mountGraph() {
  if (!container.value) return;
  cy = cytoscape({
    container: container.value,
    elements: buildElements(),
    style: buildStyle(),
    layout: { name: 'cose', animate: false, fit: true, padding: 40, idealEdgeLength: () => 110, nodeRepulsion: () => 8000 } as any,
    wheelSensitivity: 0.25,
    minZoom: 0.2, maxZoom: 2.5,
  });
  cy.on('tap', 'node', evt => {
    const id = evt.target.id();
    const n = nodes.value.find(x => x.id === id);
    if (n) selection.value = { kind: 'node', data: n };
  });
  cy.on('tap', 'edge', evt => {
    const id = evt.target.id();
    const e = edges.value.find(x => x.id === id);
    if (e) selection.value = { kind: 'edge', data: e };
  });
  cy.on('tap', evt => { if (evt.target === cy) selection.value = null; });
  cy.on('zoom', applyZoomLabelPolicy);
  applyZoomLabelPolicy();
}

function refreshGraph() {
  if (!cy) return;
  cy.json({ elements: buildElements() } as any);
  cy.style(buildStyle());
  cy.layout({ name: 'cose', animate: false, fit: true, padding: 40 } as any).run();
  applyZoomLabelPolicy();
}

function restyleOnly() {
  if (!cy) return;
  cy.style(buildStyle());
}

function relayout() {
  if (!cy) return;
  cy.layout({ name: 'cose', animate: true, animationDuration: 400, fit: true, padding: 40 } as any).run();
}

watch([nodes, edges], () => { if (cy) refreshGraph(); else mountGraph(); });
watch(visibleNodeIds, () => { if (cy) refreshGraph(); });
watch(viewMode, () => { if (cy) refreshGraph(); });
watch(() => themeStore.resolved, () => restyleOnly());

onMounted(async () => {
  await load();
  // wait for container size to be ready
  requestAnimationFrame(() => { if (!cy) mountGraph(); });
});
onBeforeUnmount(() => { cy?.destroy(); cy = null; });

// 详情面板辅助
const nodeById = computed(() => {
  const m: Record<string, GraphNode> = {};
  for (const n of nodes.value) m[n.id] = n;
  return m;
});

const selectedNodeEdges = computed<GraphEdge[]>(() => {
  if (selection.value?.kind !== 'node') return [];
  const id = selection.value.data.id;
  return edges.value
    .filter(e => e.source === id || e.target === id)
    .sort((a, b) => b.weight - a.weight);
});

function focusNode(id: string) {
  const n = nodeById.value[id];
  if (n) {
    selection.value = { kind: 'node', data: n };
    cy?.$id(id).select();
    cy?.center(cy.$id(id));
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 顶部工具条 -->
    <header class="h-12 px-4 border-b border-border flex items-center gap-3 shrink-0">
      <input v-model="search" class="input !h-8 !w-48" placeholder="搜索实体…" />

      <!-- 视图模式 -->
      <div class="inline-flex rounded border border-border overflow-hidden text-xs">
        <button class="px-2.5 h-7 transition-colors"
                :class="viewMode === 'all' ? 'bg-surface' : 'text-muted hover:bg-surface/60'"
                @click="exitEgo">总图</button>
        <button class="px-2.5 h-7 border-l border-border transition-colors disabled:opacity-50"
                :class="viewMode === 'ego' ? 'bg-surface' : 'text-muted hover:bg-surface/60'"
                :disabled="!autoCenterId"
                @click="useAutoCenter"
                title="以关系最多的人物为中心">核心人物</button>
      </div>
      <span v-if="viewMode === 'ego' && centerNode" class="text-xs text-muted truncate max-w-[180px]">
        中心：<span class="text-text">{{ centerNode.name }}</span>
        <button class="ml-1 hover:underline" @click="exitEgo">×</button>
      </span>

      <div class="flex items-center gap-1.5 text-xs">
        <span class="text-muted uppercase tracking-wider mr-1">类型</span>
        <label v-for="t in allTypes" :key="t"
               class="px-2 h-7 rounded border border-border inline-flex items-center gap-1 cursor-pointer transition-colors"
               :class="enabledTypes[t] ? 'bg-surface' : 'text-muted opacity-60'">
          <input type="checkbox" v-model="enabledTypes[t]" class="hidden" />
          <span>{{ t }}</span>
        </label>
      </div>
      <div class="flex-1" />
      <button class="btn btn-ghost text-xs" @click="relayout" title="重新布局">↻ 布局</button>
      <button class="btn btn-accent text-xs" :disabled="inferring" @click="runInfer">
        <span v-if="inferring">推断中…</span>
        <span v-else>✨ 推断关系</span>
      </button>
    </header>

    <div class="flex flex-1 min-h-0">
      <!-- 图谱画布 -->
      <div class="flex-1 min-w-0 relative">
        <div ref="container" class="absolute inset-0" />
        <div v-if="loading" class="absolute inset-0 flex items-center justify-center text-muted text-sm">加载图谱…</div>
        <div v-else-if="err" class="absolute inset-0 flex items-center justify-center text-muted text-sm">{{ err }}</div>
        <div v-else-if="nodes.length === 0" class="absolute inset-0 flex items-center justify-center text-muted text-sm">
          这个分支还没有实体。先去角色或推演里建一些。
        </div>
        <div v-else-if="edges.length === 0" class="absolute top-3 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded bg-sunken/90 border border-border text-xs text-muted">
          还没有共同事件，关系图为空。可以先点"推断关系"或推演一些事件。
        </div>
      </div>

      <!-- 详情面板 -->
      <aside class="w-[320px] shrink-0 border-l border-border surface-sunken overflow-y-auto">
        <div v-if="!selection" class="p-5 text-sm">
          <p class="text-muted text-xs uppercase tracking-wider mb-3">图例</p>
          <div class="space-y-2.5">
            <div class="flex items-center gap-2">
              <span class="w-4 h-4 rounded-full" style="background:#b04f33" />
              <span>角色</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-6 h-3 rounded-sm" style="background:#6a8e6f" />
              <span>地点</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full" style="background:#bb9856" />
              <span>物品</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full" style="background:#4a6e8c" />
              <span>派系</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full opacity-50" style="background:#8b7565; border:1px dashed rgb(var(--text))" />
              <span class="text-muted">已逝</span>
            </div>
            <div class="flex items-center gap-2 pt-1.5">
              <span class="w-8 h-0.5" style="background:rgb(var(--muted))" />
              <span>边的粗细 = 共同事件次数</span>
            </div>
          </div>
          <p class="text-muted text-xs mt-6 leading-relaxed">点击节点或边可查看详情。</p>
        </div>

        <!-- 节点详情 -->
        <div v-else-if="selection.kind === 'node'" class="p-5">
          <p class="text-muted text-xs uppercase tracking-wider mb-1">{{ selection.data.type || 'entity' }}</p>
          <h2 class="font-serif text-2xl mb-1">{{ selection.data.name }}</h2>
          <p v-if="!selection.data.alive" class="text-xs text-muted mb-3">— 已逝 —</p>
          <p v-if="selection.data.summary" class="text-sm leading-relaxed mt-3">{{ selection.data.summary }}</p>

          <button class="btn btn-ghost text-xs mt-4 px-2"
                  :disabled="viewMode === 'ego' && effectiveCenterId === selection.data.id"
                  @click="focusOn(selection!.data.id)">
            ✦ 以此为中心
          </button>

          <div class="mt-6">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">关系（{{ selectedNodeEdges.length }}）</p>
            <div v-if="selectedNodeEdges.length === 0" class="text-sm text-muted">没有关系。</div>
            <ul v-else class="space-y-1.5">
              <li v-for="e in selectedNodeEdges" :key="e.id"
                  class="flex items-center gap-2 text-sm">
                <button class="flex-1 text-left truncate hover:underline"
                        @click="focusNode(e.source === selection!.data.id ? e.target : e.source)">
                  {{ nodeById[e.source === selection!.data.id ? e.target : e.source]?.name || '?' }}
                </button>
                <span v-if="e.label" class="text-xs text-muted truncate max-w-[120px]">{{ e.label }}</span>
                <span class="font-mono text-xs text-muted">×{{ e.weight }}</span>
              </li>
            </ul>
          </div>
        </div>

        <!-- 边详情 -->
        <div v-else class="p-5">
          <p class="text-muted text-xs uppercase tracking-wider mb-2">关系</p>
          <div class="flex items-center gap-2 text-lg font-serif mb-2">
            <button class="hover:underline" @click="focusNode(selection.data.source)">
              {{ nodeById[selection.data.source]?.name || '?' }}
            </button>
            <span class="text-muted">↔</span>
            <button class="hover:underline" @click="focusNode(selection.data.target)">
              {{ nodeById[selection.data.target]?.name || '?' }}
            </button>
          </div>
          <p v-if="selection.data.label" class="text-sm italic text-muted mb-2">「{{ selection.data.label }}」</p>
          <p class="font-mono text-xs text-muted">共 {{ selection.data.weight }} 次共同事件</p>

          <div class="mt-6">
            <p class="text-muted text-xs uppercase tracking-wider mb-2">最近共同事件</p>
            <ol class="space-y-2.5">
              <li v-for="ev in selection.data.events" :key="ev.id" class="text-sm">
                <span class="font-mono text-xs text-muted mr-2">t{{ ev.tick }}</span>
                {{ ev.title || '（未命名事件）' }}
              </li>
            </ol>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
