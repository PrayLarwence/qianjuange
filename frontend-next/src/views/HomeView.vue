<script setup lang="ts">
import { useRouter } from 'vue-router';
const router = useRouter();
</script>

<template>
  <section class="max-w-3xl mx-auto px-6 py-16">
    <p class="text-muted text-sm tracking-wider uppercase mb-3">千卷阁 · Qianjuange</p>
    <h1 class="font-serif text-4xl leading-tight mb-4">让世界先成立，再让故事发生。</h1>
    <p class="font-serif text-prose text-muted mb-10 max-w-xl">
      一个用于推演、写作与排错的叙事沙盒。从世界库挑一个进入，或新建一个开始。
    </p>
    <div class="flex gap-2">
      <button class="btn btn-accent" @click="router.push('/worlds')">进入世界库</button>
      <a class="btn btn-ghost" href="/legacy/">↗ 旧版</a>
    </div>
  </section>
</template>
