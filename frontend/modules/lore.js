// E2: 世界设定库 (Lore) + B7 lore 缺口扫描
window.LoreMixin = {
  loreList: [],
  loreShowAdd: false,
  loreDraft: { title: '', content: '', category: 'setting', priority: 0, pinned: false },
  loreGapsLoading: false,
  loreGaps: [],
  loreGapsScanned: null,
  loreGapsCreating: {},

  async loadLore() {
    if (!this.currentWorldId) { this.loreList = []; return; }
    try {
      const r = await this.api('GET', `/worlds/${this.currentWorldId}/lore`);
      this.loreList = r.lore || [];
    } catch (e) {
      this.loreList = [];
    }
  },

  loreCategoryLabel(c) {
    return ({ setting: '背景', magic: '规则', taboo: '禁忌',
              culture: '文化', character: '人物', other: '其他' }[c]) || c || '其他';
  },

  async saveLoreDraft() {
    const title = (this.loreDraft.title || '').trim();
    if (!title) return;
    try {
      await this.api('POST', `/worlds/${this.currentWorldId}/lore`, {
        title,
        content: this.loreDraft.content || '',
        category: this.loreDraft.category || 'setting',
        priority: Number(this.loreDraft.priority) || 0,
        pinned: !!this.loreDraft.pinned,
      });
      this.loreDraft = { title: '', content: '', category: 'setting', priority: 0, pinned: false };
      this.loreShowAdd = false;
      await this.loadLore();
      this.flashToast('已添加世界设定');
    } catch (e) {
      alert('添加失败: ' + e.message);
    }
  },

  async deleteLore(id) {
    if (!confirm('删除这条设定？')) return;
    try {
      await this.api('DELETE', `/lore/${id}`);
      await this.loadLore();
    } catch (e) {
      alert('删除失败: ' + e.message);
    }
  },

  async scanLoreGaps() {
    if (!this.currentWorldId) return;
    this.loreGapsLoading = true;
    try {
      const r = await this.api('POST', `/worlds/${this.currentWorldId}/lore/scan_gaps`, { max_gaps: 8 });
      this.loreGaps = r.gaps || [];
      this.loreGapsScanned = r.scanned || null;
      if (this.loreGaps.length === 0) {
        this.flashToast('没扫到值得补的 lore 候选');
      }
    } catch (e) {
      alert('扫描失败: ' + (e.message || e));
    } finally {
      this.loreGapsLoading = false;
    }
  },

  loreKindLabel(k) {
    return ({ person: '人物', location: '地点', organization: '组织',
              item: '物品', concept: '概念' }[k]) || k;
  },

  loreKindToCategory(k) {
    return ({ person: 'character', location: 'setting', organization: 'culture',
              item: 'setting', concept: 'setting' }[k]) || 'setting';
  },

  async createLoreFromGap(gap) {
    if (this.loreGapsCreating[gap.name]) return;
    this.loreGapsCreating = { ...this.loreGapsCreating, [gap.name]: true };
    try {
      await this.api('POST', `/worlds/${this.currentWorldId}/lore`, {
        title: gap.name,
        content: gap.suggested_summary || gap.reason || '',
        category: this.loreKindToCategory(gap.kind),
        priority: 0,
        pinned: false,
      });
      this.loreGaps = this.loreGaps.filter(g => g.name !== gap.name);
      await this.loadLore();
      this.flashToast(`已添加 lore: ${gap.name}`);
    } catch (e) {
      alert('创建失败: ' + (e.message || e));
    } finally {
      const next = { ...this.loreGapsCreating };
      delete next[gap.name];
      this.loreGapsCreating = next;
    }
  },

  dismissLoreGap(gap) {
    this.loreGaps = this.loreGaps.filter(g => g.name !== gap.name);
  },
};
