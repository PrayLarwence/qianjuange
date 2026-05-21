<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { worldsApi } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const props = defineProps<{ worldId: string; worldName: string }>();

const router = useRouter();
const toast = useToastStore();
const confirmOpen = ref(false);
const deleting = ref(false);

async function doDelete() {
  deleting.value = true;
  try {
    await worldsApi.remove(props.worldId);
    toast.success('世界已删除');
    router.push('/');
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  } finally {
    deleting.value = false;
    confirmOpen.value = false;
  }
}
</script>

<template>
  <section class="mb-8 surface rounded p-5 border-l-2 !border-l-[#b04f33]">
    <h2 class="text-[#b04f33] text-xs uppercase tracking-wider mb-2">危险操作</h2>
    <p class="text-sm text-muted mb-4">删除这个世界后，所有分支、事件、角色和快照都会一并删除，无法恢复。</p>
    <button class="btn text-xs border border-[#b04f33]/40 text-[#b04f33] hover:bg-[#b04f33]/10"
            @click="confirmOpen = true">
      删除整个世界
    </button>

    <ConfirmDialog
      :open="confirmOpen"
      title="删除世界？"
      :message="`「${worldName}」会被永久删除，无法撤销。`"
      confirm-text="确认删除"
      danger
      @cancel="!deleting && (confirmOpen = false)"
      @confirm="doDelete" />
  </section>
</template>
