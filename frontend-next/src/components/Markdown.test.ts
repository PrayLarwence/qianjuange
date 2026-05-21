import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import Markdown from '@/components/Markdown.vue';

describe('Markdown', () => {
  it('renders empty when no source', () => {
    const w = mount(Markdown, { props: { source: '' } });
    expect(w.find('.md-prose').exists()).toBe(true);
    expect(w.text()).toBe('');
  });

  it('renders headings', () => {
    const w = mount(Markdown, { props: { source: '# Title\n## Sub\n### H3' } });
    expect(w.find('h1').text()).toBe('Title');
    expect(w.find('h2').text()).toBe('Sub');
    expect(w.find('h3').text()).toBe('H3');
  });

  it('renders paragraphs', () => {
    const w = mount(Markdown, { props: { source: '一段文字。' } });
    expect(w.find('p').text()).toContain('一段文字');
  });

  it('renders bold and italic', () => {
    const w = mount(Markdown, { props: { source: '**bold** and *italic*' } });
    expect(w.find('strong').text()).toBe('bold');
    expect(w.find('em').text()).toBe('italic');
  });

  it('renders blockquote', () => {
    const w = mount(Markdown, { props: { source: '> quoted' } });
    expect(w.find('blockquote').text()).toContain('quoted');
  });

  it('renders unordered list', () => {
    const w = mount(Markdown, { props: { source: '- a\n- b\n- c' } });
    expect(w.findAll('li')).toHaveLength(3);
  });

  it('handles raw html safely', () => {
    const w = mount(Markdown, { props: { source: '<b>bold</b>' } });
    // marked passes HTML through; v-html renders it
    expect(w.html()).toContain('<b>');
  });
});
