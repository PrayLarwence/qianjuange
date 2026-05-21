<script setup lang="ts">
import { ref } from 'vue';
import { useThemeStore, type ThemeMode } from '@/stores/theme';
import { useUiStore } from '@/stores/ui';

const ui = useUiStore();
const theme = useThemeStore();
const tab = ref<'appearance' | 'llm' | 'shortcut' | 'data'>('appearance');

const modes: { value: ThemeMode; label: string; hint: string }[] = [
  { value: 'light',  label: '浅色',     hint: '日间，editorial 米底' },
  { value: 'dark',   label: '深色',     hint: '夜间，暖黑底' },
  { value: 'system', label: '跟随系统', hint: '随操作系统变化' },
];
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
            <div class="text-xs text-muted">
              当前解析为 <span class="text-text">{{ theme.resolved }}</span>。顶栏的 ☀/🌙 按钮可在浅深之间快切。
            </div>
          </section>

          <section v-else-if="tab === 'llm'" class="space-y-3">
            <div class="text-muted">LLM 设置（provider、API key、模型、温度）将接入到下一阶段，目前先沿用旧版。</div>
          </section>

          <section v-else-if="tab === 'shortcut'" class="space-y-3">
            <div class="text-muted">键盘快捷键：</div>
            <ul class="space-y-1 text-sm">
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + K</kbd> 命令面板（待接）</li>
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + ,</kbd> 打开设置</li>
              <li><kbd class="px-1.5 py-0.5 rounded bg-sunken text-xs">⌘/Ctrl + Shift + D</kbd> 切换主题</li>
            </ul>
          </section>

          <section v-else class="space-y-3">
            <div class="text-muted">数据管理：导入 / 导出 / 快照将在迁完后接入。</div>
            <a href="/legacy/" class="btn btn-ghost">↗ 打开旧版界面</a>
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
