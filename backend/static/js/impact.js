// A late explanation must never replace a newer form or a different project.
export class ImpactExplanation {
  constructor(send) { this.send = send; this.version = 0; }
  cancel() { ++this.version; this.controller?.abort(); this.controller = null; }
  async run(pid, result, isCurrent, complete, failed) {
    this.cancel();
    const version = this.version, controller = new AbortController();
    this.controller = controller;
    const current = () => version === this.version && isCurrent();
    try {
      const data = await this.send(pid, {explanation_id:result.explanation_id}, controller.signal);
      if (current() && data.explanation_id === result.explanation_id && data.result_revision === result.result_revision) complete({...result, ...data});
    } catch (error) {
      if (error.name !== 'AbortError' && current()) failed(error);
    } finally {
      if (version === this.version) this.controller = null;
    }
  }
}
