// Navigation owns view changes and the optional assistant panel.
export class WorkspaceNavigation {
  constructor(root, {beforeChange = async () => true, changed = () => {}} = {}) {
    Object.assign(this, {root, beforeChange, changed, view:'timeline', switching:false});
  }
  async select(view) {
    if (!['timeline','table','graph'].includes(view) || this.switching) return false;
    this.switching = true;
    try {
      if (!await this.beforeChange(view)) return false;
      this.view = view;
      this.root.querySelectorAll('[data-view-panel]').forEach(panel => {
        panel.hidden = panel.dataset.viewPanel !== view;
      });
      this.root.querySelectorAll('[data-view]').forEach(button => {
        const active = button.dataset.view === view;
        button.classList.toggle('active', active);
        if (button.getAttribute('role') === 'tab') {
          button.setAttribute('aria-selected', String(active));
          button.tabIndex = active ? 0 : -1;
        }
      });
      this.changed(view);
      return true;
    } finally { this.switching = false; }
  }
  assistant(open) {
    this.root.querySelector('#assistantPanel').hidden = !open;
    this.root.querySelector('.workspace-grid').classList.toggle('assistant-collapsed', !open);
    const button = this.root.querySelector('#btnAssistant');
    button.setAttribute('aria-expanded', String(open));
    button.classList.toggle('active', open);
  }
}
