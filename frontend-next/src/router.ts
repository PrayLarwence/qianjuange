import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

const Home          = () => import('@/views/HomeView.vue');
const WorldsLibrary = () => import('@/views/WorldsLibraryView.vue');
const SettingsPage  = () => import('@/views/SettingsView.vue');
const WorldShell    = () => import('@/views/world/WorldShell.vue');

const Dashboard = () => import('@/views/world/DashboardView.vue');
const Overview = () => import('@/views/world/OverviewView.vue');
const Chapters = () => import('@/views/world/ChaptersView.vue');
const Graph    = () => import('@/views/world/GraphView.vue');
const Timeline = () => import('@/views/world/TimelineView.vue');
const Cast     = () => import('@/views/world/CastView.vue');
const Lore     = () => import('@/views/world/LoreView.vue');
const Sim      = () => import('@/views/world/SimView.vue');
const AgentRun = () => import('@/views/world/AgentRunView.vue');
const Review   = () => import('@/views/world/ReviewView.vue');
const Storyboard = () => import('@/views/world/StoryboardView.vue');
const WorldSet = () => import('@/views/world/WorldSettingsView.vue');

const routes: RouteRecordRaw[] = [
  { path: '/',          name: 'home',     component: Home },
  { path: '/worlds',    name: 'worlds',   component: WorldsLibrary },
  { path: '/settings',  name: 'settings', component: SettingsPage },
  {
    path: '/worlds/:id',
    component: WorldShell,
    children: [
      { path: '',          name: 'world.overview', component: Dashboard },
      { path: 'overview-old', name: 'world.overview-old', component: Overview },
      { path: 'chapters',  name: 'world.chapters', component: Chapters },
      { path: 'graph',     name: 'world.graph',    component: Graph },
      { path: 'timeline',  name: 'world.timeline', component: Timeline },
      { path: 'cast',      name: 'world.cast',     component: Cast },
      { path: 'lore',      name: 'world.lore',     component: Lore },
      { path: 'sim',       name: 'world.sim',      component: Sim },
      { path: 'agent-run', name: 'world.agent-run', component: AgentRun },
      { path: 'review',    name: 'world.review',     component: Review },
      { path: 'storyboard', name: 'world.storyboard', component: Storyboard },
      { path: 'settings',  name: 'world.settings',   component: WorldSet },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() { return { top: 0 }; },
});
