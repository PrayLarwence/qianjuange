function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function sandbox() {
  return {
    worlds: [],
    branches: [],
    currentWorldId: '',
    currentBranchId: '',
    world: null,
    entities: [],
    timeline: { events: [], links: [], narration: [], plot_threads: [] },
    selectedEntity: null,
    viewMode: 'graph',
    cy: null,
    graphHelpDismissed: typeof localStorage !== 'undefined' && localStorage.getItem('graphHelpSeen') === '1',

    provider: '',
    directive: '',
    stepCount: 1,
    busy: false,
    lastStep: null,

    showCreateWorld: false,
    showCreateEntity: false,
    newWorld: { name: '', description: '', outline: '' },
    newEntity: { type: 'character', name: '', summary: '', attributesJson: '' },

    showSettings: false,
    savingSettings: false,
    settingsMessage: '',
    llmConfig: { active: 'claude', providers: {} },
    llmMeta: {},
    keyDrafts: {},
    testResults: {},
    testingKey: '',

    linkSourceId: null,
    showEventEdit: false,
    eventEditDraft: { id: '', title: '', description: '', tick: 0, participants: [], participantsText: '' },
    showEdgeEdit: false,
    edgeEditDraft: { cause: '', effect: '', description: '' },
    pendingChanges: [],
    showReconcile: false,
    reconcileBranch: true,
    reconcileBranchName: '',
    reconciling: false,
    reconcileResult: null,

    branches: [],
    showBranches: false,
    branchEditDraft: { id: '', name: '' },
    compareWith: null,
    compareTimeline: { events: [], links: [], narration: [] },
    cyCompare: null,

    focusMode: false,
    toastMsg: '',

    activeJob: null,
    liveToolCalls: [],
    liveNarration: '',
    liveProgressMsg: '',

    chatTarget: null,
    chatHistory: [],
    chatInput: '',
    chatSending: false,
    chatViewTick: null,
    chatAbort: null,

    showHistory: false,
    historyList: [],
    historyLoading: false,

    showSearch: false,
    searchQuery: '',
    searchSelectedIndex: 0,

    showWorldSettings: false,
    settingsDraft: { name: '', description: '', outline: '', core_rules: [], forbidden: [], tone: '', language: '', notes: '', style_profile_id: '' },
    settingsSaving: false,
    stylesAvailable: [],
    stylePreview: { id: '', name: '', spec_text: '', samples: [] },

    showExplore: false,
    exploreVariants: [{ label: 'A', directive: '' }, { label: 'B', directive: '' }],
    exploreSteps: 1,
    exploreActive: false,
    exploreJobs: [],
    exploreParentBranchId: null,
    exploreParentTick: 0,
    exploreEvaluating: false,
    exploreRecommended: '',
    exploreReasoning: '',

    showRelations: false,
    relGraph: null,
    relNodes: [],
    relEdges: [],
    relSelected: null,
    relInferring: false,
    relFilter: 'characters',
    relEditLabel: '',
    relEditSaving: false,

    suggestions: [],
    suggestionsLoading: false,

    showExport: false,
    exportMode: 'raw',
    exportTickFrom: 0,
    exportTickTo: 0,
    exportChapterSize: 5,
    exportUseMarkers: true,
    exportIncludeCritique: false,
    exportIncludeEntities: true,
    exportIncludeEvents: true,
    exportIncludeNarration: true,
    exportLoading: false,
    exportResult: null,

    showArc: false,
    showCharView: false,
    charViewEntity: null,
    charView: null,
    charViewBusy: false,
    personaForm: { drivesText: '', voice: '', blindspotsText: '', knowledgeOfText: '' },
    personaDirty: false,
    personaSaving: false,
    personaExtracting: false,
    personaSuggestion: null,
    showPersonaSuggestion: false,
    personaExtractMsg: '',
    showNovelize: false,
    novelizeOpts: { branch_id: '', strategy: 'by_count', chapter_size: 6 },
    novelizeChapters: [],
    novelizeRunning: false,
    novelizeJobId: null,
    novelizeJobMsg: '',
    novelizeMarkdown: '',
    novelizeProgress: { done: 0, total: 0 },
    novelizePollTimer: null,
    ganttBranchIds: [],
    ganttData: null,
    ganttTimeline: null,
    ganttShowCausal: true,
    ganttShowChapters: true,
    ganttHint: '点击事件查看详情，双击空白处可以加章节标记',
    arcEntity: null,
    arcData: null,
    arcEmotionLoading: false,

    chapters: [],
    chaptersLoading: false,
    autoChapterTarget: 5,

    outline: [],
    outlineCurrentIndex: 0,
    outlineCompleted: [],
    outlineLoading: false,
    showOutlinePanel: true,
    seriesTemplates: [],
    welcomeFeatured: [],
    welcomeRecent: [],
    welcomeLoading: true,
    showConsistency: false,
    issues: [],
    issueCounts: { open: 0, ignored: 0, resolved: 0 },
    scans: [],
    issueFilter: 'open',
    scanScope: 'recent',
    scanFrom: 0,
    scanTo: 0,
    scanning: false,
    showManuscript: false,
    showStats: false,
    stats: null,
    toolMenuOpen: false,
    showMap: false,
    mapMeta: null,
    mapLayer: 'biome',
    mapImgUrl: '',
    mapInfo: null,
    mapBusy: false,
    mapTextStatus: '',
    mapGenParams: { width: 512, height: 384, seed: 0, sea_level: 0.42, octaves: 6, persistence: 0.55, base_freq: 2.5, warp: 0.12 },
    mapZoom: 1,
    mapPan: { x: 0, y: 0 },
    mapDragging: false,
    mapTool: 'view',
    mapPaintTerrain: 4,
    mapBrushSize: 3,
    mapPainting: false,
    mapHover: { x: null, y: null },
    pinnedEntities: [],
    pinTargetEntity: null,
    gotoTargetEntity: null,
    simPlaying: false,
    simInterval: null,
    simStatus: [],
    _mapDragStart: null,
    _paintBuffer: [],
    _paintFlushTimer: null,
    mapImportOpen: false,
    mapImportFile: null,
    mapImportParams: { width: 512, height: 384, sea_level: 0.42, blur: 0.6, contrast: 1.0, invert: false, seed: 0 },
    msMode: 'manuscript',
    msFormat: 'markdown',
    msPolish: 'raw',
    msStyle: '',
    msFrom: null,
    msTo: null,
    msPovEntityId: '',
    msGenerating: false,
    manuscript: null,

    showTemplates: false,
    templatesData: { templates: [], categories: [], total: 0 },
    templatesLoading: false,
    templateCategoryFilter: '',
    selectedTemplate: null,
    showTemplateEditor: false,
    editingTemplate: null,
    showSaveAsTemplate: false,
    saveAsTemplateForm: { name: '', category: '', description: '', cover_emoji: '📖', tags: '', include_entities: true },

    genesisExamples: [
      '唐朝长安，主角是不良帅周浩然，最近坊间发生连环命案，他的过去与之有关',
      '近未来赛博都市新香港 2087，主角是黑客苏沐辰，要追查一个能黑进人脑的 AI 病毒',
      '魔法学院新生入学，主角林雪是平民出身的天才法师，她将面对贵族派系的排挤',
      '末日丧尸三个月后的上海，幸存者团队 5 人困在写字楼，物资即将耗尽',
      '武侠：少年柳青云身负灭门之仇，下山闯荡江湖，第一站是繁华的杭州',
    ],
    stepExamples: [
      '引入一个意外的反派',
      '推进 7 天，发生一场冲突',
      '让主角面临一个艰难的道德抉择',
      '引入一段感情线',
      '揭露一个隐藏的真相',
    ],

    toolLabelMap: {
      create_entity: '➕ 创建实体',
      update_entity: '✎ 修改实体',
      add_event: '✦ 添加事件',
      link_causality: '⇒ 建立因果',
      advance_time: '⏱ 推进时间',
      branch_world: '⑂ 分叉世界线',
      narrate: '📖 写叙事',
      end_turn: '⏹ 结束本轮',
    },

    toolLabel(name) { return this.toolLabelMap[name] || name; },

    toolSummary(tc) {
      const a = tc.args || {};
      switch (tc.name) {
        case 'create_entity': return `${a.type} · ${a.name}${a.summary ? ' — ' + a.summary : ''}`;
        case 'update_entity': return `${a.id?.slice(0, 10) || ''} ${a.reason || JSON.stringify(a.state || a.attributes || {}).slice(0, 60)}`;
        case 'add_event': return `t${a.tick ?? '?'} · ${a.title}`;
        case 'link_causality': return `${(a.cause_event_id || '').slice(0, 8)} → ${(a.effect_event_id || '').slice(0, 8)} ${a.description || ''}`;
        case 'advance_time': return `+${a.ticks} tick`;
        case 'branch_world': return a.name;
        case 'narrate': return (a.text || '').slice(0, 80);
        case 'end_turn': return '';
        default: return JSON.stringify(a).slice(0, 80);
      }
    },

    async init() {
      await this.loadLlmConfig();
      await this.refreshWorlds();
      const lastId = (() => { try { return localStorage.getItem('lastWorldId'); } catch { return null; } })();
      if (lastId && this.worlds.find(w => w.id === lastId)) {
        this.currentWorldId = lastId;
        await this.loadWorld();
      } else {
        await this.loadWelcomeData();
      }
      this.welcomeLoading = false;
      this.$watch('currentWorldId', (id) => {
        try { if (id) localStorage.setItem('lastWorldId', id); } catch {}
      });
      this.$watch('viewMode', (m) => { if (m === 'graph') this.$nextTick(() => this.renderGraph()); });
      window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.focusMode) this.toggleFocusMode();
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
          e.preventDefault();
          this.openSearch();
        }
      });
    },

    async loadLlmConfig() {
      const r = await this.api('GET', '/llm_config');
      this.llmConfig = r.config;
      this.llmMeta = r.meta;
      this.keyDrafts = Object.fromEntries(Object.keys(this.llmMeta).map(k => [k, '']));
      this.provider = this.llmConfig.active;
    },

    async changeProvider() {
      if (!this.provider) return;
      try {
        const r = await this.api('POST', '/llm_config', { active: this.provider }, 10000);
        this.llmConfig = r.config;
      } catch (e) {
        alert('切换 Provider 失败: ' + e.message);
      }
    },

    providerHasKey(key) {
      return !!(this.llmConfig.providers[key] && this.llmConfig.providers[key].has_key);
    },

    providerKeyDraft(key) {
      return !!(this.keyDrafts[key] && this.keyDrafts[key].length > 0);
    },

    openSettings() {
      this.settingsMessage = '';
      this.testResults = {};
      this.showSettings = true;
    },

    async saveSettings() {
      this.savingSettings = true;
      this.settingsMessage = '';
      try {
        const providers = {};
        for (const [k, p] of Object.entries(this.llmConfig.providers)) {
          providers[k] = { model: p.model, base_url: p.base_url };
          if (this.keyDrafts[k]) providers[k].api_key = this.keyDrafts[k];
        }
        const r = await this.api('POST', '/llm_config', {
          active: this.llmConfig.active,
          providers,
        }, 10000);
        this.llmConfig = r.config;
        this.keyDrafts = Object.fromEntries(Object.keys(this.llmMeta).map(k => [k, '']));
        this.provider = this.llmConfig.active;
        this.settingsMessage = '已保存';
        setTimeout(() => { this.settingsMessage = ''; }, 2000);
      } catch (e) {
        this.settingsMessage = '保存失败: ' + e.message;
      } finally {
        this.savingSettings = false;
      }
    },

    async testProvider(key) {
      this.testingKey = key;
      this.testResults = { ...this.testResults, [key]: null };
      try {
        const providers = { [key]: { model: this.llmConfig.providers[key].model, base_url: this.llmConfig.providers[key].base_url } };
        if (this.keyDrafts[key]) providers[key].api_key = this.keyDrafts[key];
        await this.api('POST', '/llm_config', { providers }, 10000);
        const r = await this.api('POST', '/llm_config/test', { provider: key }, 70000);
        this.testResults = { ...this.testResults, [key]: r };
      } catch (e) {
        this.testResults = { ...this.testResults, [key]: { ok: false, error: e.message } };
      } finally {
        this.testingKey = '';
      }
    },

    async api(method, path, body, timeoutMs = 30000) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      const opts = { method, headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal };
      if (body !== undefined) opts.body = JSON.stringify(body);
      try {
        const r = await fetch('/api' + path, opts);
        if (!r.ok) {
          const text = await r.text();
          throw new Error(text || ('HTTP ' + r.status));
        }
        return r.json();
      } catch (e) {
        if (e.name === 'AbortError') throw new Error(`请求超时（${Math.round(timeoutMs/1000)}秒）`);
        throw e;
      } finally {
        clearTimeout(timer);
      }
    },

    async refreshWorlds() {
      this.worlds = await this.api('GET', '/worlds');
    },

    async loadWorld() {
      if (!this.currentWorldId) return;
      this._resetWorldScopedState();
      this.world = await this.api('GET', `/worlds/${this.currentWorldId}`);
      this.entities = this.world.entities;
      this.branches = await this.api('GET', `/worlds/${this.currentWorldId}/branches`);
      this.currentBranchId = this.world.world.branch_id;
      await this.refreshTimeline();
      this.loadChapters();
      this.loadOutline();
      this.refreshIssues();
      this.$nextTick(() => this.renderGraph());
    },

    _resetWorldScopedState() {
      this.entities = [];
      this.timeline = { events: [], links: [], narration: [], plot_threads: [] };
      this.selectedEntity = null;
      this.charViewEntity = null;
      this.charView = null;
      this.personaSuggestion = null;
      this.chatTarget = null;
      this.chatHistory = [];
      this.chatViewTick = null;
      this.liveToolCalls = [];
      this.lastStep = null;
      this.pendingChanges = [];
      this.reconcileResult = null;
      this.compareWith = null;
      this.compareTimeline = { events: [], links: [], narration: [] };
      this.relGraph = null;
      this.relNodes = [];
      this.relEdges = [];
      this.relSelected = null;
      this.chapters = [];
      this.novelizeChapters = [];
      this.linkSourceId = null;
    },

    async setMaxTick(v) {
      if (!this.currentWorldId) return;
      const n = Math.max(0, parseInt(v) || 0);
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/max_tick`, { max_tick: n });
        if (this.world?.world) this.world.world.max_tick = r.max_tick;
        this.flashToast(`目标 tick 设为 ${r.max_tick}`);
      } catch (e) { alert('设置失败: ' + e.message); }
    },

    async loadOutline() {
      if (!this.currentWorldId) return;
      this.outlineLoading = true;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/outline`);
        this.outline = r.outline || [];
        this.outlineCurrentIndex = r.current_index || 0;
        this.outlineCompleted = r.completed || [];
        if (this.world?.world) {
          this.world.world.max_tick = r.max_tick;
          this.world.world.template_id = r.template_id;
        }
        if (this.outline.length > 0 && r.template_id) {
          await this.loadSeriesSiblings(r.template_id);
        } else {
          this.seriesTemplates = [];
        }
      } catch (e) { console.error('outline', e); }
      finally { this.outlineLoading = false; }
    },

    async loadSeriesSiblings(templateId) {
      try {
        const all = await this.api('GET', '/templates');
        const me = (all.templates || []).find(t => t.id === templateId);
        if (!me || !me.series) { this.seriesTemplates = []; return; }
        const r = await this.api('GET', `/series/${encodeURIComponent(me.series)}`);
        this.seriesTemplates = r.templates || [];
      } catch (e) { this.seriesTemplates = []; }
    },

    async toggleOutlineCompleted(idx) {
      const set = new Set(this.outlineCompleted);
      if (set.has(idx)) set.delete(idx); else set.add(idx);
      const completed = [...set].sort((a, b) => a - b);
      let cur = this.outlineCurrentIndex;
      if (set.has(cur)) {
        for (let i = cur + 1; i < this.outline.length; i++) {
          if (!set.has(i)) { cur = i; break; }
        }
      }
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/outline_progress`,
          { current_index: cur, completed });
        this.outlineCompleted = completed;
        this.outlineCurrentIndex = cur;
      } catch (e) { alert('保存失败: ' + e.message); }
    },

    async setOutlineCurrent(idx) {
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/outline_progress`, { current_index: idx });
        this.outlineCurrentIndex = idx;
      } catch (e) { alert('保存失败: ' + e.message); }
    },

    outlineProgressPercent() {
      if (this.outline.length === 0) return 0;
      return Math.round((this.outlineCompleted.length / this.outline.length) * 100);
    },

    async stepToNextBeat() {
      if (!this.currentWorldId || this.busy) return;
      const beat = this.outline[this.outlineCurrentIndex];
      if (!beat) return;
      this.directive = `推进剧情到节点：${beat.beat || beat.title || ''}。完成后停止。`;
      await this.step();
    },

    nextSeriesTemplate() {
      if (!this.world?.world?.template_id || this.seriesTemplates.length === 0) return null;
      const me = this.seriesTemplates.find(t => t.id === this.world.world.template_id);
      if (!me) return null;
      return this.seriesTemplates.find(t => (t.series_order || 0) > (me.series_order || 0)) || null;
    },

    async loadWelcomeData() {
      try {
        const r = await this.api('GET', '/templates');
        const all = r.templates || [];
        const officials = all.filter(t => t.is_official).slice(0, 8);
        const others = all.filter(t => !t.is_official).slice(0, Math.max(0, 8 - officials.length));
        this.welcomeFeatured = [...officials, ...others].slice(0, 8);
      } catch { this.welcomeFeatured = []; }
      this.welcomeRecent = (this.worlds || []).slice(0, 3);
    },

    async instantiateFromTemplate(templateId) {
      try {
        const r = await this.api('POST', `/templates/${templateId}/instantiate`, {});
        await this.refreshWorlds();
        this.currentWorldId = r.world_id;
        await this.loadWorld();
        if (r.seed_directive) this.directive = r.seed_directive;
        this.flashToast('已从模板创建世界');
      } catch (e) { alert('创建失败: ' + e.message); }
    },

    async createBlankWorld() {
      const name = prompt('世界名字？', '我的新世界');
      if (!name) return;
      try {
        const r = await this.api('POST', '/worlds', { name: name.trim(), description: '', rules: {} });
        await this.refreshWorlds();
        this.currentWorldId = r.id;
        await this.loadWorld();
        this.flashToast('已创建空白世界');
      } catch (e) { alert('创建失败: ' + e.message); }
    },

    get openIssueCount() { return this.issueCounts?.open || 0; },

    filteredIssues() {
      return this.issues.filter(i => i.status === this.issueFilter);
    },

    severityBg(sev) {
      return sev === 'high' ? 'border-rose-800 bg-rose-950/20'
           : sev === 'low'  ? 'border-zinc-800 bg-zinc-950/40'
                            : 'border-amber-800/60 bg-amber-950/15';
    },
    severityDot(sev) {
      return sev === 'high' ? 'bg-rose-500'
           : sev === 'low'  ? 'bg-zinc-500'
                            : 'bg-amber-500';
    },
    entityName(eid) {
      return (this.entities || []).find(e => e.id === eid)?.name || '';
    },

    async openConsistency() {
      this.showConsistency = true;
      await this.refreshIssues();
    },

    async refreshIssues() {
      if (!this.currentWorldId) return;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/issues`);
        this.issues = r.issues || [];
        this.issueCounts = r.counts || { open: 0, ignored: 0, resolved: 0 };
        this.scans = r.scans || [];
      } catch (e) { console.error(e); }
    },

    async runScan() {
      if (!this.currentWorldId || this.scanning) return;
      this.scanning = true;
      try {
        const body = { scope: this.scanScope, provider: this.provider };
        if (this.scanScope === 'custom') {
          body.tick_from = parseInt(this.scanFrom) || 0;
          body.tick_to = parseInt(this.scanTo) || 0;
        }
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/scan_consistency`, body);
        await this.refreshIssues();
        const status = r.scan?.status;
        if (status === 'failed') {
          this.flashToast('扫描失败：' + (r.scan.error || '未知'));
        } else {
          const n = r.issues?.length || 0;
          this.flashToast(n === 0 ? '未发现问题 ✓' : `发现 ${n} 个新问题`);
          if (n > 0) this.issueFilter = 'open';
        }
      } catch (e) {
        alert('扫描失败: ' + e.message);
      } finally {
        this.scanning = false;
      }
    },

    async setIssueStatus(issueId, status) {
      try {
        await this.api('PATCH', `/issues/${issueId}`, { status });
        await this.refreshIssues();
      } catch (e) { alert('更新失败: ' + e.message); }
    },

    async deleteIssue(issueId) {
      if (!confirm('删除这个 issue？')) return;
      try {
        await this.api('DELETE', `/issues/${issueId}`);
        await this.refreshIssues();
      } catch (e) { alert('删除失败: ' + e.message); }
    },

    fixIssueWithAI(iss) {
      const hint = `[修复一致性问题：${iss.title}] ${iss.suggestion || iss.description}。请在不破坏已有情节的前提下处理。`;
      this.directive = hint;
      this.showConsistency = false;
      this.flashToast('修复提示已填入推演框，按推演继续');
    },

    openManuscript() {
      this.showManuscript = true;
    },

    async openStats() {
      this.showStats = true;
      await this.loadStats();
    },

    async openMap() {
      this.showMap = true;
      this.mapInfo = null;
      this.mapZoom = 1;
      this.mapPan = { x: 0, y: 0 };
      await this.loadMapMeta();
      if (this.mapMeta?.exists) {
        this.refreshMapImage();
        await this.loadPinned();
        await this.refreshSimStatus();
      }
    },

    async loadMapMeta() {
      if (!this.currentWorldId) return;
      try {
        this.mapMeta = await this.api('GET', `/worlds/${this.currentWorldId}/map`);
      } catch (e) {
        console.warn('load map meta failed:', e);
        this.mapMeta = null;
      }
    },

    refreshMapImage() {
      if (!this.currentWorldId || !this.mapMeta?.exists) {
        this.mapImgUrl = '';
        return;
      }
      this.mapImgUrl = `/api${`/worlds/${this.currentWorldId}/map/render.png?layer=${this.mapLayer}&t=${Date.now()}`}`;
    },

    setMapLayer(layer) {
      this.mapLayer = layer;
      this.refreshMapImage();
    },

    async generateMap() {
      if (!this.currentWorldId || this.mapBusy) return;
      this.mapBusy = true;
      try {
        const p = { ...this.mapGenParams };
        if (!p.seed) p.seed = Math.floor(Math.random() * 1e9);
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/map/generate`, p);
        this.mapGenParams.seed = p.seed;
        await this.loadMapMeta();
        this.refreshMapImage();
        this.flashToast(`生成完成 ${r.width}x${r.height}`);
      } catch (e) {
        alert('生成地图失败: ' + e.message);
      } finally {
        this.mapBusy = false;
      }
    },

    async generateMapFromText() {
      if (!this.currentWorldId || this.mapBusy) return;
      const w = this.world?.world;
      if (!w || (!(w.outline || '').trim() && !(w.description || '').trim())) {
        alert('需要先在"世界设置"里填写大纲或描述，AI 才能据此设计地图。');
        return;
      }
      if (this.mapMeta?.exists && !confirm('已有地图，从文本生成会覆盖现有地形与自动地标。继续？')) return;

      this.mapBusy = true;
      this.mapTextStatus = '正在让 AI 设计地图蓝图…';
      try {
        const p = { ...this.mapGenParams };
        if (!p.seed) p.seed = Math.floor(Math.random() * 1e9);

        const bp = await this.api('POST', `/worlds/${this.currentWorldId}/map/blueprint`, {
          width: p.width, height: p.height,
        });
        if (!bp || !Array.isArray(bp.regions)) throw new Error('蓝图为空');
        this.mapTextStatus = `蓝图就绪：${bp.regions.length} 区域 / ${bp.landmarks.length} 地标，正在渲染…`;

        const r = await this.api('POST', `/worlds/${this.currentWorldId}/map/generate_from_blueprint`, {
          ...p, blueprint: { regions: bp.regions, landmarks: bp.landmarks },
          create_landmark_entities: true,
          replace_existing_landmarks: false,
        });
        this.mapGenParams.seed = p.seed;
        await this.loadMapMeta();
        this.refreshMapImage();
        await this.loadWorld();  // refresh entities so new landmark pins appear
        this.flashToast(`✨ 从文本生成：${r.regions_painted} 区域 · ${r.landmarks_created.length} 地标`);
      } catch (e) {
        alert('从文本生成失败: ' + e.message);
      } finally {
        this.mapBusy = false;
        this.mapTextStatus = '';
      }
    },

    async dropMap() {
      if (!this.currentWorldId) return;
      if (!confirm('确定删除这个世界的地图？')) return;
      try {
        await this.api('DELETE', `/worlds/${this.currentWorldId}/map`);
        await this.loadMapMeta();
        this.mapImgUrl = '';
        this.mapInfo = null;
      } catch (e) { alert('删除失败: ' + e.message); }
    },

    onMapFileSelected(evt) {
      const f = evt.target.files?.[0];
      this.mapImportFile = f || null;
    },

    async importHeightmap() {
      if (!this.currentWorldId || !this.mapImportFile || this.mapBusy) return;
      const p = this.mapImportParams;
      if (p.width * p.height > 4_000_000) { alert('目标分辨率过大（最多 4M 像素）'); return; }
      this.mapBusy = true;
      try {
        const fd = new FormData();
        fd.append('file', this.mapImportFile);
        fd.append('width', String(p.width));
        fd.append('height', String(p.height));
        fd.append('sea_level', String(p.sea_level));
        fd.append('blur', String(p.blur));
        fd.append('contrast', String(p.contrast));
        fd.append('invert', String(!!p.invert));
        fd.append('seed', String(p.seed || 0));
        const r = await fetch(`/api/worlds/${this.currentWorldId}/map/import_heightmap`, {
          method: 'POST', body: fd,
        });
        if (!r.ok) {
          const t = await r.text();
          throw new Error(t || ('HTTP ' + r.status));
        }
        const data = await r.json();
        await this.loadMapMeta();
        this.refreshMapImage();
        await this.loadPinned();
        this.flashToast(`已导入 ${data.width}×${data.height}`);
      } catch (e) {
        alert('导入失败: ' + e.message);
      } finally {
        this.mapBusy = false;
      }
    },

    async inspectMapTile(evt) {
      if (!this.currentWorldId || !this.mapMeta?.exists) return;
      const img = evt.currentTarget;
      const rect = img.getBoundingClientRect();
      const cx = (evt.clientX - rect.left) / rect.width;
      const cy = (evt.clientY - rect.top) / rect.height;
      const x = Math.max(0, Math.min(this.mapMeta.width - 1, Math.floor(cx * this.mapMeta.width)));
      const y = Math.max(0, Math.min(this.mapMeta.height - 1, Math.floor(cy * this.mapMeta.height)));
      try {
        this.mapInfo = await this.api('GET', `/worlds/${this.currentWorldId}/map/tile?x=${x}&y=${y}`);
      } catch (e) { console.warn(e); }
    },

    mapZoomIn() { this.mapZoom = Math.min(8, this.mapZoom * 1.4); },
    mapZoomOut() { this.mapZoom = Math.max(0.25, this.mapZoom / 1.4); },
    mapZoomReset() { this.mapZoom = 1; this.mapPan = { x: 0, y: 0 }; },

    mapWheel(evt) {
      evt.preventDefault();
      const dz = evt.deltaY < 0 ? 1.15 : 1 / 1.15;
      this.mapZoom = Math.max(0.25, Math.min(8, this.mapZoom * dz));
    },

    _tileFromEvent(evt) {
      const img = this.$refs.mapImg;
      if (!img || !this.mapMeta?.exists) return null;
      const rect = img.getBoundingClientRect();
      const cx = (evt.clientX - rect.left) / rect.width;
      const cy = (evt.clientY - rect.top) / rect.height;
      const x = Math.floor(cx * this.mapMeta.width);
      const y = Math.floor(cy * this.mapMeta.height);
      if (x < 0 || y < 0 || x >= this.mapMeta.width || y >= this.mapMeta.height) return null;
      return { x, y };
    },

    mapCanvasDown(evt) {
      if (!this.mapMeta?.exists) return;
      if (this.mapTool === 'paint') {
        this.mapPainting = true;
        const t = this._tileFromEvent(evt);
        if (t) this._enqueuePaint(t.x, t.y);
        evt.preventDefault();
      } else {
        this.mapDragging = true;
        this._mapDragStart = { x: evt.clientX - this.mapPan.x, y: evt.clientY - this.mapPan.y };
      }
    },

    mapCanvasMove(evt) {
      const t = this._tileFromEvent(evt);
      if (t) this.mapHover = t; else this.mapHover = { x: null, y: null };
      if (this.mapPainting && t) {
        this._enqueuePaint(t.x, t.y);
      } else if (this.mapDragging) {
        this.mapPan = {
          x: evt.clientX - this._mapDragStart.x,
          y: evt.clientY - this._mapDragStart.y,
        };
      }
    },

    async mapCanvasUp(evt) {
      if (this.mapPainting) {
        this.mapPainting = false;
        await this._flushPaint();
      } else if (this.mapDragging) {
        const moved = Math.abs((evt.clientX - this._mapDragStart.x) - this.mapPan.x)
          + Math.abs((evt.clientY - this._mapDragStart.y) - this.mapPan.y);
        if (moved < 3 && this.mapTool === 'view') {
          const t = this._tileFromEvent(evt);
          if (t) this.inspectTile(t.x, t.y);
        } else if (moved < 3 && this.mapTool === 'pin') {
          const t = this._tileFromEvent(evt);
          if (t) this.placePinHere(t.x, t.y);
        } else if (moved < 3 && this.mapTool === 'goto') {
          const t = this._tileFromEvent(evt);
          if (t) this.commandGoto(t.x, t.y);
        }
        this.mapDragging = false;
      }
    },

    async inspectTile(x, y) {
      try {
        this.mapInfo = await this.api('GET', `/worlds/${this.currentWorldId}/map/tile?x=${x}&y=${y}`);
      } catch (e) { console.warn(e); }
    },

    _enqueuePaint(x, y) {
      this._paintBuffer.push({ x, y, terrain: this.mapPaintTerrain, brush: this.mapBrushSize });
      // throttle: flush every ~120ms while painting
      if (!this._paintFlushTimer) {
        this._paintFlushTimer = setTimeout(() => this._flushPaint(), 120);
      }
    },

    async _flushPaint() {
      if (this._paintFlushTimer) { clearTimeout(this._paintFlushTimer); this._paintFlushTimer = null; }
      if (!this._paintBuffer.length) return;
      const strokes = this._paintBuffer.splice(0);
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/map/paint`, { strokes });
        this.refreshMapImage();
      } catch (e) { console.warn('paint failed:', e); }
    },

    async clearOverlay() {
      if (!confirm('确定还原所有涂改？')) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/map/clear_overlay`, {});
        this.refreshMapImage();
      } catch (e) { alert('还原失败: ' + e.message); }
    },

    async loadPinned() {
      if (!this.currentWorldId) return;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/map/pinned`);
        this.pinnedEntities = r.items || [];
      } catch (e) { this.pinnedEntities = []; }
    },

    openMapForPin(entity) {
      if (!entity) return;
      this.pinTargetEntity = entity;
      this.mapTool = 'pin';
      this.openMap();
    },

    openMapForGoto(entity) {
      if (!entity) return;
      if (entity.map_x == null || entity.map_y == null) {
        this.flashToast('请先把该实体钉到地图上');
        return;
      }
      this.gotoTargetEntity = entity;
      this.mapTool = 'goto';
      this.openMap();
    },

    async commandGoto(x, y) {
      if (!this.gotoTargetEntity) {
        this.flashToast('请先在实体面板点「🎯 指挥」选中目标');
        return;
      }
      try {
        await this.api('POST',
          `/worlds/${this.currentWorldId}/map/entity/${this.gotoTargetEntity.id}/goto`,
          { x, y, speed: this.gotoTargetEntity.move_speed || 2.0 });
        this.flashToast(`${this.gotoTargetEntity.name} → (${x}, ${y})`);
        await this.refreshSimStatus();
      } catch (e) { alert('指挥失败: ' + e.message); }
    },

    async simStep(n) {
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/map/sim/tick`, { ticks: n });
        await this.refreshSimStatus();
        await this.loadPinned();
      } catch (e) { console.warn('sim tick failed', e); }
    },

    simToggle() {
      if (this.simPlaying) {
        clearInterval(this.simInterval);
        this.simInterval = null;
        this.simPlaying = false;
        return;
      }
      this.simPlaying = true;
      this.simInterval = setInterval(() => {
        if (!this.showMap) { this.simToggle(); return; }
        this.simStep(2);
      }, 500);
    },

    async refreshSimStatus() {
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/map/sim/status`);
        this.simStatus = r.items || [];
      } catch (e) { /* silent */ }
    },

    async placePinHere(x, y) {
      if (!this.pinTargetEntity) {
        this.flashToast('请先在实体面板点「📍 钉位」选中目标');
        return;
      }
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/map/pin`, {
          entity_id: this.pinTargetEntity.id, x, y,
        });
        this.pinTargetEntity.map_x = x;
        this.pinTargetEntity.map_y = y;
        this.flashToast(`已钉位 ${this.pinTargetEntity.name} → (${x}, ${y})`);
        await this.loadPinned();
        await this.loadWorld();
      } catch (e) { alert('钉位失败: ' + e.message); }
    },

    async unpinEntity(entity) {
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/map/pin`, { entity_id: entity.id });
        entity.map_x = null;
        entity.map_y = null;
        await this.loadPinned();
        await this.loadWorld();
      } catch (e) { alert('取消钉位失败: ' + e.message); }
    },

    async loadStats() {
      if (!this.currentWorldId) return;
      try {
        this.stats = await this.api('GET', `/worlds/${this.currentWorldId}/stats`);
      } catch (e) { alert('载入统计失败: ' + e.message); }
    },

    manuscriptText() {
      if (!this.manuscript) return '';
      if (this.manuscript.format === 'json') return JSON.stringify(this.manuscript, null, 2);
      return this.manuscript.content || '';
    },

    async generateManuscript() {
      if (!this.currentWorldId || this.msGenerating) return;
      if (this.msMode === 'pov' && !this.msPovEntityId) {
        alert('请先选择 POV 角色');
        return;
      }
      this.msGenerating = true;
      try {
        const body = {
          format: this.msFormat,
          style_hint: this.msStyle || '',
          provider: this.provider,
        };
        if (this.msFrom !== null && this.msFrom !== '' && this.msTo !== null && this.msTo !== '') {
          body.chapter_from = parseInt(this.msFrom);
          body.chapter_to = parseInt(this.msTo);
        }
        let r;
        if (this.msMode === 'pov') {
          body.entity_id = this.msPovEntityId;
          r = await this.api('POST', `/worlds/${this.currentWorldId}/pov`, body);
        } else {
          body.polish = this.msPolish;
          r = await this.api('POST', `/worlds/${this.currentWorldId}/manuscript`, body);
        }
        this.manuscript = r;
        this.flashToast(`已生成 ${r.chapter_count} 章 / ${r.total_chars} 字`);
      } catch (e) {
        alert('生成失败: ' + e.message);
      } finally {
        this.msGenerating = false;
      }
    },

    copyManuscript() {
      const text = this.manuscriptText();
      if (!text) return;
      navigator.clipboard.writeText(text).then(
        () => this.flashToast('已复制到剪贴板'),
        () => this.flashToast('复制失败'),
      );
    },

    downloadManuscript() {
      if (!this.manuscript) return;
      const ext = this.msFormat === 'markdown' ? 'md' : (this.msFormat === 'json' ? 'json' : 'txt');
      const base = (this.world?.world?.name || 'manuscript');
      const suffix = this.msMode === 'pov' && this.manuscript.pov_name ? `_${this.manuscript.pov_name}视角` : '';
      const filename = `${(base + suffix).replace(/[\\/:*?"<>|]/g,'_')}.${ext}`;
      const text = this.manuscriptText();
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      this.flashToast('已下载: ' + filename);
    },

    async upgradeToNext() {
      const next = this.nextSeriesTemplate();
      if (!next) return;
      const ok = confirm(
        `进入下一篇章「${next.name}」？\n\n` +
        `· 现有人物、事件、叙事全部保留\n` +
        `· 切换到新篇章的规则与剧情向导\n` +
        `· 推演上限会增加 ${next.max_steps_hint || 30} 步`
      );
      if (!ok) return;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/upgrade_to_template`,
          { target_template_id: next.id, keep_entities: true });
        this.flashToast(`已进入「${r.template_name}」 · 上限 ${r.max_tick}`);
        await this.loadWorld();
        if (r.seed_directive) this.directive = r.seed_directive;
      } catch (e) { alert('升级失败: ' + e.message); }
    },

    async refreshTimeline() {
      this.timeline = await this.api('GET', `/worlds/${this.currentWorldId}/timeline?branch_id=${this.currentBranchId}`);
    },

    activeBranch() {
      return this.branches.find(b => b.is_active) || null;
    },

    async switchBranch(branchId) {
      if (!this.currentWorldId || !branchId) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/switch_branch/${branchId}`);
        this.pendingChanges = [];
        this.compareWith = null;
        if (this.cyCompare) { this.cyCompare.destroy(); this.cyCompare = null; }
        await this.loadWorld();
        this.showBranches = false;
      } catch (e) {
        alert('切换分支失败: ' + e.message);
      }
    },

    startEditBranch(branch) {
      this.branchEditDraft = { id: branch.id, name: branch.name };
    },

    async saveBranchEdit() {
      const d = this.branchEditDraft;
      if (!d.id || !d.name.trim()) { this.branchEditDraft = { id: '', name: '' }; return; }
      try {
        await this.api('PATCH', `/branches/${d.id}`, { name: d.name.trim() });
        this.branchEditDraft = { id: '', name: '' };
        await this.loadWorld();
      } catch (e) {
        alert('重命名失败: ' + e.message);
      }
    },

    async deleteBranch(branch) {
      if (branch.is_main) return;
      if (!confirm(`确定删除分支「${branch.name}」？\n该分支的 ${branch.event_count} 个事件、${branch.entity_count} 个实体将一并删除，不可恢复。`)) return;
      try {
        await this.api('DELETE', `/branches/${branch.id}`);
        if (this.compareWith === branch.id) {
          this.compareWith = null;
          if (this.cyCompare) { this.cyCompare.destroy(); this.cyCompare = null; }
        }
        await this.loadWorld();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    async startCompare(branchId) {
      if (!branchId || branchId === this.currentBranchId) return;
      this.compareWith = branchId;
      this.showBranches = false;
      try {
        this.compareTimeline = await this.api('GET', `/worlds/${this.currentWorldId}/timeline?branch_id=${branchId}`);
        this.viewMode = 'graph';
        this.$nextTick(() => {
          this.renderGraph();
          this.renderCompareGraph();
        });
      } catch (e) {
        alert('加载对比分支失败: ' + e.message);
        this.compareWith = null;
      }
    },

    stopCompare() {
      this.compareWith = null;
      this.compareTimeline = { events: [], links: [], narration: [] };
      if (this.cyCompare) { this.cyCompare.destroy(); this.cyCompare = null; }
      this.$nextTick(() => this.renderGraph());
    },

    renderCompareGraph() {
      const el = document.getElementById('cy-compare');
      if (!el) return;
      const events = this.compareTimeline.events || [];
      const links = this.compareTimeline.links || [];
      const eventIds = new Set(events.map(e => e.id));
      const validLinks = links.filter(l => eventIds.has(l.cause) && eventIds.has(l.effect));
      const truncate = (s, n) => (s && s.length > n) ? s.slice(0, n) + '…' : (s || '');

      const degree = {};
      events.forEach(e => { degree[e.id] = 0; });
      validLinks.forEach(l => {
        degree[l.cause] = (degree[l.cause] || 0) + 1;
        degree[l.effect] = (degree[l.effect] || 0) + 1;
      });

      const ticks = events.map(e => e.tick);
      const tMin = ticks.length ? Math.min(...ticks) : 0;
      const tMax = ticks.length ? Math.max(...ticks) : 0;
      const tSpan = Math.max(1, tMax - tMin);
      const colorForTick = (tick) => {
        const t = (tick - tMin) / tSpan;
        return `hsl(${(280 - t * 80).toFixed(0)}, ${(50 + t * 25).toFixed(0)}%, ${(34 + t * 16).toFixed(0)}%)`;
      };

      const ourEventIds = new Set(this.timeline.events.map(e => e.id));
      const ourLinkKeys = new Set(this.timeline.links.map(l => l.cause + '__' + l.effect));

      const sorted = events.slice().sort((a, b) => a.tick - b.tick || (a.id || '').localeCompare(b.id || ''));
      const stepNo = new Map(sorted.map((e, i) => [e.id, i + 1]));

      const elements = [
        ...events.map(e => {
          const importance = (degree[e.id] || 0) + (e.participants || []).length;
          const isNew = !ourEventIds.has(e.id);
          const step = stepNo.get(e.id) || 0;
          const title = e.title || '(无标题)';
          return {
            data: {
              id: e.id,
              label: `第 ${step} 步\n${title}`,
              title,
              description: e.description || '',
              tick: e.tick,
              step,
              participants: (e.participants || []).map(p => this.nameOf(p)).join('、'),
              fillColor: colorForTick(e.tick),
              fontSize: 11 + Math.min(3, importance * 0.4),
              isNew,
            },
            classes: isNew ? 'is-new' : '',
          };
        }),
        ...validLinks.map(l => ({
          data: {
            id: `${l.cause}__${l.effect}`,
            source: l.cause,
            target: l.effect,
            description: l.description || '',
            edgeLabel: truncate(l.description || '', 22),
            isNew: !ourLinkKeys.has(l.cause + '__' + l.effect),
          },
        })),
      ];

      if (this.cyCompare) { this.cyCompare.destroy(); this.cyCompare = null; }
      if (elements.length === 0) return;

      const useDagre = this._dagreRegistered;
      this.cyCompare = cytoscape({
        container: el,
        elements,
        wheelSensitivity: 0.25,
        style: [
          { selector: 'node', style: {
            'background-color': 'data(fillColor)',
            'background-opacity': 0.92,
            'border-color': '#3b0764',
            'border-width': 1.5,
            'label': 'data(label)',
            'color': '#fafafa',
            'font-size': 'data(fontSize)',
            'font-family': 'system-ui, -apple-system, sans-serif',
            'font-weight': 500,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'text-max-width': 180,
            'line-height': 1.25,
            'width': 'label',
            'height': 'label',
            'padding': 12,
            'shape': 'round-rectangle',
            'text-outline-color': '#09090b',
            'text-outline-width': 1.2,
          }},
          { selector: 'node.is-new', style: {
            'border-color': '#fbbf24',
            'border-width': 3,
          }},
          { selector: 'edge', style: {
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'line-color': '#52525b',
            'target-arrow-color': '#a1a1aa',
            'width': 1.6,
            'arrow-scale': 1.3,
            'label': 'data(edgeLabel)',
            'font-size': 9,
            'color': '#d4d4d8',
            'text-rotation': 'autorotate',
            'text-background-color': '#09090b',
            'text-background-opacity': 0.85,
            'text-background-padding': 3,
          }},
          { selector: 'edge[?isNew]', style: {
            'line-color': '#fbbf24',
            'target-arrow-color': '#fbbf24',
            'width': 2.2,
          }},
        ],
        layout: useDagre
          ? { name: 'dagre', rankDir: 'LR', nodeSep: 50, rankSep: 130, edgeSep: 18, padding: 24, animate: false }
          : { name: 'breadthfirst', directed: true, spacingFactor: 1.6, padding: 24 },
      });
      this.cyCompare.fit(null, 30);
    },

    nameOf(id) {
      const e = this.entities.find(e => e.id === id);
      return e ? e.name : id.slice(0, 8);
    },

    entityById(id) {
      return this.entities.find(e => e.id === id) || null;
    },

    entityAvatar(entity) {
      if (!entity) return { initial: '?', color: '#3f3f46' };
      const name = entity.name || '?';
      const initial = name.charAt(0).toUpperCase();
      let h = 0;
      for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
      const hue = h % 360;
      const sat = entity.type === 'location' ? 30 : entity.type === 'item' ? 45 : 60;
      const lit = 38;
      return { initial, color: `hsl(${hue}, ${sat}%, ${lit}%)` };
    },

    typeLabel(type) {
      return ({
        character: '角色',
        location: '地点',
        item: '物品',
        organization: '组织',
        faction: '势力',
        concept: '概念',
      })[type] || type;
    },

    entityEvents(entity) {
      if (!entity) return [];
      const events = this.timeline.events || [];
      if (entity.type === 'location') {
        return events.filter(e => e.location_id === entity.id).slice().sort((a, b) => a.tick - b.tick);
      }
      return events.filter(e => (e.participants || []).includes(entity.id)).slice().sort((a, b) => a.tick - b.tick);
    },

    coOccurrence(entity) {
      if (!entity || entity.type === 'location') return [];
      const map = {};
      for (const ev of this.entityEvents(entity)) {
        for (const pid of (ev.participants || [])) {
          if (pid === entity.id) continue;
          map[pid] = (map[pid] || 0) + 1;
        }
      }
      return Object.entries(map)
        .map(([id, count]) => ({ entity: this.entityById(id), count }))
        .filter(x => x.entity)
        .sort((a, b) => b.count - a.count);
    },

    entitiesAtLocation(location) {
      if (!location) return [];
      return this.entities.filter(e => e.id !== location.id && (e.state?.location_id === location.id || e.location_id === location.id));
    },

    formatAttrValue(v) {
      if (v === null || v === undefined) return '—';
      if (Array.isArray(v)) return v.map(x => this.formatAttrValue(x)).join('、');
      if (typeof v === 'object') return JSON.stringify(v, null, 2);
      if (typeof v === 'boolean') return v ? '是' : '否';
      return String(v);
    },

    attrRows(entity) {
      const a = entity?.attributes || {};
      return Object.entries(a).map(([k, v]) => ({ key: k, value: this.formatAttrValue(v) }));
    },

    stateRows(entity) {
      const s = entity?.state || {};
      const rows = [];
      const skip = new Set(['location_id']);
      for (const [k, v] of Object.entries(s)) {
        if (skip.has(k)) continue;
        rows.push({ key: k, value: this.formatAttrValue(v) });
      }
      return rows;
    },

    locationOf(entity) {
      const lid = entity?.state?.location_id || entity?.location_id;
      return lid ? this.entityById(lid) : null;
    },

    selectEntity(entityOrId) {
      const ent = typeof entityOrId === 'string' ? this.entityById(entityOrId) : entityOrId;
      if (!ent) return;
      this.selectedEntity = ent;
      this.syncPersonaForm(ent);
    },

    syncPersonaForm(ent) {
      const p = (ent && ent.persona) || {};
      this.personaForm = {
        drivesText: (p.drives || []).join('\n'),
        voice: p.voice || '',
        blindspotsText: (p.knowledge_blindspots || []).join('\n'),
        knowledgeOfText: (p.knowledge_of || []).join('\n'),
      };
      this.personaDirty = false;
    },

    resetPersonaForm() {
      this.syncPersonaForm(this.selectedEntity);
    },

    async savePersona() {
      if (!this.selectedEntity || this.personaSaving) return;
      const splitLines = (s) => (s || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean);
      const persona = {
        drives: splitLines(this.personaForm.drivesText),
        voice: (this.personaForm.voice || '').trim(),
        knowledge_blindspots: splitLines(this.personaForm.blindspotsText),
        knowledge_of: splitLines(this.personaForm.knowledgeOfText),
      };
      // drop empty fields so we don't write {drives:[],voice:'',...} clutter
      Object.keys(persona).forEach(k => {
        const v = persona[k];
        if (Array.isArray(v) && v.length === 0) delete persona[k];
        else if (typeof v === 'string' && !v) delete persona[k];
      });
      this.personaSaving = true;
      try {
        await this.api('PATCH', `/entities/${this.selectedEntity.id}`, { persona });
        // mirror locally so UI stays consistent without a full reload
        this.selectedEntity.persona = persona;
        const idx = this.entities.findIndex(e => e.id === this.selectedEntity.id);
        if (idx >= 0) this.entities[idx].persona = persona;
        this.personaDirty = false;
        this.flashToast('🎭 人设已保存');
      } catch (e) {
        alert('保存失败: ' + e.message);
      } finally {
        this.personaSaving = false;
      }
    },

    async extractPersona() {
      if (!this.selectedEntity || this.personaExtracting) return;
      if (this.selectedEntity.type !== 'character') {
        alert('只有角色才能萃取人设');
        return;
      }
      this.personaExtracting = true;
      this.personaExtractMsg = '正在分析事件...';
      try {
        const res = await this.api('POST', `/entities/${this.selectedEntity.id}/extract_persona`, {
          branch_id: this.currentBranchId || null,
        });
        if (!res.ok) {
          alert('萃取失败：' + (res.reason || '未知原因'));
          return;
        }
        this.personaSuggestion = res;
        this.showPersonaSuggestion = true;
      } catch (e) {
        alert('萃取失败: ' + e.message);
      } finally {
        this.personaExtracting = false;
        this.personaExtractMsg = '';
      }
    },

    closePersonaSuggestion() {
      this.showPersonaSuggestion = false;
      this.personaSuggestion = null;
    },

    applyPersonaSuggestion(mode) {
      // mode: 'replace' (覆盖当前) | 'merge' (并入当前，去重)
      if (!this.personaSuggestion || !this.personaSuggestion.suggestion) return;
      const s = this.personaSuggestion.suggestion;
      const dedup = (arr) => Array.from(new Set((arr || []).map(x => String(x).trim()).filter(Boolean)));

      const existing = {
        drives: (this.personaForm.drivesText || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        blindspots: (this.personaForm.blindspotsText || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        knowledgeOf: (this.personaForm.knowledgeOfText || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        voice: (this.personaForm.voice || '').trim(),
      };

      let drives, blindspots, knowledgeOf, voice;
      if (mode === 'merge') {
        drives = dedup([...existing.drives, ...(s.drives || [])]);
        blindspots = dedup([...existing.blindspots, ...(s.knowledge_blindspots || s.blindspots || [])]);
        knowledgeOf = dedup([...existing.knowledgeOf, ...(s.knowledge_of || [])]);
        voice = existing.voice || (s.voice || '');
      } else {
        drives = dedup(s.drives || []);
        blindspots = dedup(s.knowledge_blindspots || s.blindspots || []);
        knowledgeOf = dedup(s.knowledge_of || []);
        voice = (s.voice || '').trim();
      }

      this.personaForm = {
        drivesText: drives.join('\n'),
        voice: voice,
        blindspotsText: blindspots.join('\n'),
        knowledgeOfText: knowledgeOf.join('\n'),
      };
      this.personaDirty = true;
      this.showPersonaSuggestion = false;
      this.flashToast(mode === 'merge' ? '✨ 已并入建议，记得保存' : '✨ 已采纳建议，记得保存');
    },

    jumpToEvent(eventId) {
      this.viewMode = 'timeline';
      this.$nextTick(() => {
        const el = document.getElementById('tl-' + eventId);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('flash-highlight');
          setTimeout(() => el.classList.remove('flash-highlight'), 1500);
        }
      });
    },    storyChapters() {
      const events = (this.timeline.events || []).slice().sort((a, b) => a.tick - b.tick || a.id.localeCompare(b.id));
      const narrationByTick = {};
      for (const n of (this.timeline.narration || [])) {
        (narrationByTick[n.tick] = narrationByTick[n.tick] || []).push(n.text);
      }
      const chapters = [];
      let lastTick = null;
      let chapter = null;
      const CHAPTER_GAP = 3;
      for (const ev of events) {
        if (lastTick === null || ev.tick - lastTick > CHAPTER_GAP) {
          chapter = { startTick: ev.tick, endTick: ev.tick, scenes: [] };
          chapters.push(chapter);
        } else {
          chapter.endTick = ev.tick;
        }
        chapter.scenes.push({
          ...ev,
          locationName: ev.location_id ? this.nameOf(ev.location_id) : '',
          participantNames: (ev.participants || []).map(p => this.nameOf(p)),
          participants: ev.participants || [],
          narration: narrationByTick[ev.tick] || [],
        });
        lastTick = ev.tick;
      }
      const usedTicks = new Set(events.map(e => e.tick));
      const orphan = (this.timeline.narration || []).filter(n => !usedTicks.has(n.tick));
      if (orphan.length) {
        chapters.push({
          startTick: orphan[0].tick,
          endTick: orphan[orphan.length - 1].tick,
          scenes: [],
          orphanNarration: orphan.map(o => ({ tick: o.tick, text: o.text })),
        });
      }
      return chapters;
    },

    storyTitle() {
      const w = this.world?.world;
      const branch = this.activeBranch();
      if (!w) return '未命名';
      return branch && !branch.is_main ? `${w.name} · ${branch.name}` : w.name;
    },

    splitParagraphs(text) {
      return String(text || '').split(/\n+/).map(s => s.trim()).filter(Boolean);
    },

    buildMarkdown() {
      const w = this.world?.world;
      if (!w) return '';
      const lines = [];
      lines.push(`# ${this.storyTitle()}`);
      if (w.description) lines.push('', `> ${w.description}`);
      lines.push('', `*tick 0 — ${w.current_tick} · 共 ${this.timeline.events.length} 事件*`, '');
      for (const chap of this.storyChapters()) {
        const span = chap.startTick === chap.endTick ? `t${chap.startTick}` : `t${chap.startTick} — t${chap.endTick}`;
        lines.push('', `## 第 ${span} 段`, '');
        for (const sc of chap.scenes) {
          lines.push(`### ${sc.title}`);
          const meta = [`tick ${sc.tick}`];
          if (sc.locationName) meta.push(`地点: ${sc.locationName}`);
          if (sc.participantNames.length) meta.push(`参与: ${sc.participantNames.join('、')}`);
          lines.push(`*${meta.join(' · ')}*`, '');
          if (sc.description) {
            for (const p of this.splitParagraphs(sc.description)) lines.push(p, '');
          }
          for (const n of sc.narration) {
            for (const p of this.splitParagraphs(n)) lines.push(`> ${p}`, '');
          }
        }
        if (chap.orphanNarration) {
          for (const o of chap.orphanNarration) {
            for (const p of this.splitParagraphs(o.text)) lines.push(`> ${p}`, '');
          }
        }
      }
      return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
    },

    async copyStoryMarkdown() {
      const md = this.buildMarkdown();
      if (!md) return;
      try {
        await navigator.clipboard.writeText(md);
        this.flashToast('已复制 Markdown 到剪贴板');
      } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = md;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        this.flashToast('已复制（兼容模式）');
      }
    },

    downloadStoryMarkdown() {
      const md = this.buildMarkdown();
      if (!md) return;
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const safeName = this.storyTitle().replace(/[\\/:*?"<>|]/g, '_');
      a.download = `${safeName}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    flashToast(msg) {
      this.toastMsg = msg;
      clearTimeout(this._toastT);
      this._toastT = setTimeout(() => { this.toastMsg = ''; }, 1800);
    },

    toggleFocusMode() {
      this.focusMode = !this.focusMode;
      document.body.classList.toggle('focus-mode', this.focusMode);
    },

    async exportWorld() {
      if (!this.currentWorldId) return;
      try {
        const data = await this.api('GET', `/worlds/${this.currentWorldId}/export`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const safeName = (this.world?.world?.name || 'world').replace(/[\\/:*?"<>|]/g, '_');
        const ts = new Date().toISOString().slice(0, 10);
        a.download = `${safeName}_${ts}.world.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        this.flashToast('已导出世界 JSON');
      } catch (e) {
        alert('导出失败: ' + e.message);
      }
    },

    chatStorageKey(entityId) {
      return `chat:${this.currentWorldId || 'na'}:${entityId}`;
    },

    openCharacterChat(entity) {
      if (!entity || entity.type !== 'character') return;
      this.chatTarget = entity;
      this.chatViewTick = this.world?.world?.current_tick ?? 0;
      const saved = localStorage.getItem(this.chatStorageKey(entity.id));
      this.chatHistory = saved ? JSON.parse(saved) : [];
      this.chatInput = '';
      this.$nextTick(() => {
        const el = document.getElementById('chat-input');
        if (el) el.focus();
        this.scrollChatBottom();
      });
    },

    closeCharacterChat() {
      this.cancelChatSend();
      this.chatTarget = null;
      this.chatHistory = [];
      this.chatInput = '';
    },

    clearChatHistory() {
      if (!this.chatTarget) return;
      if (!confirm('清空与 ' + this.chatTarget.name + ' 的对话记录？')) return;
      this.chatHistory = [];
      localStorage.removeItem(this.chatStorageKey(this.chatTarget.id));
    },

    scrollChatBottom() {
      this.$nextTick(() => {
        const box = document.getElementById('chat-messages');
        if (box) box.scrollTop = box.scrollHeight;
      });
    },

    persistChat() {
      if (!this.chatTarget) return;
      try { localStorage.setItem(this.chatStorageKey(this.chatTarget.id), JSON.stringify(this.chatHistory.slice(-100))); } catch {}
    },

    async sendChat() {
      const msg = (this.chatInput || '').trim();
      if (!msg || !this.chatTarget || this.chatSending) return;
      const target = this.chatTarget;
      const history = this.chatHistory.map(t => ({ role: t.role, content: t.content }));
      this.chatHistory.push({ role: 'user', content: msg, t: Date.now() });
      this.persistChat();
      this.chatInput = '';
      this.chatSending = true;
      this.scrollChatBottom();
      const controller = new AbortController();
      this.chatAbort = controller;
      try {
        const res = await fetch(`/api/entities/${target.id}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: msg,
            history,
            view_tick: this.chatViewTick,
            provider: this.provider,
          }),
          signal: controller.signal,
        });
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(`${res.status} ${txt}`);
        }
        const data = await res.json();
        if (this.chatTarget?.id === target.id) {
          this.chatHistory.push({ role: 'assistant', content: data.reply, t: Date.now() });
          this.persistChat();
          this.scrollChatBottom();
        }
      } catch (e) {
        if (e.name !== 'AbortError') {
          this.chatHistory.push({ role: 'assistant', content: '（无法回应：' + e.message + '）', error: true, t: Date.now() });
          this.persistChat();
        }
      } finally {
        this.chatSending = false;
        this.chatAbort = null;
      }
    },

    cancelChatSend() {
      if (this.chatAbort) {
        try { this.chatAbort.abort(); } catch {}
        this.chatAbort = null;
        this.chatSending = false;
      }
    },

    async openHistory() {
      if (!this.currentWorldId) return;
      this.showHistory = true;
      await this.loadHistory();
    },

    async loadHistory() {
      if (!this.currentWorldId) return;
      this.historyLoading = true;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/history`);
        this.historyList = r.snapshots || [];
      } catch (e) {
        alert('读取历史失败: ' + e.message);
      } finally {
        this.historyLoading = false;
      }
    },

    async restoreSnapshot(snap) {
      if (!confirm(`回滚到 "${snap.label || ('t' + snap.tick)}"？\n当前状态会先存为快照可再恢复，但本次推演产生的事件将被覆盖。`)) return;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/restore/${snap.id}`);
        this.flashToast(`已回滚到 t${r.restored_tick}`);
        this.showHistory = false;
        await this.loadWorld();
        await this.refreshWorlds();
      } catch (e) {
        alert('回滚失败: ' + e.message);
      }
    },

    async deleteSnapshot(snap) {
      if (!confirm(`删除快照 "${snap.label || ('t' + snap.tick)}"？此操作不可撤销。`)) return;
      try {
        await this.api('DELETE', `/snapshots/${snap.id}`);
        await this.loadHistory();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    formatHistoryTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    },

    openSearch() {
      this.showSearch = true;
      this.searchQuery = '';
      this.searchSelectedIndex = 0;
      this.$nextTick(() => {
        const el = document.getElementById('search-input');
        if (el) el.focus();
      });
    },

    closeSearch() {
      this.showSearch = false;
      this.searchQuery = '';
    },

    get searchResults() {
      const q = (this.searchQuery || '').trim().toLowerCase();
      if (!q) return [];
      const out = [];
      for (const e of this.entities) {
        const hay = [e.name, e.summary, JSON.stringify(e.attributes || {}), JSON.stringify(e.state || {})].join(' ').toLowerCase();
        if (hay.includes(q)) {
          out.push({ kind: 'entity', id: e.id, title: e.name, sub: this.typeLabel(e.type) + (e.summary ? ' · ' + e.summary : ''), data: e });
        }
      }
      for (const ev of (this.timeline.events || [])) {
        const hay = [ev.title, ev.description].join(' ').toLowerCase();
        if (hay.includes(q)) {
          out.push({ kind: 'event', id: ev.id, title: 't' + ev.tick + ' · ' + ev.title, sub: (ev.description || '').slice(0, 80), data: ev });
        }
      }
      for (const n of (this.timeline.narration || [])) {
        if ((n.text || '').toLowerCase().includes(q)) {
          out.push({ kind: 'narration', id: n.id, title: 't' + n.tick + ' · ' + (n.role || '叙述'), sub: (n.text || '').slice(0, 100), data: n });
        }
      }
      return out.slice(0, 50);
    },

    pickSearch(item) {
      if (!item) return;
      if (item.kind === 'entity') {
        this.selectEntity(item.data);
      } else if (item.kind === 'event') {
        this.jumpToEvent(item.id);
      } else if (item.kind === 'narration') {
        this.viewMode = 'reading';
      }
      this.closeSearch();
    },

    searchKeyDown(e) {
      const results = this.searchResults;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.searchSelectedIndex = Math.min(results.length - 1, this.searchSelectedIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.searchSelectedIndex = Math.max(0, this.searchSelectedIndex - 1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        this.pickSearch(results[this.searchSelectedIndex]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this.closeSearch();
      }
    },

    openWorldSettings() {
      if (!this.world?.world) return;
      const w = this.world.world;
      const r = w.rules || {};
      this.settingsDraft = {
        name: w.name || '',
        description: w.description || '',
        outline: w.outline || '',
        core_rules: Array.isArray(r.core_rules) ? [...r.core_rules] : [],
        forbidden: Array.isArray(r.forbidden) ? [...r.forbidden] : [],
        tone: r.tone || '',
        language: r.language || '',
        notes: r.notes || '',
        style_profile_id: w.style_profile_id || '',
      };
      this.stylePreview = { id: '', name: '', spec_text: '', samples: [] };
      this.showWorldSettings = true;
      // 异步加载风格列表（不阻塞弹窗显示）
      this.loadStyles();
    },

    async loadStyles() {
      try {
        const r = await this.api('GET', '/style_profiles');
        this.stylesAvailable = r.profiles || [];
      } catch (e) {
        console.error('loadStyles', e);
        this.stylesAvailable = [];
      }
    },

    async previewStyleSpec(styleId) {
      if (!styleId) return;
      // 第二次点同一卡片 = 关闭预览
      if (this.stylePreview.id === styleId) {
        this.stylePreview = { id: '', name: '', spec_text: '', samples: [] };
        return;
      }
      try {
        const sp = await this.api('GET', `/style_profiles/${styleId}`);
        this.stylePreview = {
          id: sp.id, name: sp.name,
          spec_text: sp.spec_text || '',
          samples: Array.isArray(sp.sample_paragraphs) ? sp.sample_paragraphs : [],
        };
      } catch (e) {
        console.error('previewStyle', e);
      }
    },

    addRuleLine(field) {
      this.settingsDraft[field] = [...(this.settingsDraft[field] || []), ''];
      this.$nextTick(() => {
        const inputs = document.querySelectorAll(`[data-rule-field="${field}"]`);
        const last = inputs[inputs.length - 1];
        if (last) last.focus();
      });
    },

    removeRuleLine(field, idx) {
      this.settingsDraft[field] = (this.settingsDraft[field] || []).filter((_, i) => i !== idx);
    },

    async saveWorldSettings() {
      if (!this.currentWorldId) return;
      this.settingsSaving = true;
      try {
        const cleanLines = (arr) => (arr || []).map(s => (s || '').trim()).filter(s => s);
        const rules = {
          core_rules: cleanLines(this.settingsDraft.core_rules),
          forbidden: cleanLines(this.settingsDraft.forbidden),
          tone: (this.settingsDraft.tone || '').trim(),
          language: (this.settingsDraft.language || '').trim(),
          notes: (this.settingsDraft.notes || '').trim(),
        };
        await this.api('PATCH', `/worlds/${this.currentWorldId}`, {
          name: (this.settingsDraft.name || '').trim() || undefined,
          description: this.settingsDraft.description || '',
          outline: this.settingsDraft.outline || '',
          rules,
          style_profile_id: this.settingsDraft.style_profile_id || '',
        });
        this.showWorldSettings = false;
        this.flashToast('已保存世界设置');
        await this.loadWorld();
        await this.refreshWorlds();
      } catch (e) {
        alert('保存失败: ' + e.message);
      } finally {
        this.settingsSaving = false;
      }
    },

    rulesPreview() {
      const r = this.world?.world?.rules || {};
      const lines = [];
      if (Array.isArray(r.core_rules) && r.core_rules.length) {
        lines.push('## 这个世界的硬性设定（必须遵守，不得违反）');
        for (const c of r.core_rules) if (c) lines.push('- ' + c);
      }
      if (Array.isArray(r.forbidden) && r.forbidden.length) {
        lines.push('\n## 严格禁止');
        for (const c of r.forbidden) if (c) lines.push('- ' + c);
      }
      if (r.tone) lines.push('\n## 叙事基调\n' + r.tone);
      if (r.language) lines.push('\n## 语言风格\n' + r.language);
      if (r.notes) lines.push('\n## 其他备注\n' + r.notes);
      return lines.join('\n') || '（无规则——AI 会完全按它的判断推演）';
    },

    rulesSummary() {
      const r = this.world?.world?.rules || {};
      const counts = [];
      const cn = (r.core_rules || []).filter(Boolean).length;
      const fn = (r.forbidden || []).filter(Boolean).length;
      if (cn) counts.push(cn + ' 条硬规则');
      if (fn) counts.push(fn + ' 条禁忌');
      if (r.tone) counts.push('基调');
      if (r.language) counts.push('风格');
      return counts.length ? counts.join(' · ') : '未设规则';
    },

    openExplore() {
      if (!this.currentWorldId) return;
      this.exploreVariants = [{ label: 'A', directive: '' }, { label: 'B', directive: '' }];
      this.exploreSteps = 1;
      this.exploreJobs = [];
      this.exploreActive = false;
      this.showExplore = true;
    },

    addVariant() {
      if (this.exploreVariants.length >= 5) return;
      const labels = ['A', 'B', 'C', 'D', 'E'];
      this.exploreVariants.push({ label: labels[this.exploreVariants.length], directive: '' });
    },

    removeVariant(idx) {
      if (this.exploreVariants.length <= 2) return;
      this.exploreVariants.splice(idx, 1);
    },

    async startExplore() {
      const variants = this.exploreVariants
        .map(v => ({ label: (v.label || '').trim(), directive: (v.directive || '').trim() }))
        .filter(v => v.directive);
      if (variants.length < 2) {
        alert('至少需要 2 个不同的指令');
        return;
      }
      this.exploreActive = true;
      this.exploreJobs = [];
      this.exploreRecommended = '';
      this.exploreReasoning = '';
      this.exploreParentTick = this.world?.world?.current_tick ?? 0;
      try {
        const res = await this.api('POST', `/worlds/${this.currentWorldId}/explore`, {
          variants,
          steps: this.exploreSteps,
          provider: this.provider,
        });
        this.exploreParentBranchId = res.parent_branch_id;
        this.exploreJobs = (res.variants || []).map(v => ({
          ...v,
          status: 'running', progress_message: '启动中…',
          tool_calls: [], narration: '', result: null, error: null,
          scores: null, verdict: '', total: 0,
        }));
        this.pollExploreJobs();
      } catch (e) {
        alert('启动并发探索失败: ' + e.message);
        this.exploreActive = false;
      }
    },

    async pollExploreJobs() {
      while (this.exploreActive && this.exploreJobs.some(j => j.status === 'running' || j.status === 'pending')) {
        await new Promise(r => setTimeout(r, 800));
        for (const j of this.exploreJobs) {
          if (j.status !== 'running' && j.status !== 'pending') continue;
          try {
            const data = await this.api('GET', `/jobs/${j.job_id}`);
            j.status = data.status;
            j.progress_message = data.progress_message || j.progress_message;
            j.tool_calls = data.tool_calls || [];
            j.narration = data.narration || '';
            j.result = data.result || null;
            j.error = data.error || null;
          } catch (e) {
            j.status = 'error';
            j.error = e.message;
          }
        }
      }
      const completed = this.exploreJobs.filter(j => j.status === 'completed');
      if (completed.length >= 2 && this.exploreActive) {
        this.evaluateVariants();
      }
    },

    async evaluateVariants() {
      const completedIds = this.exploreJobs.filter(j => j.status === 'completed').map(j => j.branch_id);
      if (completedIds.length < 2 || !this.exploreParentBranchId) return;
      this.exploreEvaluating = true;
      try {
        const res = await this.api('POST', `/worlds/${this.currentWorldId}/evaluate_variants`, {
          variant_branch_ids: completedIds,
          parent_branch_id: this.exploreParentBranchId,
          parent_tick: this.exploreParentTick,
          provider: this.provider,
        }, 60000);
        const byId = Object.fromEntries((res.evaluations || []).map(e => [e.branch_id, e]));
        for (const j of this.exploreJobs) {
          const e = byId[j.branch_id];
          if (e) {
            j.scores = e.scores;
            j.total = e.total;
            j.verdict = e.verdict;
          }
        }
        this.exploreRecommended = res.recommended || '';
        this.exploreReasoning = res.reasoning || '';
      } catch (e) {
        console.warn('evaluate failed:', e);
      } finally {
        this.exploreEvaluating = false;
      }
    },

    scoreColor(v) {
      if (v >= 8) return 'bg-emerald-600';
      if (v >= 6) return 'bg-amber-600';
      if (v >= 4) return 'bg-orange-700';
      return 'bg-red-800';
    },

    async openRelations() {
      if (!this.currentWorldId) return;
      this.showRelations = true;
      this.relSelected = null;
      await this.loadRelations();
    },

    async loadRelations() {
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/relationships`);
        this.relNodes = r.nodes || [];
        this.relEdges = r.edges || [];
        this.$nextTick(() => this.renderRelGraph());
      } catch (e) {
        alert('读取关系失败: ' + e.message);
      }
    },

    renderRelGraph() {
      const container = document.getElementById('rel-graph-container');
      if (!container || !window.cytoscape) return;
      const wantChars = this.relFilter === 'characters';
      const nodes = this.relNodes
        .filter(n => !wantChars || n.type === 'character')
        .map(n => ({
          data: {
            id: n.id, label: n.name,
            type: n.type, alive: n.alive,
            summary: n.summary,
          }
        }));
      const validIds = new Set(nodes.map(n => n.data.id));
      const edges = this.relEdges
        .filter(e => validIds.has(e.source) && validIds.has(e.target))
        .map(e => ({
          data: {
            id: e.id, source: e.source, target: e.target,
            label: e.label || '', weight: e.weight,
            events: e.events || [],
          }
        }));

      if (this.relGraph) { try { this.relGraph.destroy(); } catch {} this.relGraph = null; }

      this.relGraph = cytoscape({
        container,
        elements: [...nodes, ...edges],
        style: [
          { selector: 'node', style: {
            'label': 'data(label)',
            'background-color': ele => {
              const t = ele.data('type');
              if (t === 'character') return ele.data('alive') === 0 ? '#525252' : '#10b981';
              if (t === 'location') return '#0891b2';
              if (t === 'item') return '#a16207';
              return '#7c3aed';
            },
            'color': '#e4e4e7', 'font-size': '11px', 'text-valign': 'bottom',
            'text-margin-y': 5, 'text-outline-color': '#0a0a0a', 'text-outline-width': 2,
            'width': 32, 'height': 32, 'border-width': 2, 'border-color': '#27272a',
          }},
          { selector: 'node:selected', style: { 'border-color': '#fbbf24', 'border-width': 3 }},
          { selector: 'edge', style: {
            'width': ele => Math.min(8, 1 + ele.data('weight') * 0.8),
            'line-color': ele => ele.data('label') ? '#a78bfa' : '#3f3f46',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '9px', 'color': '#a78bfa',
            'text-background-color': '#0a0a0a', 'text-background-opacity': 0.85,
            'text-background-padding': '2px', 'text-background-shape': 'roundrectangle',
            'opacity': 0.85,
          }},
          { selector: 'edge:selected', style: { 'line-color': '#fbbf24', 'opacity': 1, 'width': 6 }},
        ],
        layout: { name: 'cose', animate: false, padding: 30, idealEdgeLength: 100, nodeRepulsion: 8000 },
      });

      this.relGraph.on('tap', 'node', evt => {
        const d = evt.target.data();
        const node = this.relNodes.find(n => n.id === d.id);
        if (node) this.relSelected = { kind: 'node', data: node };
      });
      this.relGraph.on('tap', 'edge', evt => {
        const d = evt.target.data();
        const edge = this.relEdges.find(e => e.id === d.id);
        if (edge) {
          const a = this.relNodes.find(n => n.id === edge.source);
          const b = this.relNodes.find(n => n.id === edge.target);
          this.relSelected = { kind: 'edge', data: edge, a, b };
          this.relEditLabel = edge.label || '';
        }
      });
      this.relGraph.on('tap', evt => {
        if (evt.target === this.relGraph) this.relSelected = null;
      });
    },

    async inferRelations() {
      if (this.relInferring) return;
      this.relInferring = true;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/relationships/infer`, { provider: this.provider }, 90000);
        this.flashToast(`AI 标注了 ${r.updated} 对关系`);
        await this.loadRelations();
      } catch (e) {
        alert('AI 推断失败: ' + e.message);
      } finally {
        this.relInferring = false;
      }
    },

    async saveRelationLabel(forceLabel) {
      if (!this.relSelected || this.relSelected.kind !== 'edge') return;
      const label = (forceLabel !== undefined ? forceLabel : this.relEditLabel || '').trim();
      this.relEditSaving = true;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/relationships/set`, {
          a_id: this.relSelected.data.source,
          b_id: this.relSelected.data.target,
          label,
        });
        this.relSelected.data.label = label;
        const ed = this.relEdges.find(e => e.id === this.relSelected.data.id);
        if (ed) ed.label = label;
        this.relEditLabel = label;
        this.renderRelGraph();
        this.flashToast(label ? '已更新关系标签' : '已清除关系标签');
      } catch (e) {
        alert('保存失败: ' + e.message);
      } finally {
        this.relEditSaving = false;
      }
    },

    closeRelations() {
      this.showRelations = false;
      if (this.relGraph) { try { this.relGraph.destroy(); } catch {} this.relGraph = null; }
    },

    selectFromRelGraph(nodeId) {
      const ent = this.entities.find(e => e.id === nodeId);
      if (ent) {
        this.selectEntity(ent);
        this.closeRelations();
      }
    },

    jumpToEventFromRel(eventId) {
      this.closeRelations();
      this.jumpToEvent(eventId);
    },

    async loadSuggestions() {
      if (!this.currentWorldId || this.suggestionsLoading) return;
      this.suggestionsLoading = true;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/suggest_directives`, {
          n: 4, provider: this.provider,
        }, 60000);
        this.suggestions = r.suggestions || [];
        if (this.suggestions.length === 0) this.flashToast('AI 没给出建议，再试一次');
      } catch (e) {
        alert('获取建议失败: ' + e.message);
      } finally {
        this.suggestionsLoading = false;
      }
    },

    suggestionKindClass(k) {
      const map = {
        twist: 'bg-purple-800 text-purple-100',
        tragic: 'bg-red-900 text-red-200',
        tender: 'bg-pink-900 text-pink-200',
        reveal: 'bg-amber-800 text-amber-100',
        conflict: 'bg-orange-900 text-orange-200',
        continue: 'bg-zinc-700 text-zinc-200',
      };
      return map[k] || map.continue;
    },

    suggestionKindLabel(k) {
      const map = { twist: '反转', tragic: '悲剧', tender: '温情', reveal: '揭秘', conflict: '冲突', continue: '顺势' };
      return map[k] || k || '?';
    },

    openExport() {
      if (!this.currentWorldId) return;
      const tk = this.world?.world?.current_tick ?? 0;
      this.exportTickFrom = 0;
      this.exportTickTo = tk;
      if (this.exportMode === 'novelize') this.exportMode = 'raw';
      this.exportResult = null;
      this.showExport = true;
    },

    async runExport() {
      if (this.exportLoading) return;
      this.exportLoading = true;
      this.exportResult = null;
      const timeout = this.exportMode === 'novelize' ? 600000 : 30000;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/export`, {
          mode: this.exportMode,
          tick_from: this.exportTickFrom,
          tick_to: this.exportTickTo,
          chapter_size: this.exportChapterSize,
          use_chapter_markers: this.exportUseMarkers,
          include_critique: this.exportIncludeCritique,
          include_events: this.exportIncludeEvents,
          include_narration: this.exportIncludeNarration,
          include_entities: this.exportIncludeEntities,
          provider: this.provider,
        }, timeout);
        this.exportResult = r;
      } catch (e) {
        alert('导出失败: ' + e.message);
      } finally {
        this.exportLoading = false;
      }
    },

    downloadExport() {
      if (!this.exportResult) return;
      const blob = new Blob([this.exportResult.content], {
        type: this.exportResult.format === 'json' ? 'application/json' : 'text/markdown'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = this.exportResult.filename || 'export.md';
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    },

    copyExport() {
      if (!this.exportResult) return;
      navigator.clipboard.writeText(this.exportResult.content).then(
        () => this.flashToast('已复制到剪贴板'),
        () => alert('复制失败，请手动选择文本')
      );
    },

    async openCharacterView(entity) {
      if (!entity || entity.type !== 'character') return;
      this.charViewEntity = entity;
      this.charView = null;
      this.showCharView = true;
      await this.reloadCharacterView();
    },

    async reloadCharacterView() {
      if (!this.charViewEntity || !this.currentWorldId) return;
      this.charViewBusy = true;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/characters/${this.charViewEntity.id}/view`);
        this.charView = r;
      } catch (e) {
        alert('加载视角失败: ' + e.message);
      } finally {
        this.charViewBusy = false;
      }
    },

    async stepMultiAgent() {
      if (this.busy || !this.currentWorldId) return;
      const chars = this.entities.filter(e => e.type === 'character' && e.alive !== 0);
      if (chars.length === 0) {
        alert('世界里还没有活着的角色，无法做角色视角推演');
        return;
      }
      this.busy = true;
      this.liveToolCalls = [];
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/step_multi_agent`, {
          character_ids: null,
          directive: this.stepDirective || null,
        });
        await this.loadWorld();
        const subN = (r.subagents || []).length;
        const evN = (r.director?.tool_calls || []).filter(t => t.name === 'add_event').length;
        this.flashToast(`🎭 ${subN} 个角色视角 → ${evN} 件事`);
      } catch (e) {
        alert('角色视角推演失败: ' + e.message);
      } finally {
        this.busy = false;
      }
    },

    openNovelize() {
      if (!this.currentWorldId) return;
      const activeBid = this.world?.world?.active_branch_id || (this.branches[0] && this.branches[0].id) || '';
      this.novelizeOpts = {
        branch_id: this.novelizeOpts.branch_id || activeBid,
        strategy: this.novelizeOpts.strategy || 'by_count',
        chapter_size: this.novelizeOpts.chapter_size || 6,
      };
      this.novelizeMarkdown = '';
      this.novelizeJobId = null;
      this.novelizeJobMsg = '';
      this.novelizeProgress = { done: 0, total: 0 };
      this.showNovelize = true;
      this.previewNovelizeChapters();
    },

    closeNovelize() {
      if (this.novelizePollTimer) {
        clearInterval(this.novelizePollTimer);
        this.novelizePollTimer = null;
      }
      this.showNovelize = false;
    },

    async previewNovelizeChapters() {
      if (!this.currentWorldId || !this.novelizeOpts.branch_id) return;
      try {
        const qs = new URLSearchParams({
          branch_id: this.novelizeOpts.branch_id,
          strategy: this.novelizeOpts.strategy,
          chapter_size: String(this.novelizeOpts.chapter_size || 6),
        });
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/novelize/chapters?${qs}`);
        this.novelizeChapters = r.chapters || [];
      } catch (e) {
        this.novelizeChapters = [];
        this.novelizeJobMsg = `预览失败: ${e.message}`;
      }
    },

    async runNovelize() {
      if (this.novelizeRunning) return;
      this.novelizeRunning = true;
      this.novelizeMarkdown = '';
      this.novelizeJobMsg = '提交任务…';
      this.novelizeProgress = { done: 0, total: this.novelizeChapters.length };
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/novelize_async`, {
          branch_id: this.novelizeOpts.branch_id,
          strategy: this.novelizeOpts.strategy,
          chapter_size: this.novelizeOpts.chapter_size || 6,
        });
        this.novelizeJobId = r.job_id;
        this.pollNovelizeJob();
      } catch (e) {
        this.novelizeRunning = false;
        this.novelizeJobMsg = `启动失败: ${e.message}`;
      }
    },

    pollNovelizeJob() {
      if (this.novelizePollTimer) clearInterval(this.novelizePollTimer);
      this.novelizePollTimer = setInterval(async () => {
        if (!this.novelizeJobId) return;
        try {
          const j = await this.api('GET', `/jobs/${this.novelizeJobId}`);
          this.novelizeJobMsg = j.progress_message || '';
          // pull "第 X/Y 章" out for the progress badge
          const m = (j.progress_message || '').match(/第\s*(\d+)\s*\/\s*(\d+)\s*章/);
          if (m) this.novelizeProgress = { done: +m[1], total: +m[2] };
          if (j.status === 'completed') {
            this.novelizeMarkdown = j.result?.markdown || '';
            this.novelizeProgress = { done: this.novelizeChapters.length, total: this.novelizeChapters.length };
            this.novelizeRunning = false;
            clearInterval(this.novelizePollTimer); this.novelizePollTimer = null;
            this.flashToast(`📖 已生成 ${this.novelizeMarkdown.length} 字`);
          } else if (j.status === 'error') {
            this.novelizeJobMsg = `失败: ${j.error || '未知错误'}`;
            this.novelizeRunning = false;
            clearInterval(this.novelizePollTimer); this.novelizePollTimer = null;
          } else if (j.status === 'cancelled') {
            this.novelizeJobMsg = '已取消';
            this.novelizeRunning = false;
            clearInterval(this.novelizePollTimer); this.novelizePollTimer = null;
          }
        } catch (e) {
          // transient — keep polling
        }
      }, 800);
    },

    copyNovelize() {
      if (!this.novelizeMarkdown) return;
      navigator.clipboard.writeText(this.novelizeMarkdown).then(
        () => this.flashToast('已复制到剪贴板'),
        () => alert('复制失败，请手动选中文本')
      );
    },

    downloadNovelize() {
      if (!this.novelizeMarkdown) return;
      const safe = (this.world?.world?.name || 'novel').replace(/[\\\/:*?"<>|]/g, '_');
      const blob = new Blob([this.novelizeMarkdown], { type: 'text/markdown;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${safe}.md`;
      document.body.appendChild(a); a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 100);
    },

    toggleGanttBranch(bid) {
      const i = this.ganttBranchIds.indexOf(bid);
      if (i >= 0) this.ganttBranchIds.splice(i, 1);
      else this.ganttBranchIds.push(bid);
      this.renderGantt();
    },

    async renderGantt() {
      if (this.viewMode !== 'gantt' || !this.currentWorldId) return;
      // default: select all branches on first paint
      if (this.ganttBranchIds.length === 0 && this.branches.length > 0) {
        this.ganttBranchIds = this.branches.map(b => b.id);
      }
      try {
        const qs = this.ganttBranchIds.length === this.branches.length
          ? '' : `?branch_ids=${this.ganttBranchIds.join(',')}`;
        const data = await this.api('GET', `/worlds/${this.currentWorldId}/gantt${qs}`);
        this.ganttData = data;
      } catch (e) {
        this.ganttHint = `加载失败: ${e.message}`;
        return;
      }

      const container = document.getElementById('gantt');
      if (!container || typeof vis === 'undefined' || !vis.Timeline) {
        this.ganttHint = 'vis-timeline 未加载';
        return;
      }
      const TICK_MS = 86400000;
      const epoch = new Date('2000-01-01T00:00:00Z').getTime();
      const tickToDate = (t) => new Date(epoch + t * TICK_MS);

      const groups = new vis.DataSet(this.ganttData.branches.map(b => ({
        id: b.id,
        content: `<span style="font-weight:${b.is_active?600:400};color:${b.is_active?'#fbbf24':'#d4d4d8'}">`
                 + this.escapeHtml(b.name) + (b.is_active?' ★':'') + '</span>',
        title: b.parent_branch_id ? `从 t=${b.diverged_at_tick} 分叉` : '主线',
      })));

      const items = [];
      for (const ev of this.ganttData.events) {
        const partNames = (ev.participants || [])
          .map(pid => (this.entityById?.(pid)?.name) || pid).join('、');
        const tooltip = `<b>${this.escapeHtml(ev.title)}</b><br>`
          + `<span style="color:#a1a1aa">t=${ev.tick}</span><br>`
          + (partNames ? `<span style="color:#86efac">出场：${this.escapeHtml(partNames)}</span><br>` : '')
          + (ev.description ? `<div style="margin-top:4px">${this.escapeHtml(ev.description.slice(0,200))}${ev.description.length>200?'…':''}</div>` : '');
        items.push({
          id: 'ev:' + ev.id,
          group: ev.branch_id,
          content: this.escapeHtml(ev.title.length > 18 ? ev.title.slice(0,18)+'…' : ev.title),
          start: tickToDate(ev.tick),
          end:   tickToDate(ev.tick + 1),
          title: tooltip,
          type: 'range',
          _kind: 'event',
          _eventId: ev.id,
        });
      }

      if (this.ganttShowChapters) {
        for (const cm of this.ganttData.chapters || []) {
          items.push({
            id: 'cm:' + cm.id,
            group: cm.branch_id,
            content: '📖 ' + this.escapeHtml(cm.title || '章节'),
            start: tickToDate(cm.tick),
            type: 'point',
            className: 'gantt-chapter',
            title: `<b>章节标记</b><br>tick ${cm.tick}<br>${this.escapeHtml(cm.title || '')}`,
            _kind: 'chapter',
            _chapterId: cm.id,
          });
        }
      }

      // current-tick marker: a tall point on each branch
      const ctick = this.ganttData.current_tick;
      if (ctick != null) {
        for (const b of this.ganttData.branches) {
          if (b.is_active) {
            items.push({
              id: `ct:${b.id}`,
              group: b.id,
              content: `▶ t${ctick}`,
              start: tickToDate(ctick),
              type: 'point',
              className: 'gantt-current-tick',
              title: `当前 tick = ${ctick}`,
              _kind: 'current',
            });
          }
        }
      }

      const options = {
        stack: false,
        zoomMin: 1000 * 60 * 60 * 6,           // 0.25 tick
        zoomMax: 1000 * 60 * 60 * 24 * 365 * 5, // 1825 ticks
        orientation: { axis: 'top' },
        showCurrentTime: false,
        margin: { item: 6, axis: 8 },
        format: {
          minorLabels: { day: 't[D]' },
          majorLabels: { day: '', month: '', week: '' },
        },
        moveable: true,
        zoomable: true,
        editable: false,
        groupOrder: 'id',
      };

      // wipe & rebuild — vis-timeline needs old instance destroyed when groups change
      if (this.ganttTimeline) {
        try { this.ganttTimeline.destroy(); } catch(e) {}
        this.ganttTimeline = null;
      }
      this.ganttTimeline = new vis.Timeline(container, items, groups, options);
      this.ganttTimeline.on('click', (props) => {
        const it = props.item;
        if (!it) return;
        if (it.startsWith('ev:')) {
          const evId = it.slice(3);
          this.jumpToEvent(evId);
        } else if (it.startsWith('cm:')) {
          this.editChapterMarker(it.slice(3));
        }
      });
      this.ganttTimeline.on('doubleClick', (props) => {
        if (props.item) return; // only blank space → add chapter
        if (!props.group || !props.time) return;
        const tick = Math.round((props.time.getTime() - epoch) / TICK_MS);
        this.addChapterMarker(props.group, tick);
      });
      // drawCausalLinks needs items rendered first
      this.$nextTick(() => this.drawGanttCausal());
    },

    drawGanttCausal() {
      // we attach an SVG layer over the timeline body to draw cause→effect curves
      const container = document.getElementById('gantt');
      if (!container || !this.ganttTimeline) return;
      // remove old svg
      const old = container.querySelector('svg.gantt-causal-layer');
      if (old) old.remove();
      if (!this.ganttShowCausal || !this.ganttData?.causal_links?.length) return;

      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS, 'svg');
      svg.classList.add('gantt-causal-layer');
      Object.assign(svg.style, {
        position: 'absolute', inset: '0',
        width: '100%', height: '100%',
        pointerEvents: 'none', zIndex: '5',
      });
      const defs = document.createElementNS(svgNS, 'defs');
      defs.innerHTML = `<marker id="gantt-arrow" viewBox="0 0 8 8" refX="7" refY="4"
        markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" class="gantt-causal-arrow" /></marker>`;
      svg.appendChild(defs);

      const cRect = container.getBoundingClientRect();
      const itemRect = (id) => {
        const el = container.querySelector(`[data-id="ev:${id}"]`)
                || container.querySelector(`[data-id="ev\\:${id}"]`);
        if (el) {
          const r = el.getBoundingClientRect();
          return { x: r.left - cRect.left + r.width/2, y: r.top - cRect.top + r.height/2 };
        }
        return null;
      };

      let drawn = 0;
      for (const lk of this.ganttData.causal_links) {
        const a = itemRect(lk.cause_event_id);
        const b = itemRect(lk.effect_event_id);
        if (!a || !b) continue;
        const path = document.createElementNS(svgNS, 'path');
        const dx = (b.x - a.x);
        const cy = (a.y + b.y) / 2 - Math.abs(dx) * 0.15 - 14;
        path.setAttribute('d', `M ${a.x} ${a.y} Q ${(a.x+b.x)/2} ${cy} ${b.x} ${b.y}`);
        path.setAttribute('fill', 'none');
        path.classList.add('gantt-causal');
        path.setAttribute('marker-end', 'url(#gantt-arrow)');
        svg.appendChild(path);
        drawn++;
      }
      container.appendChild(svg);
      this.ganttHint = `点击事件查看详情，双击空白可加章节标记 · ${drawn} 条因果钩子`;
    },

    ganttFit() {
      if (!this.ganttTimeline) return;
      this.ganttTimeline.fit({ animation: true });
    },

    async addChapterMarker(branchIdOrTick, tickOrTitle) {
      // overload: addChapterMarker(branchId, tick)  — gantt double-click path
      //         | addChapterMarker(tick, defaultTitle)  — old timeline path on active branch
      let branchId, tick, defaultTitle = '';
      if (typeof branchIdOrTick === 'string') {
        branchId = branchIdOrTick;
        tick = tickOrTitle;
      } else {
        branchId = this.world?.world?.active_branch_id;
        tick = branchIdOrTick;
        defaultTitle = tickOrTitle || '';
      }
      const branchName = this.branches.find(b => b.id === branchId)?.name || '分支';
      const title = prompt(`在「${branchName}」的 t${tick} 加章节标记，标题：`, defaultTitle);
      if (title === null) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/chapters`, {
          tick, title: (title || '').trim() || `章节 t${tick}`, branch_id: branchId,
        });
        this.flashToast('📖 章节标记已添加');
        if (this.viewMode === 'gantt') await this.renderGantt();
        if (this.loadChapters) await this.loadChapters();
      } catch (e) {
        alert('添加失败: ' + e.message);
      }
    },

    async editChapterMarker(chapterId) {
      const cm = (this.ganttData?.chapters || []).find(x => x.id === chapterId);
      if (!cm) return;
      const choice = prompt(`章节 t${cm.tick} 标题（清空则删除）：`, cm.title || '');
      if (choice === null) return;
      try {
        if (!choice.trim()) {
          await this.api('DELETE', `/chapters/${chapterId}`);
          this.flashToast('📖 已删除');
        } else {
          await this.api('PATCH', `/chapters/${chapterId}`, { title: choice.trim() });
          this.flashToast('📖 已更新');
        }
        await this.renderGantt();
      } catch (e) {
        alert('操作失败: ' + e.message);
      }
    },

    escapeHtml(s) {
      return String(s ?? '').replace(/[&<>"']/g, ch =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    },

    async openCharacterArc(entity) {
      if (!entity) return;
      this.arcEntity = entity;
      this.arcData = null;
      this.showArc = true;
      try {
        const r = await this.api('GET', `/entities/${entity.id}/arc`);
        this.arcData = r;
      } catch (e) {
        alert('读取角色弧线失败: ' + e.message);
        this.showArc = false;
      }
    },

    arcCloseAndJump(eventId) {
      this.showArc = false;
      this.jumpToEvent(eventId);
    },

    async loadEmotionCurve() {
      if (!this.arcEntity || this.arcEmotionLoading) return;
      this.arcEmotionLoading = true;
      try {
        const r = await this.api('POST', `/entities/${this.arcEntity.id}/emotion_curve`, { provider: this.provider }, 90000);
        if (this.arcData?.entity?.attributes) {
          this.arcData.entity.attributes._emotion_curve = r.curve || [];
        }
      } catch (e) {
        alert('情感分析失败: ' + e.message);
      } finally {
        this.arcEmotionLoading = false;
      }
    },

    arcEmotionCurve() {
      return this.arcData?.entity?.attributes?._emotion_curve || [];
    },

    arcEmotionSvgPath() {
      const c = this.arcEmotionCurve();
      if (c.length < 1) return '';
      const w = 760, h = 100, pad = 8;
      const xs = c.map(p => p.tick);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const span = Math.max(1, maxX - minX);
      const x = t => pad + ((t - minX) / span) * (w - pad * 2);
      const y = v => pad + (1 - (v + 1) / 2) * (h - pad * 2);
      return c.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.tick).toFixed(1)} ${y(p.valence).toFixed(1)}`).join(' ');
    },

    arcEmotionPoints() {
      const c = this.arcEmotionCurve();
      if (c.length < 1) return [];
      const w = 760, h = 100, pad = 8;
      const xs = c.map(p => p.tick);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const span = Math.max(1, maxX - minX);
      return c.map(p => ({
        ...p,
        x: pad + ((p.tick - minX) / span) * (w - pad * 2),
        y: pad + (1 - (p.valence + 1) / 2) * (h - pad * 2),
        color: p.valence > 0.3 ? '#10b981' : p.valence < -0.3 ? '#ef4444' : '#a3a3a3',
      }));
    },

    async loadChapters() {
      if (!this.currentWorldId) return;
      this.chaptersLoading = true;
      try {
        const r = await this.api('GET', `/worlds/${this.currentWorldId}/chapters`);
        this.chapters = r.chapters || [];
      } catch (e) {
        console.error('load chapters', e);
      } finally {
        this.chaptersLoading = false;
      }
    },

    async addChapterMarker(branchIdOrTick, tickOrTitle) {
      // overload: addChapterMarker(branchId, tick)  — gantt double-click path
      //         | addChapterMarker(tick, defaultTitle)  — old timeline path on active branch
      let branchId, tick, defaultTitle = '';
      if (typeof branchIdOrTick === 'string') {
        branchId = branchIdOrTick;
        tick = tickOrTitle;
      } else {
        branchId = this.world?.world?.active_branch_id;
        tick = branchIdOrTick;
        defaultTitle = tickOrTitle || '';
      }
      const branchName = this.branches.find(b => b.id === branchId)?.name || '分支';
      const title = prompt(`在「${branchName}」的 t${tick} 加章节标记，标题：`, defaultTitle);
      if (title === null) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/chapters`, {
          tick, title: (title || '').trim() || `章节 t${tick}`, branch_id: branchId,
        });
        this.flashToast('📖 章节标记已添加');
        if (this.viewMode === 'gantt') await this.renderGantt();
        if (this.loadChapters) await this.loadChapters();
      } catch (e) {
        alert('添加失败: ' + e.message);
      }
    },

    async removeChapterMarker(chapterId) {
      if (!confirm('删除此章末标记？')) return;
      try {
        await this.api('DELETE', `/worlds/${this.currentWorldId}/chapters/${chapterId}`);
        await this.loadChapters();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    async autoMarkChapters() {
      if (!confirm(`让 AI 自动分章（约 ${this.autoChapterTarget} 章）？\n这会清空现有章末标记。`)) return;
      this.chaptersLoading = true;
      try {
        const r = await this.api('POST', `/worlds/${this.currentWorldId}/chapters/auto`,
          { target_count: this.autoChapterTarget, provider: this.provider }, 120000);
        this.flashToast(`AI 分了 ${(r.chapters || []).length} 章`);
        await this.loadChapters();
      } catch (e) {
        alert('AI 分章失败: ' + e.message);
      } finally {
        this.chaptersLoading = false;
      }
    },

    chapterAtTick(tick) {
      return this.chapters.find(c => c.tick === tick) || null;
    },

    async openTemplates() {
      this.showTemplates = true;
      this.selectedTemplate = null;
      await this.refreshTemplates();
    },

    async refreshTemplates() {
      this.templatesLoading = true;
      try {
        const url = this.templateCategoryFilter
          ? `/templates?category=${encodeURIComponent(this.templateCategoryFilter)}`
          : '/templates';
        const r = await this.api('GET', url);
        this.templatesData = r;
      } catch (e) {
        alert('读取模板库失败: ' + e.message);
      } finally {
        this.templatesLoading = false;
      }
    },

    selectTemplate(t) {
      this.selectedTemplate = t;
    },

    async useTemplate(t) {
      const nameOverride = prompt(`从模板"${t.name}"创建新世界，世界名：`, t.name);
      if (!nameOverride) return;
      try {
        const r = await this.api('POST', `/templates/${t.id}/instantiate`, {
          name_override: nameOverride.trim(),
          auto_step: false,
        });
        this.showTemplates = false;
        await this.refreshWorlds();
        this.currentWorldId = r.world_id;
        await this.loadWorld();
        if (r.seed_directive) {
          this.directive = r.seed_directive;
          this.flashToast('模板已建立，已填充开局指令，点"推演"开始');
        } else {
          this.flashToast('模板世界已创建');
        }
      } catch (e) {
        alert('从模板创建失败: ' + e.message);
      }
    },

    openTemplateEditor(t) {
      this.editingTemplate = t ? JSON.parse(JSON.stringify(t)) : {
        id: null, name: '', category: '', description: '', long_description: '',
        cover_emoji: '📖', rules: { tone: '', core_rules: [], forbidden: [], language: '中文', notes: '' },
        seed_directive: '', suggested_steps: [], seed_entities: [], tags: [], is_official: false,
        canonical_outline: [], series: '', series_order: 0, max_steps_hint: 30,
      };
      if (!this.editingTemplate.canonical_outline) this.editingTemplate.canonical_outline = [];
      if (typeof this.editingTemplate.suggested_steps === 'object')
        this.editingTemplate._steps_text = (this.editingTemplate.suggested_steps || []).join('\n');
      if (typeof this.editingTemplate.tags === 'object')
        this.editingTemplate._tags_text = (this.editingTemplate.tags || []).join(', ');
      this.editingTemplate._core_rules_text = ((this.editingTemplate.rules?.core_rules) || []).join('\n');
      this.editingTemplate._forbidden_text = ((this.editingTemplate.rules?.forbidden) || []).join('\n');
      this.showTemplateEditor = true;
    },

    addOutlineBeat() {
      if (!this.editingTemplate.canonical_outline) this.editingTemplate.canonical_outline = [];
      this.editingTemplate.canonical_outline.push({ beat: '' });
    },

    moveOutlineBeat(idx, dir) {
      const arr = this.editingTemplate.canonical_outline;
      const j = idx + dir;
      if (j < 0 || j >= arr.length) return;
      [arr[idx], arr[j]] = [arr[j], arr[idx]];
    },

    async saveTemplateEdit() {
      const t = this.editingTemplate;
      if (!t.name?.trim()) { alert('请填写名称'); return; }
      const payload = {
        name: t.name.trim(),
        category: (t.category || '').trim(),
        description: (t.description || '').trim(),
        long_description: t.long_description || '',
        cover_emoji: t.cover_emoji || '📖',
        rules: {
          tone: t.rules?.tone || '',
          language: t.rules?.language || '中文',
          notes: t.rules?.notes || '',
          core_rules: (t._core_rules_text || '').split('\n').map(s => s.trim()).filter(Boolean),
          forbidden: (t._forbidden_text || '').split('\n').map(s => s.trim()).filter(Boolean),
        },
        seed_directive: t.seed_directive || '',
        suggested_steps: (t._steps_text || '').split('\n').map(s => s.trim()).filter(Boolean),
        seed_entities: t.seed_entities || [],
        canonical_outline: (t.canonical_outline || []).filter(b => (b.beat || '').trim()),
        series: (t.series || '').trim(),
        series_order: parseInt(t.series_order) || 0,
        max_steps_hint: Math.max(1, Math.min(200, parseInt(t.max_steps_hint) || 30)),
        tags: (t._tags_text || '').split(/[,，]/).map(s => s.trim()).filter(Boolean),
        is_official: !!t.is_official,
      };
      try {
        if (t.id) {
          await this.api('PUT', `/templates/${t.id}`, payload);
        } else {
          await this.api('POST', '/templates', payload);
        }
        this.showTemplateEditor = false;
        await this.refreshTemplates();
        this.flashToast('模板已保存');
      } catch (e) {
        alert('保存失败: ' + e.message);
      }
    },

    async deleteTemplate(t) {
      if (!confirm(`删除模板"${t.name}"？此操作不可撤销。`)) return;
      try {
        await this.api('DELETE', `/templates/${t.id}`);
        if (this.selectedTemplate?.id === t.id) this.selectedTemplate = null;
        await this.refreshTemplates();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    openSaveAsTemplate() {
      if (!this.currentWorldId) return;
      this.saveAsTemplateForm = {
        name: this.world?.world?.name || '',
        category: '', description: this.world?.world?.description || '',
        cover_emoji: '📖', tags: '', include_entities: true,
      };
      this.showSaveAsTemplate = true;
    },

    async saveCurrentAsTemplate() {
      if (!this.saveAsTemplateForm.name.trim()) { alert('请填写模板名称'); return; }
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/save_as_template`, {
          name: this.saveAsTemplateForm.name.trim(),
          category: this.saveAsTemplateForm.category.trim(),
          description: this.saveAsTemplateForm.description.trim(),
          cover_emoji: this.saveAsTemplateForm.cover_emoji || '📖',
          tags: this.saveAsTemplateForm.tags.split(/[,，]/).map(s => s.trim()).filter(Boolean),
          include_entities: this.saveAsTemplateForm.include_entities,
        });
        this.showSaveAsTemplate = false;
        this.flashToast('已保存为模板');
      } catch (e) {
        alert('保存失败: ' + e.message);
      }
    },

    cancelExploreJob(j) {
      if (j.status !== 'running' && j.status !== 'pending') return;
      this.api('POST', `/jobs/${j.job_id}/cancel`).catch(() => {});
      j.progress_message = '取消中…';
    },

    async adoptExploreVariant(j) {
      if (!j.branch_id) return;
      if (!confirm(`采纳 "${j.branch_name}"？\n当前世界将切换到这个分支，其他分支保留为兄弟分支可继续浏览。`)) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/switch_branch/${j.branch_id}`);
        this.flashToast('已采纳：' + j.branch_name);
        this.showExplore = false;
        this.exploreActive = false;
        await this.loadWorld();
        await this.refreshWorlds();
      } catch (e) {
        alert('切换失败: ' + e.message);
      }
    },

    closeExplore() {
      const running = this.exploreJobs.filter(j => j.status === 'running' || j.status === 'pending');
      if (running.length > 0) {
        if (!confirm(`还有 ${running.length} 个分支在跑，关闭后它们继续在后台运行（结果可在分支管理里查看）。确定关闭？`)) return;
      }
      this.showExplore = false;
      this.exploreActive = false;
    },

    triggerImportWorld() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,application/json';
      input.onchange = async () => {
        const file = input.files?.[0];
        if (!file) return;
        try {
          const text = await file.text();
          const payload = JSON.parse(text);
          if (payload.schema_version !== 1) {
            alert('不识别的导出文件版本: ' + payload.schema_version);
            return;
          }
          const newName = prompt('为导入的世界起个名字（留空使用原名 + "(导入)"）', '') || null;
          const res = await this.api('POST', '/worlds/import', { payload, new_name: newName });
          await this.refreshWorlds();
          this.currentWorldId = res.world_id;
          await this.loadWorld();
          this.flashToast('导入成功');
        } catch (e) {
          alert('导入失败: ' + e.message);
        }
      };
      input.click();
    },    eventById(id) {
      return (this.timeline.events || []).find(e => e.id === id);
    },

    changeKindLabel(kind) {
      return ({
        add_edge: '+边',
        remove_edge: '-边',
        edit_edge: '✎边',
        edit_event: '✎事件',
        delete_event: '−事件',
      })[kind] || kind;
    },

    addPendingChange(change) {
      this.pendingChanges.push(change);
    },

    removePendingChange(idx) {
      this.pendingChanges.splice(idx, 1);
    },

    showCtxMenu(x, y, items) {
      const menu = document.getElementById('cy-ctx-menu');
      if (!menu) return;
      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const div = document.createElement('div');
          div.className = 'sep';
          menu.appendChild(div);
          return;
        }
        const btn = document.createElement('button');
        btn.textContent = item.label;
        if (item.danger) btn.className = 'danger';
        btn.addEventListener('click', () => {
          this.hideCtxMenu();
          item.action();
        });
        menu.appendChild(btn);
      });
      const cyEl = document.getElementById('cy');
      const rect = cyEl.getBoundingClientRect();
      menu.style.display = 'block';
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      let left = x, top = y;
      if (left + mw > rect.width) left = rect.width - mw - 4;
      if (top + mh > rect.height) top = rect.height - mh - 4;
      menu.style.left = Math.max(4, left) + 'px';
      menu.style.top = Math.max(4, top) + 'px';
    },

    hideCtxMenu() {
      const menu = document.getElementById('cy-ctx-menu');
      if (menu) menu.style.display = 'none';
    },

    startLinkingFrom(nodeId) {
      this.linkSourceId = nodeId;
      if (this.cy) {
        this.cy.nodes().removeClass('link-source-node');
        this.cy.getElementById(nodeId).addClass('link-source-node');
      }
    },

    cancelLinking() {
      this.linkSourceId = null;
      if (this.cy) this.cy.nodes().removeClass('link-source-node');
    },

    dismissGraphHelp() {
      this.graphHelpDismissed = true;
      try { localStorage.setItem('graphHelpSeen', '1'); } catch (e) {}
    },

    async completeLink(targetNodeId) {
      const cause = this.linkSourceId;
      const effect = targetNodeId;
      this.cancelLinking();
      if (!cause || !effect || cause === effect) return;
      const desc = prompt('因果链描述（可空）', '');
      if (desc === null) return;
      try {
        await this.api('POST', `/worlds/${this.currentWorldId}/causality`, {
          cause_event_id: cause,
          effect_event_id: effect,
          description: desc || '',
        });
        const causeTitle = this.eventById(cause)?.title || cause.slice(0, 8);
        const effectTitle = this.eventById(effect)?.title || effect.slice(0, 8);
        this.addPendingChange({
          kind: 'add_edge',
          summary: `${causeTitle} → ${effectTitle}${desc ? '（' + desc + '）' : ''}`,
          payload: { cause_event_id: cause, effect_event_id: effect, description: desc },
        });
        await this.loadWorld();
      } catch (e) {
        alert('建立因果失败: ' + e.message);
      }
    },

    openEventEdit(eventId) {
      const ev = this.eventById(eventId);
      if (!ev) return;
      this.eventEditDraft = {
        id: ev.id,
        title: ev.title || '',
        description: ev.description || '',
        tick: ev.tick,
        participants: [...(ev.participants || [])],
        participantsText: (ev.participants || []).map(p => this.nameOf(p)).join('、'),
      };
      this.showEventEdit = true;
    },

    toggleParticipant(id, name) {
      const idx = this.eventEditDraft.participants.indexOf(id);
      if (idx >= 0) this.eventEditDraft.participants.splice(idx, 1);
      else this.eventEditDraft.participants.push(id);
      this.eventEditDraft.participantsText = this.eventEditDraft.participants.map(p => this.nameOf(p)).join('、');
    },

    async saveEventEdit() {
      const d = this.eventEditDraft;
      const before = this.eventById(d.id);
      if (!before) { this.showEventEdit = false; return; }
      try {
        await this.api('PATCH', `/events/${d.id}`, {
          title: d.title,
          description: d.description,
          tick: d.tick,
          participants: d.participants,
        });
        const diff = [];
        if (before.title !== d.title) diff.push(`标题"${before.title}"→"${d.title}"`);
        if (before.tick !== d.tick) diff.push(`tick ${before.tick}→${d.tick}`);
        if ((before.description || '') !== (d.description || '')) diff.push('描述改写');
        if ((before.participants || []).join(',') !== d.participants.join(',')) diff.push('参与者变更');
        this.addPendingChange({
          kind: 'edit_event',
          summary: `${before.title}：${diff.join('、') || '编辑'}`,
          payload: { id: d.id },
        });
        this.showEventEdit = false;
        await this.loadWorld();
      } catch (e) {
        alert('保存失败: ' + e.message);
      }
    },

    async deleteEventNode(eventId) {
      const ev = this.eventById(eventId);
      if (!ev) return;
      if (!confirm(`软删除事件「${ev.title}」？\n（不会真删，AI 调和时会知道这事被作者拿掉了）`)) return;
      try {
        await this.api('DELETE', `/events/${eventId}`);
        this.addPendingChange({
          kind: 'delete_event',
          summary: `${ev.title}（t${ev.tick}）`,
          payload: { id: eventId, title: ev.title, tick: ev.tick },
        });
        await this.loadWorld();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    openEdgeEdit(cause, effect) {
      const link = (this.timeline.links || []).find(l => l.cause === cause && l.effect === effect);
      this.edgeEditDraft = { cause, effect, description: link?.description || '' };
      this.showEdgeEdit = true;
    },

    async saveEdgeEdit() {
      const d = this.edgeEditDraft;
      try {
        await this.api('PATCH', `/causality?cause=${encodeURIComponent(d.cause)}&effect=${encodeURIComponent(d.effect)}`, {
          description: d.description,
        });
        const causeTitle = this.eventById(d.cause)?.title || d.cause.slice(0, 8);
        const effectTitle = this.eventById(d.effect)?.title || d.effect.slice(0, 8);
        this.addPendingChange({
          kind: 'edit_edge',
          summary: `${causeTitle} → ${effectTitle}: "${d.description}"`,
          payload: { cause: d.cause, effect: d.effect },
        });
        this.showEdgeEdit = false;
        await this.loadWorld();
      } catch (e) {
        alert('保存失败: ' + e.message);
      }
    },

    async deleteEdge(cause, effect) {
      try {
        await this.api('DELETE', `/causality?cause=${encodeURIComponent(cause)}&effect=${encodeURIComponent(effect)}`);
        const causeTitle = this.eventById(cause)?.title || cause.slice(0, 8);
        const effectTitle = this.eventById(effect)?.title || effect.slice(0, 8);
        this.addPendingChange({
          kind: 'remove_edge',
          summary: `${causeTitle} → ${effectTitle} 断开`,
          payload: { cause, effect },
        });
        await this.loadWorld();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    openReconcile() {
      this.reconcileResult = null;
      this.showReconcile = true;
    },

    async runReconcile() {
      if (this.pendingChanges.length === 0) return;
      this.reconciling = true;
      this.reconcileResult = null;
      try {
        const seedIds = new Set();
        const userChanges = [];
        for (const c of this.pendingChanges) {
          userChanges.push(`${this.changeKindLabel(c.kind)} ${c.summary}`);
          if (c.kind === 'edit_event' || c.kind === 'delete_event') seedIds.add(c.payload.id);
          if (c.kind === 'add_edge') { seedIds.add(c.payload.cause_event_id); seedIds.add(c.payload.effect_event_id); }
          if (c.kind === 'remove_edge' || c.kind === 'edit_edge') { seedIds.add(c.payload.cause); seedIds.add(c.payload.effect); }
        }
        const res = await this.api('POST', `/worlds/${this.currentWorldId}/reconcile`, {
          user_changes: userChanges,
          seed_event_ids: [...seedIds],
          branch: this.reconcileBranch,
          branch_name: this.reconcileBranchName || null,
          provider: this.provider,
        }, 360000);
        this.reconcileResult = res;
        this.pendingChanges = [];
        await this.refreshWorlds();
        await this.loadWorld();
      } catch (e) {
        alert('调和失败: ' + e.message);
      } finally {
        this.reconciling = false;
      }
    },

    renderGraph() {
      const el = document.getElementById('cy');
      if (!el) return;
      if (typeof cytoscape !== 'undefined' && typeof cytoscapeDagre !== 'undefined' && !this._dagreRegistered) {
        try { cytoscape.use(cytoscapeDagre); this._dagreRegistered = true; } catch(e) {}
      }
      const events = this.timeline.events;
      const links = this.timeline.links;
      const eventIds = new Set(events.map(e => e.id));
      const validLinks = links.filter(l => eventIds.has(l.cause) && eventIds.has(l.effect));

      const truncate = (s, n) => (s && s.length > n) ? s.slice(0, n - 1) + '…' : (s || '');

      const inDeg = {}, outDeg = {};
      events.forEach(e => { inDeg[e.id] = 0; outDeg[e.id] = 0; });
      validLinks.forEach(l => {
        outDeg[l.cause] = (outDeg[l.cause] || 0) + 1;
        inDeg[l.effect] = (inDeg[l.effect] || 0) + 1;
      });

      // 按 (tick 升, id) 编步骤号 1..N，让用户看到 "第 N 步" 而不是裸 tick
      const sorted = events.slice().sort((a, b) => a.tick - b.tick || (a.id || '').localeCompare(b.id || ''));
      const stepNo = new Map(sorted.map((e, i) => [e.id, i + 1]));

      const ticks = events.map(e => e.tick);
      const tMin = ticks.length ? Math.min(...ticks) : 0;
      const tMax = ticks.length ? Math.max(...ticks) : 0;
      const tSpan = Math.max(1, tMax - tMin);

      const colorForTick = (tick) => {
        const t = (tick - tMin) / tSpan;
        const h = 175 - t * 95;
        const s = 55 + t * 25;
        const l = 32 + t * 18;
        return `hsl(${h.toFixed(0)}, ${s.toFixed(0)}%, ${l.toFixed(0)}%)`;
      };

      const elements = [
        ...events.map(e => {
          const deg = (inDeg[e.id] || 0) + (outDeg[e.id] || 0);
          const partCount = (e.participants || []).length;
          const importance = deg + partCount;
          const isStart = (inDeg[e.id] || 0) === 0 && (outDeg[e.id] || 0) > 0;
          const isLatest = e.tick === tMax;
          const isIsolated = deg === 0;
          const step = stepNo.get(e.id) || 0;
          const title = e.title || '(无标题)';
          // 多行 label：第 1 行 step 徽章，第 2 行完整标题（不截断，由 cytoscape wrap）
          const label = `第 ${step} 步\n${title}`;
          const classes = [];
          if (isStart) classes.push('is-start');
          if (isLatest) classes.push('is-latest');
          if (isIsolated) classes.push('is-isolated');
          return {
            data: {
              id: e.id,
              label,
              tick: e.tick,
              step,
              title,
              description: e.description || '',
              participants: (e.participants || []).map(p => this.nameOf(p)).join('、'),
              importance,
              isLatest,
              isStart,
              isIsolated,
              fillColor: colorForTick(e.tick),
              fontSize: 12 + Math.min(3, importance * 0.4),
            },
            classes: classes.join(' '),
          };
        }),
        ...validLinks.map(l => ({
          data: {
            id: `${l.cause}__${l.effect}`,
            source: l.cause,
            target: l.effect,
            description: l.description || '',
            edgeLabel: truncate(l.description || '', 22),
          },
        })),
      ];

      if (this.cy) { this.cy.destroy(); this.cy = null; }
      if (elements.length === 0) return;

      const useDagre = this._dagreRegistered;
      this.cy = cytoscape({
        container: el,
        elements,
        wheelSensitivity: 0.25,
        style: [
          { selector: 'node', style: {
            'background-color': 'data(fillColor)',
            'background-opacity': 0.92,
            'border-color': '#27272a',
            'border-width': 1.5,
            'label': 'data(label)',
            'color': '#fafafa',
            'font-size': 'data(fontSize)',
            'font-family': 'system-ui, -apple-system, sans-serif',
            'font-weight': 500,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'text-max-width': 180,
            'line-height': 1.25,
            'width': 'label',
            'height': 'label',
            'padding': 12,
            'shape': 'round-rectangle',
            'text-outline-color': '#09090b',
            'text-outline-width': 1.2,
          }},
          { selector: 'node.is-start', style: {
            'border-color': '#10b981',
            'border-width': 3.5,
          }},
          { selector: 'node.is-latest', style: {
            'border-color': '#fbbf24',
            'border-width': 3.5,
          }},
          { selector: 'node.is-isolated', style: {
            'opacity': 0.45,
            'border-style': 'dashed',
            'border-color': '#52525b',
          }},
          { selector: 'node:selected', style: {
            'border-color': '#fef3c7',
            'border-width': 4,
          }},
          { selector: 'edge', style: {
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'line-color': '#52525b',
            'target-arrow-color': '#a1a1aa',
            'width': 1.8,
            'arrow-scale': 1.4,
            'label': 'data(edgeLabel)',
            'font-size': 9,
            'color': '#d4d4d8',
            'text-rotation': 'autorotate',
            'text-background-color': '#09090b',
            'text-background-opacity': 0.85,
            'text-background-padding': 3,
            'text-background-shape': 'round-rectangle',
            'text-border-color': '#3f3f46',
            'text-border-width': 0.5,
            'text-border-opacity': 0.6,
          }},
          { selector: 'edge:selected', style: {
            'line-color': '#f59e0b',
            'target-arrow-color': '#f59e0b',
            'width': 2.8,
            'color': '#fde68a',
          }},
          { selector: '.faded', style: { 'opacity': 0.15 } },
          { selector: '.hover-highlight', style: {
            'line-color': '#10b981',
            'target-arrow-color': '#10b981',
            'border-color': '#10b981',
            'border-width': 3.5,
          }},
        ],
        layout: useDagre
          ? { name: 'dagre', rankDir: 'LR', nodeSep: 50, rankSep: 130, edgeSep: 18, padding: 24, animate: false }
          : { name: 'breadthfirst', directed: true, spacingFactor: 1.6, padding: 24 },
      });

      const cyEl = el;
      const tip = document.getElementById('cy-tooltip');
      let hovering = null;

      const showTip = (html) => { tip.innerHTML = html; tip.style.display = 'block'; };
      const hideTip = () => { tip.style.display = 'none'; };

      this.cy.on('mouseover', 'node', (evt) => {
        const d = evt.target.data();
        hovering = evt.target;
        evt.target.addClass('hover-highlight');
        const tagBits = [];
        if (d.isStart) tagBits.push('<span class="tt-tag tt-start">起点</span>');
        if (d.isLatest) tagBits.push('<span class="tt-tag tt-latest">最新</span>');
        if (d.isIsolated) tagBits.push('<span class="tt-tag tt-isolated">孤立</span>');
        const head = `<div class="tt-step">第 ${d.step} 步 · tick ${d.tick}${tagBits.length ? ' ' + tagBits.join('') : ''}</div>`;
        const parts = [head, `<div class="tt-title">${escapeHtml(d.title || '')}</div>`];
        if (d.participants) parts.push(`<div class="tt-meta">👥 ${escapeHtml(d.participants)}</div>`);
        if (d.description) parts.push(`<div class="tt-desc">${escapeHtml(d.description)}</div>`);
        showTip(parts.join(''));
      });
      this.cy.on('mouseout', 'node', (evt) => {
        if (hovering === evt.target) hovering = null;
        evt.target.removeClass('hover-highlight');
        hideTip();
      });
      this.cy.on('mouseover', 'edge', (evt) => {
        const d = evt.target.data();
        hovering = evt.target;
        evt.target.addClass('hover-highlight');
        const text = d.description || '(没写因果描述)';
        showTip(`<div class="tt-edge-head">因为 → 所以</div><div class="tt-desc">${escapeHtml(text)}</div>`);
      });
      this.cy.on('mouseout', 'edge', (evt) => {
        if (hovering === evt.target) hovering = null;
        evt.target.removeClass('hover-highlight');
        hideTip();
      });

      cyEl.addEventListener('mousemove', (e) => {
        if (tip.style.display !== 'block') return;
        const rect = cyEl.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const tipW = tip.offsetWidth;
        const tipH = tip.offsetHeight;
        let left = x + 14;
        let top = y + 14;
        if (left + tipW > rect.width) left = x - tipW - 14;
        if (top + tipH > rect.height) top = y - tipH - 14;
        tip.style.left = Math.max(4, left) + 'px';
        tip.style.top = Math.max(4, top) + 'px';
      }, { passive: true });

      this.cy.on('tap', 'node', (evt) => {
        if (this.linkSourceId) {
          this.completeLink(evt.target.id());
          return;
        }
        this.cy.elements().removeClass('faded');
        const neighborhood = evt.target.closedNeighborhood();
        this.cy.elements().not(neighborhood).addClass('faded');
      });
      this.cy.on('tap', (evt) => {
        if (evt.target === this.cy) {
          this.cy.elements().removeClass('faded');
          this.hideCtxMenu();
          if (this.linkSourceId) this.cancelLinking();
        }
      });

      this.cy.on('cxttap', 'node', (evt) => {
        evt.preventDefault?.();
        const nodeId = evt.target.id();
        const rect = cyEl.getBoundingClientRect();
        const x = evt.originalEvent.clientX - rect.left;
        const y = evt.originalEvent.clientY - rect.top;
        this.showCtxMenu(x, y, [
          { label: '编辑事件…', action: () => this.openEventEdit(nodeId) },
          { label: '从此节点连出…', action: () => this.startLinkingFrom(nodeId) },
          { sep: true },
          { label: '软删除事件', danger: true, action: () => this.deleteEventNode(nodeId) },
        ]);
      });

      this.cy.on('cxttap', 'edge', (evt) => {
        evt.preventDefault?.();
        const d = evt.target.data();
        const rect = cyEl.getBoundingClientRect();
        const x = evt.originalEvent.clientX - rect.left;
        const y = evt.originalEvent.clientY - rect.top;
        this.showCtxMenu(x, y, [
          { label: '编辑因果描述…', action: () => this.openEdgeEdit(d.source, d.target) },
          { sep: true },
          { label: '删除这条因果链', danger: true, action: () => this.deleteEdge(d.source, d.target) },
        ]);
      });

      this.cy.on('cxttap', (evt) => {
        if (evt.target === this.cy) this.hideCtxMenu();
      });

      this.cy.fit(null, 30);
      this._graphMeta = { tMin, tMax };
    },

    async step() {
      if (!this.currentWorldId || this.busy) return;
      this.busy = true;
      this.activeJob = null;
      this.liveToolCalls = [];
      this.liveNarration = '';
      this.liveProgressMsg = '';
      try {
        const startRes = await this.api('POST', `/worlds/${this.currentWorldId}/step_async`, {
          directive: this.directive || null,
          provider: this.provider,
          steps: this.stepCount,
        });
        const jobId = startRes.job_id;
        this.activeJob = { id: jobId };
        const finalJob = await this.pollJob(jobId);
        if (finalJob.status === 'cancelled') {
          this.flashToast('已取消');
        } else if (finalJob.status === 'error') {
          alert('推演失败: ' + (finalJob.error || 'unknown'));
        } else if (finalJob.result) {
          const results = finalJob.result.results || [];
          this.lastStep = results.length ? results[results.length - 1] : finalJob.result;
        }
        this.directive = '';
        await this.loadWorld();
        await this.refreshWorlds();
      } catch (e) {
        alert('推演失败: ' + e.message);
      } finally {
        this.busy = false;
        this.activeJob = null;
        this.liveToolCalls = [];
        this.liveNarration = '';
        this.liveProgressMsg = '';
      }
    },

    async pollJob(jobId) {
      while (true) {
        await new Promise(r => setTimeout(r, 600));
        let job;
        try {
          job = await this.api('GET', `/jobs/${jobId}`);
        } catch (e) {
          throw new Error('轮询任务失败: ' + e.message);
        }
        this.liveToolCalls = job.tool_calls || [];
        this.liveNarration = job.narration || '';
        this.liveProgressMsg = job.progress_message || '';
        if (job.status === 'running' || job.status === 'pending') continue;
        return job;
      }
    },

    async cancelActiveJob() {
      if (!this.activeJob) return;
      try {
        await this.api('POST', `/jobs/${this.activeJob.id}/cancel`);
        this.liveProgressMsg = '取消中…';
      } catch (e) {
        alert('取消失败: ' + e.message);
      }
    },

    async createWorld() {
      if (!this.newWorld.name) return;
      const r = await this.api('POST', '/worlds', this.newWorld);
      this.showCreateWorld = false;
      this.newWorld = { name: '', description: '', outline: '' };
      await this.refreshWorlds();
      this.currentWorldId = r.id;
      await this.loadWorld();
    },

    async createEntity() {
      if (!this.newEntity.name) return;
      let attrs = {};
      try { if (this.newEntity.attributesJson) attrs = JSON.parse(this.newEntity.attributesJson); }
      catch (e) { alert('attributes JSON 格式错误'); return; }
      await this.api('POST', `/worlds/${this.currentWorldId}/entities`, {
        type: this.newEntity.type,
        name: this.newEntity.name,
        summary: this.newEntity.summary,
        attributes: attrs,
      });
      this.showCreateEntity = false;
      this.newEntity = { type: 'character', name: '', summary: '', attributesJson: '' };
      await this.loadWorld();
    },
  };
}
