<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  worldsApi, stylesApi,
  type WorldDetail, type StyleProfileSummary, type StyleProfileDetail,
} from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';

const props = defineProps<{
  world: WorldDetail;
  worldId: string;
  profiles: StyleProfileSummary[];
}>();
const emit = defineEmits<{ (e: 'reload'): void }>();

const toast = useToastStore();
const binding = ref(false);
const previewProfile = ref<StyleProfileDetail | null>(null);
const loadingPreview = ref(false);

const current = computed(() =>
  props.profiles.find(p => p.id === props.world.style_profile_id) || null,
);
const grouped = computed(() => {
  const builtin: StyleProfileSummary[] = [];
  const custom: StyleProfileSummary[] = [];
  for (const p of props.profiles) {
    (p.kind === 'custom' ? custom : builtin).push(p);
  }
  return { builtin, custom };
});

async function bind(id: string | null) {
  binding.value = true;
  try {
    await worldsApi.update(props.worldId, { style_profile_id: id || '' });
    toast.success(id ? '已绑定风格档案' : '已解除绑定');
    emit('reload');
  } catch (e: any) {
    toast.error(`绑定失败：${e.message || e}`);
  } finally {
    binding.value = false;
  }
}

async function openPreview(id: string) {
  loadingPreview.value = true;
  try {
    previewProfile.value = await stylesApi.get(id);
  } catch (e: any) {
    toast.error(`加载失败：${e.message || e}`);
  } finally {
    loadingPreview.value = false;
  }
}
</script>

<template>
  <section class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">写作风格</h2>
      <span class="text-xs text-muted">导出成稿时套用的语感模板</span>
    </header>

    <div class="surface rounded p-5 space-y-4">
      <div>
        <p class="text-xs text-muted mb-1">当前绑定</p>
        <div v-if="current" class="flex items-center gap-3">
          <span class="font-medium">{{ current.name }}</span>
          <span class="text-xs text-muted">{{ current.kind === 'custom' ? '自建' : '内置' }}</span>
          <span v-if="current.category" class="text-xs text-muted">· {{ current.category }}</span>
          <button class="btn btn-ghost text-xs ml-auto" @click="openPreview(current.id)">查看</button>
          <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                  :disabled="binding"
                  @click="bind(null)">解绑</button>
        </div>
        <p v-else class="text-sm text-muted">未绑定，导出时使用默认语感。</p>
      </div>

      <div v-if="profiles.length > 0" class="border-t border-border pt-4 space-y-3">
        <p class="text-xs text-muted">可选档案</p>
        <div v-if="grouped.builtin.length > 0" class="space-y-1">
          <p class="text-[10px] uppercase tracking-wider text-muted">内置</p>
          <ul class="space-y-1">
            <li v-for="p in grouped.builtin" :key="p.id"
                class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-sunken/50">
              <span class="flex-1 min-w-0">
                <span class="text-sm">{{ p.name }}</span>
                <span v-if="p.description" class="text-xs text-muted ml-2">{{ p.description }}</span>
              </span>
              <button class="btn btn-ghost text-xs" @click="openPreview(p.id)">预览</button>
              <button v-if="p.id !== world.style_profile_id"
                      class="btn btn-accent text-xs"
                      :disabled="binding"
                      @click="bind(p.id)">绑定</button>
              <span v-else class="text-xs text-accent px-2">✓ 已绑定</span>
            </li>
          </ul>
        </div>
        <div v-if="grouped.custom.length > 0" class="space-y-1">
          <p class="text-[10px] uppercase tracking-wider text-muted">自建</p>
          <ul class="space-y-1">
            <li v-for="p in grouped.custom" :key="p.id"
                class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-sunken/50">
              <span class="flex-1 min-w-0">
                <span class="text-sm">{{ p.name }}</span>
                <span v-if="p.description" class="text-xs text-muted ml-2">{{ p.description }}</span>
              </span>
              <button class="btn btn-ghost text-xs" @click="openPreview(p.id)">预览</button>
              <button v-if="p.id !== world.style_profile_id"
                      class="btn btn-accent text-xs"
                      :disabled="binding"
                      @click="bind(p.id)">绑定</button>
              <span v-else class="text-xs text-accent px-2">✓ 已绑定</span>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <Dialog v-if="previewProfile"
            :open="!!previewProfile"
            :title="previewProfile.name"
            width="640px"
            @close="previewProfile = null">
      <div class="space-y-4 max-h-[60vh] overflow-y-auto">
        <div v-if="previewProfile.description" class="text-sm text-muted">
          {{ previewProfile.description }}
        </div>
        <div>
          <p class="text-xs uppercase tracking-wider text-muted mb-2">spec</p>
          <pre class="surface rounded p-3 text-xs leading-relaxed font-mono whitespace-pre-wrap">{{ previewProfile.spec_text || '（空）' }}</pre>
        </div>
        <div v-if="previewProfile.sample_paragraphs?.length">
          <p class="text-xs uppercase tracking-wider text-muted mb-2">范文段落</p>
          <div class="space-y-2">
            <p v-for="(s, i) in previewProfile.sample_paragraphs" :key="i"
               class="surface rounded p-3 text-sm font-serif leading-relaxed whitespace-pre-wrap">{{ s }}</p>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="previewProfile = null">关闭</button>
        <button v-if="previewProfile.id !== world.style_profile_id"
                class="btn btn-accent"
                :disabled="binding"
                @click="bind(previewProfile.id); previewProfile = null">
          绑定到这个世界
        </button>
      </template>
    </Dialog>
  </section>
</template>
