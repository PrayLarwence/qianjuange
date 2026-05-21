<script setup lang="ts">
import { onMounted, onBeforeUnmount, watch } from 'vue';

const props = defineProps<{
  open: boolean;
  title?: string;
  width?: string;
  closeOnBackdrop?: boolean;
}>();
const emit = defineEmits<{ (e: 'close'): void }>();

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close');
}

onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));

watch(() => props.open, (v) => {
  document.documentElement.style.overflow = v ? 'hidden' : '';
});
</script>

<template>
  <Teleport to="body">
    <Transition name="dlg-fade">
      <div v-if="open"
           class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
           @click.self="closeOnBackdrop !== false && emit('close')">
        <div class="surface rounded shadow-soft flex flex-col max-h-[85vh] w-full"
             :style="{ maxWidth: width || '480px' }">
          <header v-if="title || $slots.header" class="px-5 h-12 flex items-center justify-between border-b border-border">
            <slot name="header"><h2 class="font-medium">{{ title }}</h2></slot>
            <button class="btn btn-ghost !h-7 !px-2" @click="emit('close')" aria-label="关闭">×</button>
          </header>
          <div class="flex-1 overflow-y-auto p-5">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="px-5 h-14 flex items-center justify-end gap-2 border-t border-border">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dlg-fade-enter-active, .dlg-fade-leave-active { transition: opacity .15s ease; }
.dlg-fade-enter-from, .dlg-fade-leave-to { opacity: 0; }
.dlg-fade-enter-active > div, .dlg-fade-leave-active > div { transition: transform .15s ease; }
.dlg-fade-enter-from > div, .dlg-fade-leave-to > div { transform: scale(.97); }
</style>
