<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { worldsApi, type WorldDetail } from '@/services/api';
import { useToastStore } from '@/stores/toast';

const props = defineProps<{ world: WorldDetail; worldId: string }>();
const emit = defineEmits<{ (e: 'reload'): void }>();

const toast = useToastStore();
const draft = ref({
  name: props.world.name || '',
  description: props.world.description || '',
  outline: props.world.outline || '',
});
const saving = ref(false);

watch(() => props.world, w => {
  draft.value = {
    name: w.name || '',
    description: w.description || '',
    outline: w.outline || '',
  };
}, { deep: true });

const dirty = computed(() => (
  draft.value.name !== (props.world.name || '') ||
  draft.value.description !== (props.world.description || '') ||
  draft.value.outline !== (props.world.outline || '')
));

async function save() {
  if (!dirty.value) return;
  saving.value = true;
  try {
    await worldsApi.update(props.worldId, {
      name: draft.value.name.trim() || props.world.name,
      description: draft.value.description,
      outline: draft.value.outline,
    });
    toast.success('已保存');
    emit('reload');
  } catch (e: any) {
    toast.error(`保存失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}

function revert() {
  draft.value = {
    name: props.world.name || '',
    description: props.world.description || '',
    outline: props.world.outline || '',
  };
}
</script>

<template>
  <section class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">基础信息</h2>
      <div v-if="dirty" class="flex items-center gap-2">
        <button class="btn btn-ghost text-xs" @click="revert">撤回</button>
        <button class="btn btn-accent text-xs" :disabled="saving" @click="save">
          {{ saving ? '保存…' : '保存修改' }}
        </button>
      </div>
    </header>
    <div class="space-y-4">
      <label class="block">
        <span class="text-xs text-muted mb-1 block">名称</span>
        <input v-model="draft.name" class="input" />
      </label>
      <label class="block">
        <span class="text-xs text-muted mb-1 block">描述（一句话）</span>
        <input v-model="draft.description" class="input" placeholder="一两句话告诉自己这是什么世界" />
      </label>
      <label class="block">
        <span class="text-xs text-muted mb-1 block">大纲（在推演时作为长程目标）</span>
        <textarea v-model="draft.outline" rows="6" class="input !h-auto py-2 font-serif leading-relaxed"
                  placeholder="可以是几行设定，或者一段类似剧情梗概的东西" />
      </label>
    </div>
  </section>
</template>
