import { defineStore } from 'pinia';

export type ToastKind = 'info' | 'success' | 'error';
export interface Toast { id: number; kind: ToastKind; text: string; }

let counter = 0;

export const useToastStore = defineStore('toast', {
  state: () => ({ items: [] as Toast[] }),
  actions: {
    push(text: string, kind: ToastKind = 'info', ttl = 3000) {
      const id = ++counter;
      this.items.push({ id, kind, text });
      window.setTimeout(() => this.dismiss(id), ttl);
    },
    success(t: string) { this.push(t, 'success'); },
    error(t: string)   { this.push(t, 'error', 5000); },
    info(t: string)    { this.push(t, 'info'); },
    dismiss(id: number) {
      const i = this.items.findIndex(x => x.id === id);
      if (i >= 0) this.items.splice(i, 1);
    },
  },
});
