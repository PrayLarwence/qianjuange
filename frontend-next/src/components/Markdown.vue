<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';

const props = defineProps<{ source: string }>();

marked.setOptions({ breaks: false, gfm: true });

const html = computed(() => {
  if (!props.source) return '';
  return marked.parse(props.source, { async: false }) as string;
});
</script>

<template>
  <div class="md-prose font-serif" v-html="html" />
</template>

<style>
.md-prose h1 { font-size: 2.25rem; line-height: 1.2; margin: 0 0 1.25rem; font-weight: 600; }
.md-prose h2 { font-size: 1.5rem;  line-height: 1.3; margin: 2rem 0 .75rem; font-weight: 600; }
.md-prose h3 { font-size: 1.25rem; line-height: 1.4; margin: 1.75rem 0 .5rem; font-weight: 600; }
.md-prose p  { line-height: 1.85; margin: 0 0 1.1rem; text-align: justify; text-indent: 2em; }
.md-prose p:first-of-type { text-indent: 0; }
.md-prose blockquote {
  margin: 1.25rem 0; padding: .25rem 1rem; border-left: 2px solid var(--color-accent, #d97757);
  color: var(--color-muted, #6b6b6b); font-style: italic;
}
.md-prose hr { border: 0; border-top: 1px solid currentColor; opacity: .15; margin: 2.5rem auto; width: 6rem; }
.md-prose ul, .md-prose ol { padding-left: 1.5rem; margin: 0 0 1.1rem; line-height: 1.8; }
.md-prose ul { list-style: disc; }
.md-prose ol { list-style: decimal; }
.md-prose li { margin: 0 0 .35rem; }
.md-prose strong { font-weight: 600; }
.md-prose em { font-style: italic; }
.md-prose code {
  font-family: ui-monospace, monospace; font-size: .9em;
  padding: .1em .35em; border-radius: .2em;
  background: rgba(0,0,0,.06);
}
</style>
