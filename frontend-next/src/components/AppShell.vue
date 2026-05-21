<script setup lang="ts">
import TopBar from './TopBar.vue';
import SettingsDrawer from './SettingsDrawer.vue';
import ToastHost from './ToastHost.vue';
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <TopBar />
    <main class="flex-1 min-h-0">
      <RouterView v-slot="{ Component }">
        <component :is="Component" />
      </RouterView>
    </main>
    <SettingsDrawer />
    <ToastHost />
  </div>
</template>
