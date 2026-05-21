<script setup lang="ts">
import { useToastStore } from '@/stores/toast';
const toast = useToastStore();
</script>

<template>
  <Teleport to="body">
    <div class="fixed bottom-6 right-6 z-[60] flex flex-col gap-2 pointer-events-none">
      <TransitionGroup name="toast">
        <div v-for="t in toast.items" :key="t.id"
             class="surface rounded shadow-soft px-4 py-3 text-sm pointer-events-auto min-w-[240px] max-w-[360px] flex items-start gap-2"
             :class="{
               '!border-accent': t.kind === 'success',
               '!border-red-500': t.kind === 'error',
             }">
          <span class="mt-0.5"
                :class="{
                  'text-accent': t.kind === 'success',
                  'text-red-500': t.kind === 'error',
                  'text-muted':   t.kind === 'info',
                }">
            {{ t.kind === 'success' ? '✓' : t.kind === 'error' ? '!' : 'i' }}
          </span>
          <div class="flex-1">{{ t.text }}</div>
          <button class="btn btn-ghost !h-5 !px-1 text-muted" @click="toast.dismiss(t.id)">×</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all .2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to   { opacity: 0; transform: translateX(20px); }
</style>
