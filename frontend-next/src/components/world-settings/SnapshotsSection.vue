<script setup lang="ts">
import { ref } from 'vue';
import { snapshotsApi, type SnapshotInfo } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const props = defineProps<{ worldId: string; snapshots: SnapshotInfo[] }>();
const emit = defineEmits<{ (e: 'reload'): void }>();

const toast = useToastStore();
const confirmDelete = ref<SnapshotInfo | null>(null);

async function restore(id: string) {
  try {
    const r = await snapshotsApi.restore(props.worldId, id);
    toast.success(`已回滚到 tick ${r.restored_tick}`);
    emit('reload');
  } catch (e: any) {
    toast.error(`回滚失败：${e.message || e}`);
  }
}

async function doDelete() {
  const s = confirmDelete.value;
  if (!s) return;
  try {
    await snapshotsApi.remove(s.id);
    toast.success('快照已删除');
    confirmDelete.value = null;
    emit('reload');
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  }
}

function fmtTime(s?: string | null): string {
  if (!s) return '';
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }); }
  catch { return s; }
}
</script>

<template>
  <section class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">快照（{{ snapshots.length }}）</h2>
      <span class="text-xs text-muted">每次推演前会自动建快照，可随时回滚</span>
    </header>
    <ul v-if="snapshots.length > 0" class="space-y-1.5">
      <li v-for="s in snapshots" :key="s.id"
          class="surface rounded px-4 py-2.5 flex items-center gap-3 text-sm">
        <span class="font-mono text-xs text-muted w-12 shrink-0">t{{ s.tick }}</span>
        <span class="flex-1 min-w-0 truncate">{{ s.label || '（未命名快照）' }}</span>
        <span class="text-xs text-muted hidden md:block">{{ fmtTime(s.created_at) }}</span>
        <span v-if="s.is_current" class="text-xs text-accent">当前</span>
        <button v-else class="btn btn-ghost text-xs" @click="restore(s.id)">回滚</button>
        <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                @click="confirmDelete = s">×</button>
      </li>
    </ul>
    <p v-else class="text-muted text-sm">还没有快照。</p>

    <ConfirmDialog
      :open="confirmDelete !== null"
      title="删除快照？"
      :message="confirmDelete ? `t${confirmDelete.tick} · ${confirmDelete.label || '未命名'}` : ''"
      confirm-text="删除"
      danger
      @cancel="confirmDelete = null"
      @confirm="doDelete" />
  </section>
</template>
