// E2: 地图 / 沙盘 / 钉位 / 仿真 mixin
window.MapMixin = {
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
    this.mapImgUrl = `/api/worlds/${this.currentWorldId}/map/render.png?layer=${this.mapLayer}&t=${Date.now()}`;
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
      await this.loadWorld();
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
};
