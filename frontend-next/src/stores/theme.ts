import { defineStore } from 'pinia';

export type ThemeMode = 'light' | 'dark' | 'system';

function isDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true;
  if (mode === 'light') return false;
  return matchMedia('(prefers-color-scheme: dark)').matches;
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: (localStorage.getItem('theme') as ThemeMode) || 'system',
  }),
  getters: {
    resolved(state): 'light' | 'dark' {
      return isDark(state.mode) ? 'dark' : 'light';
    },
  },
  actions: {
    init() {
      this.apply();
      // 跟随系统时监听变化
      matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (this.mode === 'system') this.apply();
      });
    },
    set(mode: ThemeMode) {
      this.mode = mode;
      localStorage.setItem('theme', mode);
      this.apply();
    },
    toggle() {
      // 单击：在 light/dark 之间切换；从 system 出发切到与当前解析相反
      const next: ThemeMode = this.resolved === 'dark' ? 'light' : 'dark';
      this.set(next);
    },
    apply() {
      document.documentElement.classList.toggle('dark', isDark(this.mode));
    },
  },
});
