// E2: 双角色对话演练 mixin
// 由 sandbox() 通过 Object.assign 合并。
window.DialogueMixin = {
  showDialogueRehearsal: false,
  dialogueRehearsal: {
    actorA: '', actorB: '',
    scene: '', goal: '', turns: 12,
    running: false, result: null,
  },

  characterEntities() {
    return (this.entities || []).filter(e => (e.type || 'character') === 'character');
  },

  openDialogueRehearsal() {
    if (!this.currentWorldId) return;
    this.dialogueRehearsal.result = null;
    this.showDialogueRehearsal = true;
  },

  dialogueSpeakerName(sid) {
    const r = this.dialogueRehearsal.result;
    if (!r) return sid;
    const a = (r.actors || []).find(x => x.id === sid);
    return a ? a.name : sid;
  },

  async runDialogueRehearsal() {
    const d = this.dialogueRehearsal;
    if (!this.currentWorldId || d.running) return;
    if (!d.actorA || !d.actorB || d.actorA === d.actorB) return;
    d.running = true;
    d.result = null;
    try {
      const r = await this.api('POST', `/worlds/${this.currentWorldId}/dialogue/rehearse`, {
        actor_a_id: d.actorA, actor_b_id: d.actorB,
        scene: d.scene || '', goal: d.goal || '',
        turns: parseInt(d.turns) || 12,
        provider: this.provider,
      });
      d.result = r;
      if (!r.turns || r.turns.length === 0) {
        this.flashToast('生成失败，请检查 raw_text');
      }
    } catch (e) {
      alert('对话生成失败: ' + e.message);
    } finally {
      d.running = false;
    }
  },

  async saveDialogueRehearsal() {
    const r = this.dialogueRehearsal.result;
    if (!r || !r.turns?.length) return;
    try {
      await this.api('POST', `/worlds/${this.currentWorldId}/dialogue/save`, {
        actors: r.actors || [], title: r.title || '',
        summary: r.summary || '', turns: r.turns,
      });
      this.flashToast('已落到当前 tick 的旁注');
      this.showDialogueRehearsal = false;
      await this.loadWorld(this.currentWorldId);
    } catch (e) {
      alert('保存失败: ' + e.message);
    }
  },
};
