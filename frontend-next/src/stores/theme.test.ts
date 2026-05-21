import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useThemeStore } from '@/stores/theme';

describe('useThemeStore', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('defaults to system', () => {
    const store = useThemeStore();
    expect(store.mode).toBe('system');
  });

  it('set stores in localStorage', () => {
    const store = useThemeStore();
    store.set('dark');
    expect(store.mode).toBe('dark');
    expect(localStorage.getItem('theme')).toBe('dark');
  });

  it('set applies dark class', () => {
    const store = useThemeStore();
    store.set('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('set light removes dark class', () => {
    const store = useThemeStore();
    store.set('dark');
    store.set('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('toggle switches light↔dark', () => {
    const store = useThemeStore();
    store.set('light');
    store.toggle();
    expect(store.mode).toBe('dark');
    store.toggle();
    expect(store.mode).toBe('light');
  });

  it('resolved getter returns light or dark', () => {
    const store = useThemeStore();
    store.set('dark');
    expect(store.resolved).toBe('dark');
    store.set('light');
    expect(store.resolved).toBe('light');
  });

  it('restores from localStorage', () => {
    localStorage.setItem('theme', 'dark');
    setActivePinia(createPinia());
    const store = useThemeStore();
    expect(store.mode).toBe('dark');
  });
});
