// Owns a draft against one saved revision. No dates or dependencies are calculated here.
export class SandboxSession {
  constructor(send, changed, {
    delay = 650,
    // Browser timers require the global receiver, not the SandboxSession instance.
    schedule = (callback, milliseconds) => globalThis.setTimeout(callback, milliseconds),
    cancel = timer => globalThis.clearTimeout(timer),
  } = {}) {
    Object.assign(this, {send, changed, delay, schedule, cancel, version:0, active:false,
      shifts:{}, data:null, phase:'idle', aiPhase:'idle', error:'', timer:null, controller:null});
  }
  get dirty() { return Object.keys(this.shifts).length > 0; }
  get canApply() { return this.active && this.phase === 'ready' && this.dirty && Boolean(this.data); }
  emit() { this.changed(this); }
  invalidate() {
    ++this.version;
    this.cancel(this.timer); this.timer = null;
    this.controller?.abort(); this.controller = null;
  }
  enter(pid, revision) {
    this.invalidate();
    Object.assign(this, {active:true, pid, revision, shifts:{}, data:null,
      phase:'idle', aiPhase:'idle', error:''});
    this.emit();
  }
  leave() {
    this.invalidate();
    Object.assign(this, {active:false, shifts:{}, data:null, phase:'idle', aiPhase:'idle', error:''});
    this.emit();
  }
  reset() { if (this.phase !== 'applying') this.enter(this.pid, this.revision); }
  pause() {
    if (!this.active || ['applying','conflict'].includes(this.phase)) return false;
    this.paused = {phase:this.phase, aiPhase:this.aiPhase, error:this.error};
    this.invalidate(); this.phase = 'dragging'; this.aiPhase = 'idle'; this.error = '';
    // The pointer owns the bar until release; don't replace the timeline DOM here.
    return true;
  }
  resume() {
    if (this.phase !== 'dragging' || !this.paused) return;
    const paused = this.paused; this.paused = null;
    if (paused.phase === 'calculating') return this.calculate();
    Object.assign(this, paused);
    if (this.phase === 'ready' && ['waiting','loading'].includes(this.aiPhase)) {
      this.aiPhase = 'waiting';
      const version = this.version, body = {shifts:{...this.shifts}, base_revision:this.revision};
      this.timer = this.schedule(() => { this.timer = null; void this.explain(version, body); }, this.delay);
    }
    this.emit();
  }
  shift(taskId, delta, minimum = 0) {
    if (!this.active || ['applying','conflict'].includes(this.phase)) return;
    const shifts = {...this.shifts};
    const value = Math.min(100000 + minimum, Math.max(minimum, (shifts[taskId] || 0) + delta));
    if (value) shifts[taskId] = value; else delete shifts[taskId];
    if (Object.keys(shifts).length === Object.keys(this.shifts).length &&
        Object.entries(shifts).every(([key, item]) => this.shifts[key] === item)) {
      return this.resume();
    }
    return this.calculate(shifts);
  }
  async calculate(shifts = this.shifts) {
    this.invalidate();
    const version = this.version;
    Object.assign(this, {shifts:{...shifts}, aiPhase:'idle', error:'', paused:null});
    if (!this.dirty) { this.data = null; this.phase = 'idle'; this.emit(); return; }
    this.phase = 'calculating'; this.emit();
    const controller = this.controller = new AbortController();
    const body = {shifts:{...this.shifts}, base_revision:this.revision};
    try {
      const data = await this.send(this.pid, '/sandbox', {...body, explain:false}, controller.signal);
      if (version !== this.version || !this.active) return;
      this.data = data; this.phase = 'ready'; this.aiPhase = 'waiting'; this.emit();
      this.timer = this.schedule(() => { this.timer = null; void this.explain(version, body); }, this.delay);
    } catch (error) {
      if (version !== this.version || !this.active) return;
      this.phase = error.code === 'revision_conflict' || error.status === 404 ? 'conflict' : 'error';
      this.error = error.message; this.aiPhase = 'idle'; this.emit();
    }
  }
  async explain(version, body) {
    if (version !== this.version || !this.active) return;
    const controller = this.controller = new AbortController();
    this.aiPhase = 'loading'; this.emit();
    try {
      const data = await this.send(this.pid, '/sandbox', {...body, explain:true}, controller.signal);
      if (version !== this.version || !this.active || this.phase !== 'ready') return;
      if (data.scenario_key !== this.data.scenario_key) throw new Error('Сценарий изменился. Повторите анализ.');
      this.data = {...this.data, explanation:data.explanation, ai:data.ai, llm:data.llm};
      this.aiPhase = data.llm ? 'ready' : 'fallback'; this.emit();
    } catch (error) {
      if (version !== this.version || !this.active) return;
      if (error.code === 'revision_conflict' || error.status === 404) {
        this.phase = 'conflict'; this.error = error.message;
      }
      this.aiPhase = 'error'; this.emit();
    }
  }
  retryExplanation() {
    if (!this.canApply) return;
    this.invalidate();
    return this.explain(this.version, {shifts:{...this.shifts}, base_revision:this.revision});
  }
  async apply() {
    if (!this.canApply) return null;
    this.invalidate();
    this.phase = 'applying'; this.aiPhase = 'idle'; this.emit();
    try {
      return await this.send(this.pid, '/sandbox/apply', {shifts:{...this.shifts},
        base_revision:this.revision, scenario_key:this.data.scenario_key});
    } catch (error) {
      // A lost response may mean the write succeeded. Require a reload before retrying.
      this.phase = 'conflict';
      this.error = error.code === 'revision_conflict' ? error.message
        : 'Не удалось подтвердить сохранение. Обновите проект, чтобы увидеть актуальный план.';
      this.emit();
      return null;
    }
  }
}
