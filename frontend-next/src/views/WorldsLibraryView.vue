<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { worldsApi, jobsApi, type WorldSummary, type JobStatus } from '@/services/api';
import { useToastStore } from '@/stores/toast';
import Dialog from '@/components/Dialog.vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

const router = useRouter();
const toast = useToastStore();

const worlds = ref<WorldSummary[]>([]);
const loading = ref(true);
const err = ref('');

async function load() {
  loading.value = true;
  err.value = '';
  try {
    worlds.value = await worldsApi.list();
  } catch (e: any) {
    err.value = e.message || String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

onBeforeUnmount(() => {
  if (importJobTimer) clearInterval(importJobTimer);
});

// 新建
const createOpen = ref(false);
const draft = ref({ name: '', description: '' });
const creating = ref(false);
function openCreate() {
  draft.value = { name: '', description: '' };
  createOpen.value = true;
}
async function submitCreate() {
  if (!draft.value.name.trim()) { toast.error('请填写世界名称'); return; }
  creating.value = true;
  try {
    const r = await worldsApi.create({
      name: draft.value.name.trim(),
      description: draft.value.description.trim(),
    });
    toast.success(`已创建：${draft.value.name.trim()}`);
    createOpen.value = false;
    await load();
    router.push(`/worlds/${r.id}`);
  } catch (e: any) {
    toast.error(`创建失败：${e.message || e}`);
  } finally {
    creating.value = false;
  }
}

// JSON 导入（已导出的存档）
const jsonFileInput = ref<HTMLInputElement | null>(null);
const jsonImporting = ref(false);
function pickJson() {
  jsonFileInput.value?.click();
}
async function onJsonPicked(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const f = input.files?.[0];
  input.value = '';
  if (!f) return;
  jsonImporting.value = true;
  try {
    const txt = await f.text();
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(txt);
    } catch (e: any) {
      toast.error('文件不是合法 JSON');
      return;
    }
    const r = await worldsApi.importJson(payload);
    toast.success('已导入');
    await load();
    router.push(`/worlds/${r.world_id}`);
  } catch (e: any) {
    toast.error(`导入失败：${e.message || e}`);
  } finally {
    jsonImporting.value = false;
  }
}

// 从手稿建世界
const manuscriptOpen = ref(false);
const manuscriptDraft = ref<{ name: string; description: string; text: string; _bigText?: string; _fileSize?: number }>({ name: '', description: '', text: '' });
const manuscriptBusy = ref(false);
const manuscriptResult = ref<{
  ok: boolean; world_id: string;
  stats: { chunks: number; outline: number; cast: number; locations: number; factions: number };
  warnings: string[];
} | null>(null);
// 异步导入进度
const importJobId = ref<string | null>(null);
const importJobStatus = ref<string>('');
const importJobMsg = ref<string>('');
let importJobTimer: number | null = null;

function watchImportJob(jobId: string) {
  importJobId.value = jobId;
  importJobStatus.value = 'running';
  importJobMsg.value = '正在启动…';
  if (importJobTimer) clearInterval(importJobTimer);
  importJobTimer = window.setInterval(async () => {
    try {
      const j = await jobsApi.get(jobId);
      importJobStatus.value = j.status;
      importJobMsg.value = j.progress_message || '';
      if (j.status === 'completed') {
        clearInterval(importJobTimer!);
        importJobTimer = null;
        toast.success(`导入完成！${j.result?.stats?.chapters || j.result?.stats?.chunks || '?'} 章`);
        importJobId.value = null;
        await load();
      } else if (j.status === 'error' || (j as any).status === 'failed') {
        clearInterval(importJobTimer!);
        importJobTimer = null;
        toast.error(`导入失败：${j.progress_message || j.error || '未知错误'}`);
        importJobId.value = null;
      }
    } catch { /* polling error, ignore */ }
  }, 2000);
}
const manuscriptCharCount = computed(() => {
  if (manuscriptDraft.value._fileSize) return `${(manuscriptDraft.value._fileSize / 1024 / 1024).toFixed(1)} MB`;
  return `${manuscriptDraft.value.text.length.toLocaleString()} 字`;
});

function openManuscript() {
  manuscriptDraft.value = { name: '', description: '', text: '' };
  manuscriptResult.value = null;
  manuscriptOpen.value = true;
}
async function onManuscriptFile(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const f = input.files?.[0];
  input.value = '';
  if (!f) return;
  if (f.size > 50 * 1024 * 1024) {
    toast.error('文件超过 50MB，请分割后再试');
    return;
  }
  try {
    manuscriptDraft.value.text = '';
    if (f.size > 512 * 1024) {
      manuscriptDraft.value._bigText = await f.text();
      manuscriptDraft.value._fileSize = f.size;
    } else {
      manuscriptDraft.value.text = await f.text();
    }
    if (!manuscriptDraft.value.name.trim()) {
      manuscriptDraft.value.name = f.name.replace(/\.(txt|md|markdown|html?|htm)$/i, '');
    }
  } catch (e: any) {
    toast.error(`读取失败：${e.message || e}`);
  }
}
async function submitManuscript() {
  const name = manuscriptDraft.value.name.trim();
  const text = manuscriptDraft.value.text || manuscriptDraft.value._bigText || '';
  if (!name) { toast.error('请填写世界名称'); return; }
  if (text.length < 50) { toast.error('手稿内容太短，至少 50 字'); return; }
  manuscriptBusy.value = true;
  try {
    if (text.length > 100_000) {
      const r = await worldsApi.fromManuscriptAsync({
        name, text, description: manuscriptDraft.value.description.trim() || undefined,
      });
      watchImportJob(r.job_id);
      manuscriptOpen.value = false;
    } else {
      const r = await worldsApi.fromManuscript({
        name, text, description: manuscriptDraft.value.description.trim() || undefined,
      });
      manuscriptResult.value = r;
      if (r.warnings?.length) toast.error(r.warnings[0]);
      else toast.success('已从手稿建世界');
    }
    await load();
  } catch (e: any) {
    toast.error(`导入失败：${e.message || e}`);
  } finally {
    manuscriptBusy.value = false;
  }
}
function gotoNewWorld() {
  if (!manuscriptResult.value) return;
  const id = manuscriptResult.value.world_id;
  manuscriptOpen.value = false;
  router.push(`/worlds/${id}`);
}

// 删除
const confirmOpen = ref(false);
const target = ref<WorldSummary | null>(null);
const deleting = ref(false);
function askDelete(w: WorldSummary, ev: Event) {
  ev.stopPropagation();
  target.value = w;
  confirmOpen.value = true;
}
async function doDelete() {
  if (!target.value) return;
  deleting.value = true;
  try {
    await worldsApi.remove(target.value.id);
    toast.success(`已删除：${target.value.name}`);
    confirmOpen.value = false;
    target.value = null;
    await load();
  } catch (e: any) {
    toast.error(`删除失败：${e.message || e}`);
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <section class="max-w-6xl mx-auto px-6 py-10">
    <header class="flex items-end justify-between mb-8 gap-4 flex-wrap">
      <div>
        <p class="text-muted text-xs uppercase tracking-wider mb-1">世界库</p>
        <h1 class="font-serif text-3xl">所有世界</h1>
      </div>
      <div class="flex items-center gap-2">
        <input ref="jsonFileInput" type="file"
               class="hidden" @change="onJsonPicked" />
        <button class="btn btn-ghost" :disabled="jsonImporting" @click="pickJson">
          {{ jsonImporting ? '恢复中…' : '⬆ 恢复 JSON 备份' }}
        </button>
        <button class="btn btn-accent" @click="openManuscript">📖 从手稿建</button>
        <button class="btn btn-ghost" @click="openCreate">+ 新建空白世界</button>
      </div>
    </header>

    <div v-if="loading" class="text-muted">加载中…</div>
    <div v-else-if="err" class="text-muted">无法加载：{{ err }}</div>
    <div v-else-if="worlds.length === 0" class="surface rounded p-10 text-center">
      <p class="font-serif text-xl mb-2">还没有世界</p>
      <p class="text-muted text-sm mb-5">从空白开始，或者把已有的小说丢进来续写。</p>
      <div class="flex items-center justify-center gap-2">
        <button class="btn btn-accent" @click="openCreate">+ 新建第一个世界</button>
        <button class="btn btn-ghost" @click="openManuscript">📖 从手稿建</button>
      </div>
    </div>

    <!-- 异步导入进度条 -->
    <div v-if="importJobId" class="mb-4 p-3 rounded border border-accent/30 bg-accent/5">
      <div class="flex items-center gap-2 text-sm">
        <span class="inline-block w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin"></span>
        <span class="font-medium">后台导入中</span>
        <span class="text-muted text-xs ml-auto">{{ importJobMsg }}</span>
      </div>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="w in worlds" :key="w.id"
           class="surface rounded p-5 transition-shadow hover:shadow-soft cursor-pointer relative group"
           @click="router.push(`/worlds/${w.id}`)">
        <button class="absolute top-3 right-3 btn btn-ghost !h-7 !px-2 opacity-0 group-hover:opacity-100 transition-opacity hover:!text-red-500"
                title="删除世界" @click="askDelete(w, $event)">
          删除
        </button>
        <h3 class="font-serif text-xl mb-2 pr-12">{{ w.name }}</h3>
        <p class="text-sm text-muted line-clamp-3 min-h-[3.5rem]">
          {{ w.description || '（暂无描述）' }}
        </p>
        <div class="mt-4 text-xs text-muted flex items-center gap-3">
          <span>#{{ w.id.slice(-6) }}</span>
          <span v-if="w.current_tick !== undefined">tick {{ w.current_tick }}</span>
        </div>
      </div>
    </div>

    <!-- 新建 -->
    <Dialog :open="createOpen" title="新建世界" width="480px" @close="!creating && (createOpen = false)">
      <form class="space-y-4" @submit.prevent="submitCreate">
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">名称</span>
          <input v-model="draft.name" class="input" placeholder="例如：第二纪元的港口城市" autofocus />
        </label>
        <label class="block">
          <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">描述（可选）</span>
          <textarea v-model="draft.description" rows="4" class="input !h-auto py-2 leading-relaxed"
                    placeholder="一两句话写下世界基调与你想推演的核心冲突"></textarea>
        </label>
      </form>
      <template #footer>
        <button class="btn btn-ghost" :disabled="creating" @click="createOpen = false">取消</button>
        <button class="btn btn-accent" :disabled="creating" @click="submitCreate">
          <span v-if="creating">创建中…</span><span v-else>创建</span>
        </button>
      </template>
    </Dialog>

    <!-- 从手稿建 -->
    <Dialog :open="manuscriptOpen" title="从手稿建世界" width="720px"
            @close="!manuscriptBusy && (manuscriptOpen = false)">
      <div v-if="!manuscriptResult" class="space-y-4">
        <p class="text-sm text-muted leading-relaxed">
          粘贴或上传 .txt / .md 小说原稿。系统会按章节切分，调用 LLM 抽出大纲、主要角色、地点、势力，
          建一个新世界让你接着推演。<span class="text-text">不会写入事件 / 时间轴</span>，只搭骨架。
        </p>

        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">世界名称</span>
            <input v-model="manuscriptDraft.name" class="input" placeholder="作品名 / 续写名" />
          </label>
          <label class="block">
            <span class="block text-xs uppercase tracking-wider text-muted mb-1.5">补充描述（可选）</span>
            <input v-model="manuscriptDraft.description" class="input"
                   placeholder="留空将用 LLM 抽到的世界设定" />
          </label>
        </div>

        <div>
          <div class="flex items-baseline justify-between mb-1.5">
            <span class="text-xs uppercase tracking-wider text-muted">原稿正文</span>
            <div class="flex items-center gap-2">
              <label class="btn btn-ghost text-xs cursor-pointer">
                ⬆ 上传文本文件
                <input type="file"
                       class="hidden" @change="onManuscriptFile" />
              </label>
              <span class="text-xs text-muted font-mono">
                {{ manuscriptCharCount }}
              </span>
            </div>
          </div>
          <textarea v-if="!manuscriptDraft._bigText" v-model="manuscriptDraft.text" rows="14"
                    class="input !h-auto py-2 font-serif leading-relaxed text-sm"
                    placeholder="把你的小说粘进来，或者点上面的按钮选文件。建议有「第N章」「Chapter N」「## 标题」之类的分章。" />
          <div v-else class="h-40 flex items-center justify-center surface rounded text-sm text-muted">
            📄 已加载 {{ manuscriptDraft._fileSize ? (manuscriptDraft._fileSize / 1024 / 1024).toFixed(1) : '?' }} MB 文本，
            提交后将走后台异步导入
          </div>
          <p class="text-xs text-muted mt-1.5">
            原文超过 10 万字时自动走后台异步导入，不阻塞页面。LLM 分析通常需要 30-120 秒。
          </p>
        </div>
      </div>

      <div v-else class="space-y-4">
        <p class="font-serif text-xl">已从手稿建世界 ✓</p>
        <div class="grid grid-cols-5 gap-3 text-center">
          <div class="surface rounded p-3">
            <p class="font-serif text-2xl">{{ manuscriptResult.stats.chunks }}</p>
            <p class="text-xs text-muted mt-0.5">章节</p>
          </div>
          <div class="surface rounded p-3">
            <p class="font-serif text-2xl">{{ manuscriptResult.stats.outline }}</p>
            <p class="text-xs text-muted mt-0.5">大纲条目</p>
          </div>
          <div class="surface rounded p-3">
            <p class="font-serif text-2xl">{{ manuscriptResult.stats.cast }}</p>
            <p class="text-xs text-muted mt-0.5">角色</p>
          </div>
          <div class="surface rounded p-3">
            <p class="font-serif text-2xl">{{ manuscriptResult.stats.locations }}</p>
            <p class="text-xs text-muted mt-0.5">地点</p>
          </div>
          <div class="surface rounded p-3">
            <p class="font-serif text-2xl">{{ manuscriptResult.stats.factions }}</p>
            <p class="text-xs text-muted mt-0.5">势力</p>
          </div>
        </div>
        <div v-if="manuscriptResult.warnings?.length"
             class="surface rounded p-3 border border-[#bb9856]/30 bg-[#bb9856]/10">
          <p class="text-xs uppercase tracking-wider text-[#bb9856] mb-1">注意</p>
          <ul class="text-sm space-y-1">
            <li v-for="(w, i) in manuscriptResult.warnings" :key="i">· {{ w }}</li>
          </ul>
        </div>
        <p class="text-sm text-muted">
          可以进世界检查抽出来的角色、大纲，调整后再继续推演 / 续写。
        </p>
      </div>

      <template #footer>
        <button v-if="!manuscriptResult" class="btn btn-ghost"
                :disabled="manuscriptBusy" @click="manuscriptOpen = false">取消</button>
        <button v-if="!manuscriptResult" class="btn btn-accent"
                :disabled="manuscriptBusy" @click="submitManuscript">
          <span v-if="manuscriptBusy">分析中… 请稍候</span>
          <span v-else>开始分析</span>
        </button>
        <template v-else>
          <button class="btn btn-ghost" @click="manuscriptOpen = false">留在这里</button>
          <button class="btn btn-accent" @click="gotoNewWorld">进入新世界 →</button>
        </template>
      </template>
    </Dialog>

    <!-- 删除确认 -->
    <ConfirmDialog
      :open="confirmOpen"
      :busy="deleting"
      title="删除世界"
      :confirm-text="'永久删除'"
      danger
      @cancel="!deleting && (confirmOpen = false)"
      @confirm="doDelete">
      将删除世界
      <strong class="text-text">「{{ target?.name }}」</strong>
      及其所有分支、事件、实体与因果记录。该操作不可撤销。
    </ConfirmDialog>
  </section>
</template>
