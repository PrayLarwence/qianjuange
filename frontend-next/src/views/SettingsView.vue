<script setup lang="ts">
import { useUiStore } from '@/stores/ui';
const ui = useUiStore();
</script>

<template>
  <section class="max-w-3xl mx-auto px-6 py-12">
    <p class="text-muted text-xs uppercase tracking-wider mb-2">设置</p>
    <h1 class="font-serif text-3xl mb-4">全局设置</h1>
    <p class="text-muted mb-6">设置已聚合到右上角的设置抽屉，可随时打开。</p>
    <button class="btn btn-accent" @click="ui.openSettings()">打开设置抽屉</button>
  </section>
</template>
