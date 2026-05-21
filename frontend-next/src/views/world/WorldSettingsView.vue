<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  worldsApi, branchesApi, snapshotsApi, stylesApi,
  type WorldDetail, type BranchInfo, type SnapshotInfo, type WorldEntity,
  type StyleProfileSummary,
} from '@/services/api';
import BasicInfoSection from '@/components/world-settings/BasicInfoSection.vue';
import MaxTickSection from '@/components/world-settings/MaxTickSection.vue';
import StyleProfileSection from '@/components/world-settings/StyleProfileSection.vue';
import AgentPipelineSection from '@/components/world-settings/AgentPipelineSection.vue';
import BranchesSection from '@/components/world-settings/BranchesSection.vue';
import SnapshotsSection from '@/components/world-settings/SnapshotsSection.vue';
import ManuscriptExtractSection from '@/components/world-settings/ManuscriptExtractSection.vue';
import DangerZoneSection from '@/components/world-settings/DangerZoneSection.vue';

const route = useRoute();
const worldId = computed(() => route.params.id as string);

const world = ref<WorldDetail | null>(null);
const branches = ref<BranchInfo[]>([]);
const snapshots = ref<SnapshotInfo[]>([]);
const allEntities = ref<WorldEntity[]>([]);
const styleProfiles = ref<StyleProfileSummary[]>([]);
const loading = ref(true);
const err = ref('');

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const [snap, brs, hist, profiles] = await Promise.all([
      worldsApi.get(worldId.value),
      branchesApi.list(worldId.value),
      snapshotsApi.history(worldId.value).catch(() => ({ snapshots: [] as SnapshotInfo[], branch_id: '', current_tick: 0 })),
      stylesApi.list().catch(() => [] as StyleProfileSummary[]),
    ]);
    world.value = snap.world;
    allEntities.value = snap.entities || [];
    branches.value = brs;
    snapshots.value = hist.snapshots || [];
    styleProfiles.value = profiles;
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(worldId, load);

function onMaxTickUpdated(v: number) {
  if (world.value) world.value.max_tick = v;
}
function onTickChanged(v: number) {
  if (world.value) world.value.current_tick = v;
}
</script>

<template>
  <div class="px-8 py-10 max-w-4xl">
    <p class="text-muted text-xs uppercase tracking-wider mb-2">世界设置</p>
    <h1 class="font-serif text-4xl mb-8">{{ world?.name || '加载中…' }}</h1>

    <div v-if="err" class="text-muted text-sm mb-8">{{ err }}</div>

    <template v-if="world">
      <BasicInfoSection :world="world" :world-id="worldId" @reload="load" />
      <MaxTickSection :world="world" :world-id="worldId" @updated="onMaxTickUpdated" />
      <StyleProfileSection :world="world" :world-id="worldId" :profiles="styleProfiles" @reload="load" />
      <AgentPipelineSection :world="world" :world-id="worldId" />
      <BranchesSection :world="world" :world-id="worldId" :branches="branches" @reload="load" />
      <SnapshotsSection :world-id="worldId" :snapshots="snapshots" @reload="load" />
      <ManuscriptExtractSection :world-id="worldId" :entities="allEntities" @tick-changed="onTickChanged" />
      <DangerZoneSection :world-id="worldId" :world-name="world.name || ''" />
    </template>
  </div>
</template>
