import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { h } from 'vue';
import ConfirmDialog from '@/components/ConfirmDialog.vue';

// Stub Dialog because it uses Teleport which is tricky in jsdom
const DialogStub = {
  props: ['open', 'title', 'width'],
  emits: ['close'],
  template: `
    <div v-if="open" class="dialog-backdrop" @click="$emit('close')">
      <div class="surface"><slot /><slot name="footer" /></div>
    </div>
  `,
};

describe('ConfirmDialog', () => {
  it('renders when open', () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, title: '删除?', message: '确定要删除吗?' },
      global: { stubs: { Dialog: DialogStub } },
    });
    expect(w.text()).toContain('确定要删除吗?');
    expect(w.text()).toContain('取消');
    expect(w.text()).toContain('确认');
  });

  it('hides when not open', () => {
    const w = mount(ConfirmDialog, {
      props: { open: false, title: 'test' },
      global: { stubs: { Dialog: DialogStub } },
    });
    expect(w.find('.dialog-backdrop').exists()).toBe(false);
  });

  it('emits confirm on click', async () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, title: 'test' },
      global: { stubs: { Dialog: DialogStub } },
    });
    const buttons = w.findAll('button');
    const confirmBtn = buttons.find(b => b.text().includes('确认'));
    await confirmBtn!.trigger('click');
    expect(w.emitted('confirm')).toHaveLength(1);
  });

  it('emits cancel on click', async () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, title: 'test' },
      global: { stubs: { Dialog: DialogStub } },
    });
    // Click the cancel button directly
    const cancelBtn = w.find('button.btn-ghost');
    await cancelBtn.trigger('click');
    expect(w.emitted('cancel')).toBeTruthy();
  });

  it('custom button text', () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, confirmText: '删除', cancelText: '返回' },
      global: { stubs: { Dialog: DialogStub } },
    });
    expect(w.text()).toContain('删除');
    expect(w.text()).toContain('返回');
  });

  it('danger adds red class', () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, danger: true },
      global: { stubs: { Dialog: DialogStub } },
    });
    const buttons = w.findAll('button');
    const confirmBtn = buttons.find(b => b.text().includes('确认'));
    expect(confirmBtn!.classes()).toContain('!bg-red-600');
  });

  it('busy disables buttons and shows processing', () => {
    const w = mount(ConfirmDialog, {
      props: { open: true, busy: true },
      global: { stubs: { Dialog: DialogStub } },
    });
    const buttons = w.findAll('button');
    for (const btn of buttons) {
      expect(btn.attributes('disabled')).toBeDefined();
    }
    expect(w.text()).toContain('处理中…');
  });
});
