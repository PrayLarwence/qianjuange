<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { worldsApi, type WorldDetail } from '@/services/api';
import { useToastStore } from '@/stores/toast';

const props = defineProps<{ world: WorldDetail; worldId: string }>();
const emit = defineEmits<{ (e: 'updated', maxTick: number): void }>();

const toast = useToastStore();
const draft = ref<number>(props.world.max_tick ?? 0);
const saving = ref(false);

watch(() => props.world.max_tick, v => { draft.value = v ?? 0; });

const dirty = computed(() => Number(draft.value) !== (props.world.max_tick ?? 0));

async function save() {
  if (!dirty.value) return;
  saving.value = true;
  try {
    const v = Math.max(0, Math.floor(Number(draft.value) || 0));
    const r = await worldsApi.setMaxTick(props.worldId, v);
    toast.success(r.max_tick > 0 ? `上限已设为 ${r.max_tick}` : '已解除上限');
    draft.value = r.max_tick;
    emit('updated', r.max_tick);
  } catch (e: any) {
    toast.error(`设置失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="mb-12">
    <h2 class="text-muted text-xs uppercase tracking-wider mb-3">推演上限</h2>
    <div class="surface rounded p-5">
      <div class="flex items-baseline gap-3 mb-2">
        <span class="text-sm">当前 tick</span>
        <span class="font-mono text-2xl">{{ world.current_tick ?? 0 }}</span>
        <span class="text-muted text-xs">/ {{ world.max_tick && world.max_tick > 0 ? world.max_tick : '无上限' }}</span>
      </div>
      <div class="flex items-center gap-2 mt-4">
        <input v-model.number="draft" type="number" min="0" class="input !w-32" />
        <button class="btn text-xs border border-border"
                :disabled="!dirty || saving"
                @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <span class="text-xs text-muted">设 0 表示无上限</span>
      </div>
    </div>
  </section>
</template>
