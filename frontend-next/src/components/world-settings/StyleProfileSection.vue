<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  worldsApi, stylesApi,
  type WorldDetail, type StyleProfileSummary, type StyleProfileDetail, type NegativeRule,
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
const editingProfile = ref<StyleProfileDetail | null>(null);
const editRules = ref<NegativeRule[]>([]);
const editSamples = ref<{ title: string; text: string }[]>([]);
const saving = ref(false);
const showNewRuleForm = ref(false);
const newRuleLabel = ref('');
const newRuleDesc = ref('');
const showNewSampleForm = ref(false);
const newSampleTitle = ref('');
const newSampleText = ref('');
const editorTab = ref<'rules' | 'samples'>('rules');

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

async function deriveCustom(sourceId: string) {
  try {
    const result = await stylesApi.create({
      source_id: sourceId,
      name: '',
      world_id: props.worldId,
    });
    await bind(result.id);
    toast.success('已创建自定义副本并绑定');
    emit('reload');
  } catch (e: any) {
    toast.error(`创建失败：${e.message || e}`);
  }
}

async function openEditor(id: string) {
  loadingPreview.value = true;
  try {
    const detail = await stylesApi.get(id);
    editingProfile.value = detail;
    editRules.value = (detail.negative_rules || []).map(r => ({ ...r }));
    editSamples.value = (detail.sample_paragraphs || []).map((s: any) =>
      typeof s === 'string' ? { title: '', text: s } : { title: s.title || '', text: s.text || '' },
    );
    editorTab.value = 'rules';
  } catch (e: any) {
    toast.error(`加载失败：${e.message || e}`);
  } finally {
    loadingPreview.value = false;
  }
}

function toggleRule(index: number) {
  editRules.value[index].enabled = !editRules.value[index].enabled;
}

function removeRule(index: number) {
  editRules.value.splice(index, 1);
}

function addRule() {
  if (!newRuleLabel.value.trim() || !newRuleDesc.value.trim()) return;
  editRules.value.push({
    label: newRuleLabel.value.trim(),
    description: newRuleDesc.value.trim(),
    enabled: true,
  });
  newRuleLabel.value = '';
  newRuleDesc.value = '';
  showNewRuleForm.value = false;
}

function removeSample(index: number) {
  editSamples.value.splice(index, 1);
}

function addSample() {
  if (!newSampleText.value.trim()) return;
  editSamples.value.push({
    title: newSampleTitle.value.trim(),
    text: newSampleText.value.trim(),
  });
  newSampleTitle.value = '';
  newSampleText.value = '';
  showNewSampleForm.value = false;
}

async function saveRules() {
  if (!editingProfile.value) return;
  saving.value = true;
  try {
    await stylesApi.update(editingProfile.value.id, {
      negative_rules: editRules.value,
      sample_paragraphs: editSamples.value,
    });
    toast.success('已保存');
    editingProfile.value = null;
    emit('reload');
  } catch (e: any) {
    toast.error(`保存失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}

async function resetToDefault() {
  if (!editingProfile.value) return;
  saving.value = true;
  try {
    await stylesApi.reset(editingProfile.value.id);
    const refreshed = await stylesApi.get(editingProfile.value.id);
    editingProfile.value = refreshed;
    editRules.value = (refreshed.negative_rules || []).map(r => ({ ...r }));
    editSamples.value = (refreshed.sample_paragraphs || []).map((s: any) =>
      typeof s === 'string' ? { title: '', text: s } : { title: s.title || '', text: s.text || '' },
    );
    toast.success('已恢复为官方预设');
  } catch (e: any) {
    toast.error(`恢复失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}

async function deleteCustom(id: string) {
  try {
    await stylesApi.delete(id);
    toast.success('已删除');
    emit('reload');
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
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
      <!-- 当前绑定 -->
      <div>
        <p class="text-xs text-muted mb-1">当前绑定</p>
        <div v-if="current" class="flex items-center gap-3">
          <span class="font-medium">{{ current.name }}</span>
          <span class="text-xs text-muted">{{ current.kind === 'custom' ? '自建' : '内置' }}</span>
          <span v-if="current.category" class="text-xs text-muted">· {{ current.category }}</span>
          <button class="btn btn-ghost text-xs ml-auto" @click="openPreview(current.id)">查看</button>
          <button v-if="current.kind === 'custom'"
                  class="btn btn-accent text-xs" @click="openEditor(current.id)">编辑规则</button>
          <button v-else
                  class="btn btn-accent text-xs" @click="deriveCustom(current.id)">自定义</button>
          <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                  :disabled="binding"
                  @click="bind(null)">解绑</button>
        </div>
        <p v-else class="text-sm text-muted">未绑定，导出时使用默认语感。</p>
      </div>

      <!-- 可选档案列表 -->
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
              <span v-else class="text-xs text-accent px-2">已绑定</span>
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
              <button class="btn btn-ghost text-xs" @click="openEditor(p.id)">编辑</button>
              <button v-if="p.id !== world.style_profile_id"
                      class="btn btn-accent text-xs"
                      :disabled="binding"
                      @click="bind(p.id)">绑定</button>
              <span v-else class="text-xs text-accent px-2">已绑定</span>
              <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                      @click="deleteCustom(p.id)">删除</button>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 预览弹窗 -->
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
        <div v-if="previewProfile.negative_rules?.length">
          <p class="text-xs uppercase tracking-wider text-muted mb-2">反提示词规则</p>
          <ul class="space-y-1">
            <li v-for="(r, i) in previewProfile.negative_rules" :key="i"
                class="text-sm px-2 py-1 rounded"
                :class="r.enabled ? 'opacity-100' : 'opacity-40 line-through'">
              <span class="font-medium">{{ r.label }}</span>
              <span class="text-muted ml-2">{{ r.description }}</span>
            </li>
          </ul>
        </div>
        <div v-if="previewProfile.sample_paragraphs?.length">
          <p class="text-xs uppercase tracking-wider text-muted mb-2">范文段落</p>
          <div class="space-y-2">
            <p v-for="(s, i) in previewProfile.sample_paragraphs" :key="i"
               class="surface rounded p-3 text-sm font-serif leading-relaxed whitespace-pre-wrap">{{ typeof s === 'string' ? s : s.text }}</p>
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

    <!-- 编辑弹窗 -->
    <Dialog v-if="editingProfile"
            :open="!!editingProfile"
            :title="`编辑 · ${editingProfile.name}`"
            width="680px"
            @close="editingProfile = null">
      <div class="space-y-4 max-h-[60vh] overflow-y-auto">
        <!-- Tab 切换 -->
        <div class="flex gap-4 border-b border-border pb-2">
          <button class="text-sm pb-1"
                  :class="editorTab === 'rules' ? 'text-accent border-b-2 border-accent font-medium' : 'text-muted'"
                  @click="editorTab = 'rules'">反提示词规则</button>
          <button class="text-sm pb-1"
                  :class="editorTab === 'samples' ? 'text-accent border-b-2 border-accent font-medium' : 'text-muted'"
                  @click="editorTab = 'samples'">风格范文</button>
        </div>

        <!-- 规则 Tab -->
        <template v-if="editorTab === 'rules'">
          <p class="text-xs text-muted">
            开关控制该规则是否生效。关闭的规则不会注入到 Author 提示词中。
          </p>

          <ul class="space-y-2">
            <li v-for="(rule, i) in editRules" :key="i"
                class="flex items-start gap-3 px-3 py-2 rounded border border-border">
              <button class="mt-0.5 w-5 h-5 rounded border flex items-center justify-center shrink-0"
                      :class="rule.enabled ? 'bg-accent border-accent text-white' : 'border-border'"
                      @click="toggleRule(i)">
                <span v-if="rule.enabled" class="text-xs">&#10003;</span>
              </button>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium" :class="{ 'opacity-40': !rule.enabled }">{{ rule.label }}</p>
                <p class="text-xs text-muted mt-0.5" :class="{ 'opacity-40': !rule.enabled }">{{ rule.description }}</p>
              </div>
              <button class="text-xs text-muted hover:text-[#b04f33] shrink-0"
                      @click="removeRule(i)">移除</button>
            </li>
          </ul>

          <div v-if="!showNewRuleForm" class="pt-2">
            <button class="btn btn-ghost text-xs" @click="showNewRuleForm = true">+ 添加自定义规则</button>
          </div>
          <div v-else class="border border-border rounded p-3 space-y-2">
            <input v-model="newRuleLabel"
                   class="input w-full text-sm"
                   placeholder="规则名称（如：禁止感叹号）" />
            <textarea v-model="newRuleDesc"
                      class="input w-full text-sm h-16 resize-none"
                      placeholder="详细描述（如：禁止在叙述中使用感叹号，对白中可以）"></textarea>
            <div class="flex gap-2">
              <button class="btn btn-accent text-xs" @click="addRule">添加</button>
              <button class="btn btn-ghost text-xs" @click="showNewRuleForm = false">取消</button>
            </div>
          </div>
        </template>

        <!-- 范文 Tab -->
        <template v-if="editorTab === 'samples'">
          <p class="text-xs text-muted">
            粘贴你喜欢的小说片段作为风格锚定范文。建议总量 1000-2000 字，来源于真实作品效果最佳。
          </p>

          <ul class="space-y-3">
            <li v-for="(sample, i) in editSamples" :key="i"
                class="border border-border rounded p-3">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs font-medium text-muted">{{ sample.title || `片段 ${i + 1}` }}</span>
                <button class="text-xs text-muted hover:text-[#b04f33]"
                        @click="removeSample(i)">移除</button>
              </div>
              <p class="text-sm font-serif leading-relaxed whitespace-pre-wrap max-h-32 overflow-y-auto">{{ sample.text }}</p>
            </li>
          </ul>

          <p class="text-xs text-muted text-right">
            当前总字数：{{ editSamples.reduce((sum, s) => sum + s.text.length, 0) }} 字
          </p>

          <div v-if="!showNewSampleForm" class="pt-2">
            <button class="btn btn-ghost text-xs" @click="showNewSampleForm = true">+ 粘贴新范文</button>
          </div>
          <div v-else class="border border-border rounded p-3 space-y-2">
            <input v-model="newSampleTitle"
                   class="input w-full text-sm"
                   placeholder="来源标注（如：余华《活着》第三章）" />
            <textarea v-model="newSampleText"
                      class="input w-full text-sm h-40 resize-y font-serif"
                      placeholder="粘贴小说原文片段……"></textarea>
            <div class="flex gap-2">
              <button class="btn btn-accent text-xs" @click="addSample">添加</button>
              <button class="btn btn-ghost text-xs" @click="showNewSampleForm = false">取消</button>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <button v-if="editingProfile.builtin_source_id"
                class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                :disabled="saving"
                @click="resetToDefault">恢复官方预设</button>
        <span class="flex-1"></span>
        <button class="btn btn-ghost" @click="editingProfile = null">取消</button>
        <button class="btn btn-accent" :disabled="saving" @click="saveRules">保存</button>
      </template>
    </Dialog>
  </section>
</template>
