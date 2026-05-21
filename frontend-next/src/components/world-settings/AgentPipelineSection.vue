<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import {
  agentPipelineApi,
  type PipelineConfig, type PipelineLimits,
  type CriticAgent, emptyCritic,
} from '@/services/agentApi';
import type { WorldDetail } from '@/services/api';
import { useToastStore } from '@/stores/toast';

const props = defineProps<{ world: WorldDetail; worldId: string }>();
const toast = useToastStore();

const loading = ref(true);
const saving = ref(false);
const inherited = ref(true); // 当前是否在继承全局 default
const cfg = ref<PipelineConfig | null>(null);
const limits = ref<PipelineLimits | null>(null);
const dirty = ref(false);

async function load() {
  loading.value = true;
  try {
    const [resp, lim] = await Promise.all([
      agentPipelineApi.getForWorld(props.worldId),
      agentPipelineApi.limits(),
    ]);
    cfg.value = resp.config;
    inherited.value = resp.inherited;
    limits.value = lim;
    dirty.value = false;
  } catch (e: any) {
    toast.error(`加载 agent 配置失败：${e.message || e}`);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(() => props.worldId, load);

function markDirty() { dirty.value = true; }

function addCritic() {
  if (!cfg.value || !limits.value) return;
  if (cfg.value.critics.length >= limits.value.max_critics) {
    toast.error(`最多 ${limits.value.max_critics} 个 critic`);
    return;
  }
  cfg.value.critics.push(emptyCritic());
  markDirty();
}

function removeCritic(i: number) {
  if (!cfg.value) return;
  cfg.value.critics.splice(i, 1);
  markDirty();
}

async function saveAsWorld(saveAsDefault = false) {
  if (!cfg.value) return;
  saving.value = true;
  try {
    const resp = await agentPipelineApi.setForWorld(props.worldId, {
      config: cfg.value,
      save_as_default: saveAsDefault,
    });
    inherited.value = false;
    cfg.value = resp.config;
    dirty.value = false;
    if (resp.default_save_error) {
      toast.error(`保存为全局默认失败：${resp.default_save_error}`);
    } else {
      toast.success(saveAsDefault ? '已保存（同时设为全局默认）' : '已保存到该世界');
    }
  } catch (e: any) {
    toast.error(`保存失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}

async function resetToInherited() {
  saving.value = true;
  try {
    const resp = await agentPipelineApi.setForWorld(props.worldId, { config: null });
    inherited.value = true;
    cfg.value = resp.config;
    dirty.value = false;
    toast.success('已重置为继承全局默认');
  } catch (e: any) {
    toast.error(`重置失败：${e.message || e}`);
  } finally {
    saving.value = false;
  }
}

const severityOptions: { value: CriticAgent['severity']; label: string; hint: string }[] = [
  { value: 'lenient', label: '宽松', hint: '只在严重问题时打 fail' },
  { value: 'normal',  label: '标准', hint: '中等问题就打 fail' },
  { value: 'strict',  label: '严格', hint: '高标准，明显瑕疵即 fail' },
];
</script>

<template>
  <section class="mb-12">
    <header class="flex items-baseline justify-between mb-3">
      <h2 class="text-muted text-xs uppercase tracking-wider">Agent 流水线</h2>
      <span class="text-xs text-muted">推演时由谁导演 / 落笔 / 审稿</span>
    </header>

    <div v-if="loading" class="surface rounded p-5 text-sm text-muted">加载中…</div>

    <div v-else-if="cfg && limits" class="surface rounded p-5 space-y-5">
      <!-- 状态条 -->
      <div class="flex items-center gap-3 text-xs">
        <span class="px-2 py-0.5 rounded"
              :class="inherited ? 'bg-sunken text-muted' : 'bg-accent/15 text-accent'">
          {{ inherited ? '继承全局默认' : '当前世界自定义' }}
        </span>
        <span v-if="dirty" class="text-[#b04f33]">● 未保存改动</span>
        <span class="ml-auto text-muted">
          上限：critic 最多 {{ limits.max_critics }}，重试最多 {{ limits.max_critic_retries }}
        </span>
      </div>

      <!-- Director（MVP：只配主 director；多 director 留 TODO 提示） -->
      <div>
        <p class="text-xs text-muted mb-2">Director（推动世界状态 + 工具调用）</p>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-muted col-span-3">名称</label>
          <input v-model="cfg.directors[0].name" @input="markDirty" class="input col-span-3" />
          <label class="text-xs text-muted">模型</label>
          <label class="text-xs text-muted">温度</label>
          <label class="text-xs text-muted">最大 hops</label>
          <input v-model="cfg.directors[0].model" @input="markDirty" placeholder="留空=用全局 LLM 设置" class="input" />
          <input type="number" step="0.1" min="0" max="2"
                 v-model.number="cfg.directors[0].temperature" @input="markDirty" class="input" />
          <input type="number" min="1" max="32"
                 v-model.number="cfg.directors[0].max_hops" @input="markDirty" class="input" />
        </div>
        <p v-if="cfg.directors.length > 1" class="text-[11px] text-muted mt-1">
          ⚠ 配置了 {{ cfg.directors.length }} 个 director，但当前实现只跑第一个（多 director 同时改世界状态会冲突）。
        </p>
      </div>

      <!-- Author（固定 1 个） -->
      <div class="border-t border-border pt-4">
        <p class="text-xs text-muted mb-2">Author（把粗稿改写为定稿）</p>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-muted col-span-3">名称</label>
          <input v-model="cfg.authors[0].name" @input="markDirty" class="input col-span-3" />
          <label class="text-xs text-muted col-span-2">模型</label>
          <label class="text-xs text-muted">温度</label>
          <input v-model="cfg.authors[0].model" @input="markDirty" placeholder="留空=用全局 LLM 设置" class="input col-span-2" />
          <input type="number" step="0.1" min="0" max="2"
                 v-model.number="cfg.authors[0].temperature" @input="markDirty" class="input" />
        </div>
      </div>

      <!-- Critics 数组 -->
      <div class="border-t border-border pt-4 space-y-3">
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted">Critics（审稿，fail 触发 author 重写）</p>
          <button class="btn btn-ghost text-xs" @click="addCritic"
                  :disabled="cfg.critics.length >= limits.max_critics">+ 添加</button>
        </div>

        <div v-if="cfg.critics.length === 0" class="text-xs text-muted">
          没有 critic，定稿直接通过（速度最快但无质量校验）。
        </div>

        <div v-for="(c, i) in cfg.critics" :key="i" class="surface rounded p-3 space-y-2 border border-border">
          <div class="flex items-center gap-2">
            <input v-model="c.name" @input="markDirty" placeholder="critic 名称（如：语感、人设、节奏）"
                   class="input flex-1 text-sm" />
            <button class="btn btn-ghost text-xs hover:!text-[#b04f33]"
                    @click="removeCritic(i)">移除</button>
          </div>
          <div>
            <label class="text-xs text-muted">关注点（focus）— 留空则整体把关</label>
            <textarea v-model="c.focus" @input="markDirty" rows="2"
                      placeholder="比如：人物语言是否符合身份、情节节奏是否拖沓"
                      class="input w-full text-sm"></textarea>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <div>
              <label class="text-xs text-muted">严格度</label>
              <select v-model="c.severity" @change="markDirty" class="input w-full text-sm">
                <option v-for="o in severityOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
            <div>
              <label class="text-xs text-muted">模型（留空=全局）</label>
              <input v-model="c.model" @input="markDirty" class="input w-full text-sm" />
            </div>
            <div>
              <label class="text-xs text-muted">温度</label>
              <input type="number" step="0.1" min="0" max="2"
                     v-model.number="c.temperature" @input="markDirty" class="input w-full text-sm" />
            </div>
          </div>
        </div>
      </div>

      <!-- 全局选项 -->
      <div class="border-t border-border pt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <label class="text-xs text-muted">Critic 模式</label>
          <select v-model="cfg.critic_mode" @change="markDirty" class="input w-full">
            <option value="parallel">并行（每轮所有 critic 全跑）</option>
            <option value="serial">串行（第一个 fail 即停）</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-muted">最多重试轮数（max_critic_retries）</label>
          <input type="number" min="0" :max="limits.max_critic_retries"
                 v-model.number="cfg.max_critic_retries" @input="markDirty" class="input w-full" />
        </div>
        <div>
          <label class="text-xs text-muted">每次推演最多 LLM 调用</label>
          <input type="number" min="1" :max="limits.max_llm_calls"
                 v-model.number="cfg.budget.max_llm_calls" @input="markDirty" class="input w-full" />
        </div>
        <div>
          <label class="text-xs text-muted">每次推演最大墙钟（秒）</label>
          <input type="number" min="10" :max="limits.max_wall_seconds"
                 v-model.number="cfg.budget.max_wall_seconds" @input="markDirty" class="input w-full" />
        </div>
      </div>

      <!-- 操作 -->
      <div class="border-t border-border pt-4 flex flex-wrap items-center gap-2">
        <button class="btn btn-accent" :disabled="saving || !dirty" @click="saveAsWorld(false)">
          保存到该世界
        </button>
        <button class="btn btn-ghost" :disabled="saving || !dirty" @click="saveAsWorld(true)">
          保存并设为全局默认
        </button>
        <button class="btn btn-ghost ml-auto hover:!text-[#b04f33]"
                :disabled="saving || inherited"
                @click="resetToInherited">
          重置为继承全局
        </button>
      </div>
    </div>
  </section>
</template>
