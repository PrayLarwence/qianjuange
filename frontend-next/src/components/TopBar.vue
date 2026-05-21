<script setup lang="ts">
import { useThemeStore } from '@/stores/theme';
import { useUiStore } from '@/stores/ui';
import { useRoute } from 'vue-router';

const theme = useThemeStore();
const ui = useUiStore();
const route = useRoute();
</script>

<template>
  <header class="h-12 px-4 flex items-center gap-3 border-b border-border bg-bg/80 backdrop-blur sticky top-0 z-30">
    <RouterLink to="/" class="flex items-center gap-2 group">
      <span class="w-6 h-6 rounded bg-accent flex items-center justify-center text-white text-xs font-bold">N</span>
      <span class="text-sm font-medium tracking-wide">Narrative Sandbox</span>
    </RouterLink>

    <nav class="flex items-center gap-1 ml-4 text-sm">
      <RouterLink to="/worlds"
        class="btn btn-ghost"
        :class="{ 'text-text': route.path.startsWith('/worlds') }">世界库</RouterLink>
    </nav>

    <div class="flex-1" />

    <button class="btn btn-ghost" :title="theme.resolved === 'dark' ? '切到浅色' : '切到深色'"
            @click="theme.toggle()">
      <svg v-if="theme.resolved === 'dark'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>
      <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
    </button>

    <button class="btn btn-ghost" title="设置" @click="ui.openSettings()">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    </button>
  </header>
</template>
