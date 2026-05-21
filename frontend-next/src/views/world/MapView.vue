<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  mapApi, worldsApi,
  type MapMeta, type MapPin, type WorldEntity,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const route = useRoute();
const toast = useToastStore();
const worldId = computed(() => route.params.id as string);

type Layer = 'biome' | 'terrain' | 'height' | 'temp' | 'moist';
const LAYER_LABELS: Record<Layer, string> = {
  biome: '生物群系', terrain: '地形', height: '海拔', temp: '气温', moist: '湿度',
};

const meta = ref<MapMeta | null>(null);
const pins = ref<MapPin[]>([]);
const allEntities = ref<WorldEntity[]>([]);
const loading = ref(true);
const err = ref('');
const layer = ref<Layer>('biome');
const renderKey = ref(0);

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [m, snap] = await Promise.all([
      mapApi.meta(worldId.value),
      worldsApi.get(worldId.value),
    ]);
    meta.value = m;
    allEntities.value = (snap.entities || []) as WorldEntity[];
    if (m.exists) {
      const list = await mapApi.pinned(worldId.value).catch(() => [] as MapPin[]);
      pins.value = list;
    } else {
      pins.value = [];
    }
    renderKey.value += 1;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, load);

const renderUrl = computed(() => {
  if (!meta.value?.exists) return '';
  return mapApi.renderUrl(worldId.value, layer.value) + `&k=${renderKey.value}`;
});

const hover = ref<{ x: number; y: number; pin?: MapPin } | null>(null);
function onPinHover(p: MapPin | null, e: MouseEvent) {
  if (!p) { hover.value = null; return; }
  hover.value = { x: e.clientX, y: e.clientY, pin: p };
}

const biomeLegend = computed(() => {
  const m = meta.value;
  if (!m) return [];
  return Object.entries(m.biomes).map(([_id, b]) => ({
    label: b.label,
    color: `rgb(${b.color[0]},${b.color[1]},${b.color[2]})`,
  }));
});

const PIN_TYPE_COLOR: Record<string, string> = {
  character: '#bb9856',
  location:  '#6a8e6f',
  item:      '#a07a4a',
  faction:   '#b04f33',
  concept:   '#7a7a8e',
};
function pinColor(type: string): string {
  return PIN_TYPE_COLOR[type] || '#888';
}

const pinnedIds = computed(() => new Set(pins.value.map(p => p.id)));
const unpinnedEntities = computed(() =>
  allEntities.value.filter(e => !pinnedIds.value.has(e.id)),
);

// 钉模式：选了一个实体后，点地图任意位置即定位
const armedEntityId = ref<string | null>(null);
const armedEntity = computed(() =>
  allEntities.value.find(e => e.id === armedEntityId.value) || null,
);

async function onMapClick(ev: MouseEvent) {
  if (!armedEntityId.value || !meta.value?.exists) return;
  const target = ev.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  const x = Math.round((ev.clientX - rect.left) * (meta.value.width / rect.width));
  const y = Math.round((ev.clientY - rect.top) * (meta.value.height / rect.height));
  const ent = armedEntity.value;
  try {
    await mapApi.pin(worldId.value, { entity_id: armedEntityId.value, x, y });
    toast.success(`已把「${ent?.name || ''}」钉到 ${x},${y}`);
    armedEntityId.value = null;
    await load();
  } catch (e: any) {
    toast.error(`定位失败：${e.message || e}`);
  }
}

async function unpin(p: MapPin) {
  try {
    await mapApi.pin(worldId.value, { entity_id: p.id, x: null, y: null });
    toast.success(`已取消「${p.name}」的定位`);
    await load();
  } catch (e: any) {
    toast.error(`取消失败：${e.message || e}`);
  }
}

// ---------- 生成地图 ----------
const generateOpen = ref(false);
const generating = ref(false);
const showAdvanced = ref(false);
const genDraft = ref({
  width: 512,
  height: 384,
  seed: 0,
  sea_level: 0.42,
  octaves: 6,
  persistence: 0.55,
  base_freq: 2.5,
  warp: 0.12,
});

function openGenerate() {
  if (meta.value?.exists) {
    genDraft.value = {
      width: meta.value.width,
      height: meta.value.height,
      seed: meta.value.seed,
      sea_level: 0.42,
      octaves: 6,
      persistence: 0.55,
      base_freq: 2.5,
      warp: 0.12,
    };
  } else {
    genDraft.value = {
      width: 512, height: 384, seed: Math.floor(Math.random() * 1_000_000),
      sea_level: 0.42, octaves: 6, persistence: 0.55, base_freq: 2.5, warp: 0.12,
    };
  }
  showAdvanced.value = false;
  generateOpen.value = true;
}

async function submitGenerate() {
  generating.value = true;
  try {
    const r = await mapApi.generate(worldId.value, genDraft.value);
    toast.success(`地图已生成 ${r.width}×${r.height} (seed ${r.seed})`);
    generateOpen.value = false;
    await load();
  } catch (e: any) {
    toast.error(`生成失败：${e.message || e}`);
  } finally {
    generating.value = false;
  }
}

// ---------- 删除地图 ----------
const confirmDrop = ref(false);
const dropping = ref(false);
async function dropMap() {
  dropping.value = true;
  try {
    await mapApi.drop(worldId.value);
    toast.success('地图已删除');
    confirmDrop.value = false;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  } finally {
    dropping.value = false;
  }
}
</script>

<template>
  <div class="flex h-full">
    <main class="flex-1 min-w-0 overflow-auto bg-sunken/30 relative">
      <div v-if="loading" class="h-full flex items-center justify-center text-muted text-sm">加载中…</div>
      <div v-else-if="err" class="h-full flex items-center justify-center text-muted text-sm">{{ err }}</div>

      <!-- 还没生成地图 -->
      <div v-else-if="!meta?.exists" class="h-full flex items-center justify-center px-8 text-center">
        <div class="max-w-md">
          <p class="font-serif text-3xl mb-3">还没有地图</p>
          <p class="text-muted text-sm leading-relaxed mb-6">
            生成一张柏林噪声地图作为世界的空间底图。生成完之后，可以在右侧把角色和地点钉到具体坐标上。
          </p>
          <button class="btn btn-accent" @click="openGenerate">✨ 生成地图</button>
        </div>
      </div>

      <!-- 地图存在 -->
      <div v-else class="relative inline-block min-w-full min-h-full p-6">
        <!-- 钉模式提示条 -->
        <div v-if="armedEntity"
             class="sticky top-0 z-20 -mx-6 -mt-6 mb-4 px-6 py-2 bg-accent text-white text-sm flex items-center gap-3">
          <span>选择 <b>「{{ armedEntity.name }}」</b> 的位置 — 点击地图任意位置确认</span>
          <button class="ml-auto text-xs px-2 py-1 rounded bg-white/15 hover:bg-white/25"
                  @click="armedEntityId = null">取消</button>
        </div>

        <div class="relative inline-block surface rounded shadow-soft overflow-hidden"
             :class="armedEntity ? 'cursor-crosshair' : ''"
             @click="onMapClick">
          <img :src="renderUrl"
               :width="meta.width" :height="meta.height"
               class="block max-w-none select-none"
               draggable="false"
               alt="map" />

          <!-- 已钉实体 -->
          <div v-for="p in pins" :key="p.id"
               class="absolute -translate-x-1/2 -translate-y-1/2 group"
               :style="{ left: p.x + 'px', top: p.y + 'px' }"
               @click.stop
               @mouseenter="onPinHover(p, $event)"
               @mouseleave="onPinHover(null, $event)">
            <span class="block w-2.5 h-2.5 rounded-full ring-2 ring-white"
                  :style="{ background: pinColor(p.type) }" />
            <button class="absolute -top-2 -right-2 w-4 h-4 rounded-full bg-bg border border-border text-[10px] leading-none opacity-0 group-hover:opacity-100 hover:!text-[#b04f33]"
                    title="取消定位"
                    @click.stop="unpin(p)">×</button>
          </div>
        </div>
      </div>
    </main>

    <!-- 右侧栏 -->
    <aside class="w-[300px] shrink-0 border-l border-border bg-sunken/40 flex flex-col">
      <header class="h-12 px-4 border-b border-border flex items-center gap-2 shrink-0">
        <span class="text-muted text-xs uppercase tracking-wider">地图</span>
        <span v-if="meta?.exists" class="text-xs text-muted font-mono ml-auto">{{ meta.width }}×{{ meta.height }}</span>
      </header>

      <!-- 操作 -->
      <div class="px-3 py-3 border-b border-border space-y-1.5">
        <button class="btn btn-ghost text-xs w-full !justify-start" @click="openGenerate">
          {{ meta?.exists ? '✨ 重新生成（会覆盖）' : '✨ 生成地图' }}
        </button>
        <button v-if="meta?.exists"
                class="btn btn-ghost text-xs w-full !justify-start hover:!text-[#b04f33]"
                @click="confirmDrop = true">删除地图</button>
      </div>

      <template v-if="meta?.exists">
        <!-- 图层 -->
        <div class="px-4 py-3 border-b border-border space-y-2">
          <p class="text-xs text-muted">图层</p>
          <div class="grid grid-cols-2 gap-1">
            <button v-for="key in (Object.keys(LAYER_LABELS) as Layer[])" :key="key"
                    class="px-2 h-7 rounded text-xs border"
                    :class="layer === key
                      ? 'bg-accent border-accent text-white'
                      : 'border-border text-muted hover:bg-surface'"
                    @click="layer = key">
              {{ LAYER_LABELS[key] }}
            </button>
          </div>
        </div>

        <!-- 群系图例 -->
        <div v-if="layer === 'biome' && biomeLegend.length > 0"
             class="px-4 py-3 border-b border-border">
          <p class="text-xs text-muted mb-2">生物群系</p>
          <ul class="space-y-1 text-xs max-h-40 overflow-y-auto">
            <li v-for="(b, i) in biomeLegend" :key="i" class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-sm shrink-0" :style="{ background: b.color }" />
              <span class="truncate">{{ b.label }}</span>
            </li>
          </ul>
        </div>

        <!-- 钉列表 + 待钉 -->
        <div class="flex-1 overflow-y-auto">
          <div class="px-4 py-3">
            <p class="text-xs text-muted mb-2">已定位（{{ pins.length }}）</p>
            <ul v-if="pins.length > 0" class="space-y-1 text-xs">
              <li v-for="p in pins" :key="p.id"
                  class="flex items-center gap-2 py-1 px-2 rounded hover:bg-surface group">
                <span class="w-2 h-2 rounded-full shrink-0" :style="{ background: pinColor(p.type) }" />
                <span class="flex-1 min-w-0 truncate">{{ p.name }}</span>
                <span class="text-muted font-mono shrink-0">{{ p.x }},{{ p.y }}</span>
                <button class="opacity-0 group-hover:opacity-100 text-muted hover:!text-[#b04f33]"
                        title="取消定位"
                        @click="unpin(p)">×</button>
              </li>
            </ul>
            <p v-else class="text-xs text-muted">还没有实体被钉到地图上。</p>
          </div>

          <div v-if="unpinnedEntities.length > 0" class="px-4 py-3 border-t border-border">
            <p class="text-xs text-muted mb-2">未定位（{{ unpinnedEntities.length }}）</p>
            <ul class="space-y-1 text-xs">
              <li v-for="e in unpinnedEntities" :key="e.id"
                  class="flex items-center gap-2 py-1 px-2 rounded transition-colors"
                  :class="armedEntityId === e.id ? 'bg-accent/15 ring-1 ring-accent' : 'hover:bg-surface'">
                <span class="w-2 h-2 rounded-full shrink-0 opacity-50"
                      :style="{ background: pinColor(e.type || 'character') }" />
                <span class="flex-1 min-w-0 truncate">{{ e.name }}</span>
                <button class="text-muted hover:text-accent text-xs"
                        @click="armedEntityId = armedEntityId === e.id ? null : e.id">
                  {{ armedEntityId === e.id ? '取消' : '钉到地图' }}
                </button>
              </li>
            </ul>
          </div>
        </div>
      </template>
    </aside>

    <!-- hover tooltip -->
    <div v-if="hover && hover.pin"
         class="fixed pointer-events-none z-50 surface rounded shadow-soft px-3 py-2 text-xs"
         :style="{ left: (hover.x + 12) + 'px', top: (hover.y + 12) + 'px' }">
      <div class="font-medium">{{ hover.pin.name }}</div>
      <div class="text-muted font-mono">{{ hover.pin.type }} · {{ hover.pin.x }},{{ hover.pin.y }}</div>
    </div>

    <!-- generate dialog -->
    <Dialog :open="generateOpen" title="生成地图" width="480px" @close="generateOpen = false">
      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-muted mb-1 block">宽 (px)</span>
            <input v-model.number="genDraft.width" type="number" min="64" max="2048" step="64" class="input" />
          </label>
          <label class="block">
            <span class="text-xs text-muted mb-1 block">高 (px)</span>
            <input v-model.number="genDraft.height" type="number" min="64" max="2048" step="64" class="input" />
          </label>
        </div>
        <label class="block">
          <span class="text-xs text-muted mb-1 block">随机种子</span>
          <div class="flex gap-2">
            <input v-model.number="genDraft.seed" type="number" class="input flex-1" />
            <button class="btn btn-ghost text-xs" @click="genDraft.seed = Math.floor(Math.random() * 1_000_000)">🎲</button>
          </div>
        </label>
        <label class="block">
          <span class="text-xs text-muted mb-1 flex items-baseline justify-between">
            <span>海平面</span>
            <span class="font-mono text-muted">{{ genDraft.sea_level.toFixed(2) }}</span>
          </span>
          <input v-model.number="genDraft.sea_level" type="range" min="0.05" max="0.95" step="0.01" class="w-full" />
          <span class="text-[10px] text-muted">越高陆地越少</span>
        </label>

        <button class="text-xs text-muted hover:text-text"
                @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '▾ 收起高级' : '▸ 高级噪声参数' }}
        </button>

        <div v-if="showAdvanced" class="space-y-3 pt-2 border-t border-border">
          <label class="block">
            <span class="text-xs text-muted mb-1 flex items-baseline justify-between">
              <span>octaves</span><span class="font-mono">{{ genDraft.octaves }}</span>
            </span>
            <input v-model.number="genDraft.octaves" type="range" min="1" max="8" step="1" class="w-full" />
          </label>
          <label class="block">
            <span class="text-xs text-muted mb-1 flex items-baseline justify-between">
              <span>persistence</span><span class="font-mono">{{ genDraft.persistence.toFixed(2) }}</span>
            </span>
            <input v-model.number="genDraft.persistence" type="range" min="0.2" max="0.9" step="0.01" class="w-full" />
          </label>
          <label class="block">
            <span class="text-xs text-muted mb-1 flex items-baseline justify-between">
              <span>base_freq</span><span class="font-mono">{{ genDraft.base_freq.toFixed(2) }}</span>
            </span>
            <input v-model.number="genDraft.base_freq" type="range" min="0.5" max="8" step="0.1" class="w-full" />
          </label>
          <label class="block">
            <span class="text-xs text-muted mb-1 flex items-baseline justify-between">
              <span>warp</span><span class="font-mono">{{ genDraft.warp.toFixed(2) }}</span>
            </span>
            <input v-model.number="genDraft.warp" type="range" min="0" max="0.4" step="0.01" class="w-full" />
          </label>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" :disabled="generating" @click="generateOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="generating" @click="submitGenerate">
          {{ generating ? '生成中…' : '生成' }}
        </button>
      </template>
    </Dialog>

    <ConfirmDialog
      :open="confirmDrop"
      title="删除地图？"
      message="地图数据会被清除，已钉的实体坐标也会同时取消。"
      confirm-text="删除"
      :busy="dropping"
      danger
      @cancel="confirmDrop = false"
      @confirm="dropMap" />
  </div>
</template>
