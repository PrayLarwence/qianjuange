<script setup lang="ts">
import Dialog from './Dialog.vue';

const props = defineProps<{
  open: boolean;
  title?: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  busy?: boolean;
}>();
const emit = defineEmits<{
  (e: 'confirm'): void;
  (e: 'cancel'): void;
}>();
</script>

<template>
  <Dialog :open="open" :title="title || '请确认'" width="420px" @close="!busy && emit('cancel')">
    <p class="text-sm leading-relaxed">
      <slot>{{ message }}</slot>
    </p>
    <template #footer>
      <button class="btn btn-ghost" :disabled="busy" @click="emit('cancel')">
        {{ cancelText || '取消' }}
      </button>
      <button class="btn"
              :class="danger ? '!bg-red-600 !text-white hover:!brightness-110' : 'btn-accent'"
              :disabled="busy"
              @click="emit('confirm')">
        <span v-if="busy">处理中…</span>
        <span v-else>{{ confirmText || '确认' }}</span>
      </button>
    </template>
  </Dialog>
</template>
