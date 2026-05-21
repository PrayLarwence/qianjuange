import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { router } from './router';
import { useThemeStore } from './stores/theme';
import './styles.css';

const app = createApp(App);
app.use(createPinia());
app.use(router);

// 挂载前同步主题（与 index.html 内联脚本协作）
useThemeStore().init();

app.mount('#app');
