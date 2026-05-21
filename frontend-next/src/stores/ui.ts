import { defineStore } from 'pinia';

export const useUiStore = defineStore('ui', {
  state: () => ({
    settingsOpen: false,
    sidebarCollapsed: false,
    contextOpen: true,
  }),
  actions: {
    openSettings() { this.settingsOpen = true; },
    closeSettings() { this.settingsOpen = false; },
    toggleSidebar() { this.sidebarCollapsed = !this.sidebarCollapsed; },
    toggleContext() { this.contextOpen = !this.contextOpen; },
  },
});
