import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useToastStore } from '@/stores/toast';

describe('useToastStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('starts empty', () => {
    const store = useToastStore();
    expect(store.items).toEqual([]);
  });

  it('push adds an item', () => {
    const store = useToastStore();
    store.push('hello', 'info', 99999);
    expect(store.items).toHaveLength(1);
    expect(store.items[0].text).toBe('hello');
    expect(store.items[0].kind).toBe('info');
  });

  it('success / error / info shortcuts', () => {
    const store = useToastStore();
    store.success('ok');
    store.error('fail');
    store.info('note');
    expect(store.items).toHaveLength(3);
    expect(store.items[0].kind).toBe('success');
    expect(store.items[1].kind).toBe('error');
    expect(store.items[2].kind).toBe('info');
  });

  it('dismiss removes by id', () => {
    const store = useToastStore();
    store.push('a', 'info', 99999);
    store.push('b', 'info', 99999);
    const idA = store.items[0].id;
    store.dismiss(idA);
    expect(store.items).toHaveLength(1);
    expect(store.items[0].text).toBe('b');
  });

  it('dismiss non-existent id is no-op', () => {
    const store = useToastStore();
    store.push('x', 'info', 99999);
    store.dismiss(9999);
    expect(store.items).toHaveLength(1);
  });

  it('increments id counter', () => {
    const store = useToastStore();
    store.push('1', 'info', 99999);
    store.push('2', 'info', 99999);
    expect(store.items[1].id).toBeGreaterThan(store.items[0].id);
  });
});
