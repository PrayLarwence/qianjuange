<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string }>();
</script>

<template>
  <div class="px-8 py-10 max-w-5xl">
    <p class="text-muted text-xs uppercase tracking-wider mb-2">{{ subtitle || '占位' }}</p>
    <h1 class="font-serif text-3xl mb-3">{{ title || '即将到来' }}</h1>
    <p class="text-muted mb-6">这个视图正在迁移中。在新 UI 完成之前，可在<a href="/legacy/" class="text-accent">旧版</a>使用对应功能。</p>
    <slot />
  </div>
</template>
