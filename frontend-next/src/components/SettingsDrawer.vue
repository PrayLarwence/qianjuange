<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useThemeStore, type ThemeMode } from '@/stores/theme';
import { useUiStore } from '@/stores/ui';
import { llmApi, type LLMConfig, type ProviderMeta, type ModelEntry } from '@/services/api';

const ui = useUiStore();
const theme = useThemeStore();
const tab = ref<'appearance' | 'llm' | 'shortcut' | 'data'>('appearance');

const modes: { value: ThemeMode; label: string; hint: string }[] = [
  { value: 'light',  label: '浅色',     hint: '日间，editorial 米底' },
  { value: 'dark',   label: '深色',     hint: '夜间，暖黑底' },
  { value: 'system', label: '跟随系统', hint: '随操作系统变化' },
];

// ─── LLM 状态 ───
const llmConfig = ref<LLMConfig | null>(null);
const llmMeta = ref<Record<string, ProviderMeta>>({});
const llmLoading = ref(false);
const llmError = ref('');
const testResult = ref<{ ok: boolean; reply?: string; error?: string; elapsed?: number } | null>(null);
const providerList = ref<string[]>([]);

// 编辑中的 provider
const editingProvider = ref<string>('');
const editModel = ref('');
const editKey = ref('');
const editUrl = ref('');

// 动态模型列表 (OpenRouter 等支持)
const fetchedModels = ref<ModelEntry[]>([]);
const fetchingModels = ref(false);
const fetchModelsError = ref('');
const showModelSuggestions = ref(false);

const supportsListing = computed(() => !!llmMeta.value[editingProvider.value]?.supports_listing);
const suggestedModels = computed(() => llmMeta.value[editingProvider.value]?.default_models || []);

const modelOptions = computed<ModelEntry[]>(() =>
  fetchedModels.value.length
    ? fetchedModels.value
    : suggestedModels.value.map(s => ({ id: s, name: s })),
);

const filteredModels = computed(() => {
  const q = editModel.value.trim().toLowerCase();
  if (!q) return modelOptions.value.slice(0, 50);
  return modelOptions.value
    .filter(m => m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q))
    .slice(0, 50);
});

function pickModel(id: string) {
  editModel.value = id;
  showModelSuggestions.value = false;
}

function blurModelInput() {
  setTimeout(() => (showModelSuggestions.value = false), 150);
}

async function loadLLM() {
  llmLoading.value = true;
  llmError.value = '';
  try {
    const [cfg, prov] = await Promise.all([
      llmApi.getConfig(),
      llmApi.providers(),
    ]);
    llmConfig.value = cfg.config;
    llmMeta.value = cfg.meta || {};
    providerList.value = prov.available;
    if (prov.current) startEdit(prov.current);
  } catch (e: any) {
    llmError.value = e.message || String(e);
  } finally {
    llmLoading.value = false;
  }
}

function startEdit(name: string) {
  editingProvider.value = name;
  const p = llmConfig.value?.providers?.[name];
  editModel.value = p?.model || '';
  editKey.value = p?.has_key ? '' : '';
  editUrl.value = p?.base_url || '';
}

async function saveProvider() {
  llmError.value = '';
  try {
    const body: any = { active: editingProvider.value, providers: {} };
    const p: any = {};
    if (editKey.value) p.api_key = editKey.value;
    if (editModel.value) p.model = editModel.value;
    if (editUrl.value) p.base_url = editUrl.value;
    if (Object.keys(p).length) body.providers[editingProvider.value] = p;
    await llmApi.setConfig(body);
    editKey.value = '';
    await loadLLM();
  } catch (e: any) {
    llmError.value = e.message || String(e);
  }
}

async function switchProvider(name: string) {
  await llmApi.setConfig({ active: name });
  startEdit(name);
  await loadLLM();
}

async function testProvider() {
  testResult.value = null;
  llmError.value = '';
  try {
    testResult.value = await llmApi.test(editingProvider.value);
  } catch (e: any) {
    testResult.value = { ok: false, error: e.message || String(e) };
  }
}

async function loadModelsList() {
  fetchModelsError.value = '';
  fetchingModels.value = true;
  try {
    const r = await llmApi.listModels(editingProvider.value);
    if (!r.ok) {
      fetchModelsError.value = r.error || '加载失败';
      fetchedModels.value = [];
    } else {
      fetchedModels.value = r.models;
    }
  } catch (e: any) {
    fetchModelsError.value = e.message || String(e);
  } finally {
    fetchingModels.value = false;
  }
}

watch(editingProvider, () => {
  fetchedModels.value = [];
  fetchModelsError.value = '';
});

// ─── metrics ───
const metrics = ref<any>(null);
async function loadMetrics() {
  try { metrics.value = await llmApi.metrics(); } catch {}
}
watch(() => tab.value, v => { if (v === 'data') loadMetrics(); });
onMounted(() => loadLLM());
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="ui.settingsOpen" class="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" @click="ui.closeSettings()" />
    </Transition>
    <Transition name="slide">
      <aside v-if="ui.settingsOpen"
             class="fixed right-0 top-0 bottom-0 w-[420px] z-50 bg-surface border-l border-border shadow-soft flex flex-col">
        <header class="h-12 px-4 flex items-center justify-between border-b border-border">
          <h2 class="text-sm font-medium tracking-wide">设置</h2>
          <button class="btn btn-ghost" @click="ui.closeSettings()">关闭</button>
        </header>

        <div class="px-4 py-3 flex gap-1 border-b border-border text-sm">
          <button v-for="t in [
                    {k:'appearance', l:'外观'},
                    {k:'llm',        l:'LLM'},
                    {k:'shortcut',   l:'快捷键'},
                    {k:'data',       l:'数据'},
                  ]" :key="t.k"
                  class="px-3 h-8 rounded transition-colors"
                  :class="tab === t.k ? 'bg-sunken text-text' : 'text-muted hover:text-text'"
                  @click="tab = t.k as any">
            {{ t.l }}
          </button>
        </div>

        <div class="flex-1 overflow-y-auto p-4 text-sm">
          <!-- 外观 -->
          <section v-if="tab === 'appearance'" class="space-y-5">
            <div>
              <h3 class="text-muted text-xs uppercase tracking-wider mb-2">主题</h3>
              <div class="grid grid-cols-3 gap-2">
                <button v-for="m in modes" :key="m.value"
                        class="surface rounded p-3 text-left transition-colors"
                        :class="theme.mode === m.value ? '!border-accent' : 'hover:bg-sunken'"
                        @click="theme.set(m.value)">
                  <div class="font-medium">{{ m.label }}</div>
                  <div class="text-xs text-muted mt-1">{{ m.hint }}</div>
                </button>
              </div>
            </div>
            <div class="text-xs text-muted">当前 <span class="text-text">{{ theme.resolved }}</span></div>
          </section>

          <!-- LLM -->
          <section v-else-if="tab === 'llm'" class="space-y-4">
            <div v-if="llmLoading" class="text-muted">加载中…</div>
            <div v-if="llmError" class="text-red-500 text-xs">{{ llmError }}</div>
            <template v-if="llmConfig">
              <!-- provider 选择 -->
              <div>
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">当前 Provider</h3>
                <select class="w-full h-9 px-2 rounded border border-border bg-transparent text-sm"
                        :value="llmConfig.active"
                        @change="switchProvider(($event.target as HTMLSelectElement).value)">
                  <option v-for="name in providerList" :key="name" :value="name">
                    {{ llmMeta[name]?.label || name }}
                  </option>
                </select>
              </div>

              <!-- 模型 -->
              <div>
                <label class="text-muted text-xs uppercase tracking-wider mb-1 block flex items-center justify-between">
                  <span>模型</span>
                  <button v-if="supportsListing"
                          class="text-[11px] text-accent hover:underline disabled:opacity-50"
                          :disabled="fetchingModels"
                          @click="loadModelsList">
                    {{ fetchingModels ? '加载中…' : (fetchedModels.length ? `刷新 (${fetchedModels.length})` : '加载可用模型') }}
                  </button>
                </label>
                <div class="relative">
                  <input v-model="editModel"
                         class="w-full h-9 px-2 rounded border border-border bg-transparent text-sm"
                         :placeholder="llmConfig.providers?.[editingProvider]?.model || ''"
                         @focus="showModelSuggestions = true"
                         @blur="blurModelInput" />
                  <div v-if="showModelSuggestions && filteredModels.length"
                       class="absolute left-0 right-0 mt-1 max-h-64 overflow-y-auto rounded border border-border bg-surface shadow-soft z-10">
                    <button v-for="m in filteredModels" :key="m.id"
                            type="button"
                            class="w-full text-left px-2 py-1.5 text-sm hover:bg-sunken transition-colors flex items-baseline justify-between gap-2"
                            @mousedown.prevent="pickModel(m.id)">
                      <span class="truncate">{{ m.id }}</span>
                      <span v-if="m.context_length" class="text-[10px] text-muted shrink-0">{{ (m.context_length / 1000).toFixed(0) }}k</span>
                    </button>
                  </div>
                </div>
                <div v-if="fetchModelsError" class="text-red-500 text-[11px] mt-1">{{ fetchModelsError }}</div>
                <div v-else-if="fetchedModels.length" class="text-[11px] text-muted mt-1">
                  共 {{ fetchedModels.length }} 个模型可选 · 输入框支持搜索
                </div>
              </div>

              <!-- API Key -->
              <div>
                <label class="text-muted text-xs uppercase tracking-wider mb-1 block">
                  API Key
                  <span v-if="llmConfig.providers?.[editingProvider]?.has_key" class="text-green-600">（已配置）</span>
                </label>
                <input v-model="editKey" type="password"
                       class="w-full h-9 px-2 rounded border border-border bg-transparent text-sm"
                       placeholder="粘贴新 Key（留空不修改）" />
              </div>

              <!-- Base URL (non-Ollama) -->
              <div v-if="editingProvider !== 'ollama'">
                <label class="text-muted text-xs uppercase tracking-wider mb-1 block">Base URL</label>
                <input v-model="editUrl" class="w-full h-9 px-2 rounded border border-border bg-transparent text-sm"
                       :placeholder="llmConfig.providers?.[editingProvider]?.base_url || ''" />
              </div>

              <!-- Actions -->
              <div class="flex gap-2">
                <button class="btn btn-ghost text-xs" @click="testProvider" :disabled="testResult?.ok === true">
                  {{ testResult?.ok ? '✓ 连接成功' : '测试连接' }}
                </button>
                <button class="btn btn-accent text-xs" @click="saveProvider">保存</button>
              </div>

              <!-- Test result -->
              <div v-if="testResult && !testResult.ok" class="text-red-500 text-xs break-all">
                {{ testResult.error }}
              </div>
              <div v-if="testResult?.ok" class="text-green-600 text-xs">
                连接成功 · {{ testResult.elapsed }}s · {{ testResult.reply }}
              </div>

              <!-- Homepage link -->
              <div v-if="llmMeta[editingProvider]?.homepage" class="text-xs text-muted">
                <a :href="llmMeta[editingProvider].homepage" target="_blank" class="underline">
                  ↗ {{ llmMeta[editingProvider].homepage }}
                </a>
              </div>
            </template>
          </section>

          <!-- 快捷键 -->
          <section v-else-if="tab === 'shortcut'" class="space-y-3">
            <ul class="space-y-1 text-sm">
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + K</kbd> 命令面板（待接）</li>
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + ,</kbd> 打开设置</li>
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + Shift + D</kbd> 切换主题</li>
            </ul>
          </section>

          <!-- 数据 -->
          <section v-else class="space-y-4">
            <div>
              <h3 class="text-muted text-xs uppercase tracking-wider mb-2">LLM 调用统计（24h）</h3>
              <div v-if="metrics?.summary" class="space-y-1">
                <div class="grid grid-cols-2 gap-1 text-xs">
                  <div class="text-muted">调用次数</div><div>{{ metrics.summary.total_calls }}</div>
                  <div class="text-muted">输入 token</div><div>{{ metrics.summary.total_tokens_in?.toLocaleString() }}</div>
                  <div class="text-muted">输出 token</div><div>{{ metrics.summary.total_tokens_out?.toLocaleString() }}</div>
                  <div class="text-muted">错误数</div><div :class="metrics.summary.errors ? 'text-red-500' : ''">{{ metrics.summary.errors }}</div>
                  <div class="text-muted">平均延迟</div><div>{{ metrics.summary.avg_latency_ms }}ms</div>
                </div>

                <div v-if="Object.keys(metrics.by_provider || {}).length" class="mt-3">
                  <h4 class="text-muted text-xs uppercase tracking-wider mb-1">按 Provider</h4>
                  <div v-for="(d, p) in metrics.by_provider" :key="p" class="flex justify-between text-xs py-1 border-t border-border/50">
                    <span>{{ p }}</span>
                    <span class="text-muted">{{ d.calls }} 次 · {{ ((d.tokens_in + d.tokens_out) || 0).toLocaleString() }} tokens</span>
                  </div>
                </div>
              </div>
              <div v-else class="text-xs text-muted">暂无调用记录</div>
            </div>
            <div class="pt-3 border-t border-border">
              <a href="/legacy/" class="btn btn-ghost text-xs">↗ 打开旧版（完整数据管理）</a>
            </div>
          </section>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.slide-enter-active, .slide-leave-active { transition: transform .2s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }
</style>
