<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useUiStore } from '@/stores/ui';
import { worldsApi, type WorldDetail } from '@/services/api';

const route = useRoute();
const ui = useUiStore();

const world = ref<WorldDetail | null>(null);
const err = ref('');

const worldId = computed(() => route.params.id as string);

const items = [
  { to: '',          label: '仪表盘',   icon: '◐' },
  { to: 'chapters',  label: '章节',     icon: '✎' },
  { to: 'graph',     label: '图谱',     icon: '◇' },
  { to: 'timeline',  label: '时间轴',   icon: '─' },
  { to: 'map',       label: '地图',     icon: '◰' },
  { to: 'cast',      label: '角色',     icon: '☻' },
  { to: 'lore',      label: '设定库',   icon: '✦' },
  { to: 'sim',       label: '推演',     icon: '↻' },
  { to: 'agent-run', label: 'Agent 编排', icon: '◈' },
  { to: 'review',    label: '审阅',     icon: '⊙' },
  { to: 'storyboard',label: '故事板',   icon: '▦' },
  { to: 'settings',  label: '世界设置', icon: '⚙' },
];

async function load() {
  err.value = '';
  try {
    const snap = await worldsApi.get(worldId.value);
    world.value = snap.world;
  } catch (e: any) {
    err.value = e.message || String(e);
  }
}

onMounted(load);
watch(worldId, load);

function isActive(to: string) {
  const base = `/worlds/${worldId.value}`;
  const target = to ? `${base}/${to}` : base;
  if (!to) return route.path === base || route.path === base + '/';
  return route.path === target || route.path.startsWith(target + '/');
}
</script>

<template>
  <div class="flex h-[calc(100vh-3rem)]">
    <!-- 左侧导航 -->
    <aside class="border-r border-border bg-bg flex flex-col"
           :class="ui.sidebarCollapsed ? 'w-12' : 'w-56'">
      <div class="px-3 py-3 border-b border-border h-12 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-sunken flex items-center justify-center text-xs">{{ (world?.name || '?').charAt(0) }}</span>
        <div v-if="!ui.sidebarCollapsed" class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate">{{ world?.name || '加载中…' }}</div>
        </div>
        <button class="btn btn-ghost !h-6 !px-1" @click="ui.toggleSidebar()" title="折叠/展开">
          {{ ui.sidebarCollapsed ? '›' : '‹' }}
        </button>
      </div>

      <nav class="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        <RouterLink v-for="it in items" :key="it.to"
                    :to="`/worlds/${worldId}${it.to ? '/' + it.to : ''}`"
                    class="nav-item"
                    :class="{ 'is-active': isActive(it.to) }">
          <span class="w-4 text-center text-muted">{{ it.icon }}</span>
          <span v-if="!ui.sidebarCollapsed">{{ it.label }}</span>
        </RouterLink>
      </nav>

      <div v-if="!ui.sidebarCollapsed" class="px-3 py-2 border-t border-border text-xs text-muted">
        #{{ worldId }}
      </div>
    </aside>

    <!-- 主画布 -->
    <section class="flex-1 min-w-0 overflow-y-auto">
      <RouterView v-if="!err" />
      <div v-else class="p-10 text-muted">
        <p class="font-serif text-xl mb-2">未能载入世界</p>
        <p class="text-sm">{{ err }}</p>
      </div>
    </section>
  </div>
</template>
