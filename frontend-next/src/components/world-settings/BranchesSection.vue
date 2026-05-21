<script setup lang="ts">
import { ref } from 'vue';
import { branchesApi, type BranchInfo, type WorldDetail } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const props = defineProps<{ world: WorldDetail; worldId: string; branches: BranchInfo[] }>();
const emit = defineEmits<{ (e: 'reload'): void }>();

const toast = useToastStore();
const renaming = ref<{ id: string; name: string; description: string } | null>(null);
const confirmDelete = ref<BranchInfo | null>(null);

async function switchBranch(id: string) {
  if (id === props.world.branch_id) return;
  try {
    await branchesApi.switch(props.worldId, id);
    toast.success('已切换分支');
    emit('reload');
  } catch (e: any) {
    toast.error(`切换失败：${e.message || e}`);
  }
}

async function commitRename() {
  if (!renaming.value) return;
  const { id, name, description } = renaming.value;
  try {
    await branchesApi.patch(id, { name: name.trim(), description });
    renaming.value = null;
    toast.success('已更新分支');
    emit('reload');
  } catch (e: any) {
    toast.error(`更新失败：${e.message || e}`);
  }
}

async function doDelete() {
  const b = confirmDelete.value;
  if (!b) return;
  try {
    await branchesApi.remove(b.id);
    toast.success('分支已删除');
    confirmDelete.value = null;
    emit('reload');
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  }
}
</script>

<template>
  <section class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">分支（{{ branches?.length || 0 }}）</h2>
      <span class="text-xs text-muted">从「推演」里探索不同走向时会产生新的分支</span>
    </header>
    <ul class="space-y-2">
      <li v-for="b in branches" :key="b.id"
          class="surface rounded p-4 flex items-center gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span v-if="b.is_active" class="text-xs px-1.5 py-0.5 rounded bg-accent text-white">活跃</span>
            <span class="font-medium truncate">{{ b.name }}</span>
            <span v-if="b.parent_branch_id" class="text-xs text-muted">分叉自 t{{ b.diverged_at_tick }}</span>
            <span v-else class="text-xs text-muted">主分支</span>
          </div>
          <div v-if="b.description" class="text-xs text-muted mt-0.5 truncate">{{ b.description }}</div>
          <div class="text-xs text-muted mt-1 font-mono">
            {{ b.event_count }} 事件 · {{ b.entity_count }} 实体 · 最大 t{{ b.max_tick }}
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button v-if="!b.is_active" class="btn btn-ghost text-xs" @click="switchBranch(b.id)">切换</button>
          <button class="btn btn-ghost text-xs"
                  @click="renaming = { id: b.id, name: b.name, description: b.description || '' }">
            重命名
          </button>
          <button v-if="b.parent_branch_id"
                  class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                  @click="confirmDelete = b">删除</button>
        </div>
      </li>
    </ul>

    <Teleport to="body">
      <div v-if="renaming"
           class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
           @click.self="renaming = null">
        <div class="surface rounded shadow-soft w-full max-w-md p-5 space-y-3">
          <h3 class="font-medium">重命名分支</h3>
          <label class="block">
            <span class="text-xs text-muted mb-1 block">名称</span>
            <input v-model="renaming.name" class="input" />
          </label>
          <label class="block">
            <span class="text-xs text-muted mb-1 block">说明</span>
            <textarea v-model="renaming.description" rows="3" class="input !h-auto py-2" />
          </label>
          <div class="flex justify-end gap-2 pt-2">
            <button class="btn btn-ghost text-xs" @click="renaming = null">取消</button>
            <button class="btn btn-accent text-xs" @click="commitRename">保存</button>
          </div>
        </div>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="confirmDelete !== null"
      title="删除分支？"
      :message="confirmDelete ? `「${confirmDelete.name}」上的 ${confirmDelete.event_count} 个事件会一并删除。` : ''"
      confirm-text="删除"
      danger
      @cancel="confirmDelete = null"
      @confirm="doDelete" />
  </section>
</template>
